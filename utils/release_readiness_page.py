"""Streamlit glue shared by the Release Plan readiness sub-pages (no rule logic here).

Read-only: Jira and Confluence are only read (GET). Data lives in session keys ``rr<N>_*`` and nothing
is fetched until a Load Information button is clicked. On the aggregate pages (Overview, Scope,
Notifications, By owner) and Post Actions, one click loads all of them (see ``load_information``).
"""
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import streamlit as st

from utils import confluence_helpers, jira_helpers
from utils import release_checks as rc
from utils import release_plan_helpers as rp


NOT_RELEVANT_WINDOW_DAYS = 90


@dataclass
class Context:
    prefix: str
    server: str
    token: str
    auth: str
    email: str
    conf_server: str
    conf_token: str
    cfg: object
    sandbox: bool
    version: str = ""         # typed version (also names the Release Plan page)
    source_version: str = ""  # version whose Jira issues are read
    valid: bool = False


def page_header(title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)


def load_context(prefix: str) -> Context:
    """Check config, render the version input and the sandbox banner. Stops on config errors."""
    import dotenv
    dotenv.load_dotenv(override=True)
    missing = rp.missing_config(os.environ)
    if missing:
        st.error("Missing configuration (set in .env): " + ", ".join(missing))
        st.stop()
    try:
        cfg = rp.load_release_plan_config(os.environ)
        sandbox_cfg = rp.load_sandbox_config(os.environ)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    version = bind_release_version_input(prefix, label="Release version (X.Y.Z)")
    ctx = Context(
        prefix=prefix,
        server=os.getenv("JIRA_SERVER", ""), token=os.getenv("JIRA_API_TOKEN", ""),
        auth=os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)"), email=os.getenv("JIRA_EMAIL", ""),
        conf_server=os.getenv("CONFLUENCE_SERVER", ""), conf_token=os.getenv("CONFLUENCE_API_TOKEN", ""),
        cfg=cfg, sandbox=False, version=version,
    )
    try:
        ctx.version = rp.validate_version(version)
        ctx.valid = True
    except ValueError:
        return ctx
    ctx.source_version, ctx.sandbox = rp.resolve_source_version(ctx.version, sandbox_cfg)
    if ctx.sandbox:
        st.warning(
            f"SANDBOX: Release {ctx.version} reads the Jira issues of "
            f"{rp.build_fix_version(ctx.source_version, cfg.label)} (read-only). "
            f"Confluence writes are limited to page {rp.SANDBOX_WRITE_PAGE_ID}; Jira is never written."
        )
    return ctx


def _read_freeze(ctx: Context):
    """Return (date|None, note). Read-only GETs of the typed version's Release Plan page."""
    try:
        children = confluence_helpers.list_child_pages(
            ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, ctx.cfg.parent_id)
        if children.get("error"):
            return None, children["error"]
        title = rp.build_target_title(ctx.cfg.title_template, ctx.version)
        target = rp.select_target_page(children["results"], title, ctx.cfg.parent_id)
        page = confluence_helpers.get_confluence_page(
            ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, target["id"])
        if page.get("error"):
            return None, page["error"]
        return rc.extract_freeze_date(page.get("storage", "")), ""
    except ValueError as e:
        return None, str(e)


def freeze_date_input(prefix: str, data: Optional[dict]) -> Optional[date]:
    """Freeze date from the Release Plan page, else a manual date input (AC12/AC13)."""
    if not data:
        return None
    if data.get("freeze") is not None:
        st.caption(f"Freeze date (from the Release Plan page): {data['freeze'].isoformat()}")
        return data["freeze"]
    note = data.get("freeze_note")
    st.info("No 'Freeze date' found on the Release Plan page"
            + (f" ({note})" if note else "") + ". Enter it manually (optional); without it, "
            "missing approvals are only warnings.")
    return st.date_input("Freeze date (manual)", value=None, key=f"{prefix}_freeze_manual")


def fetch_issues(ctx: Context, fields: str = jira_helpers.RELEASE_READINESS_FIELDS):
    """Read-only Jira search for the release. Returns (issues, error)."""
    jql = rp.build_release_jql(ctx.source_version, ctx.cfg.label)
    res = jira_helpers.fetch_release_issues_with_comments(
        ctx.server, ctx.token, ctx.auth, ctx.email, jql, fields=fields)
    if res.get("error"):
        if rp.is_missing_fix_version_error(res["error"]):
            return [], f"Version {rp.build_fix_version(ctx.source_version, ctx.cfg.label)} does not exist in Jira."
        return [], res["error"]
    return [rc.issue_from_jira(i) for i in res["issues"]], None


def fetch_not_relevant(ctx: Context, fields: str = jira_helpers.RELEASE_READINESS_FIELDS):
    """Read-only: issues carrying the 'Not release relevant' fixVersion.

    That fixVersion is shared by every release, so the query is bounded to issues updated in the
    last NOT_RELEVANT_WINDOW_DAYS days (paginated GET by the helper) to keep volume sane.
    """
    jql = (f'project = {rp.JIRA_PROJECT} AND issuetype in ({", ".join(rp.ISSUE_TYPES)}) '
           f'AND fixVersion = "{rc.NOT_RELEVANT_FIX_VERSION}" '
           f'AND updated >= -{NOT_RELEVANT_WINDOW_DAYS}d')
    res = jira_helpers.fetch_release_issues_with_comments(
        ctx.server, ctx.token, ctx.auth, ctx.email, jql, fields=fields)
    if res.get("error"):
        return [], res["error"]
    return [rc.issue_from_jira(i) for i in res["issues"]], None


def refresh(ctx: Context, with_freeze: bool = False) -> None:
    """The page's own Load Information button: fetches only when clicked; stores under rr<N>_data."""
    key = f"{ctx.prefix}_data"
    if not st.button("Load Information", key=f"{ctx.prefix}_refresh", disabled=not ctx.valid):
        return
    st.session_state.pop(key, None)
    st.session_state.pop(f"{ctx.prefix}_freeze_manual", None)
    data = {}
    if with_freeze:
        data["freeze"], data["freeze_note"] = _read_freeze(ctx)
    issues, err = fetch_issues(ctx)
    if err:
        st.error(err)
        return
    data["issues"] = issues
    data["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["version"] = ctx.version
    st.session_state[key] = data


def get_data(ctx: Context) -> Optional[dict]:
    if not ctx.valid:
        st.info("Enter a release version X.Y.Z, then click Load Information.")
        return None
    data = st.session_state.get(f"{ctx.prefix}_data")
    if data and data.get("version") not in (None, ctx.version):
        st.info(f"The loaded data is for release {data['version']}. Click Load Information to load {ctx.version}.")
        return None
    if not data:
        st.info("Nothing loaded yet. Click Load Information to check this rule.")
    return data


def render_findings(findings: list, checked_at: str = "", empty_msg: str = "No findings.") -> None:
    ordered = rc.sort_findings(findings)
    if checked_at:
        st.caption(f"Checked at {checked_at}")
    counts = {s: sum(1 for f in ordered if f.severity == s) for s in (rc.ERROR, rc.WARN, rc.INFO)}
    st.write(f"ERROR: {counts[rc.ERROR]} | WARN: {counts[rc.WARN]} | INFO: {counts[rc.INFO]}")
    if not ordered:
        st.success(empty_msg)
        return
    import pandas as pd
    st.dataframe(pd.DataFrame([
        {"Severity": f.severity, "Issue": f.issue_key, "Summary": f.summary,
         "Assignee": f.assignee or "Unassigned", "Reason": f.reason} for f in ordered
    ]), hide_index=True, width='stretch')


def render_critical(rows: list, checked_at: str = "", others: Optional[list] = None) -> None:
    if checked_at:
        st.caption(f"Checked at {checked_at}")
    import pandas as pd
    if not rows:
        st.success("No critical changes.")
    else:
        st.dataframe(pd.DataFrame([
            {"Issue": r.issue_key, "Summary": r.summary, "Assignee": r.assignee or "Unassigned",
             "Reasons": "; ".join(r.reasons)} for r in rows
        ]), hide_index=True, width='stretch')
    if others is not None:
        with st.expander("Other in-scope issues", expanded=False):
            if not others:
                st.write("No other in-scope issues.")
            else:
                st.dataframe(pd.DataFrame([
                    {"Issue": i.key, "Summary": i.summary, "Status": i.status,
                     "Assignee": i.assignee or "Unassigned"} for i in others
                ]), hide_index=True, width='stretch')


def render_by_owner(data: dict, freeze, release: str) -> None:
    import pandas as pd
    results = rc.run_all(data["issues"], freeze, date.today())
    st.caption(f"Checked at {data['checked_at']}")
    show_info = st.checkbox("Show INFO", value=False, key="rr9_show_info")
    groups = rc.group_by_owner(results, data["issues"], include_info=show_info)
    if not groups:
        st.success("No issues to review for this release.")
        return
    choice = st.selectbox("Owner", ["All"] + rc.owner_names(groups), key="rr9_owner")
    shown = groups if choice == "All" else [g for g in groups if g.owner == choice]
    for g in shown:
        st.subheader(g.owner)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Issues", len(g.issues))
        c2.metric("ERROR", g.counts[rc.ERROR], help="Issues whose highest severity is ERROR")
        c3.metric("WARN", g.counts[rc.WARN], help="Issues whose highest severity is WARN")
        c4.metric("INFO", g.counts[rc.INFO], help="Issues whose highest severity is INFO")
        st.caption("Counts are per issue, by its highest severity.")
        st.dataframe(pd.DataFrame([
            {"Issue": i.key, "Summary": i.summary, "Status": i.status, "Severity": i.max_severity,
             "What is missing": "; ".join(f"{r}: {x}" for r, x in i.problems)} for i in g.issues
        ]), hide_index=True, width='stretch')
        st.code(rc.owner_message(g, release), language="text")
    if choice == "All":
        st.markdown("#### Summary")
        st.code(rc.owners_summary(groups, release), language="text")


def refresh_all(ctx: Context, with_not_relevant: bool = True) -> None:
    """Load Information button of the aggregate pages (0, 1, 8, 9).

    One click loads every Release Plan tab (readiness data for all aggregate pages + Post Actions),
    so the other tabs do not need their own load.
    """
    if not st.button("Load Information", key=f"{ctx.prefix}_refresh", disabled=not ctx.valid):
        return
    err, warning = load_information(ctx, with_not_relevant)
    if err:
        st.error(err)
    elif warning:
        st.warning(warning)


# Pages sharing one readiness dataset; their data is loaded together by load_information().
AGGREGATE_PREFIXES = ("rr0", "rr1", "rr8", "rr9")
POST_ACTIONS_STATE_KEY = "rp_preview"
POST_ACTIONS_ERRORS_KEY = "rp_load_errors"
POST_ACTIONS_TARGET_KEY = "rp_target"


def _collect_readiness(ctx: Context, with_not_relevant: bool):
    """Pure fetch (no Streamlit calls: runs in a worker thread). Returns (data|None, error, warning)."""
    data = {}
    data["freeze"], data["freeze_note"] = _read_freeze(ctx)
    issues, err = fetch_issues(ctx)
    if err:
        return None, err, None
    warning = None
    data["scope_issues"] = list(issues)
    data["not_relevant_issues"] = []
    if with_not_relevant:
        extra, err = fetch_not_relevant(ctx)
        if err:
            warning = f"Could not read 'Not release relevant' issues: {err}"
        else:
            seen = {i.key for i in issues}
            data["not_relevant_issues"] = [i for i in extra if i.key not in seen]
    data["issues"] = data["scope_issues"] + data["not_relevant_issues"]
    data["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return data, None, warning


def _collect_post_actions(ctx: Context) -> dict:
    """Pure fetch (no Streamlit calls). Returns {"state": dict|None, "errors": [..], "target": tuple|None}."""
    out = {"state": None, "errors": [], "target": None}
    try:
        version = rp.validate_version(ctx.version)
        children = confluence_helpers.list_child_pages(
            ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, ctx.cfg.parent_id)
        if children.get("error"):
            raise ValueError(children["error"])
        title = rp.build_target_title(ctx.cfg.title_template, version)
        target = rp.select_target_page(children["results"], title, ctx.cfg.parent_id)
        page_id = target["id"]
        page = confluence_helpers.get_confluence_page(
            ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, page_id)
        # Guard and target first, before any Jira call.
        guard = rp.check_target_guard(page, version, ctx.cfg.label, parent_id=ctx.cfg.parent_id)
        out["target"] = (guard.title or target.get("title", ""), page_id, target.get("url", ""))
        if not guard.ok:
            out["errors"] = list(guard.errors)
            return out
        res = jira_helpers.fetch_release_issues_with_comments(
            ctx.server, ctx.token, ctx.auth, ctx.email, rp.build_release_jql(version, ctx.cfg.label))
        if res.get("error"):
            if rp.is_missing_fix_version_error(res["error"]):
                out["errors"] = [f"Version {rp.build_fix_version(version, ctx.cfg.label)} does not exist in Jira. "
                                 "Nothing to extract."]
            else:
                out["errors"] = [res["error"]]
            return out
        preview = rp.build_preview(page, res["issues"], version, ctx.cfg.label, ctx.server, ctx.cfg.parent_id)
        out["state"] = {
            "page_id": page_id, "version": version, "label": ctx.cfg.label, "parent_id": ctx.cfg.parent_id,
            "page_url": target.get("url", ""),
            "page_version": page.get("version"), "preview": preview,
            "actions": rp.extract_actions(res["issues"]), "issue_count": len(res["issues"]),
        }
    except ValueError as e:
        out["errors"] = [str(e)]
    except Exception as e:  # a worker must never take the page down
        out["errors"] = [f"Could not load Post Actions: {e}"]
    return out


def load_information(ctx: Context, with_not_relevant: bool = True):
    """Load everything the Release Plan tabs need in one go (read-only), in parallel.

    Fills the readiness data of every aggregate page and the Post Actions preview, tagged with the
    release version. Returns (readiness_error, readiness_warning) for the calling page to display.
    """
    from concurrent.futures import ThreadPoolExecutor
    for prefix in AGGREGATE_PREFIXES:
        st.session_state.pop(f"{prefix}_data", None)
        st.session_state.pop(f"{prefix}_freeze_manual", None)
    for key in (POST_ACTIONS_STATE_KEY, POST_ACTIONS_ERRORS_KEY, POST_ACTIONS_TARGET_KEY):
        st.session_state.pop(key, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        readiness_f = pool.submit(_collect_readiness, ctx, with_not_relevant)
        post_f = pool.submit(_collect_post_actions, ctx)
        data, err, warning = readiness_f.result()
        post = post_f.result()
    if data is not None:
        data["version"] = ctx.version
        for prefix in AGGREGATE_PREFIXES:
            st.session_state[f"{prefix}_data"] = dict(data)
    st.session_state[POST_ACTIONS_ERRORS_KEY] = post["errors"]
    st.session_state[POST_ACTIONS_TARGET_KEY] = post["target"]
    if post["state"]:
        st.session_state[POST_ACTIONS_STATE_KEY] = post["state"]
    return err, warning


def render_overview(data: dict, freeze) -> None:
    import pandas as pd
    results = rc.run_all(data["issues"], freeze, date.today())
    summ = rc.summarize(results)
    icon = {"GREEN": "🟢", "AMBER": "🟠", "RED": "🔴"}[summ["semaphore"]]
    st.caption(f"Checked at {data['checked_at']}")
    st.subheader(f"{icon} Release readiness: {summ['semaphore']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("ERROR", summ["counts"][rc.ERROR])
    c2.metric("WARN", summ["counts"][rc.WARN])
    c3.metric("INFO", summ["counts"][rc.INFO])
    st.markdown("#### Critical changes")
    render_critical(results["Critical changes"])
    st.markdown("#### Per owner")
    if summ["per_owner"]:
        st.dataframe(pd.DataFrame([
            {"Owner": o, "ERROR": c[rc.ERROR], "WARN": c[rc.WARN], "INFO": c[rc.INFO]}
            for o, c in sorted(summ["per_owner"].items())
        ]), hide_index=True, width='stretch')
    else:
        st.success("No findings.")
    st.markdown("#### Findings per rule")
    for rule, items in results.items():
        if rule == "Critical changes":
            continue
        with st.expander(f"{rule} ({len(items)})", expanded=False):
            render_findings(items)


RELEASE_PLAN_SHARED_VERSION_KEY = "release_plan_version"
RELEASE_PLAN_SHARED_LINK_KEY = "release_plan_version_link"
RELEASE_PLAN_SHARED_NAME_KEY = "release_plan_version_jira_name"
_VERSION_ERROR_KEY = "release_plan_version_error"


def _fetch_jira_version(version_id):
    from utils.release_helpers import jira_request
    import requests
    try:
        resp = jira_request(
            os.getenv("JIRA_SERVER", ""), os.getenv("JIRA_API_TOKEN", ""), f"/rest/api/2/version/{version_id}",
            auth_type=os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)"), email=os.getenv("JIRA_EMAIL", ""))
        return resp.status_code, (resp.json() if resp.status_code == 200 else {})
    except (requests.RequestException, ValueError) as e:
        raise ValueError(f"Could not reach Jira ({e}).") from None


def _load_version_from_link(prefix: str) -> None:
    """Link field callback: resolve the link, then share the extracted X.Y.Z with every release page."""
    link = st.session_state.get(f"{prefix}_version_link", "")
    base = os.getenv(rp.ENV_VERSION_LINK_BASE, "")
    if not link.strip() or link.strip() == base.strip():  # nothing but the prefilled base yet
        st.session_state[_VERSION_ERROR_KEY] = ""
        return
    try:
        name, number = rp.resolve_version_link(link, _fetch_jira_version)
    except ValueError as e:
        st.session_state[_VERSION_ERROR_KEY] = str(e)
        return
    st.session_state[_VERSION_ERROR_KEY] = ""
    st.session_state[RELEASE_PLAN_SHARED_VERSION_KEY] = number
    st.session_state[RELEASE_PLAN_SHARED_NAME_KEY] = name
    st.session_state[RELEASE_PLAN_SHARED_LINK_KEY] = link
    st.session_state[f"{prefix}_version"] = number  # shown in the editable field


def _commit_typed_version(prefix: str) -> None:
    typed = str(st.session_state.get(f"{prefix}_version", "")).strip()
    if typed:
        st.session_state[RELEASE_PLAN_SHARED_VERSION_KEY] = typed


def bind_release_version_input(prefix: str, label: str = "Release version (X.Y.Z)") -> str:
    """Release version selector shared by all Release Plan pages: enter it once, every page uses it.

    Paste a Jira version link (prefilled with JIRA_VERSION_LINK_BASE, like Release Notes) and X.Y.Z is
    extracted from Jira's response into an editable field, or just type X.Y.Z. Always visible (no
    expander, so it never collapses on rerun).
    """
    shared = st.session_state.get(RELEASE_PLAN_SHARED_VERSION_KEY, "")
    base = os.getenv(rp.ENV_VERSION_LINK_BASE, "")
    version_key, link_key = f"{prefix}_version", f"{prefix}_version_link"
    st.session_state.setdefault(version_key, shared)
    st.session_state.setdefault(link_key, st.session_state.get(RELEASE_PLAN_SHARED_LINK_KEY) or base)
    with st.container():
        link_col, version_col = st.columns([3, 1])
        with link_col:
            st.text_input("Jira version link", key=link_key, placeholder=f"{base}543216",
                          on_change=_load_version_from_link, args=(prefix,),
                          help="Paste the link and press Enter (or click outside): X.Y.Z is extracted automatically.")
        with version_col:
            st.text_input(label, key=version_key, placeholder="e.g. 35.0.0",
                          on_change=_commit_typed_version, args=(prefix,))
        if st.session_state.get(_VERSION_ERROR_KEY):
            st.error(st.session_state[_VERSION_ERROR_KEY])
        if st.session_state.get(RELEASE_PLAN_SHARED_NAME_KEY):
            st.caption(f"Jira version: {st.session_state[RELEASE_PLAN_SHARED_NAME_KEY]}")
    version = str(st.session_state.get(version_key, "")).strip()
    if version:
        st.session_state[RELEASE_PLAN_SHARED_VERSION_KEY] = version
        return version
    return shared


# ----------------------------------------------------------------- publish (sandbox only)
def resolve_publish_page(ctx: Context):
    """Read-only GETs to find the typed version's Release Plan page. Returns (page|None, error)."""
    from utils import release_publish as rpub
    try:
        children = confluence_helpers.list_child_pages(
            ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, ctx.cfg.parent_id)
        if children.get("error"):
            return None, children["error"]
        title = rp.build_target_title(ctx.cfg.title_template, ctx.version)
        target = rp.select_target_page(children["results"], title, ctx.cfg.parent_id)
        rpub.assert_publish_allowed(target["id"])  # before reading the page itself
        page = confluence_helpers.get_confluence_page(
            ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, target["id"])
        if page.get("error"):
            return None, page["error"]
        page = dict(page)
        page.setdefault("id", target["id"])
        return page, ""
    except (ValueError, rpub.PublishRefused) as e:
        return None, str(e)


def render_publish_panel(ctx: Context, kind: str, new_fragment: str, button_label: str) -> None:
    """Preview + confirm publish of one fragment. Sandbox page only; nothing runs on load."""
    from utils import release_publish as rpub
    st.markdown("---")
    if not ctx.sandbox:
        st.button(button_label, key=f"{ctx.prefix}_pub_disabled_{kind}", disabled=True)
        st.caption(f"Publishing is only enabled for the sandbox release (page {rp.SANDBOX_WRITE_PAGE_ID}).")
        return
    skey = f"{ctx.prefix}_pub_{kind}"
    if st.button("Preview", key=f"{skey}_preview"):
        st.session_state.pop(skey, None)
        page, err = resolve_publish_page(ctx)
        if err:
            st.error(err)
        else:
            try:
                plan = rpub.plan_splice(page, kind, new_fragment, version=ctx.version,
                                        source_version=ctx.source_version, label=ctx.cfg.label,
                                        parent_id=ctx.cfg.parent_id)
                st.session_state[skey] = {"page_id": plan.page_id, "base_version": plan.base_version,
                                          "plan": plan}
            except rpub.PublishRefused as e:
                st.error(str(e))
    state = st.session_state.get(skey)
    if not state:
        st.button(button_label, key=f"{skey}_confirm", disabled=True)
        return
    plan = state["plan"]
    st.write(f"Target: {plan.title} (ID {plan.page_id}, version {state['base_version']})")
    st.caption("Current fragment")
    st.code(plan.old_fragment, language="html")
    st.caption("New fragment")
    st.code(plan.new_fragment, language="html")
    if not plan.changed:
        st.info("Page already up to date.")
    if not st.button(button_label, key=f"{skey}_confirm", disabled=not plan.changed):
        return
    try:
        res = rpub.publish_splice(
            page_id=state["page_id"], kind=kind, new_fragment=plan.new_fragment,
            expected_version=state["base_version"],
            get_page=lambda pid: confluence_helpers.get_confluence_page(
                ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, pid),
            update_page=lambda pid, title, ver, storage: confluence_helpers.update_confluence_page(
                ctx.conf_server, ctx.conf_token, ctx.auth, ctx.email, pid, title, ver, storage),
            version=ctx.version, source_version=ctx.source_version, label=ctx.cfg.label,
            parent_id=ctx.cfg.parent_id, backup_dir=rpub.BACKUP_DIR)
    except rpub.PublishRefused as e:
        st.error(str(e))
        return
    backup = f" Backup: {res['backup']}" if res.get("backup") else ""
    if res["ok"]:
        st.success(f"Published ({res['status']})." + backup)
        st.session_state.pop(skey, None)
    else:
        st.error(f"{res['error']}{backup}")
