"""Roadmap Reporting: project KPIs by initiative (slide 3 of Template QP).

Two reporting levels identified by Jira labels: Group labels (on Initiatives) and, inside
each group, Topic labels (on Initiatives or Epics), each Topic with an optional due date. The Label configuration tab
defines which labels belong to each level; the Report tab lays them out as in the slide.
Each Topic's Harvey ball is the average score of the tickets under its Epics (utils.roadmap_progress).
"""
import html
import math
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from utils import roadmap_labels as rl
from utils import roadmap_export as rx
from utils import roadmap_progress as rp

BASE_KEY = "rr_cfg_base"      # configuration the editors start from (saved file, or defaults after a reset)
VERSION_KEY = "rr_cfg_ver"    # bumped to reset the editors after save / discard / reset
EXPORT_KEY = "rr_export"      # bytes of the last prepared PowerPoint
PROGRESS_KEY = "rr_progress"  # {"data": load_topic_progress result, "loaded_at", "project"}

if BASE_KEY not in st.session_state:
    st.session_state[BASE_KEY] = rl.load_config()
    st.session_state[VERSION_KEY] = 0

st.title("🗺️ Roadmap Reporting")
st.caption("Project KPIs by initiative, as in slide 3 of the Template QP. "
           "Groups and topics are identified by Jira group labels and topic labels.")


def harvey_ball_svg(pct, size=22):
    """Harvey ball filled in proportion to pct (0-100); None draws a dashed empty ring."""
    r = size / 2 - 1.5
    c = size / 2
    if pct is None:
        return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"><circle cx="{c}" cy="{c}" '
                f'r="{r}" fill="none" stroke="#64748B" stroke-width="1.5" stroke-dasharray="3 2"/></svg>')
    ring = f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="#60A5FA" stroke-width="1.5"/>'
    frac = max(0.0, min(1.0, pct / 100))
    if frac >= 0.999:
        fill = f'<circle cx="{c}" cy="{c}" r="{r}" fill="#60A5FA"/>'
    elif frac <= 0.001:
        fill = ""
    else:
        # Wedge from 12 o'clock, clockwise
        angle = 2 * math.pi * frac
        x, y = c + r * math.sin(angle), c - r * math.cos(angle)
        large = 1 if frac > 0.5 else 0
        fill = f'<path d="M{c},{c} L{c},{c - r} A{r},{r} 0 {large} 1 {x:.2f},{y:.2f} Z" fill="#60A5FA"/>'
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{fill}{ring}</svg>'


st.markdown("""
    <style>
        .rr-banner { background: #1E293B; border-radius: 8px; padding: 0.35rem 0.8rem;
                     font-weight: 600; text-align: center; margin-bottom: 0.8rem; }
        .rr-head { background: #1E3A8A; border-radius: 8px; padding: 0.55rem 0.8rem;
                   font-weight: 700; text-align: center; margin-bottom: 0.6rem; min-height: 3.2rem;
                   display: flex; align-items: center; justify-content: center; }
        .rr-item { display: flex; gap: 0.7rem; align-items: flex-start; margin: 0.7rem 0; }
        .rr-ball { flex: 0 0 4.2rem; display: flex; flex-direction: column; align-items: center; gap: 2px; }
        .rr-pct { font-size: 0.78rem; font-weight: 700; line-height: 1.1; }
        .rr-due { font-size: 0.72rem; font-weight: 600; line-height: 1; white-space: nowrap; margin-top: 3px;
                  padding: 0.18rem 0.45rem; border-radius: 999px; }
        .rr-legend { font-size: 0.85rem; font-weight: 600; margin: -0.3rem 0 0.8rem 0; }
        .rr-legend .rr-swatch { display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%;
                                vertical-align: 0.02rem; margin: 0 0.3rem 0 0.8rem; }
        .rr-text { min-width: 0; padding-top: 2px; }
        .rr-text b { display: block; font-size: 0.95rem; line-height: 1.25; }
        .rr-text span { display: block; font-size: 0.8rem; opacity: 0.7; overflow-wrap: anywhere; margin-top: 2px; }
    </style>
""", unsafe_allow_html=True)

tab_report, tab_details, tab_config = st.tabs(["📊 Report", "📋 Details", "🏷️ Label configuration"])

# ---------------------------------------------------------------- Report
with tab_report:
    saved = rl.load_config()
    groups = saved["groups"]

    with st.container(border=True):
        col_project, col_load = st.columns([3, 1], vertical_alignment="bottom")
        with col_project:
            project = st.text_input(
                "Jira project key", key="rr_project",
                value=os.getenv("RELEASE_PLAN_JIRA_PROJECT", "") or os.getenv("JIRA_PROJECT_KEY", ""),
                help="Only Epics of this project are counted. Leave empty to search all projects.")
        with col_load:
            load_clicked = st.button("📥 Load progress from Jira", type="primary", width="stretch")
        st.caption(
            "Per ticket under the Epics with each Topic label: **100%** closed in a released version "
            f"(or in *{rp.NOT_RELEASE_RELEVANT}*) · **90%** closed, version not released yet · "
            "**50%** in progress (no resolution) · **0%** To Do. The Topic is the average; every ticket weighs the same.")

    if load_clicked:
        server = st.session_state.get("jira_server")
        token = st.session_state.get("jira_token")
        if not server or not token:
            st.error("Configure and test the Jira connection first on the Configuration page.")
        else:
            try:
                with st.spinner("Downloading Epics and tickets from Jira..."):
                    data = rp.load_topic_progress(
                        server, token, st.session_state.get("jira_auth_method", "Personal Access Token (Bearer PAT)"),
                        st.session_state.get("jira_email", ""), saved, project.strip())
            except Exception as e:  # Jira or network failure: keep the previous result
                st.error(f"Jira could not be read: {e}")
            else:
                st.session_state.pop(EXPORT_KEY, None)
                st.session_state[PROGRESS_KEY] = {"data": data, "project": project.strip(),
                                                  "loaded_at": datetime.now().strftime("%d.%m.%Y %H:%M")}

    loaded = st.session_state.get(PROGRESS_KEY)
    progress = loaded["data"] if loaded else {}
    if loaded:
        st.caption(f"Loaded {loaded['loaded_at']} · project {loaded['project'] or 'all'}.")
    else:
        st.info("Load the progress from Jira to fill the Harvey balls.")

    st.markdown(f'<div class="rr-banner">{html.escape(st.session_state.get("rr_exp_banner", rx.DEFAULT_BANNER))}</div>', unsafe_allow_html=True)
    if any(t.get("due") for g in groups for t in g["topics"]):
        st.markdown('<div class="rr-legend">Due date:' + "".join(
            f'<span class="rr-swatch" style="background:{color}"></span>{label}'
            for label, color in rl.DUE_STATUS.values()) + '</div>',
            unsafe_allow_html=True)
    if not groups:
        st.warning("No group labels configured. Add them in the Label configuration tab.")
    per_row = 4
    for start in range(0, len(groups), per_row):
        row = groups[start:start + per_row]
        for col, group in zip(st.columns(per_row, gap="small"), row):
            with col, st.container(border=True):
                st.markdown(f'<div class="rr-head">{html.escape(group["name"])}</div>', unsafe_allow_html=True)
                if not group["topics"]:
                    st.caption("No topics configured.")
                for topic in group["topics"]:
                    info = progress.get(topic["label"])
                    pct = info["progress"] if info else None
                    if not info:
                        hover = "Progress not loaded"
                    elif not info["epics"]:
                        hover = "No Epics with this label"
                    else:
                        hover = f"{len(info['tickets'])} tickets · {len(info['epics'])} Epics"
                    pct_text = "–" if pct is None else f"{pct:.0f}%"
                    due_html = ""
                    if topic.get("due"):
                        status = topic.get("status")
                        status_label = rl.DUE_STATUS[status][0] if status in rl.DUE_STATUS else "No status set"
                        due_html = (f'<span class="rr-due" title="{status_label}" style="background:'
                                    f'{rl.due_box_color(status)};color:{rl.DUE_TEXT_COLOR}">'
                                    f'{datetime.fromisoformat(topic["due"]):%d.%m.%y}</span>')
                    subtitle = (f'<span>{html.escape(topic["subtitle"])}</span>'
                                if topic.get("subtitle") else "")
                    st.markdown(
                        f'<div class="rr-item" title="{html.escape(hover)}">'
                        f'<div class="rr-ball">{harvey_ball_svg(pct, size=30)}'
                        f'<span class="rr-pct">{pct_text}</span>{due_html}</div>'
                        f'<div class="rr-text"><b>{html.escape(topic["name"])}</b>{subtitle}</div></div>',
                        unsafe_allow_html=True,
                    )

    st.subheader("📤 Export")
    template_path = rx.find_template()
    if not template_path:
        st.warning("No slide template found. Add 'Template QP.pptx' to assets/templates/ to export.")
    elif not progress:
        st.info("Load the progress from Jira first; the export uses the loaded data.")
    else:
        with st.container(border=True):
            st.caption(f"Fills the 'Project KPIs by initiative' slide of {os.path.basename(template_path)} "
                       "with the configured groups, topics and Harvey balls.")
            exp_title = st.text_input("Slide title", value=rx.DEFAULT_TITLE, key="rr_exp_title")
            exp_subtitle = st.text_input("Subtitle", value=rx.DEFAULT_SUBTITLE, key="rr_exp_subtitle")
            exp_banner = st.text_input("Banner", value=rx.DEFAULT_BANNER, key="rr_exp_banner")
            if st.button("🛠️ Prepare PowerPoint"):
                try:
                    st.session_state[EXPORT_KEY] = rx.build_roadmap_pptx(
                        saved, progress, template_path, exp_title, exp_subtitle, exp_banner)
                except rx.TemplateError as e:
                    st.session_state.pop(EXPORT_KEY, None)
                    st.error(f"The template could not be used: {e}")
            if st.session_state.get(EXPORT_KEY):
                st.download_button(
                    "⬇️ Download PowerPoint", data=st.session_state[EXPORT_KEY], type="primary",
                    file_name=f"Roadmap_Reporting_{datetime.now():%Y%m%d}.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")

# ---------------------------------------------------------------- Details
with tab_details:
    if not progress:
        st.info("Load the progress from Jira in the Report tab to see the details.")
    else:
        st.caption(f"Loaded {loaded['loaded_at']} · project {loaded['project'] or 'all'}.")
        summary = []
        for group in groups:
            for topic in group["topics"]:
                info = progress.get(topic["label"]) or {"epics": [], "tickets": [], "progress": None}
                counts = rp.bucket_counts(info["tickets"])
                summary.append({"Group": group["name"], "Topic": topic["name"],
                                "Progress": None if info["progress"] is None else round(info["progress"], 1),
                                "Due date": topic.get("due") or None,
                                "Due status": rl.DUE_STATUS[topic["status"]][0] if topic.get("status") else None,
                                "Epics": len(info["epics"]), "Tickets": len(info["tickets"]), **counts})
        st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch",
                     column_config={"Progress": st.column_config.ProgressColumn(
                         "Progress", format="%.0f%%", min_value=0, max_value=100)})
        for group in groups:
            for topic in group["topics"]:
                info = progress.get(topic["label"])
                if not info or not info["tickets"]:
                    continue
                with st.expander(f"{group['name']} › {topic['name']} · {len(info['tickets'])} tickets"):
                    tickets = pd.DataFrame(info["tickets"])
                    tickets["Score"] = tickets["bucket"].map(rp.BUCKET_SCORES)
                    st.dataframe(
                        tickets.rename(columns={"key": "Key", "summary": "Summary", "status": "Status",
                                                "epic": "Epic", "fix_versions": "Fix versions", "bucket": "Counted as"}),
                        hide_index=True, width="stretch")

# ---------------------------------------------------------------- Label configuration
with tab_config:
    st.markdown(
        "**Group labels** cluster big overarching topics and go on Initiatives "
        "(`RC2_G<#>_<Group Name>`). **Topic labels** are work packages inside one group and go on "
        "Initiatives or Epics (`RC2_G<#>_T<#>_<Topic Name>`). Each topic can have a subtitle (shown under its "
        "name), a due date and a status (On track, At risk, Late) that colours the date box under its Harvey ball. "
        "Table order is report order."
    )
    base = st.session_state[BASE_KEY]
    ver = st.session_state[VERSION_KEY]

    st.subheader("Group labels")
    groups_df = st.data_editor(
        pd.DataFrame(rl.groups_to_rows(base), columns=["Group", "Label"]),
        num_rows="dynamic", width="stretch", hide_index=True, key=f"rr_groups_{ver}",
        column_config={
            "Group": st.column_config.TextColumn("Group name", required=True),
            "Label": st.column_config.TextColumn("Jira label (Initiative level)", required=True),
        },
    )

    st.subheader("Topic labels per group")
    group_rows, topic_rows = [], []
    for idx, grow in groups_df.iterrows():
        # The editor keeps the original index of existing rows, so a group keeps its topics
        # when another row is deleted; new rows get a new index and start empty.
        base_group = base["groups"][idx] if isinstance(idx, int) and idx < len(base["groups"]) else {"topics": []}
        title = str(grow.get("Group") or "").strip() or "(unnamed group)"
        with st.expander(f"{title} · {str(grow.get('Label') or '').strip() or 'no label'}", expanded=False):
            topics_df = pd.DataFrame(rl.topics_to_rows(base_group), columns=["Topic", "Label", "Subtitle", "Due date", "Status"])
            topics_df["Due date"] = pd.to_datetime(topics_df["Due date"])
            tdf = st.data_editor(
                topics_df,
                num_rows="dynamic", width="stretch", hide_index=True, key=f"rr_topics_{ver}_{idx}",
                column_config={
                    "Topic": st.column_config.TextColumn("Topic name", required=True),
                    "Label": st.column_config.TextColumn("Jira label (Initiative or Epic level)", required=True),
                    "Subtitle": st.column_config.TextColumn(
                        "Subtitle", help="Short text shown under the topic name in the report and the slide."),
                    "Due date": st.column_config.DateColumn("Due date", format="DD.MM.YYYY"),
                    "Status": st.column_config.SelectboxColumn(
                        "Status", options=[label for label, _ in rl.DUE_STATUS.values()],
                        help="Due-date status shown under the Harvey ball: On track, At risk or Late."),
                },
            )
        group_rows.append(grow.to_dict())
        topic_rows.append(tdf.to_dict("records"))

    draft = rl.build_config(group_rows, topic_rows)
    errors, warnings = rl.validate_config(draft)
    dirty = draft != rl.load_config()

    for e in errors:
        st.error(e)
    for w in warnings:
        st.warning(w)
    n_topics = sum(len(g["topics"]) for g in draft["groups"])
    st.caption(f"{len(draft['groups'])} groups · {n_topics} topics"
               + (" · unsaved changes" if dirty else " · saved"))

    with st.container(horizontal=True):
        if st.button("💾 Save configuration", type="primary", disabled=bool(errors) or not dirty):
            rl.save_config(draft)
            st.session_state[BASE_KEY] = draft
            st.session_state[VERSION_KEY] += 1
            st.toast("Label configuration saved.")
            st.rerun()
        if st.button("↩️ Discard changes", disabled=not dirty):
            st.session_state[BASE_KEY] = rl.load_config()
            st.session_state[VERSION_KEY] += 1
            st.rerun()
        if st.button("🔄 Load defaults", help="Fill the tables with the labels from the Project Milestone "
                                               "Tracking document. Nothing is saved until you click Save."):
            st.session_state[BASE_KEY] = rl.normalize_config(rl.DEFAULT_CONFIG)
            st.session_state[VERSION_KEY] += 1
            st.rerun()
