"""Release Calendar: read a Confluence Team Calendar ICS export and turn it into release data.

Pure helpers (no Streamlit) so they can be tested with fixtures. Only the standard library is used to
parse the ICS: Confluence exports all-day events with simple recurrences, so a full iCalendar
dependency is not needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import pandas as pd
import requests

ENV_ICS_URL = "RELEASE_CALENDAR_ICS_URL"

# Confluence event types (CATEGORIES) that describe a release step. Matching is case-insensitive.
PROD_DEPLOY = "Prod Deploy"
PRE_DEPLOY = "Pre Deploy"
QS_FREEZE = "QS Freeze"
LOAD_TEST = "Load Test"
BAT = "BAT"
REGRESSION = "Regression Test"
PEN_TEST = "PEN test PreLive"
CONSTRAINT = "Constraint"

# Column order of the per-release view: (column title, event type, which date to keep).
RELEASE_STEPS = (
    ("QS Freeze start", QS_FREEZE, "start"),
    ("QS Freeze end", QS_FREEZE, "end"),
    ("Pre Deploy", PRE_DEPLOY, "start"),
    ("Regression", REGRESSION, "start"),
    ("Load Test", LOAD_TEST, "start"),
    ("PEN test", PEN_TEST, "start"),
    ("BAT", BAT, "start"),
    ("Prod Deploy", PROD_DEPLOY, "start"),
)

EVENT_COLUMNS = ["Start", "End", "Type", "Summary", "Version", "Description", "UID"]

_VERSION_RE = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})(?:\.(\d{1,3}))?(?![\d.])")
_MAX_OCCURRENCES = 500


class CalendarError(Exception):
    """Readable error for the UI (download or format problems)."""


@dataclass
class CalendarEvent:
    uid: str
    summary: str
    start: date
    end: date  # inclusive (last day of the event)
    category: str = ""
    description: str = ""
    status: str = ""
    recurrence_id: Optional[date] = None
    rrule: dict = field(default_factory=dict)
    exdates: set = field(default_factory=set)

    @property
    def version(self) -> str:
        return extract_version(self.summary)


@dataclass
class Calendar:
    name: str
    timezone: str
    events: list


# --------------------------------------------------------------------------- download

def fetch_ics(url: str, token: str = "", auth_type: str = "", email: str = "", timeout: int = 30) -> str:
    """Download the ICS. Uses the Confluence credentials: anonymous calls are rate limited (HTTP 429)."""
    if not url:
        raise CalendarError(f"Set {ENV_ICS_URL} in .env (Confluence calendar → Subscribe → copy the link).")
    headers = {"Accept": "text/calendar"}
    auth = None
    token_clean = (token or "").strip().removeprefix("Bearer ").strip()
    if token_clean:
        if auth_type in ("Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"):
            auth = ((email or "").strip(), token_clean)
        else:
            headers["Authorization"] = f"Bearer {token_clean}"
    try:
        resp = requests.get(url, headers=headers, auth=auth, timeout=timeout)
    except requests.RequestException as exc:
        raise CalendarError(f"Could not reach the calendar: {exc.__class__.__name__}") from exc
    if resp.status_code == 429:
        raise CalendarError("Confluence rate limit (HTTP 429). Check CONFLUENCE_API_TOKEN and try again in a minute.")
    if resp.status_code in (401, 403):
        raise CalendarError(f"Access denied to the calendar (HTTP {resp.status_code}). Check CONFLUENCE_API_TOKEN.")
    if resp.status_code != 200:
        raise CalendarError(f"Calendar download failed (HTTP {resp.status_code}).")
    resp.encoding = resp.encoding or "utf-8"
    text = resp.text
    if "BEGIN:VCALENDAR" not in text:
        raise CalendarError("The link did not return an iCalendar (.ics) file.")
    return text


# --------------------------------------------------------------------------- parsing

def _unfold(text: str) -> list:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _split_prop(line: str) -> tuple:
    """'DTSTART;VALUE=DATE:20240101' -> ('DTSTART', {'VALUE': 'DATE'}, '20240101'). Quote-aware."""
    in_quotes, colon = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon = i
            break
    if colon < 0:
        return line.upper(), {}, ""
    head, value = line[:colon], line[colon + 1:]
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out).strip()


def _parse_date(value: str) -> date:
    value = value.strip()
    try:
        if "T" in value:
            return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").date()
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise CalendarError(f"Unexpected date in the calendar: {value!r}") from exc


def _parse_rrule(value: str) -> dict:
    return {k.upper(): v for k, v in (p.split("=", 1) for p in value.split(";") if "=" in p)}


def _event_from_props(props: list) -> Optional[CalendarEvent]:
    data, start, end_raw, end_is_date = {}, None, None, False
    recurrence_id, rrule, exdates = None, {}, set()
    for name, params, value in props:
        if name == "DTSTART":
            start = _parse_date(value)
        elif name == "DTEND":
            end_raw = _parse_date(value)
            end_is_date = params.get("VALUE") == "DATE" or "T" not in value
        elif name == "RECURRENCE-ID":
            recurrence_id = _parse_date(value)
        elif name == "RRULE":
            rrule = _parse_rrule(value)
        elif name == "EXDATE":
            exdates.update(_parse_date(v) for v in value.split(",") if v.strip())
        elif name not in data:
            data[name] = _unescape(value)
    if start is None:
        return None
    if end_raw is None:
        end = start
    elif end_is_date:
        end = max(start, end_raw - timedelta(days=1))  # all-day DTEND is exclusive
    else:
        end = max(start, end_raw)
    return CalendarEvent(
        uid=data.get("UID", ""),
        summary=data.get("SUMMARY", ""),
        start=start,
        end=end,
        category=data.get("CATEGORIES", ""),
        description=data.get("DESCRIPTION", ""),
        status=data.get("STATUS", ""),
        recurrence_id=recurrence_id,
        rrule=rrule,
        exdates=exdates,
    )


def _add_months(d: date, months: int) -> Optional[date]:
    y, m = divmod(d.month - 1 + months, 12)
    try:
        return d.replace(year=d.year + y, month=m + 1)
    except ValueError:
        return None  # e.g. 31st in a shorter month: skipped, as iCalendar does


def _occurrence_starts(event: CalendarEvent) -> Iterable[date]:
    rule = event.rrule
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = _parse_date(rule["UNTIL"]) if rule.get("UNTIL") else None
    produced = 0
    for n in range(_MAX_OCCURRENCES):
        if freq == "DAILY":
            current = event.start + timedelta(days=n * interval)
        elif freq == "WEEKLY":
            current = event.start + timedelta(weeks=n * interval)
        elif freq == "MONTHLY":
            current = _add_months(event.start, n * interval)
        elif freq == "YEARLY":
            current = _add_months(event.start, 12 * n * interval)
        else:
            yield event.start
            return
        if current is None:
            continue
        if until and current > until:
            return
        produced += 1
        if count and produced > count:
            return
        yield current


def _expand(events: list) -> list:
    """Expand simple recurrences (FREQ/INTERVAL/COUNT/UNTIL/EXDATE) and apply RECURRENCE-ID overrides."""
    overrides = {(e.uid, e.recurrence_id): e for e in events if e.recurrence_id}
    result = []
    for e in events:
        if e.recurrence_id:
            continue
        if not e.rrule:
            result.append(e)
            continue
        length = e.end - e.start
        for occ in _occurrence_starts(e):
            if occ in e.exdates:
                continue
            override = overrides.pop((e.uid, occ), None)
            if override:
                result.append(override)
            else:
                result.append(CalendarEvent(e.uid, e.summary, occ, occ + length, e.category,
                                            e.description, e.status))
    result.extend(overrides.values())  # overrides of an unknown series: keep them as single events
    return result


def parse_ics(text: str) -> Calendar:
    """Parse an ICS export. Only VEVENTs are kept; cancelled events are dropped."""
    if "BEGIN:VCALENDAR" not in (text or ""):
        raise CalendarError("Not an iCalendar (.ics) file.")
    name, tz = "", ""
    stack, props, events = [], [], []
    for line in _unfold(text):
        prop, params, value = _split_prop(line)
        if prop == "BEGIN":
            stack.append(value.upper())
            if value.upper() == "VEVENT":
                props = []
            continue
        if prop == "END":
            if stack and stack[-1] == "VEVENT" and value.upper() == "VEVENT":
                event = _event_from_props(props)
                if event and event.status.upper() != "CANCELLED":
                    events.append(event)
            if stack:
                stack.pop()
            continue
        if stack == ["VCALENDAR"]:
            if prop == "X-WR-CALNAME":
                name = _unescape(value)
            elif prop == "X-WR-TIMEZONE":
                tz = value.strip()
        elif stack and stack[-1] == "VEVENT":
            props.append((prop, params, value))
    return Calendar(name=name, timezone=tz, events=sorted(_expand(events), key=lambda e: (e.start, e.summary)))


# --------------------------------------------------------------------------- data model

def extract_version(text: str) -> str:
    """First X.Y(.Z) in a summary, normalised to X.Y.Z ('Release 11.0' -> '11.0.0'). '' when none."""
    m = _VERSION_RE.search(text or "")
    if not m:
        return ""
    major, minor, patch = m.group(1), m.group(2), m.group(3) or "0"
    return f"{int(major)}.{int(minor)}.{int(patch)}"


def version_key(version: str) -> tuple:
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return (0,)


def events_dataframe(calendar: Calendar) -> pd.DataFrame:
    rows = [{
        "Start": pd.Timestamp(e.start),
        "End": pd.Timestamp(e.end),
        "Type": e.category.strip() or "Other",
        "Summary": e.summary,
        "Version": e.version,
        "Description": e.description,
        "UID": e.uid,
    } for e in calendar.events]
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def _is_type(series: pd.Series, name: str) -> pd.Series:
    return series.str.strip().str.casefold() == name.casefold()


def releases_dataframe(events: pd.DataFrame, today: Optional[date] = None) -> pd.DataFrame:
    """One row per version: the date of each release step and a status.

    A version appears if it has at least one release-step event. When a step occurs more than once
    (rescheduled or split), the earliest start / latest end is kept.
    """
    today = pd.Timestamp(today or date.today())
    columns = ["Version", *(c for c, _, _ in RELEASE_STEPS), "Status", "Days to Prod"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    step_types = {t.casefold() for _, t, _ in RELEASE_STEPS}
    df = events[(events["Version"] != "") & events["Type"].str.strip().str.casefold().isin(step_types)]
    rows = []
    for version, group in df.groupby("Version"):
        row = {"Version": version}
        for col, etype, which in RELEASE_STEPS:
            sub = group[_is_type(group["Type"], etype)]
            row[col] = (sub["Start"].min() if which == "start" else sub["End"].max()) if not sub.empty else pd.NaT
        prod = row["Prod Deploy"]
        if pd.isna(prod):
            row["Status"] = "No Prod date"
            row["Days to Prod"] = None
        else:
            row["Status"] = "Deployed" if prod < today else ("Today" if prod == today else "Planned")
            row["Days to Prod"] = int((prod - today).days)
        rows.append(row)
    out = pd.DataFrame(rows, columns=columns)
    out["Days to Prod"] = out["Days to Prod"].astype("Int64")
    out = out.iloc[sorted(range(len(out)), key=lambda i: version_key(out.iloc[i]["Version"]))]
    return out.reset_index(drop=True)


def filter_events(events: pd.DataFrame, start: Optional[date] = None, end: Optional[date] = None,
                  types: Optional[Iterable[str]] = None, text: str = "") -> pd.DataFrame:
    """Events overlapping [start, end], of the given types, whose summary/version/description contain text."""
    df = events
    if start is not None:
        df = df[df["End"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["Start"] <= pd.Timestamp(end)]
    if types is not None:
        df = df[df["Type"].isin(list(types))]
    needle = (text or "").strip().casefold()
    if needle:
        hay = (df["Summary"] + " " + df["Version"] + " " + df["Description"]).str.casefold()
        df = df[hay.str.contains(needle, regex=False)]
    return df.reset_index(drop=True)


def _quarter_bounds(today: pd.Timestamp) -> tuple:
    q_start = pd.Timestamp(year=today.year, month=3 * ((today.month - 1) // 3) + 1, day=1)
    return q_start, q_start + pd.DateOffset(months=3) - pd.Timedelta(days=1)


def calendar_kpis(events: pd.DataFrame, releases: pd.DataFrame, today: Optional[date] = None) -> dict:
    """Headline numbers: next Prod deploy, Prod deploys this quarter, upcoming constraints, warnings."""
    today = pd.Timestamp(today or date.today())
    prod = events[_is_type(events["Type"], PROD_DEPLOY)] if not events.empty else events
    upcoming = prod[prod["Start"] >= today].sort_values("Start")
    nxt = upcoming.iloc[0] if not upcoming.empty else None
    q_start, q_end = _quarter_bounds(today)
    in_quarter = prod[(prod["Start"] >= q_start) & (prod["Start"] <= q_end)] if not prod.empty else prod
    constraints = (events[_is_type(events["Type"], CONSTRAINT) & (events["End"] >= today)
                          & (events["Start"] <= today + pd.Timedelta(days=30))]
                   if not events.empty else events)
    warnings = []
    if not releases.empty:
        step_cols = [c for c, _, _ in RELEASE_STEPS]
        last_step = releases[step_cols].max(axis=1)
        no_prod = releases[(releases["Status"] == "No Prod date") & (last_step >= today)]  # old ones are history
        for v in no_prod["Version"]:
            warnings.append(f"Release {v} has calendar steps but no Prod Deploy date.")
        late = releases[(releases["Status"] == "Planned") & releases["Pre Deploy"].notna()
                        & (releases["Pre Deploy"] > releases["Prod Deploy"])]
        for v in late["Version"]:
            warnings.append(f"Release {v}: Pre Deploy is after Prod Deploy.")
    if not prod.empty:
        unversioned = prod[prod["Version"] == ""]
        for _, r in unversioned[unversioned["Start"] >= today].iterrows():
            warnings.append(f"Prod Deploy on {r['Start']:%d %b %Y} has no version in its title: \"{r['Summary']}\".")
    return {
        "next_version": (nxt["Version"] or nxt["Summary"]) if nxt is not None else None,
        "next_date": nxt["Start"] if nxt is not None else None,
        "days_to_next": int((nxt["Start"] - today).days) if nxt is not None else None,
        "quarter_label": f"Q{(today.month - 1) // 3 + 1} {today.year}",
        "prod_in_quarter": int(len(in_quarter)),
        "constraints_30d": constraints.sort_values("Start").reset_index(drop=True),
        "warnings": warnings,
    }


def timeline_label_levels(events: pd.DataFrame, labels: Iterable[str], chars_in_view: int = 120,
                          max_levels: int = 4) -> list:
    """Where to draw each bar title in the timeline, as a level per event (same order as `events`).

    Level 0 = just above the bar, 1 = just below, 2 = above level 0, 3 = below level 1, ...
    Titles start at the bar start and are estimated to cover len(title) / chars_in_view of the visible
    date range. Each title takes the lowest free level of its row; when every level is busy it takes
    the one that frees first.
    """
    labels = list(labels)
    if events.empty:
        return []
    lo = events["Start"].min()
    hi = (events["End"] + pd.Timedelta(days=1)).max()
    days_per_char = max((hi - lo).days, 1) / max(chars_in_view, 1)
    levels = [0] * len(events)
    for _, group in events.reset_index(drop=True).groupby("Type", sort=False):
        busy_until = [pd.Timestamp.min] * max(1, max_levels)  # where the last title of each level ends
        for i in group.sort_values("Start", kind="stable").index:
            start = events.iloc[i]["Start"]
            width = pd.Timedelta(days=(len(labels[i]) + 2) * days_per_char)
            free = [lvl for lvl, until in enumerate(busy_until) if start >= until]
            level = free[0] if free else min(range(len(busy_until)), key=lambda lvl: busy_until[lvl])
            levels[i] = level
            busy_until[level] = start + width
    return levels


def _iso(value) -> str:
    return "" if pd.isna(value) else f"{value:%Y-%m-%d}"


def releases_display(releases: pd.DataFrame) -> pd.DataFrame:
    """Releases table as shown on the page: dates as ISO text (blank when missing, still sortable) and
    QS Freeze as one range column ('2026-11-27 → 2026-12-15') instead of separate start / end columns."""
    out = releases.copy()
    start, end = out.pop("QS Freeze start"), out.pop("QS Freeze end")
    out.insert(1, "QS Freeze", [
        f"{_iso(s)} → {_iso(e)}" if _iso(s) and _iso(e) and _iso(s) != _iso(e) else (_iso(s) or _iso(e))
        for s, e in zip(start, end)
    ])
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = [_iso(v) for v in out[col]]
    return out


def prod_deploy_info(events: pd.DataFrame, version: str) -> dict:
    """The calendar's Prod Deploy event(s) of ``version``: earliest date, titles and description.

    Returns {"date": Timestamp | None, "title": str, "description": str}; with several Prod Deploy events
    (rescheduled or split) the date is the earliest and the distinct non-empty descriptions are joined.
    """
    empty = {"date": None, "title": "", "description": ""}
    if events is None or events.empty or not version:
        return empty
    prod = events[_is_type(events["Type"], PROD_DEPLOY) & (events["Version"] == version)].sort_values("Start")
    if prod.empty:
        return empty
    descriptions = []
    for d in prod["Description"]:
        d = (d or "").strip()
        if d and d not in descriptions:
            descriptions.append(d)
    return {"date": prod.iloc[0]["Start"], "title": " / ".join(dict.fromkeys(prod["Summary"])),
            "description": "\n\n".join(descriptions)}
