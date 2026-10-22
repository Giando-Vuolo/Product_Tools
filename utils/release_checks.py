"""Pure release-readiness rules (no Streamlit, no network, no env access).

One function per rule, all over plain data. Pages/glue fetch the data and call
exactly the rule they need; this module never performs any I/O.
"""
import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"
SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}

APPROVAL_FIELD = "customfield_14202"
APPROVAL_READY = "Ready to release"
DOC_TABLE_FIELD = "customfield_25263"
NOT_RELEVANT_FIX_VERSION = "DIGI:HUB Not release relevant"
FIX_VERSION_RE = re.compile(r"^DIGITAL:HUB \d+\.\d+\.\d+$")
CHECKED_ISSUE_TYPES = ("Bug", "Improvement", "Story", "Task")

DOC_ROWS = (
    "Tested in PRE",
    "E2E Coverage",
    "Tested with PROD data volume",
    "Test results added in Jira",
    "Critical modification",
    "Load test completed",
    "Testing with interfaces completed",
    "Feature flag implemented",
    "Downtime required",
    "Libraries and Service Details",
    "Config Server Modifications",
    "Schema Changes",
    "Data Regularization Details",
    "Special Deployment Steps",
    "Production Monitoring (How to monitor success in PROD)",
    "Rollback Method",
)
PLACEHOLDERS = frozenset({"", "lorem ipsum", "yes-no-n/a", "tbd"})
NEGATIVE_VALUES = frozenset({"n/a", "na", "no", "none", "-"})

# Ordered workflow statuses; UNVERIFIED against the RECALLTWO workflow, configurable by editing.
# Unknown status counts as "before" (WARN).
STATUS_ORDER = (
    "Open", "To Do", "Backlog", "Refinement", "Ready for Development", "In Progress",
    "In Review", "Code Review", "Ready for Test", "In Test", "Acceptance Test",
    "Ready to release", "Released", "Done", "Closed",
)
LATE_STATUS_FROM = "Acceptance Test"
CLOSED_STATUS = "Closed"
UNASSIGNED_MENTIONS = ("[~UGN44UN]", "[~FC0KEWC]", "[~APMKRYI]")
# Bare "No" in "Tested in PRE" + at least one Jira comment counts as explained (flag for review).
PRE_COMMENT_COUNTS_AS_EXPLANATION = True

RULE_SCOPE = "Scope"
RULE_APPROVAL = "Approval"
RULE_DOC = "Documentation table"
RULE_PRE = "PRE testing"
RULE_UNASSIGNED = "Unassigned"
UNASSIGNED_OWNER = "Unassigned"


@dataclass(frozen=True)
class Issue:
    key: str
    summary: str = ""
    issuetype: str = ""
    status: str = ""
    assignee: Optional[str] = None
    fix_versions: tuple = ()
    approval: Optional[str] = None
    doc_table_raw: str = ""
    comment_count: int = 0


@dataclass(frozen=True)
class DocTable:
    rows: dict = field(default_factory=dict)  # canonical row name -> cleaned value
    missing_rows: tuple = ()
    present: bool = False


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    issue_key: str
    reason: str
    assignee: Optional[str] = None
    summary: str = ""


@dataclass(frozen=True)
class CriticalRow:
    issue_key: str
    summary: str
    assignee: Optional[str]
    reasons: tuple


# ------------------------------------------------------------------ conversion
def _option_value(v) -> Optional[str]:
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        return v.get("value") or v.get("name")
    return v if isinstance(v, str) and v.strip() else None


def issue_from_jira(raw: dict) -> Issue:
    f = (raw or {}).get("fields") or {}
    assignee = f.get("assignee")
    name = (assignee.get("displayName") or assignee.get("name")) if isinstance(assignee, dict) else None
    comment = f.get("comment") or {}
    comments = comment.get("comments") or []
    count = max(len(comments), int(comment.get("total", 0) or 0))
    return Issue(
        key=raw.get("key", ""),
        summary=f.get("summary") or "",
        issuetype=((f.get("issuetype") or {}).get("name")) or "",
        status=((f.get("status") or {}).get("name")) or "",
        assignee=name or None,
        fix_versions=tuple(v.get("name", "") for v in (f.get("fixVersions") or []) if isinstance(v, dict)),
        approval=_option_value(f.get(APPROVAL_FIELD)),
        doc_table_raw=f.get(DOC_TABLE_FIELD) or "",
        comment_count=count,
    )


# --------------------------------------------------------------- table parsing
def _clean_cell(text: str) -> str:
    text = re.sub(r"\{color(?::[^}]*)?\}", "", text or "")
    text = re.sub(r"\{code(?::[^}]*)?\}|\{noformat\}", "", text)
    return " ".join(text.replace("\r", "\n").split())


def _canonical_row(name: str) -> Optional[str]:
    n = _clean_cell(name).casefold().strip("* _")
    for canon in DOC_ROWS:
        c = canon.casefold()
        if n == c or n == c.split("(")[0].strip():
            return canon
    return None


def parse_doc_table(raw: str) -> DocTable:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"(?m)^[ \t]*\|(?!\|)", text)[1:]
    rows = {}
    for chunk in chunks:
        name, sep, rest = chunk.partition("|")
        canon = _canonical_row(name)
        if canon is None or canon in rows:
            continue
        value = rest.rstrip().rstrip("|") if sep else ""
        rows[canon] = _clean_cell(value)
    present = bool(rows)
    missing = tuple(r for r in DOC_ROWS if r not in rows)
    return DocTable(rows, missing, present)


def is_placeholder(value: Optional[str]) -> bool:
    v = " ".join((value or "").split()).casefold()
    return v in PLACEHOLDERS or v.startswith("lorem ipsum")


def _yn(value: Optional[str]) -> str:
    m = re.match(r"[a-z/]+", (value or "").strip().casefold())
    return m.group(0) if m else ""


def _is_filled(value: Optional[str]) -> bool:
    return not is_placeholder(value)


def _not_na(value: Optional[str]) -> bool:
    v = " ".join((value or "").split()).casefold()
    return _is_filled(value) and v not in NEGATIVE_VALUES and _yn(value) not in NEGATIVE_VALUES


def _table(issue: Issue) -> DocTable:
    return parse_doc_table(issue.doc_table_raw)


def _table_problems(t: DocTable) -> list:
    """Reasons why the table is incomplete (empty list = complete)."""
    if not t.present:
        return ["Documentation table missing"]
    problems = []
    if t.missing_rows:
        problems.append("Missing rows: " + ", ".join(t.missing_rows))
    bad = [r for r in DOC_ROWS if r in t.rows and is_placeholder(t.rows[r])]
    if bad:
        problems.append("Empty or placeholder values: " + ", ".join(bad))
    return problems


def _table_filled(t: DocTable) -> bool:
    return any(_is_filled(v) for v in t.rows.values())


# ----------------------------------------------------------------- status/date
def is_late_status(status: str) -> bool:
    order = [s.casefold() for s in STATUS_ORDER]
    s = (status or "").strip().casefold()
    if s not in order:
        return False
    return order.index(s) >= order.index(LATE_STATUS_FROM.casefold())


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y")


def parse_freeze_date(text: Optional[str]) -> Optional[date]:
    t = " ".join((text or "").split())
    m = re.search(r"\d{4}-\d{2}-\d{2}", t)
    if m:
        try:
            return datetime.strptime(m.group(0), "%Y-%m-%d").date()
        except ValueError:
            return None
    for fmt in _DATE_FORMATS[1:]:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def extract_freeze_date(storage: str) -> Optional[date]:
    """Read the value of a `Freeze date` row (case-insensitive) from Confluence storage."""
    for m in re.finditer(r"<t[hd]\b[^>]*>(.*?)</t[hd]>\s*<t[hd]\b[^>]*>(.*?)</t[hd]>", storage or "", re.S):
        if _plain(m.group(1)).casefold() == "freeze date":
            tm = re.search(r'<time\b[^>]*datetime="([^"]+)"', m.group(2))
            return parse_freeze_date(tm.group(1) if tm else _plain(m.group(2)))
    return None


def freeze_passed(freeze: Optional[date], today: date) -> Optional[bool]:
    """True only after the end of the freeze day; None when there is no freeze date."""
    if freeze is None:
        return None
    return today > freeze


# ----------------------------------------------------------------------- scope
def select_in_scope(issues: list) -> list:
    return [
        i for i in issues
        if i.issuetype in CHECKED_ISSUE_TYPES and any(FIX_VERSION_RE.match(v or "") for v in i.fix_versions)
    ]


def _finding(rule, severity, issue, reason) -> Finding:
    return Finding(rule, severity, issue.key, reason, issue.assignee, issue.summary)


def check_scope(issues: list) -> list:
    out = []
    for i in issues:
        if i.issuetype not in CHECKED_ISSUE_TYPES or NOT_RELEVANT_FIX_VERSION not in i.fix_versions:
            continue
        reasons = []
        if (i.approval or "").strip() == APPROVAL_READY:
            reasons.append(f"has Approval '{APPROVAL_READY}'")
        if _table_filled(_table(i)):
            reasons.append("has a filled documentation table")
        if reasons:
            out.append(_finding(RULE_SCOPE, WARN, i,
                                f"Probably misclassified as '{NOT_RELEVANT_FIX_VERSION}': " + " and ".join(reasons)))
    return out


# -------------------------------------------------------------------- approval
def check_approval(issues: list, freeze: Optional[date], today: date) -> list:
    out = []
    passed = freeze_passed(freeze, today)
    for i in select_in_scope(issues):
        if (i.approval or "").strip() != APPROVAL_READY:
            if passed:
                out.append(_finding(RULE_APPROVAL, ERROR, i,
                                    f"Missing '{APPROVAL_READY}' after freeze date {freeze.isoformat()}: needs freeze exception"))
            else:
                out.append(_finding(RULE_APPROVAL, WARN, i, f"Missing '{APPROVAL_READY}'"))
        else:
            problems = _table_problems(_table(i))
            if problems:
                out.append(_finding(RULE_APPROVAL, ERROR, i,
                                    "Approved but documentation table incomplete: " + "; ".join(problems)))
    return out


# ------------------------------------------------------------------- doc table
def check_doc_table(issues: list) -> list:
    out = []
    for i in select_in_scope(issues):
        t = _table(i)
        sev = ERROR if is_late_status(i.status) else WARN
        for p in _table_problems(t):
            out.append(_finding(RULE_DOC, sev, i, p))
        if not t.present:
            continue
        schema, rollback = t.rows.get("Schema Changes"), t.rows.get("Rollback Method")
        if _not_na(schema) and _yn(rollback) in ("n/a", "na"):
            out.append(_finding(RULE_DOC, WARN, i, "Schema Changes declared but Rollback Method is N/A"))
        if _yn(t.rows.get("Critical modification")) == "yes":
            for name in ("Rollback Method", "Production Monitoring (How to monitor success in PROD)"):
                if is_placeholder(t.rows.get(name)):
                    out.append(_finding(RULE_DOC, WARN, i, f"Critical modification=Yes but '{name}' is empty"))
    return out


# ------------------------------------------------------------------------- PRE
def _pre_explained(value: str, comment_count: int) -> bool:
    rest = re.sub(r"^no\b[\s\-\u2013\u2014:,.;]*", "", value.strip(), flags=re.I)
    if re.search(r"explained in comments?", rest, re.I):
        return comment_count >= 1
    if rest and not is_placeholder(rest):
        return True
    return PRE_COMMENT_COUNTS_AS_EXPLANATION and comment_count >= 1


def check_pre_testing(issues: list) -> list:
    out = []
    for i in select_in_scope(issues):
        value = _table(i).rows.get("Tested in PRE")
        if value is None or _yn(value) != "no":
            continue
        if _pre_explained(value, i.comment_count):
            out.append(_finding(RULE_PRE, INFO, i, f"Not tested in PRE, explained: {value}"))
        else:
            out.append(_finding(RULE_PRE, ERROR, i, f"Not tested in PRE and no explanation in the table or Jira comments: {value}"))
    return out


# ------------------------------------------------------------------ unassigned
def check_unassigned(issues: list) -> list:
    out = []
    for i in select_in_scope(issues):
        if i.assignee:
            continue
        if i.status.strip() == CLOSED_STATUS:
            out.append(_finding(RULE_UNASSIGNED, INFO, i, "No assignee (issue is Closed)"))
        else:
            out.append(_finding(RULE_UNASSIGNED, ERROR, i, f"No assignee (status: {i.status or 'unknown'})"))
    return out


# -------------------------------------------------------------------- critical
def find_critical_changes(issues: list) -> list:
    rows = []
    for i in select_in_scope(issues):
        r = _table(i).rows
        reasons = []

        def val(name):
            v = r.get(name)
            return v if _is_filled(v) else None

        crit = _yn(val("Critical modification")) == "yes"
        if crit:
            reasons.append("Critical modification = Yes")
        if _yn(val("Downtime required")) == "yes":
            reasons.append("Downtime required = Yes")
        if _not_na(r.get("Schema Changes")):
            reasons.append(f"Schema Changes: {r['Schema Changes']}")
        if _not_na(r.get("Data Regularization Details")):
            reasons.append(f"Data Regularization Details: {r['Data Regularization Details']}")
        if _not_na(r.get("Special Deployment Steps")):
            reasons.append(f"Special Deployment Steps: {r['Special Deployment Steps']}")
        if _yn(val("Config Server Modifications")) == "yes":
            reasons.append("Config Server Modifications = Yes")
        if _yn(val("Tested in PRE")) == "no":
            reasons.append("Tested in PRE = No")
        if crit and _yn(val("Load test completed")) == "no":
            reasons.append("Load test completed = No with Critical modification = Yes")
        if reasons:
            rows.append(CriticalRow(i.key, i.summary, i.assignee, tuple(reasons)))
    return rows


# ----------------------------------------------------------------- aggregation
def sort_findings(findings: list) -> list:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.issue_key, f.rule))


def run_all(issues: list, freeze: Optional[date], today: date) -> dict:
    return {
        RULE_SCOPE: check_scope(issues),
        RULE_APPROVAL: check_approval(issues, freeze, today),
        RULE_DOC: check_doc_table(issues),
        RULE_PRE: check_pre_testing(issues),
        RULE_UNASSIGNED: check_unassigned(issues),
        "Critical changes": find_critical_changes(issues),
    }


def summarize(results: dict) -> dict:
    """results: output of run_all (Critical changes are not findings and are skipped)."""
    counts = {ERROR: 0, WARN: 0, INFO: 0}
    owners: dict = {}
    for items in results.values():
        for f in items:
            if not isinstance(f, Finding):
                continue
            counts[f.severity] += 1
            o = owners.setdefault(f.assignee or UNASSIGNED_OWNER, {ERROR: 0, WARN: 0, INFO: 0})
            o[f.severity] += 1
    semaphore = "RED" if counts[ERROR] else ("AMBER" if counts[WARN] else "GREEN")
    return {"semaphore": semaphore, "counts": counts, "per_owner": owners}


def notification_texts(results: dict) -> dict:
    """Copy-ready English text per rule that has ERROR/WARN findings."""
    texts = {}
    for rule, items in results.items():
        fs = sort_findings([f for f in items if isinstance(f, Finding) and f.severity != INFO])
        if not fs:
            continue
        lines = []
        if rule == RULE_UNASSIGNED:
            lines.append(" ".join(UNASSIGNED_MENTIONS))
            lines.append("These release issues have no assignee. Please assign an owner:")
        else:
            lines.append(f"Release readiness - {rule}: please review the following issues:")
        for f in fs:
            who = f" ({f.assignee})" if f.assignee else ""
            lines.append(f"* {f.issue_key}{who} [{f.severity}] {f.reason}")
        texts[rule] = "\n".join(lines)
    return texts
