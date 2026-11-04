"""Span-only publishing of Release readiness data into the sandbox Release Plan page.

Pure logic + injected I/O (get_page / update_page). No Streamlit, no network here.
Only the "Critical changes" section content and the "Release readiness:" line are
ever replaced; everything else stays byte-for-byte identical.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from utils import release_plan_helpers as rp

BACKUP_DIR = Path("data/confluence_backups")
CRITICAL_TITLES = ("critical changes",)
READINESS_PREFIX = "release readiness:"
SEMAPHORE_LABEL = {"RED": "🔴 RED", "AMBER": "🟠 AMBER", "GREEN": "🟢 GREEN"}
NONE_PARAGRAPH = "<p>No critical changes for this release.</p>"
KINDS = ("critical", "readiness")

_HEADING_RE = re.compile(r"<h[1-6]\b[^>]*>.*?</h[1-6]>", re.S)
_PARAGRAPH_RE = re.compile(r"<p\b[^>]*>.*?</p>", re.S)


class PublishRefused(Exception):
    """A publish step was refused; nothing was written."""


@dataclass(frozen=True)
class SplicePlan:
    kind: str
    page_id: str
    title: str
    base_version: int
    start: int
    end: int
    old_fragment: str
    new_fragment: str
    new_storage: str
    changed: bool


# ------------------------------------------------------------------- allowlist
def assert_publish_allowed(page_id) -> None:
    """Strict: only the sandbox page may be written. No network."""
    pid = "" if page_id is None else str(page_id)
    if pid != rp.SANDBOX_WRITE_PAGE_ID:
        raise PublishRefused(
            f"Publishing is only allowed on page {rp.SANDBOX_WRITE_PAGE_ID}, not {pid or '?'}."
        )
    try:
        rp.check_write_allowed(pid, is_sandbox=True, target="confluence")
    except PermissionError as e:
        raise PublishRefused(str(e))


# -------------------------------------------------------------------- locators
def find_critical_span(storage: str) -> tuple:
    """(start, end): content strictly between the Critical changes heading and the next heading."""
    try:
        _, h_end, section_end = rp.find_heading_section(
            storage, CRITICAL_TITLES, label="Critical changes", stop="any"
        )
    except ValueError as e:
        raise PublishRefused(str(e))
    return h_end, section_end


def find_readiness_span(storage: str) -> tuple:
    """(start, end) of the single <p>...</p> whose text starts with 'Release readiness:'."""
    found = [
        m for m in _PARAGRAPH_RE.finditer(storage)
        if rp._normalise_heading(rp._plain(m.group(0))).startswith(READINESS_PREFIX)
    ]
    if not found:
        raise PublishRefused("Release readiness line not found on the page. Nothing was written.")
    if len(found) > 1:
        raise PublishRefused("More than one Release readiness line found on the page. Nothing was written.")
    return found[0].start(), found[0].end()


_LOCATORS = {"critical": find_critical_span, "readiness": find_readiness_span}


# ------------------------------------------------------------------- renderers
def render_critical_table(rows: list, jira_server: str) -> str:
    if not rows:
        return NONE_PARAGRAPH
    base = rp._esc((jira_server or "").rstrip("/"))
    out = ["<table><tbody><tr><th>Issue</th><th>Summary</th><th>Assignee</th><th>Reasons</th></tr>"]
    for r in rows:
        key = rp._esc(r.issue_key)
        out.append(
            f'<tr><td><a href="{base}/browse/{key}">{key}</a></td>'
            f"<td>{rp._esc(r.summary or '')}</td>"
            f"<td>{rp._esc(r.assignee or 'Unassigned')}</td>"
            f"<td>{rp._esc('; '.join(r.reasons))}</td></tr>"
        )
    out.append("</tbody></table>")
    fragment = "".join(out)
    rp.assert_well_formed(fragment)
    return fragment


def render_readiness_line(summary: dict, checked_at: str) -> str:
    c = summary["counts"]
    fragment = (
        f"<p>🚦 <strong>Release readiness:</strong> {SEMAPHORE_LABEL[summary['semaphore']]} — "
        f"{c['ERROR']} errors · {c['WARN']} warnings · {c['INFO']} info — "
        f"checked {(checked_at or '')[:16]}</p>"
    )
    rp.assert_well_formed(fragment)
    return fragment


# ------------------------------------------------------------------------ plan
def _headings(storage: str) -> list:
    return _HEADING_RE.findall(storage)


def plan_splice(page: dict, kind: str, new_fragment: str, *, version: str, source_version: str,
                label: str, parent_id: str) -> SplicePlan:
    page = page or {}
    pid = str(page.get("id", "") or "")
    assert_publish_allowed(pid)
    if kind not in _LOCATORS:
        raise PublishRefused(f"Unknown publish kind '{kind}'.")
    guard = rp.check_target_guard(
        page, version, label, parent_id=parent_id,
        accepted_versions=(source_version,) if source_version and source_version != version else (),
    )
    if not guard.ok:
        raise PublishRefused(" ".join(guard.errors))
    storage = page.get("storage", "") or ""
    try:
        rp.assert_well_formed(storage)
        rp.assert_well_formed(new_fragment)
    except ValueError as e:
        raise PublishRefused(str(e))
    start, end = _LOCATORS[kind](storage)
    new_storage = storage[:start] + new_fragment + storage[end:]
    try:
        rp.assert_well_formed(new_storage)
    except ValueError as e:
        raise PublishRefused(str(e))
    if _headings(new_storage) != _headings(storage):
        raise PublishRefused("Headings would change; refusing to publish.")
    return SplicePlan(
        kind, pid, page.get("title", ""), int(page.get("version", 0)), start, end,
        storage[start:end], new_fragment, new_storage, new_storage != storage,
    )


def write_backup(plan: SplicePlan, storage: str, *, backup_dir=BACKUP_DIR, now: Optional[datetime] = None) -> Path:
    now = now or datetime.now()
    d = Path(backup_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{plan.page_id}_v{plan.base_version}_{plan.kind}_{now:%Y%m%d-%H%M%S}.xml"
    path.write_text(storage, encoding="utf-8")
    return path


def verify_after_write(before: dict, plan: SplicePlan, after: dict) -> list:
    errors = []
    after = after or {}
    if after.get("error"):
        return [f"Re-read failed: {after['error']}"]
    old = before.get("storage", "") or ""
    new = after.get("storage", "") or ""
    if int(after.get("version", 0)) != plan.base_version + 1:
        errors.append(f"Version is {after.get('version')}, expected {plan.base_version + 1}.")
    if str(after.get("id", "")) != str(before.get("id", "")):
        errors.append("Page id changed.")
    if after.get("title") != before.get("title"):
        errors.append("Page title changed.")
    prefix, suffix = old[:plan.start], old[plan.end:]
    if not new.startswith(prefix):
        errors.append("Content before the replaced span changed.")
    if not new.endswith(suffix):
        errors.append("Content after the replaced span changed.")
    if len(new) != len(prefix) + len(plan.new_fragment) + len(suffix):
        errors.append("Unexpected page length after write.")
    elif new[len(prefix):len(new) - len(suffix)] != plan.new_fragment:
        errors.append("Replaced span does not match the published fragment.")
    if _headings(new) != _headings(old):
        errors.append("Headings changed.")
    return errors


# --------------------------------------------------------------------- publish
def _result(ok, status, error=None, backup=None, **extra) -> dict:
    d = {"ok": ok, "status": status, "error": error, "backup": backup}
    d.update(extra)
    return d


def publish_splice(*, page_id, kind: str, new_fragment: str, expected_version: int,
                   get_page: Callable[[str], dict], update_page: Callable[[str, str, int, str], dict],
                   version: str, source_version: str, label: str, parent_id: str,
                   backup_dir=BACKUP_DIR, now: Optional[datetime] = None) -> dict:
    try:
        assert_publish_allowed(page_id)
    except PublishRefused as e:
        return _result(False, "refused", str(e))
    page = get_page(str(page_id))
    if not page or page.get("error"):
        return _result(False, "refused", f"Page not accessible: {(page or {}).get('error', 'empty response')}")
    if int(page.get("version", 0)) != int(expected_version):
        return _result(False, "refused", "Page changed since preview; preview again before publishing.")
    try:
        plan = plan_splice(page, kind, new_fragment, version=version, source_version=source_version,
                           label=label, parent_id=parent_id)
    except PublishRefused as e:
        return _result(False, "refused", str(e))
    if not plan.changed:
        return _result(True, "unchanged")
    try:
        path = write_backup(plan, page.get("storage", ""), backup_dir=backup_dir, now=now)
    except OSError as e:
        return _result(False, "refused", f"Backup failed, nothing was written: {e}")
    new_version = plan.base_version + 1
    res = update_page(plan.page_id, plan.title, new_version, plan.new_storage)
    if not res or res.get("error") or not res.get("ok"):
        return _result(False, "failed", (res or {}).get("error", "Unknown error while updating the page"), str(path))
    after = get_page(plan.page_id)
    errors = verify_after_write(page, plan, after)
    if errors:
        return _result(False, "verification_failed", "Verification failed: " + " ".join(errors), str(path))
    return _result(True, "published", None, str(path), version=new_version)
