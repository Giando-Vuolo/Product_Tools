"""Confluence Team Calendars REST client for the release calendar (read and write events).

The ICS subscription (utils/release_calendar.py) is read-only. Editing goes through the Team Calendars
REST resource used by Confluence's own UI (Server/Data Center, verified on Team Calendars 20.2):

- GET  /rest/calendar-services/1.0/calendar/subcalendars.json?include=<calendar id>   calendar + event types
- GET  /rest/calendar-services/1.0/calendar/events.json?subCalendarId=<child>&start&end
- PUT  /rest/calendar-services/1.0/calendar/events.json   form body: create (no uid) or update (uid)
- DELETE same URL, form body subCalendarId=<child>&uid=<uid>   delete one (non-recurring) event

A Team Calendar is a parent sub-calendar with one child sub-calendar per event type. The HTTP layer is
injected (``send(method, path, params=None, data=None)`` returning a requests-like response) so the logic
is testable without network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

import requests

from utils import release_calendar as rc

ENV_CALENDAR_ID = "RELEASE_CALENDAR_ID"
API = "/rest/calendar-services/1.0/calendar"
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class CalendarApiError(Exception):
    """Readable error for the UI."""


@dataclass(frozen=True)
class EventType:
    title: str
    type_id: str      # customEventTypeId
    child_id: str     # child sub-calendar holding the events of this type


@dataclass(frozen=True)
class CalendarInfo:
    id: str
    name: str
    timezone: str
    space_key: str
    events_editable: bool
    types: tuple = ()  # of EventType

    def type_by_title(self, title: str) -> Optional[EventType]:
        key = (title or "").strip().casefold()
        return next((t for t in self.types if t.title.strip().casefold() == key), None)


@dataclass(frozen=True)
class ApiEvent:
    uid: str
    title: str
    type_title: str
    type_id: str
    child_id: str
    start: date
    end: date            # inclusive
    all_day: bool
    description: str = ""
    recurring: bool = False
    has_invitees: bool = False
    extra: dict = field(default_factory=dict, compare=False)  # where / url when the API returns them

    @property
    def version(self) -> str:
        return rc.extract_version(self.title)

    @property
    def editable(self) -> bool:
        """PO Tools only rewrites simple events: all-day, not recurring, no invitees."""
        return self.all_day and not self.recurring and not self.has_invitees


def parse_calendar_id(value: str) -> str:
    """Calendar id from a raw id or a Confluence calendar link ('.../calendar/<id>?calendarName=...')."""
    m = _UUID_RE.search(value or "")
    return m.group(0).lower() if m else ""


# --------------------------------------------------------------------------- HTTP

def make_sender(server: str, token: str, auth_type: str = "", email: str = "", timeout: int = 30) -> Callable:
    """requests-based sender for the Confluence server (same auth rules as the other Confluence calls)."""
    from utils.confluence_helpers import _confluence_base_and_auth

    def send(method, path, params=None, data=None):
        base, headers, auth = _confluence_base_and_auth(server, token, auth_type, email)
        headers = dict(headers, **{"X-Atlassian-Token": "no-check"})  # form posts need the XSRF opt-out
        return requests.request(method, f"{base}{path}", headers=headers, auth=auth, params=params,
                                data=data, timeout=timeout)
    return send


def _call(send, method, path, *, params=None, data=None, what="calendar"):
    try:
        resp = send(method, path, params=params, data=data)
    except requests.RequestException as exc:
        raise CalendarApiError(f"Could not reach Confluence ({what}): {exc.__class__.__name__}") from exc
    if resp.status_code in (401, 403):
        raise CalendarApiError(f"Access denied to the {what} (HTTP {resp.status_code}). Check CONFLUENCE_API_TOKEN "
                               "and that your user can edit the calendar.")
    if resp.status_code == 404:
        raise CalendarApiError(f"The {what} was not found (HTTP 404). Check {ENV_CALENDAR_ID}.")
    if resp.status_code not in (200, 204):
        raise CalendarApiError(f"Confluence answered HTTP {resp.status_code} for the {what}.")
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    try:
        body = resp.json()
    except ValueError as exc:
        raise CalendarApiError(f"Confluence did not return JSON for the {what} (is the session/token valid?).") from exc
    if isinstance(body, dict) and body.get("success") is False:
        msg = body.get("message") or body.get("fieldErrors") or body
        raise CalendarApiError(f"Confluence refused the {what}: {msg}")
    return body


# --------------------------------------------------------------------------- read

def get_calendar(send, calendar_id: str) -> CalendarInfo:
    """Parent calendar with its event types and their child sub-calendars."""
    if not calendar_id:
        raise CalendarApiError(f"Set the release calendar id in Configuration ({ENV_CALENDAR_ID}).")
    body = _call(send, "GET", f"{API}/subcalendars.json",
                 params={"include": calendar_id, "calendarContext": "spaceCalendars"}, what="calendar")
    entry = next((p for p in body.get("payload") or []
                  if ((p.get("subCalendar") or {}).get("id") or "") == calendar_id), None)
    if entry is None:
        raise CalendarApiError(f"Calendar {calendar_id} was not found or is not visible to your user.")
    sub = entry["subCalendar"]
    types = []
    for child in entry.get("childSubCalendars") or []:
        cs = child.get("subCalendar") or {}
        for t in cs.get("customEventTypes") or []:
            types.append(EventType(str(t.get("title", "")).strip(), str(t.get("customEventTypeId", "")),
                                   str(cs.get("id", ""))))
    return CalendarInfo(id=calendar_id, name=sub.get("name", ""), timezone=sub.get("timeZoneId", "") or "UTC",
                        space_key=sub.get("spaceKey", ""), events_editable=bool(entry.get("eventsEditable")),
                        types=tuple(types))


def _local_date(value: str) -> date:
    """'2026-09-28T00:00:00.000+02:00' -> 2026-09-28 (the calendar's local date, offset ignored)."""
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise CalendarApiError(f"Unexpected event date from Confluence: {value!r}") from exc


def parse_event(raw: dict, etype: EventType) -> ApiEvent:
    start = _local_date(raw.get("start") or raw.get("originalStartDateTime", ""))
    end_raw = raw.get("end") or raw.get("originalEndDateTime") or raw.get("start", "")
    end = max(start, _local_date(end_raw))
    return ApiEvent(
        uid=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        type_title=etype.title,
        type_id=str(raw.get("customEventTypeId") or etype.type_id),
        child_id=str(raw.get("subCalendarId") or etype.child_id),
        start=start, end=end, all_day=bool(raw.get("allDay")),
        description=str(raw.get("description") or ""),
        recurring=bool(raw.get("rruleStr") or raw.get("recurrenceId") or raw.get("recurId")),
        has_invitees=bool(raw.get("invitees")),
        extra={k: raw[k] for k in ("where", "url") if raw.get(k)},
    )


def list_events(send, cal: CalendarInfo, start: date, end: date, types=None) -> list:
    """Events of every (or the given) event type overlapping [start, end]. Recurring series come expanded."""
    wanted = cal.types if types is None else [t for t in cal.types if t.title in set(types)]
    out, seen = [], set()
    for etype in wanted:
        body = _call(send, "GET", f"{API}/events.json", what=f"'{etype.title}' events", params={
            "subCalendarId": etype.child_id, "userTimeZoneId": cal.timezone,
            "start": f"{start:%Y-%m-%d}T00:00:00.000Z", "end": f"{end:%Y-%m-%d}T23:59:59.000Z"})
        for raw in body.get("events") or []:
            if raw.get("customEventTypeId") and raw["customEventTypeId"] != etype.type_id:
                continue
            ev = parse_event(raw, etype)
            key = (ev.uid, ev.start)
            if key not in seen:
                seen.add(key)
                out.append(ev)
    return sorted(out, key=lambda e: (e.start, e.type_title, e.title))


# --------------------------------------------------------------------------- write

def event_form(cal: CalendarInfo, etype: EventType, *, title: str, start: date, end: date, description: str,
               uid: str = "", where: str = "", url: str = "") -> dict:
    """Form body of the PUT, as Confluence's own dialog sends it (all-day, not recurring, no invitees)."""
    form = {
        "confirmRemoveInvalidUsers": "false",
        "childSubCalendarId": etype.child_id,
        "customEventTypeId": etype.type_id,
        "eventType": "custom",
        "isSingleJiraDate": "false",
        "recurrenceId": "",
        "subCalendarId": cal.id,
        "what": title,
        "startDate": f"{start:%Y-%m-%d}",
        "endDate": f"{end:%Y-%m-%d}",
        "startTime": "",
        "endTime": "",
        "allDayEvent": "true",
        "rruleStr": "",
        "until": "",
        "editAllInRecurrenceSeries": "true",
        "where": where,
        "url": url,
        "description": description,
        "userTimeZoneId": cal.timezone,
    }
    if uid:
        form.update({
            "uid": uid,
            "originalSubCalendarId": cal.id,
            "originalEventSubCalendarId": etype.child_id,
            "originalStartDate": "",
            "originalEventType": "custom",
            "originalCustomEventTypeId": etype.type_id,
        })
    return form


def put_event(send, form: dict) -> str:
    """Create or update an event; returns its uid."""
    body = _call(send, "PUT", f"{API}/events.json", data=form, what="event")
    uid = str(((body or {}).get("event") or {}).get("id", "") or form.get("uid", ""))
    if not uid:
        raise CalendarApiError("Confluence did not return the event id after saving.")
    return uid


def delete_event(send, child_id: str, uid: str) -> None:
    """Delete one non-recurring event (form body as Confluence's own dialog sends it)."""
    if not (child_id and uid):
        raise CalendarApiError("Missing sub-calendar or event id for the deletion.")
    _call(send, "DELETE", f"{API}/events.json", data={"subCalendarId": child_id, "uid": uid}, what="event deletion")
