"""Load step shared by the Quarterly Review pages (Progress and Planning).

Both pages load their data the same way: either from a CSV file or from Jira
(a project plus the committed and quarter labels). The person picks exactly one.
"""
import os

import streamlit as st

SOURCE_CSV = "📄 Upload a CSV file"
SOURCE_JIRA = "🔗 Load from Jira (project and labels)"


def _remembered(key, default):
    """Prepare a widget key so its value survives leaving the Load step.

    Streamlit forgets a widget's value when the widget is not drawn (for example
    after moving to another step). A copy is kept under "<key>__saved" and put
    back before the widget is drawn again.
    """
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(f"{key}__saved", default)
    return key


def _remember(key):
    st.session_state[f"{key}__saved"] = st.session_state[key]


def render_load_source(prefix, csv_help, template_bytes, template_name, loaded_summary=None):
    """Draw the load step and return the request when the person clicks Load.

    Returns None until Load is clicked with valid input, then either
    {"source": "csv", "file": <uploaded file>} or
    {"source": "jira", "project": str, "committed_label": str, "quarter_label": str}.
    """
    if loaded_summary:
        st.info(loaded_summary)

    source = st.radio(
        "Where should the data come from?",
        [SOURCE_CSV, SOURCE_JIRA],
        horizontal=True,
        key=_remembered(f"{prefix}_load_source", SOURCE_CSV),
        help="Choose one: a CSV file or a Jira query. Loading replaces the data currently loaded.",
    )
    _remember(f"{prefix}_load_source")

    with st.container(border=True):
        if source == SOURCE_CSV:
            st.markdown("**Upload a CSV file**")
            st.caption(csv_help)
            uploaded_file = st.file_uploader("CSV file", type=["csv"], key=f"{prefix}_csv_file")
            st.download_button(
                label="⬇️ Download a template",
                data=template_bytes,
                file_name=template_name,
                mime="text/csv",
                key=f"{prefix}_csv_template",
            )
        else:
            st.markdown("**Load from Jira**")
            st.caption("Loads the Epics of the project that carry both labels.")
            col_project, col_committed, col_quarter = st.columns(3)
            with col_project:
                project = st.text_input(
                    "Project key", key=_remembered(f"{prefix}_project", os.getenv("JIRA_PROJECT_KEY", "")),
                    help="The Jira project key, e.g. RECALLTWO. Leave empty to search all projects.",
                )
            with col_committed:
                committed_label = st.text_input(
                    "Committed Epic label",
                    key=_remembered(f"{prefix}_committed", os.getenv("COMMITTED_LABEL", "Project_committed")),
                )
            with col_quarter:
                quarter_label = st.text_input(
                    "Quarter label", key=_remembered(f"{prefix}_quarter", os.getenv("QUARTER_LABEL", "Project_Quarter_1")),
                )
            for name in ("project", "committed", "quarter"):
                _remember(f"{prefix}_{name}")

        clicked = st.button("📥 Load", use_container_width=True, key=f"{prefix}_load_button")

    if not clicked:
        return None
    if source == SOURCE_CSV:
        if uploaded_file is None:
            st.error("Choose a CSV file first.")
            return None
        return {"source": "csv", "file": uploaded_file}
    if not st.session_state.get("jira_server") or not st.session_state.get("jira_token"):
        st.error("Configure and test the Jira connection first on the Configuration page.")
        return None
    if not committed_label.strip() or not quarter_label.strip():
        st.error("Enter both the committed Epic label and the quarter label.")
        return None
    return {
        "source": "jira",
        "project": project.strip(),
        "committed_label": committed_label.strip(),
        "quarter_label": quarter_label.strip(),
    }


def render_title_fields(heading, title_label, subtitle_label, config, prefix):
    """Always-visible, framed title and subtitle fields for a slide or report.

    Updates config["title"] and config["subtitle"] in place.
    """
    with st.container(border=True, key=f"{prefix}_title_box"):
        st.markdown(f"##### {heading}")
        st.caption("These texts appear at the top of the slide. Edit them before downloading.")
        col_title, col_subtitle = st.columns(2)
        with col_title:
            config["title"] = st.text_input(title_label, value=config["title"], key=f"{prefix}_title")
        with col_subtitle:
            config["subtitle"] = st.text_input(subtitle_label, value=config["subtitle"], key=f"{prefix}_subtitle")
    st.markdown(
        f"""<style>
        .st-key-{prefix}_title_box {{
            border: 1px solid #60A5FA !important; background: #60A5FA14 !important; border-radius: 12px !important;
        }}
        .st-key-{prefix}_title_box label p {{ font-weight: 700 !important; font-size: 0.95rem !important; color: #E2E8F0 !important; }}
        </style>""",
        unsafe_allow_html=True,
    )


def jira_auth_args():
    """(server, token, auth method, email) from the Configuration page."""
    return (
        st.session_state.jira_server,
        st.session_state.jira_token,
        st.session_state.get("jira_auth_method", "Personal Access Token (Bearer PAT)"),
        st.session_state.get("jira_email", ""),
    )


def show_jira_error(what):
    """Error for a failed Jira load, with Jira's own message when there is one."""
    jira_error = st.session_state.pop("jira_query_error", None)
    st.error(
        f"The {what} could not be loaded. Check the Jira connection, project key and labels."
        + (f"\n\n**Jira said:** {jira_error}" if jira_error else "")
    )


def show_flash(state_key):
    """Show and clear a one-time {"type", "text"} message stored in session state."""
    fb = st.session_state.pop(state_key, None)
    if fb:
        getattr(st, fb.get("type", "info"), st.info)(fb.get("text"))
