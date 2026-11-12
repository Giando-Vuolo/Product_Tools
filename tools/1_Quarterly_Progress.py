import base64

import pandas as pd
import streamlit as st

from utils.df_helpers import blank_if_missing
from utils.jira_helpers import build_quarterly_epic_progress_table
from utils.quarterly_load import render_load_source, render_title_fields, jira_auth_args, show_jira_error, show_flash
from utils.quarterly_planner_helpers import (
    prepare_quarterly_progress_for_presentation, build_quarterly_progress_slide_pdf, build_quarterly_progress_pptx,
    normalize_progress_csv, PROGRESS_CSV_TEMPLATE,
)
from utils.quarterly_theme import apply_quarterly_page_setup
from utils.stepper import render_stepper

apply_quarterly_page_setup()

if 'quarterly_progress_df' not in st.session_state:
    st.session_state.quarterly_progress_df = None
if 'quarterly_progress_config' not in st.session_state:
    st.session_state.quarterly_progress_config = {}

LAYOUT_ALL = "📋 All Epics in one table"
LAYOUT_BY_INITIATIVE = "🧭 One slide per initiative (Parent Link)"

SLIDE_DEFAULTS = {
    "title": "Committed Epics Q3 - Status",
    "subtitle": "Detail overview of Epics Progress for Q3",
}

st.title("📈 Quarterly Progress")

# ---------------------------------------------------------
# Step Navigation (stepper)
# ---------------------------------------------------------
STEPS = ["📥 Load", "✍️ Updates", "📤 Report"]
render_stepper(STEPS, "active_tab_qprog", key="qprog_stepper")

# ---------------------------------------------------------
# STEP 1: Load (CSV file or Jira project and labels)
# ---------------------------------------------------------
if st.session_state.active_tab_qprog == STEPS[0]:
    st.subheader("📥 Load committed Epics")
    st.write("Load the committed Epics of the quarter with their completion. You add the presentation updates in the next step.")
    show_flash("progress_load_feedback")

    loaded = st.session_state.get("quarterly_progress_df")
    request = render_load_source(
        "qprog",
        csv_help="One row per Epic. Needs Key and Summary; Parent Link, Completion, Status, Labels, the issue counts and Presentation update are optional.",
        template_bytes=PROGRESS_CSV_TEMPLATE.encode("utf-8"),
        template_name="quarterly_progress_template.csv",
        loaded_summary=(
            f"📊 **Currently loaded:** {len(loaded)} Epics from {st.session_state.quarterly_progress_config.get('source', 'Jira')}."
            if isinstance(loaded, pd.DataFrame) and not loaded.empty else None
        ),
    )

    progress_df = None
    if request and request["source"] == "csv":
        try:
            progress_df = normalize_progress_csv(pd.read_csv(request["file"]))
        except Exception as e:
            st.error(f"❌ The CSV file could not be read: {e}")
        else:
            if progress_df.empty:
                st.warning("The CSV file has no Epics.")
                progress_df = None
        source_label = "a CSV file"
    elif request and request["source"] == "jira":
        server, token, auth_type, email = jira_auth_args()
        st.session_state.pop("jira_query_error", None)
        with st.spinner("Downloading committed Epics and calculating progress..."):
            result = build_quarterly_epic_progress_table(
                server, token, request["committed_label"], request["quarter_label"],
                "Quarterly Epic Progress", "Quarterly Progress", auth_type, email,
                project_key=request["project"], include_parent_link=True,
            )
        if result is None:
            show_jira_error("committed Epics")
        elif result["df"].empty:
            st.warning("No committed Epics were found for those labels.")
        else:
            progress_df = result["df"].drop(columns=["Select"], errors="ignore")
        source_label = f"Jira ({request['project'] or 'all projects'})"

    if progress_df is not None:
        # Keep updates already written for the same Epics; a non-empty update in the CSV wins.
        previous = st.session_state.get("quarterly_progress_df")
        previous_updates = {}
        if isinstance(previous, pd.DataFrame) and not previous.empty and "Presentation update" in previous.columns:
            previous_updates = blank_if_missing(previous.set_index("Key")["Presentation update"]).to_dict()
        incoming = blank_if_missing(progress_df["Presentation update"]) if "Presentation update" in progress_df.columns else ""
        progress_df["Presentation update"] = incoming
        progress_df["Presentation update"] = progress_df["Presentation update"].where(
            progress_df["Presentation update"].astype(str).str.strip() != "",
            blank_if_missing(progress_df["Key"].map(previous_updates)),
        )
        st.session_state.quarterly_progress_df = prepare_quarterly_progress_for_presentation(progress_df)
        config = {**SLIDE_DEFAULTS, **st.session_state.quarterly_progress_config}
        config["source"] = source_label
        if request["source"] == "jira":
            config["quarter_label"] = request["quarter_label"]
        st.session_state.quarterly_progress_config = config
        st.session_state.progress_feedback = {"type": "success", "text": f"✅ Loaded {len(progress_df)} committed Epics from {source_label}. Add the presentation updates below."}
        st.session_state.active_tab_qprog = STEPS[1]
        st.rerun()


# ---------------------------------------------------------
# STEP 2: Presentation updates and roadmap selections
# ---------------------------------------------------------
elif st.session_state.active_tab_qprog == STEPS[1]:
    st.subheader("✍️ Presentation updates")
    show_flash("progress_feedback")

    progress_df = st.session_state.get("quarterly_progress_df")
    if isinstance(progress_df, pd.DataFrame) and not progress_df.empty:
        st.caption("Write a short update for each Epic; it appears in the report. Jira fields remain read-only. The delivery roadmap is built in Quarterly Review → Planning.")
        progress_columns = [
            "Parent Link", "Key", "Summary", "Completion", "Closed / Resolved", "To Do", "In progress", "Status", "Team", "Presentation update",
        ]
        progress_columns = [column for column in progress_columns if column in progress_df.columns]
        # Row number for on-screen reference only: it is not stored in
        # session state and does not reach the slides or exports.
        progress_view = progress_df[progress_columns].copy()
        progress_view.insert(0, "#", range(1, len(progress_view) + 1))
        with st.form("quarterly_progress_updates_form", border=False):
            edited_progress = st.data_editor(
                progress_view,
                use_container_width=True,
                hide_index=True,
                disabled=["#"] + [column for column in progress_columns if column != "Presentation update"],
                column_config={
                    "#": st.column_config.NumberColumn("#", width="small", format="%d"),
                    "Parent Link": st.column_config.TextColumn("Parent Link", width="medium"),
                    "Key": st.column_config.TextColumn("Key", width="small"),
                    "Summary": st.column_config.TextColumn("Epic", width="large"),
                "Completion": st.column_config.TextColumn("Completion", width="small"),
                "Closed / Resolved": st.column_config.NumberColumn("Closed / Resolved", width="small", format="%d"),
                "To Do": st.column_config.NumberColumn("To Do", width="small", format="%d"),
                "In progress": st.column_config.NumberColumn("In progress", width="small", format="%d"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Team": st.column_config.TextColumn("Team", width="medium"),
                    "Presentation update": st.column_config.TextColumn("Update / context", width="large"),
                },
                key="quarterly_progress_editor",
            )
            save_progress_updates = st.form_submit_button("Save updates", use_container_width=True)
        if save_progress_updates:
            updated_progress = progress_df.copy()
            updated_progress["Presentation update"] = edited_progress["Presentation update"]
            st.session_state.quarterly_progress_df = prepare_quarterly_progress_for_presentation(updated_progress)
            st.success("Presentation updates saved.")
    else:
        st.info("Load the committed Epics in step 1 to add the updates that will appear in the report.")

# ---------------------------------------------------------
# STEP 3: Report (PDF / PowerPoint)
# ---------------------------------------------------------
elif st.session_state.active_tab_qprog == STEPS[2]:
    progress_df = st.session_state.get("quarterly_progress_df")
    if isinstance(progress_df, pd.DataFrame) and not progress_df.empty:
        st.subheader("📤 Progress report")
        st.write("A presentation-ready report of the committed Epics with their completion and your update/context column.")
        config = {**SLIDE_DEFAULTS, **st.session_state.quarterly_progress_config}
        render_title_fields("🏷️ Report title and subtitle", "Report title", "Report subtitle", config, "qprog")
        st.session_state.quarterly_progress_config = config
        layouts = [LAYOUT_ALL, LAYOUT_BY_INITIATIVE]
        config["layout"] = st.radio(
            "Report layout", layouts, horizontal=True, key="qprog_layout",
            index=layouts.index(config.get("layout", LAYOUT_ALL)) if config.get("layout") in layouts else 0,
            help="By initiative: one slide per Parent Link, with the subtitle \"Initiative: <Parent Link>\" "
                 "and a table of that initiative's Epics. The report subtitle above is then not used.",
        )
        st.session_state.quarterly_progress_config = config
        by_initiative = config["layout"] == LAYOUT_BY_INITIATIVE
        progress_title = config["title"].strip() or "Quarterly Epic Progress"
        progress_subtitle = config["subtitle"].strip()
        report_df = prepare_quarterly_progress_for_presentation(progress_df)
        primary = st.session_state.get("primary_color", "#0B2756")
        progress_pdf = build_quarterly_progress_slide_pdf(report_df, progress_title, primary, progress_subtitle, by_initiative=by_initiative)
        col_pdf, col_pptx = st.columns(2)
        with col_pdf:
            st.download_button(
                label="⬇️ Download Progress Report (PDF)", data=progress_pdf,
                file_name="quarterly_epic_progress.pdf", mime="application/pdf", use_container_width=True,
            )
        with col_pptx:
            st.download_button(
                label="⬇️ Download Progress Report (PowerPoint)",
                data=build_quarterly_progress_pptx(report_df, None, progress_title, progress_subtitle, "", "", primary, by_initiative=by_initiative),
                file_name="quarterly_epic_progress.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )
        st.markdown("#### 👁️ Report preview")
        progress_preview = base64.b64encode(progress_pdf).decode("utf-8")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{progress_preview}" width="100%" height="520" '
            'type="application/pdf" style="border: 1px solid #3E3E4A; border-radius: 12px; background: #ffffff;"></iframe>',
            unsafe_allow_html=True,
        )
    else:
        st.warning("⚠️ Load the committed Epics in step 1 first.")
