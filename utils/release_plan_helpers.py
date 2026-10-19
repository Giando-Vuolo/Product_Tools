"""Pure logic for the Release Plan "Post-actions" feature.

No network and no Streamlit here: everything is testable with fixtures.
The merge into Confluence storage format is an offset-based string splice so
that all untouched content stays byte-for-byte identical.
"""
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

DEFAULT_FIX_VERSION_PREFIX = "DIGITAL:HUB "
JIRA_PROJECT = "RECALLTWO"
ALLOWED_SPACE_KEY = "RECALLTWO"
ALLOWED_PARENT_ID = "7177194568"
FORBIDDEN_PAGE_IDS = frozenset({"8307791929"})  # template page
ISSUE_TYPES = ("Bug", "Improvement", "Story", "Task")
REQUIRED_ENV = ("JIRA_SERVER", "JIRA_API_TOKEN", "CONFLUENCE_SERVER", "CONFLUENCE_API_TOKEN")

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^\s*(?:[*#-]+\s+)?post-action:\s*(.*?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PostAction:
    issue_key: str
    text: str
    author: str
    source: str  # "description" | "comment:<id>"


@dataclass(frozen=True)
class ExistingTask:
    task_id: Optional[int]
    status: str
    issue_key: Optional[str]
    text: str


@dataclass
class GuardResult:
    ok: bool
    errors: list = field(default_factory=list)
    page_id: str = ""
    title: str = ""
    found_fix_version: Optional[str] = None


@dataclass
class MergePlan:
    new_actions: list
    skipped: list
    new_storage: str
    new_task_ids: list


# ---------------------------------------------------------------- input helpers
def missing_config(env: Mapping) -> list:
    return [name for name in REQUIRED_ENV if not str(env.get(name, "") or "").strip()]


def validate_version(version: str) -> str:
    v = (version or "").strip()
    if not VERSION_RE.match(v):
        raise ValueError("Version must be numeric X.Y.Z, e.g. 35.0.0")
    return v


def build_fix_version(version: str, prefix: str = DEFAULT_FIX_VERSION_PREFIX) -> str:
    return f"{prefix}{version}"


def build_release_jql(version: str, prefix: str = DEFAULT_FIX_VERSION_PREFIX) -> str:
    return (
        f"project = {JIRA_PROJECT} AND issuetype in ({', '.join(ISSUE_TYPES)}) "
        f'AND fixVersion = "{build_fix_version(version, prefix)}"'
    )


def parse_page_id(target: str) -> str:
    t = (target or "").strip()
    if re.fullmatch(r"\d+", t):
        return t
    m = re.search(r"[?&]pageId=(\d+)", t) or re.search(r"/pages/(\d+)(?:/|$|\?|#)", t)
    if m:
        return m.group(1)
    raise ValueError("Could not find a page ID. Enter a numeric page ID or a Confluence page URL.")


# --------------------------------------------------------------------- parsing
def strip_wiki_markup(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\{code(?::[^}]*)?\}|\{noformat\}", "", text)
    text = re.sub(r"\{\{(.*?)\}\}", r"\1", text)
    text = re.sub(r"\[([^\]|\n]+)\|[^\]\n]*\]", r"\1", text)
    text = re.sub(r"\[([^\]\n]+)\]", r"\1", text)
    out = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*[*#-]+\s+", "", line)
        for ch in ("*", "_", "+", "-"):
            e = re.escape(ch)
            line = re.sub(rf"(?<!\w){e}(\S(?:.*?\S)?){e}(?!\w)", r"\1", line)
        out.append(line)
    return "\n".join(out)


def parse_post_actions(text: str) -> list:
    result = []
    for line in strip_wiki_markup(text).split("\n"):
        m = TAG_RE.match(line)
        if m and m.group(1).strip():
            result.append(m.group(1).strip())
    return result


def _display_name(user) -> str:
    if isinstance(user, dict):
        return user.get("displayName") or user.get("name") or "Unknown"
    return "Unknown"


def extract_actions_from_issue(issue: dict) -> list:
    key = issue.get("key", "")
    fields = issue.get("fields") or {}
    actions = []
    reporter = _display_name(fields.get("reporter"))
    for t in parse_post_actions(fields.get("description") or ""):
        actions.append(PostAction(key, t, reporter, "description"))
    comments = (fields.get("comment") or {}).get("comments") or []
    for c in comments:
        author = _display_name(c.get("author"))
        for t in parse_post_actions(c.get("body") or ""):
            actions.append(PostAction(key, t, author, f"comment:{c.get('id', '')}"))
    return actions


def extract_actions(issues: list) -> list:
    out = []
    for issue in issues:
        out.extend(extract_actions_from_issue(issue))
    return out


def normalise_text(text: str) -> str:
    return " ".join((text or "").split()).casefold()


# -------------------------------------------------------------- storage scanning
def assert_well_formed(storage: str) -> None:
    """Validation only (works on a throwaway copy)."""
    copy = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)\w+;", "&amp;", storage)
    wrapped = f'<root xmlns:ac="urn:ac" xmlns:ri="urn:ri" xmlns:at="urn:at">{copy}</root>'
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        raise ValueError(f"Page storage is not well-formed XML: {e}")


def _plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def find_post_actions_section(storage: str) -> tuple:
    """Return (heading_start, heading_end, section_end)."""
    headings = list(re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", storage, re.S))
    matches = []
    for i, m in enumerate(headings):
        title = re.sub(r"^[\d.]+\s*", "", _plain(m.group(2))).casefold()
        if title in ("post-actions", "post actions"):
            matches.append(i)
    if not matches:
        raise ValueError("Post-actions section not found on the page. Nothing was written.")
    if len(matches) > 1:
        raise ValueError("More than one Post-actions heading found on the page. Nothing was written.")
    idx = matches[0]
    h = headings[idx]
    level = int(h.group(1))
    section_end = len(storage)
    for nxt in headings[idx + 1:]:
        if int(nxt.group(1)) <= level:
            section_end = nxt.start()
            break
    return h.start(), h.end(), section_end


def find_all_tasks(storage: str) -> list:
    """Return [(start, end, ExistingTask)] for every <ac:task> on the page."""
    token = re.compile(r"<ac:task(?=[\s>])[^>]*>|</ac:task>")
    result = []
    depth = 0
    start = None
    for m in token.finditer(storage):
        if m.group(0).startswith("</"):
            if depth > 0:
                depth -= 1
                if depth == 0:
                    result.append((start, m.end(), _parse_task(storage[start:m.end()])))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return result


def _parse_task(xml: str) -> ExistingTask:
    mid = re.search(r"<ac:task-id>\s*(\d+)\s*</ac:task-id>", xml)
    mst = re.search(r"<ac:task-status>\s*(.*?)\s*</ac:task-status>", xml, re.S)
    mbody = re.search(r"<ac:task-body>(.*)</ac:task-body>", xml, re.S)
    body = mbody.group(1) if mbody else ""
    mkey = re.search(r'<a\s[^>]*href="[^"]*/browse/([A-Z][A-Z0-9_]+-\d+)"', body)
    key = mkey.group(1) if mkey else None
    text = _plain(body)
    # text is kept whole (incl. "KEY (author): " prefix); see _already_present.
    return ExistingTask(int(mid.group(1)) if mid else None, mst.group(1) if mst else "", key, text)


def find_task_list_in_section(storage: str, start: int, end: int):
    """Span (open_start, close_start) of the first top-level <ac:task-list> in [start, end)."""
    token = re.compile(r"<ac:task-list(?=[\s>])[^>]*>|</ac:task-list>")
    depth = 0
    open_start = None
    for m in token.finditer(storage, start, end):
        if m.group(0).startswith("</"):
            if depth > 0:
                depth -= 1
                if depth == 0:
                    return open_start, m.start()
        else:
            if depth == 0:
                open_start = m.start()
            depth += 1
    return None


def extract_release_list_fix_versions(storage: str) -> list:
    versions = []
    for macro in re.finditer(
        r'<ac:structured-macro\b[^>]*ac:name="jira"[^>]*>(.*?)</ac:structured-macro>', storage, re.S
    ):
        for p in re.finditer(
            r'<ac:parameter\b[^>]*ac:name="jqlQuery"[^>]*>(.*?)</ac:parameter>', macro.group(1), re.S
        ):
            jql = html.unescape(re.sub(r"<[^>]+>", "", p.group(1)))
            for fm in re.finditer(r'fixVersion\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(\S+))', jql):
                versions.append((fm.group(1) or fm.group(2) or fm.group(3)).strip())
    return versions


# ------------------------------------------------------------------------ guard
def check_target_guard(page: dict, version: str, prefix: str = DEFAULT_FIX_VERSION_PREFIX) -> GuardResult:
    page = page or {}
    pid = str(page.get("id", "") or "")
    if page.get("error"):
        return GuardResult(False, [f"Page {pid or '?'} not found or not accessible: {page['error']}"], pid, "")
    title = page.get("title", "")
    errors = []
    if pid in FORBIDDEN_PAGE_IDS:
        errors.append(f"Template page {pid} can never be written.")
    space = page.get("space_key")
    if space != ALLOWED_SPACE_KEY:
        errors.append(f"Page is in space {space}, expected {ALLOWED_SPACE_KEY}.")
    ancestors = [str(a) for a in (page.get("ancestor_ids") or [])]
    if pid == ALLOWED_PARENT_ID:
        errors.append("Target is the parent page itself.")
    elif str(page.get("parent_id") or "") != ALLOWED_PARENT_ID:
        if ALLOWED_PARENT_ID in ancestors:
            errors.append(f"Page is a grandchild (not a direct child) of {ALLOWED_PARENT_ID}.")
        else:
            errors.append(f"Page is not under {ALLOWED_PARENT_ID}.")
    expected = build_fix_version(version, prefix)
    found = extract_release_list_fix_versions(page.get("storage", "") or "")
    found_str = None
    if not found:
        errors.append(f"Release List Jira macro/JQL not found; expected fixVersion '{expected}'.")
    else:
        found_str = ", ".join(found)
        if expected not in [f.strip() for f in found]:
            errors.append(f"fixVersion mismatch: expected '{expected}', found '{found_str}'.")
    return GuardResult(not errors, errors, pid, title, found_str)


# ------------------------------------------------------------------- rendering
def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_task(task_id: int, action: PostAction, jira_server: str) -> str:
    base = _esc((jira_server or "").rstrip("/"))
    key = _esc(action.issue_key)
    return (
        f"<ac:task><ac:task-id>{task_id}</ac:task-id><ac:task-status>incomplete</ac:task-status>"
        f'<ac:task-body><a href="{base}/browse/{key}">{key}</a> '
        f"({_esc(action.author)}): {_esc(action.text)}</ac:task-body></ac:task>"
    )


def render_new_task_list(tasks_xml: str) -> str:
    return f'<ul><li style="list-style-type: none;"><ac:task-list>{tasks_xml}</ac:task-list></li></ul>'


# ----------------------------------------------------------------------- merge
def _already_present(existing: list, action: PostAction) -> bool:
    """Author-independent match: existing text is "KEY (<author>): <text>".

    Author may contain ')' or '):', so instead of stripping the prefix we require
    it to start with "KEY (" and end with "): <action text>".
    """
    key = normalise_text(action.issue_key)
    tail = "): " + normalise_text(action.text)
    for k, full in existing:
        if k == action.issue_key and full.startswith(key + " (") and full.endswith(tail):
            return True
    return False


def plan_merge(storage: str, actions: list, jira_server: str) -> MergePlan:
    assert_well_formed(storage)
    h_start, h_end, s_end = find_post_actions_section(storage)
    tasks = find_all_tasks(storage)
    max_id = max((t.task_id for _, _, t in tasks if t.task_id is not None), default=0)
    existing = [
        (t.issue_key, normalise_text(t.text))
        for s, e, t in tasks
        if t.issue_key and h_end <= s < s_end
    ]
    seen = set()
    new, skipped = [], []
    for a in actions:
        ident = (a.issue_key, normalise_text(a.text))
        if ident in seen or _already_present(existing, a):
            skipped.append(a)
        else:
            seen.add(ident)
            new.append(a)
    if not new:
        return MergePlan([], skipped, storage, [])
    ids = list(range(max_id + 1, max_id + 1 + len(new)))
    tasks_xml = "".join(render_task(i, a, jira_server) for i, a in zip(ids, new))
    tl = find_task_list_in_section(storage, h_end, s_end)
    if tl:
        offset, insert = tl[1], tasks_xml
    else:
        offset, insert = h_end, render_new_task_list(tasks_xml)
    new_storage = storage[:offset] + insert + storage[offset:]
    assert_well_formed(new_storage)
    return MergePlan(new, skipped, new_storage, ids)


# ------------------------------------------------------- preview / publish flow
def build_preview(page: dict, issues: list, version: str, prefix: str, jira_server: str) -> dict:
    """Never writes. Returns {"guard", "plan", "error"}."""
    guard = check_target_guard(page, version, prefix)
    if not guard.ok:
        return {"guard": guard, "plan": None, "error": None}
    try:
        plan = plan_merge(page.get("storage", ""), extract_actions(issues), jira_server)
    except ValueError as e:
        return {"guard": guard, "plan": None, "error": str(e)}
    return {"guard": guard, "plan": plan, "error": None}


def publish(
    get_page: Callable[[], dict],
    update_page: Callable[[str, str, int, str], dict],
    actions: list,
    version: str,
    prefix: str,
    jira_server: str,
) -> dict:
    """Re-fetch, re-guard, re-plan, then (only if needed) write once.

    update_page(page_id, title, new_version, storage) -> {"ok": True} | {"error": str}
    """
    page = get_page()
    guard = check_target_guard(page, version, prefix)
    if not guard.ok:
        return {"ok": False, "added": 0, "skipped": 0, "error": " ".join(guard.errors)}
    try:
        plan = plan_merge(page.get("storage", ""), actions, jira_server)
    except ValueError as e:
        return {"ok": False, "added": 0, "skipped": 0, "error": str(e)}
    if not plan.new_actions:
        return {"ok": True, "added": 0, "skipped": len(plan.skipped), "error": None}
    res = update_page(guard.page_id, page.get("title", ""), int(page.get("version", 0)) + 1, plan.new_storage)
    if not res or res.get("error") or not res.get("ok"):
        return {"ok": False, "added": 0, "skipped": len(plan.skipped),
                "error": (res or {}).get("error", "Unknown error while updating the page")}
    return {"ok": True, "added": len(plan.new_actions), "skipped": len(plan.skipped), "error": None}
