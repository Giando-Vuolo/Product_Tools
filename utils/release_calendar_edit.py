"""Release Calendar editing (Epic 2): editable table, validation, change plan and safe publish.

Pure logic plus injected HTTP (``send``) so it is testable without network. Only the events behind the
cells that changed are written; every other event of the calendar is left untouched.

One row per release (X.Y.Z) with the date of each release step and the Description of the Prod Deploy event.
A cell maps to the calendar event of that step whose title carries the version:
- no event + date        -> create the event (title from RELEASE_CALENDAR_EVENT_TITLE)
- one simple event       -> update its dates (duration kept) / description; title unchanged
- several, recurring, timed or with invitees -> locked: edit it in Confluence
Deleting a row deletes every release-step event of that release (refused if one is recurring).
Clearing a single date or renaming a release is refused.

Publishing: allow-list + sandbox check, re-read of the affected events and refusal if they changed
since loading, local JSON backup, writes one by one (stop at the first error), re-read to verify, and
an audit line in data/release_calendar_audit.jsonl.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Optional

import pandas as pd

from utils import release_calendar as rc
from utils import release_calendar_api as api
from utils import release_calendar_jira as rcj

ENV_TITLE_TEMPLATE = "RELEASE_CALENDAR_EVENT_TITLE"
DEFAULT_TITLE_TEMPLATE = "{type} - Release {version}"
ENV_WRITE_MODE = "RELEASE_CALENDAR_WRITE_MODE"   # "sandbox" (default) or "live"
ENV_SANDBOX_VERSIONS = "RELEASE_CALENDAR_SANDBOX_VERSIONS"
DEFAULT_SANDBOX_VERSIONS = ("999.0.0",)
BACKUP_DIR = Path("data/confluence_backups")
AUDIT_FILE = Path("data/release_calendar_audit.jsonl")

QS_START, QS_END, NOTES, KEY, LOCKED = "QS Freeze start", "QS Freeze end", "Description", "_key", "Locked"
# simple one-date steps: (column, event type title)
SIMPLE_STEPS = tuple((c, t) for c, t, _ in rc.RELEASE_STEPS if t != rc.QS_FREEZE)
DATE_COLUMNS = [QS_START, QS_END, *(c for c, _ in SIMPLE_STEPS)]
EDIT_COLUMNS = [KEY, "Version", *DATE_COLUMNS, NOTES, LOCKED]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class PublishRefused(Exception):
    """Publishing was refused before anything was written."""


@dataclass(frozen=True)
class Change:
    action: str            # "create" | "update" | "delete"
    version: str
    type_title: str
    uid: str = ""
    before: Optional[dict] = None   # {"title", "start", "end", "description"} (ISO dates)
    after: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)  # where / url kept on update

    def label(self) -> str:
        return f"{self.version} · {self.type_title}"


@dataclass
class Plan:
    changes: list
    errors: list
    rows: pd.DataFrame     # Version, Status (New/Changed/Unchanged/Deleted), Details

    @property
    def deletions(self) -> list:
        return [c for c in self.changes if c.action == "delete"]


# --------------------------------------------------------------------------- config

def load_write_config(env: Mapping) -> tuple:
    """(mode, sandbox_versions or None when live)."""
    mode = str(env.get(ENV_WRITE_MODE, "") or "sandbox").strip().lower()
    if mode not in ("sandbox", "live"):
        raise ValueError(f"{ENV_WRITE_MODE} must be 'sandbox' or 'live'.")
    if mode == "live":
        return mode, None
    raw = str(env.get(ENV_SANDBOX_VERSIONS, "") or "")
    versions = tuple(v.strip() for v in raw.split(",") if v.strip()) or DEFAULT_SANDBOX_VERSIONS
    for v in versions:
        if not VERSION_RE.match(v):
            raise ValueError(f"{ENV_SANDBOX_VERSIONS} must list X.Y.Z versions, e.g. 999.0.0.")
    return mode, versions


def event_title(template: str, type_title: str, version: str) -> str:
    t = (template or "").strip() or DEFAULT_TITLE_TEMPLATE
    if "{version}" not in t:
        raise ValueError(f"{ENV_TITLE_TEMPLATE} must contain {{version}}, e.g. '{DEFAULT_TITLE_TEMPLATE}'.")
    return t.replace("{type}", type_title).replace("{version}", version)


def assert_write_allowed(calendar_id: str, allowed_id: str, changes: Iterable, sandbox_versions) -> None:
    """Only the configured release calendar may be written; in sandbox mode only the sandbox versions."""
    if not allowed_id or str(calendar_id) != str(allowed_id):
        raise PublishRefused(f"Writing is only allowed on the configured release calendar "
                             f"({allowed_id or 'not set'}), not {calendar_id or '?'}.")
    if sandbox_versions is not None:
        bad = sorted({c.version for c in changes if c.version not in sandbox_versions}, key=rc.version_key)
        if bad:
            raise PublishRefused(f"Sandbox mode: only {', '.join(sandbox_versions)} can be written, "
                                 f"not {', '.join(bad)}. Set {ENV_WRITE_MODE}=live to edit real releases.")


# --------------------------------------------------------------------------- table

def _d(value) -> Optional[date]:
    """Cell value -> date or None (accepts date, datetime, Timestamp, ISO text, NaT/None/'')."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"'{value}' is not a date") from exc


def _txt(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def event_index(events: Iterable) -> dict:
    """{(version, step type title): [ApiEvent, ...]} for release-step events with a version."""
    steps = {t.casefold(): t for _, t, _ in rc.RELEASE_STEPS}
    idx = {}
    for e in events:
        t = steps.get((e.type_title or "").strip().casefold())
        if t and e.version:
            idx.setdefault((e.version, t), []).append(e)
    return idx


def _lock_reason(evs: list) -> str:
    if len(evs) > 1:
        return f"{len(evs)} events"
    e = evs[0]
    if e.recurring:
        return "recurring"
    if not e.all_day:
        return "has a time"
    if e.has_invitees:
        return "has invitees"
    return ""


def editable_table(events: Iterable) -> pd.DataFrame:
    """One row per release for st.data_editor. ``_key`` keeps the original version of existing rows."""
    idx = event_index(events)
    rows = []
    for version in sorted({v for v, _ in idx}, key=rc.version_key):
        row = {KEY: version, "Version": version, NOTES: ""}
        locked = []
        qs = idx.get((version, rc.QS_FREEZE), [])
        row[QS_START] = min(e.start for e in qs) if qs else None
        row[QS_END] = max(e.end for e in qs) if qs else None
        if qs and _lock_reason(qs):
            locked.append(f"QS Freeze ({_lock_reason(qs)})")
        for col, t in SIMPLE_STEPS:
            evs = idx.get((version, t), [])
            row[col] = min(e.start for e in evs) if evs else None
            if evs and _lock_reason(evs):
                locked.append(f"{col} ({_lock_reason(evs)})")
        prod = idx.get((version, rc.PROD_DEPLOY), [])
        if len(prod) == 1:
            row[NOTES] = prod[0].description
        row[LOCKED] = ", ".join(locked)
        rows.append(row)
    return pd.DataFrame(rows, columns=EDIT_COLUMNS)


def jira_proposals(jira: pd.DataFrame, calendar_versions: Iterable, links: Mapping,
                   template: str = rcj.DEFAULT_NAME_TEMPLATE) -> pd.DataFrame:
    """Jira versions following the name template that are not in the calendar yet (not archived or
    released, not manually linked to a calendar release), with their release date as Prod Deploy."""
    cols = ["Version", "Jira version", "Jira id", "Prod Deploy"]
    if jira is None or jira.empty:
        return pd.DataFrame(columns=cols)
    in_cal = set(calendar_versions)
    linked_ids = {v.get("jira_id") for v in links.values() if v.get("jira_id")}
    pattern = rcj.template_regex(template)
    rows = []
    for _, r in jira.iterrows():
        m = pattern.match(r["Jira version"] or "")
        if not m or r["Archived"] or r["Released"] or r["Jira id"] in linked_ids:
            continue
        version = m.group("version")
        if version in in_cal:
            continue
        rd = r["Jira release date"]
        rows.append({"Version": version, "Jira version": r["Jira version"], "Jira id": r["Jira id"],
                     "Prod Deploy": None if pd.isna(rd) else pd.Timestamp(rd).date()})
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out
    return out.iloc[sorted(range(len(out)), key=lambda i: rc.version_key(out.iloc[i]["Version"]))].reset_index(drop=True)


def proposal_rows(proposals: pd.DataFrame) -> pd.DataFrame:
    """New editor rows for the chosen Jira proposals."""
    rows = [{KEY: None, "Version": r["Version"], **{c: None for c in DATE_COLUMNS},
             "Prod Deploy": r["Prod Deploy"], NOTES: "", LOCKED: ""} for _, r in proposals.iterrows()]
    return pd.DataFrame(rows, columns=EDIT_COLUMNS)


# --------------------------------------------------------------------------- plan

def _ev_state(e) -> dict:
    return {"title": e.title, "start": f"{e.start:%Y-%m-%d}", "end": f"{e.end:%Y-%m-%d}", "description": e.description}


def _fmt(d) -> str:
    return f"{d:%Y-%m-%d}" if d else "—"


def plan_changes(original: pd.DataFrame, edited: pd.DataFrame, events: Iterable, cal: api.CalendarInfo,
                 title_template: str = DEFAULT_TITLE_TEMPLATE, sandbox_versions=None) -> Plan:
    """Validate the edited table against the loaded events and list the event writes it needs."""
    idx = event_index(events)
    orig_by_key = {r[KEY]: r for _, r in original.iterrows()}
    changes, errors, status_rows = [], [], []
    try:
        event_title(title_template, "x", "1.0.0")
    except ValueError as exc:
        return Plan([], [str(exc)], pd.DataFrame(columns=["Version", "Status", "Details"]))

    keys_seen, versions_seen = set(), {}
    for n, (_, row) in enumerate(edited.iterrows(), start=1):
        key = _txt(row.get(KEY)) or None
        version = _txt(row.get("Version"))
        label = f"Row {n}" + (f" ({version})" if version else "")
        if not version:
            if any(_txt(row.get(c)) for c in [*DATE_COLUMNS, NOTES]):
                errors.append(f"{label}: the version is empty.")
            continue  # empty row added by mistake
        if not VERSION_RE.match(version):
            errors.append(f"{label}: version must be X.Y.Z, e.g. 37.0.0.")
            continue
        if version in versions_seen:
            errors.append(f"Release {version} appears twice (rows {versions_seen[version]} and {n}).")
            continue
        versions_seen[version] = n
        if key and key not in orig_by_key:
            key = None
        if key:
            keys_seen.add(key)
            if version != key:
                errors.append(f"Release {key}: renaming to {version} is not supported. Rename the events in "
                              "Confluence or add a new row.")
                continue
        elif any(v == version for v, _ in idx):
            errors.append(f"Release {version} is already in the calendar; edit its row instead of adding one.")
            continue

        try:
            new = {c: _d(row.get(c)) for c in DATE_COLUMNS}
        except ValueError as exc:
            errors.append(f"Release {version}: {exc}.")
            continue
        notes = _txt(row.get(NOTES))
        old = {c: (_d(orig_by_key[key].get(c)) if key else None) for c in DATE_COLUMNS}
        old_notes = _txt(orig_by_key[key].get(NOTES)) if key else ""
        row_changes, row_errors, details = [], [], []

        def need_type(title):
            et = cal.type_by_title(title)
            if et is None:
                row_errors.append(f"Release {version}: the calendar has no '{title}' event type.")
            return et

        def blocked(step, evs):
            reason = _lock_reason(evs)
            row_errors.append(f"Release {version}: {step} cannot be edited here ({reason}); change it in Confluence.")

        # QS Freeze: one event, start/end columns
        qs_s, qs_e = new[QS_START], new[QS_END]
        if qs_s and not qs_e:
            qs_e = qs_s
        if qs_e and not qs_s:
            row_errors.append(f"Release {version}: QS Freeze end without a start.")
        elif qs_s and qs_e < qs_s:
            row_errors.append(f"Release {version}: QS Freeze ends before it starts.")
        elif (qs_s, qs_e) != (old[QS_START], old[QS_END] or old[QS_START]) and not (qs_s is None and old[QS_START] is None):
            evs = idx.get((version, rc.QS_FREEZE), [])
            if not evs:
                et = need_type(rc.QS_FREEZE)
                if et:
                    row_changes.append(Change("create", version, et.title, after={
                        "title": event_title(title_template, et.title, version), "start": _fmt(qs_s),
                        "end": _fmt(qs_e), "description": ""}))
            elif qs_s is None:
                row_errors.append(f"Release {version}: clearing QS Freeze is not supported; delete it in Confluence.")
            elif _lock_reason(evs):
                blocked("QS Freeze", evs)
            else:
                e = evs[0]
                row_changes.append(Change("update", version, e.type_title, e.uid, _ev_state(e),
                                          dict(_ev_state(e), start=_fmt(qs_s), end=_fmt(qs_e)), e.extra))
            details.append(f"QS Freeze: {_fmt(old[QS_START])} → {_fmt(old[QS_END])} ⇒ {_fmt(qs_s)} → {_fmt(qs_e)}")

        # simple steps (+ the description of Prod Deploy)
        for col, t in SIMPLE_STEPS:
            value, before = new[col], old[col]
            notes_change = t == rc.PROD_DEPLOY and notes != old_notes
            if value == before and not notes_change:
                continue
            evs = idx.get((version, t), [])
            if not evs:
                if value is None:
                    if notes_change:
                        row_errors.append(f"Release {version}: the description is saved on the Prod Deploy event; "
                                          "set a Prod Deploy date.")
                    continue
                et = need_type(t)
                if et:
                    row_changes.append(Change("create", version, et.title, after={
                        "title": event_title(title_template, et.title, version), "start": _fmt(value),
                        "end": _fmt(value), "description": notes if t == rc.PROD_DEPLOY else ""}))
                    details.append(f"{col}: — ⇒ {_fmt(value)}")
                continue
            if value is None:
                row_errors.append(f"Release {version}: clearing {col} is not supported; delete it in Confluence.")
                continue
            if _lock_reason(evs):
                blocked(col, evs)
                continue
            e = evs[0]
            after = _ev_state(e)
            if value != before:
                length = e.end - e.start
                after.update(start=_fmt(value), end=_fmt(value + length))
                details.append(f"{col}: {_fmt(before)} ⇒ {_fmt(value)}")
            if notes_change:
                after["description"] = notes
                details.append("Description changed")
            row_changes.append(Change("update", version, e.type_title, e.uid, _ev_state(e), after, e.extra))

        if not key and not row_changes and not row_errors:
            row_errors.append(f"Release {version}: add at least one date.")
        if sandbox_versions is not None and row_changes and version not in sandbox_versions:
            row_errors.append(f"Release {version}: sandbox mode only allows {', '.join(sandbox_versions)}.")
        errors.extend(row_errors)
        changes.extend(row_changes)
        status = "New" if not key else ("Changed" if row_changes or row_errors else "Unchanged")
        status_rows.append({"Version": version, "Status": status, "Details": "; ".join(details)})

    for missing in sorted(set(orig_by_key) - keys_seen, key=rc.version_key):
        evs = sorted((e for (v, _), group in idx.items() if v == missing for e in group),
                     key=lambda e: (e.start, e.type_title))
        recurring = [e for e in evs if e.recurring]
        if recurring:
            errors.append(f"Release {missing}: cannot delete it here because "
                          f"{', '.join(sorted({e.type_title for e in recurring}))} is a recurring event; "
                          "delete it in Confluence.")
            continue
        if sandbox_versions is not None and missing not in sandbox_versions:
            errors.append(f"Release {missing}: sandbox mode only allows {', '.join(sandbox_versions)}.")
            continue
        for e in evs:
            changes.append(Change("delete", missing, e.type_title, e.uid, _ev_state(e), {}, {"child_id": e.child_id}))
        status_rows.append({"Version": missing, "Status": "Deleted",
                            "Details": f"{len(evs)} event(s): " + ", ".join(f"{e.type_title} {e.start:%Y-%m-%d}"
                                                                            for e in evs)})
    rows = pd.DataFrame(status_rows, columns=["Version", "Status", "Details"])
    return Plan(changes, errors, rows)


# --------------------------------------------------------------------------- publish

def _fingerprint(events: Iterable, keys: set) -> dict:
    out = {}
    for (v, t), evs in event_index(events).items():
        if (v, t) in keys:
            out[(v, t)] = sorted((e.uid, f"{e.start}", f"{e.end}", e.title, e.description) for e in evs)
    return out


def find_conflicts(loaded: Iterable, current: Iterable, changes: Iterable) -> list:
    """Releases/steps touched by ``changes`` whose events changed in the calendar since loading."""
    keys = {(c.version, c.type_title) for c in changes}
    before, now = _fingerprint(loaded, keys), _fingerprint(current, keys)
    return sorted(f"{v} · {t}" for v, t in keys if before.get((v, t), []) != now.get((v, t), []))


def write_backup(cal: api.CalendarInfo, current: Iterable, changes: Iterable, *, backup_dir=BACKUP_DIR,
                 now: Optional[datetime] = None) -> Path:
    now = now or datetime.now()
    d = Path(backup_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"calendar_{cal.id}_{now:%Y%m%d-%H%M%S}.json"
    payload = {"calendar": cal.id, "name": cal.name, "saved_at": now.isoformat(timespec="seconds"),
               "events": [dict(asdict(e), start=f"{e.start}", end=f"{e.end}") for e in current],
               "planned_changes": [asdict(c) for c in changes]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def verify_after_write(applied: Iterable, after: Iterable) -> list:
    by_uid = {e.uid: e for e in after}
    errors = []
    for c, uid in applied:
        e = by_uid.get(uid)
        if c.action == "delete":
            if e is not None:
                errors.append(f"{c.label()}: event {uid} is still in the calendar after deleting it.")
            continue
        if e is None:
            errors.append(f"{c.label()}: event {uid} not found after writing.")
            continue
        got = _ev_state(e)
        for k in ("title", "start", "end", "description"):
            if (got[k] or "").strip() != (c.after.get(k) or "").strip():
                errors.append(f"{c.label()}: {k} is '{got[k]}', expected '{c.after.get(k)}'.")
    return errors


def append_audit(entry: dict, path=AUDIT_FILE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _window(changes: Iterable, base: tuple) -> tuple:
    """Read window: the load window widened to every planned date (± 1 day)."""
    dates = [date.fromisoformat(x) for c in changes for x in (c.after.get("start"), c.after.get("end"),
             (c.before or {}).get("start"), (c.before or {}).get("end")) if x]
    lo, hi = base
    if dates:
        lo, hi = min([lo, *dates]) - timedelta(days=1), max([hi, *dates]) + timedelta(days=1)
    return lo, hi


def publish(send, cal: api.CalendarInfo, changes: list, loaded_events: list, window: tuple, *, allowed_id: str,
            sandbox_versions=None, user: str = "", backup_dir=BACKUP_DIR, audit_path=AUDIT_FILE,
            now: Optional[datetime] = None) -> dict:
    """Write ``changes`` safely. Returns {ok, status, error, backup, applied, audit}."""
    now = now or datetime.now()
    result = {"ok": False, "status": "refused", "error": None, "backup": None, "applied": []}

    def finish(**kw):
        result.update(kw)
        entry = {"at": now.isoformat(timespec="seconds"), "by": user, "calendar": cal.id,
                 "status": result["status"], "error": result["error"], "backup": result["backup"],
                 "changes": [dict(asdict(c), uid=uid or c.uid, applied=bool(uid))
                             for c, uid in [(c, dict(result["applied"]).get(i)) for i, c in enumerate(changes)]]}
        try:
            append_audit(entry, audit_path)
            result["audit"] = str(audit_path)
        except OSError as exc:
            result["audit"] = None
            result["error"] = (result["error"] + " " if result["error"] else "") + f"(Audit log not written: {exc})"
        result["applied"] = [uid for _, uid in result["applied"]]
        return result

    if not changes:
        return finish(ok=True, status="unchanged")
    try:
        assert_write_allowed(cal.id, allowed_id, changes, sandbox_versions)
        if not cal.events_editable:
            raise PublishRefused("Your user cannot edit events in this calendar.")
    except PublishRefused as exc:
        return finish(error=str(exc))

    types = sorted({c.type_title for c in changes})
    lo, hi = _window(changes, window)
    try:
        current = api.list_events(send, cal, lo, hi, types)
    except api.CalendarApiError as exc:
        return finish(error=f"Could not re-read the calendar, nothing was written: {exc}")
    loaded = [e for e in loaded_events if e.type_title in types]
    conflicts = find_conflicts(loaded, current, changes)
    if conflicts:
        return finish(error="The calendar changed since you loaded it (" + ", ".join(conflicts) +
                      "). Reload the calendar and apply your edits again. Nothing was written.")
    try:
        backup = write_backup(cal, current, changes, backup_dir=backup_dir, now=now)
    except OSError as exc:
        return finish(error=f"Backup failed, nothing was written: {exc}")
    result["backup"] = str(backup)

    applied = []  # (index in changes, uid)
    for i, c in enumerate(changes):
        etype = cal.type_by_title(c.type_title)
        try:
            if c.action == "delete":
                api.delete_event(send, c.extra.get("child_id") or etype.child_id, c.uid)
                uid = c.uid
            else:
                form = api.event_form(cal, etype, title=c.after["title"], start=date.fromisoformat(c.after["start"]),
                                      end=date.fromisoformat(c.after["end"]),
                                      description=c.after.get("description", ""), uid=c.uid,
                                      where=str(c.extra.get("where", "")), url=str(c.extra.get("url", "")))
                uid = api.put_event(send, form)
        except api.CalendarApiError as exc:
            result["applied"] = applied
            done = f"{len(applied)} of {len(changes)} changes were saved before the error. " if applied else ""
            return finish(status="failed", error=f"{c.label()}: {exc} {done}Backup: {backup}")
        applied.append((i, uid))
    result["applied"] = applied

    try:
        after = api.list_events(send, cal, lo, hi, types)
    except api.CalendarApiError as exc:
        return finish(status="verification_failed", error=f"Saved, but the re-read failed: {exc} Backup: {backup}")
    errors = verify_after_write([(changes[i], uid) for i, uid in applied], after)
    if errors:
        return finish(status="verification_failed", error="Verification failed: " + " ".join(errors) +
                      f" Backup: {backup}")
    return finish(ok=True, status="published")
