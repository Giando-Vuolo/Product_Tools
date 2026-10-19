import os

import streamlit as st
from dotenv import load_dotenv

from utils.confluence_helpers import get_confluence_page, update_confluence_page
from utils.jira_helpers import fetch_release_issues_with_comments
from utils.release_plan_helpers import (
    DEFAULT_FIX_VERSION_PREFIX,
    build_preview,
    build_release_jql,
    extract_actions,
    missing_config,
    parse_page_id,
    publish,
    validate_version,
)

load_dotenv(override=True)

JIRA_SERVER = os.getenv("JIRA_SERVER", "")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_AUTH_METHOD = os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
CONF_SERVER = os.getenv("CONFLUENCE_SERVER", "")
CONF_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")

st.title("🚀 Release Plan Post-actions")
st.caption(
    "Extracts `POST-ACTION: <text>` lines from the Jira descriptions and comments of a release and "
    "adds them, unchecked, to the Post-actions section of a Release Plan page. Existing content is never overwritten."
)

missing = missing_config(os.environ)
if missing:
    st.error("Missing configuration (set in .env): " + ", ".join(missing))
    st.stop()


def _get_page(page_id):
    return get_confluence_page(CONF_SERVER, CONF_TOKEN, JIRA_AUTH_METHOD, JIRA_EMAIL, page_id)


version_in = st.text_input("Release version (X.Y.Z)", value="", placeholder="e.g. 35.0.0", key="rp_version")
target_in = st.text_input("Target Release Plan page (ID or URL)", value="", key="rp_target")
with st.expander("Advanced"):
    prefix = st.text_input("fixVersion prefix", value=DEFAULT_FIX_VERSION_PREFIX, key="rp_prefix")

if st.button("Generate preview", key="rp_preview_btn"):
    st.session_state.pop("rp_preview", None)
    try:
        version = validate_version(version_in)
        page_id = parse_page_id(target_in)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    page = _get_page(page_id)
    jql = build_release_jql(version, prefix)
    res = fetch_release_issues_with_comments(JIRA_SERVER, JIRA_TOKEN, JIRA_AUTH_METHOD, JIRA_EMAIL, jql)
    if res.get("error"):
        st.error(res["error"])
        st.stop()
    preview = build_preview(page, res["issues"], version, prefix, JIRA_SERVER)
    st.session_state["rp_preview"] = {
        "page_id": page_id, "version": version, "prefix": prefix,
        "page_version": page.get("version"), "preview": preview,
        "actions": extract_actions(res["issues"]), "issue_count": len(res["issues"]),
    }

state = st.session_state.get("rp_preview")
if state:
    preview = state["preview"]
    guard = preview["guard"]
    st.subheader("Preview")
    st.write(f"Target page: **{guard.title or '?'}** (ID {guard.page_id})")
    if not guard.ok:
        for err in guard.errors:
            st.error(err)
    elif preview["error"]:
        st.error(preview["error"])
    else:
        plan = preview["plan"]
        st.write(f"Issues processed: {state['issue_count']}")
        rows = [(a, "New") for a in plan.new_actions] + [(a, "Already present (skipped)") for a in plan.skipped]
        if not rows:
            st.info("No post-actions found for this release.")
        else:
            st.write(f"{len(plan.new_actions)} new, {len(plan.skipped)} already present")
            lines = ["| Issue | Text | Author | Status |", "|---|---|---|---|"]
            for a, status in rows:
                link = f"[{a.issue_key}]({JIRA_SERVER.rstrip('/')}/browse/{a.issue_key})"
                text = a.text.replace("|", "\\|")
                lines.append(f"| {link} | {text} | {a.author} | {status} |")
            st.markdown("\n".join(lines))

        if st.button("Publish to Confluence", key="rp_publish_btn", disabled=not plan.new_actions):
            result = publish(
                get_page=lambda: _get_page(state["page_id"]),
                update_page=lambda pid, title, ver, storage: update_confluence_page(
                    CONF_SERVER, CONF_TOKEN, JIRA_AUTH_METHOD, JIRA_EMAIL, pid, title, ver, storage),
                actions=state["actions"], version=state["version"], prefix=state["prefix"],
                jira_server=JIRA_SERVER,
            )
            if result["ok"]:
                st.success(f"Published: {result['added']} new action(s) added, {result['skipped']} skipped.")
                st.session_state.pop("rp_preview", None)
            else:
                st.error(result["error"])
