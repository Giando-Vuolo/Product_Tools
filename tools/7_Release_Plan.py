import os

import streamlit as st
from dotenv import load_dotenv

from utils import release_readiness_page as rr
from utils.confluence_helpers import get_confluence_page, update_confluence_page
from utils.release_plan_helpers import publish

load_dotenv(override=True)

JIRA_SERVER = os.getenv("JIRA_SERVER", "")
JIRA_AUTH_METHOD = os.getenv("JIRA_AUTH_METHOD", "Jira Server Token (Bearer)")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
CONF_SERVER = os.getenv("CONFLUENCE_SERVER", "")
CONF_TOKEN = os.getenv("CONFLUENCE_API_TOKEN", "")

st.title("📋 Post Actions")
st.caption(
    "Extracts `POST-ACTION: <text>` lines from the Jira descriptions and comments of a release and "
    "adds them, unchecked, to the Post-actions section of a Release Plan page. Existing content is never overwritten."
)

# Config check, shared release version input and sandbox banner (same as the readiness tabs).
ctx = rr.load_context("rp")


def _get_page(page_id):
    return get_confluence_page(CONF_SERVER, CONF_TOKEN, JIRA_AUTH_METHOD, JIRA_EMAIL, page_id)


def _show_target(title, page_id, url):
    link = f" - [open page]({url})" if url else ""
    st.write(f"Target page: **{title or '?'}** (ID {page_id}){link}")


# One Load Information loads every Release Plan tab (readiness data + this preview).
if st.button("Load Information", key="rp_preview_btn", disabled=not ctx.valid):
    rr.load_information(ctx)

load_target = st.session_state.get(rr.POST_ACTIONS_TARGET_KEY)
if load_target:
    _show_target(*load_target)
for load_error in st.session_state.get(rr.POST_ACTIONS_ERRORS_KEY) or []:
    st.error(load_error)
if not ctx.valid:
    st.info("Enter a release version X.Y.Z, then click Load Information.")

state = st.session_state.get(rr.POST_ACTIONS_STATE_KEY)
if state and state["version"] != ctx.version:
    st.info(f"The loaded preview is for release {state['version']}. Click Load Information to load {ctx.version}.")
    state = None
if state:
    preview = state["preview"]
    guard = preview["guard"]
    st.subheader("Preview")
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
                actions=state["actions"], version=state["version"], label=state["label"],
                jira_server=JIRA_SERVER, parent_id=state["parent_id"],
            )
            if result["ok"]:
                st.success(f"Published: {result['added']} new action(s) added, {result['skipped']} skipped.")
                st.session_state.pop("rp_preview", None)
            else:
                st.error(result["error"])
