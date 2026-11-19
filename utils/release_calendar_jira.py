"""Release Calendar ↔ Jira: link each calendar release (X.Y.Z) to its Jira fixVersion.

Pure helpers (no Streamlit). Release names follow a template such as ``DIGITAL:HUB {version}``
(``RELEASE_NAME_TEMPLATE``): a calendar release is linked automatically to the Jira version whose name is
the template filled with its X.Y.Z (case and repeated spaces ignored). Jira versions with the same X.Y.Z
but another name are only offered first for a manual link. A manual link, saved locally in
``data/release_calendar_jira_links.json``, always wins over the automatic match: it links a release whose
Jira name differs or marks it as "not in Jira". The Confluence calendar is never written.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

import pandas as pd

from utils import release_calendar as rc

LINKS_FILE = Path("data/release_calendar_jira_links.json")
ENV_NAME_TEMPLATE = "RELEASE_NAME_TEMPLATE"
DEFAULT_NAME_TEMPLATE = "DIGITAL:HUB {version}"
VERSION_PLACEHOLDER = "{version}"

AUTO, MANUAL, NOT_IN_JIRA, NAME_DIFFERS, UNLINKED = "Auto", "Manual", "Not in Jira", "Name differs", "Not linked"

JIRA_COLUMNS = ["Jira id", "Jira version", "Version", "Jira release date", "Released", "Archived"]
LINK_COLUMNS = ["Expected name", "Jira id", "Jira version", "Jira release date", "Released", "Link",
                "Date check", "Days off"]


class JiraVersionsError(Exception):
    """Readable error for the UI."""


# --------------------------------------------------------------------------- name template

def validate_template(template: str) -> str:
    """The template stripped; it must contain {version} exactly once."""
    t = (template or "").strip()
    if t.count(VERSION_PLACEHOLDER) != 1:
        raise ValueError(f"The release name template must contain {VERSION_PLACEHOLDER} once, "
                         f"e.g. '{DEFAULT_NAME_TEMPLATE}'.")
    return t


def release_name(template: str, version: str) -> str:
    """'DIGITAL:HUB {version}' + '37.0.0' -> 'DIGITAL:HUB 37.0.0'."""
    return validate_template(template).replace(VERSION_PLACEHOLDER, version)


def _norm_name(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def template_regex(template: str) -> re.Pattern:
    """Regex matching names built from the template; group 'version' is the X.Y.Z."""
    head, tail = validate_template(template).split(VERSION_PLACEHOLDER)
    def lit(part):
        return r"\s+".join(re.escape(w) for w in part.split()) if part.strip() else ""
    sep_head = r"\s+" if head and head[-1].isspace() else ""
    sep_tail = r"\s+" if tail and tail[0].isspace() else ""
    return re.compile(rf"^\s*{lit(head)}{sep_head}(?P<version>\d+\.\d+\.\d+){sep_tail}{lit(tail)}\s*$",
                      re.IGNORECASE)


def follows_template(name: str, template: str) -> bool:
    return bool(template_regex(template).match(name or ""))


# --------------------------------------------------------------------------- Jira versions

def fetch_jira_versions(request: Callable, project: str) -> list:
    """All versions of ``project``. ``request(path)`` returns a requests-like response."""
    if not (project or "").strip():
        raise JiraVersionsError("No Jira project configured (RELEASE_PLAN_JIRA_PROJECT).")
    try:
        resp = request(f"/rest/api/2/project/{project.strip()}/versions")
    except Exception as exc:  # network errors from requests
        raise JiraVersionsError(f"Could not reach Jira: {exc.__class__.__name__}") from exc
    if resp.status_code in (401, 403):
        raise JiraVersionsError(f"Access denied to the Jira versions (HTTP {resp.status_code}). Check JIRA_API_TOKEN.")
    if resp.status_code == 404:
        raise JiraVersionsError(f"Jira project '{project}' not found (HTTP 404).")
    if resp.status_code != 200:
        raise JiraVersionsError(f"Jira versions download failed (HTTP {resp.status_code}).")
    try:
        body = resp.json()
    except ValueError as exc:
        raise JiraVersionsError("Jira did not return JSON for the project versions.") from exc
    if not isinstance(body, list):
        raise JiraVersionsError("Unexpected answer from Jira for the project versions.")
    return body


def jira_versions_dataframe(versions: list) -> pd.DataFrame:
    """One row per Jira version with the X.Y.Z found in its name ('' when none)."""
    rows = []
    for v in versions or []:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        name = str(v.get("name", "") or "")
        rd = v.get("releaseDate")
        rows.append({
            "Jira id": str(v["id"]),
            "Jira version": name,
            "Version": rc.extract_version(name),
            "Jira release date": pd.Timestamp(rd) if rd else pd.NaT,
            "Released": bool(v.get("released")),
            "Archived": bool(v.get("archived")),
        })
    return pd.DataFrame(rows, columns=JIRA_COLUMNS)


def version_url(jira_id: str, link_base: str = "", server: str = "", project: str = "") -> str:
    """Browser link to a Jira version: JIRA_VERSION_LINK_BASE + id, else <server>/projects/<P>/versions/<id>."""
    if not jira_id:
        return ""
    if link_base:
        return f"{link_base.rstrip('/')}/{jira_id}"
    if server and project:
        return f"{server.rstrip('/')}/projects/{project}/versions/{jira_id}"
    return ""


# --------------------------------------------------------------------------- manual links

def load_links(path: Path = LINKS_FILE) -> dict:
    """{calendar version: {"jira_id", "jira_name", "linked_by", "linked_at"}}; jira_id '' = not in Jira."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise JiraVersionsError(f"Could not read the saved Jira links ({path}): {exc}") from exc
    return {str(k): dict(v) for k, v in (data.get("links") or {}).items() if isinstance(v, dict)}


def save_links(links: Mapping, path: Path = LINKS_FILE) -> None:
    """Atomic write so a reader never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"links": dict(sorted(links.items(), key=lambda kv: rc.version_key(kv[0])))},
                         indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def set_link(links: Mapping, version: str, jira_id: str, jira_name: str, *, linked_by: str = "",
             now: Optional[datetime] = None) -> dict:
    """New dict with ``version`` linked to ``jira_id`` ('' marks it as not in Jira)."""
    out = dict(links)
    out[version] = {"jira_id": str(jira_id or ""), "jira_name": jira_name or "", "linked_by": linked_by,
                    "linked_at": (now or datetime.now()).isoformat(timespec="seconds")}
    return out


def clear_link(links: Mapping, version: str) -> dict:
    """New dict without the manual link: the release goes back to the automatic match."""
    return {k: v for k, v in links.items() if k != version}


# --------------------------------------------------------------------------- matching

def template_match(jira: pd.DataFrame, version: str, template: str) -> pd.DataFrame:
    """Jira versions named exactly as the template filled with ``version`` (case/spaces ignored)."""
    if jira.empty or not version:
        return jira.iloc[0:0]
    expected = _norm_name(release_name(template, version))
    return jira[[_norm_name(n) == expected for n in jira["Jira version"]]]


def same_number(jira: pd.DataFrame, version: str) -> pd.DataFrame:
    """Jira versions with the same X.Y.Z in their name, whatever the rest of the name."""
    if jira.empty or not version:
        return jira.iloc[0:0]
    return jira[jira["Version"] == version]


def _date_check(prod, jira_date) -> tuple:
    if pd.isna(jira_date):
        return "No Jira date", None
    if pd.isna(prod):
        return "No Prod date", None
    days = int((pd.Timestamp(jira_date) - pd.Timestamp(prod)).days)
    return ("Match", 0) if days == 0 else (f"Jira {'+' if days > 0 else ''}{days} d", days)


def link_releases(releases: pd.DataFrame, jira: pd.DataFrame, links: Mapping,
                  template: str = DEFAULT_NAME_TEMPLATE) -> pd.DataFrame:
    """``releases`` plus the expected Jira name, the linked Jira version, how it was linked and
    Prod Deploy vs Jira release date."""
    validate_template(template)
    out = releases.copy()
    by_id = jira.set_index("Jira id") if not jira.empty else None
    rows = []
    for version, prod in zip(out["Version"], out.get("Prod Deploy", pd.Series([pd.NaT] * len(out)))):
        manual = links.get(version)
        match, how = None, UNLINKED
        expected = release_name(template, version)
        if manual is not None:
            jid = manual.get("jira_id", "")
            if not jid:
                how = NOT_IN_JIRA
            elif by_id is not None and jid in by_id.index:
                match, how = by_id.loc[jid], MANUAL
            else:  # saved link to a version that is gone (deleted or other project)
                how = f"{MANUAL} (missing in Jira)"
                match = pd.Series({"Jira version": manual.get("jira_name", ""), "Jira release date": pd.NaT,
                                   "Released": False}, name=jid)
        else:
            exact = template_match(jira, version, template)
            if len(exact) >= 1:  # Jira names are unique per project, so at most one in practice
                match, how = exact.iloc[0].copy(), AUTO
                match.name = exact.iloc[0]["Jira id"]
            elif not same_number(jira, version).empty:
                how = NAME_DIFFERS
        if match is None:
            rows.append({"Expected name": expected, "Jira id": "", "Jira version": "", "Jira release date": pd.NaT, "Released": None,
                         "Link": how, "Date check": "", "Days off": None})
            continue
        check, days = _date_check(prod, match["Jira release date"])
        rows.append({"Expected name": expected, "Jira id": str(match.name), "Jira version": match["Jira version"],
                     "Jira release date": match["Jira release date"], "Released": bool(match["Released"]),
                     "Link": how, "Date check": check, "Days off": days})
    extra = pd.DataFrame(rows, columns=LINK_COLUMNS, index=out.index)
    extra["Days off"] = extra["Days off"].astype("Int64")
    return pd.concat([out, extra], axis=1)


def link_warnings(linked: pd.DataFrame, today=None) -> list:
    """Upcoming releases that need attention: not linked, ambiguous, or dates that disagree with Jira."""
    today = pd.Timestamp(today or datetime.now().date())
    step_cols = [c for c, _, _ in rc.RELEASE_STEPS if c in linked.columns]
    last = linked[step_cols].max(axis=1) if step_cols else pd.Series(pd.NaT, index=linked.index)
    out = []
    for (_, r), last_step in zip(linked.iterrows(), last):
        if pd.notna(last_step) and last_step < today:
            continue  # history
        v = r["Version"]
        if r["Link"] == NAME_DIFFERS:
            out.append(f"Release {v}: no Jira version named '{r['Expected name']}', but there are versions "
                       f"with {v} under another name. Link one in Link to Jira.")
        elif r["Link"] == UNLINKED:
            out.append(f"Release {v} is not linked: no Jira version named '{r['Expected name']}'.")
        elif r["Link"].endswith("(missing in Jira)"):
            out.append(f"Release {v} is linked to Jira version {r['Jira id']}, which no longer exists.")
        elif pd.notna(r["Days off"]) and r["Days off"] != 0:
            out.append(f"Release {v}: Jira release date {r['Jira release date']:%d %b %Y} "
                       f"differs from the Prod Deploy {r['Prod Deploy']:%d %b %Y}.")
    return out


def link_options(jira: pd.DataFrame, linked: pd.DataFrame, version: str,
                 template: str = DEFAULT_NAME_TEMPLATE) -> pd.DataFrame:
    """Jira versions offered for ``version``: not archived and not already linked to another release.
    The template name first, then the same X.Y.Z, then unreleased versions following the template,
    then the rest; newest first inside each group."""
    if jira.empty:
        return jira
    taken = set(linked.loc[(linked["Version"] != version) & (linked["Jira id"] != ""), "Jira id"])
    opts = jira[~jira["Archived"] & ~jira["Jira id"].isin(taken)].copy()
    expected = _norm_name(release_name(template, version))
    pattern = template_regex(template)
    opts["_rank"] = [0 if _norm_name(n) == expected else 1 if v == version else 2 if pattern.match(n) else 3
                     for n, v in zip(opts["Jira version"], opts["Version"])]
    opts["_key"] = [tuple(-p for p in rc.version_key(v)) if v else (1,) for v in opts["Version"]]
    opts = opts.sort_values(["_rank", "Released", "_key", "Jira version"])
    return opts.drop(columns=["_rank", "_key"]).reset_index(drop=True)
