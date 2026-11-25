"""Roadmap Reporting: project KPIs by initiative (slide 3 of Template QP).

Three steps:
1. Set up: the Jira group labels (on Initiatives) and, inside each group, the topic labels (on
   Initiatives or Epics), each topic with an optional subtitle, due date and status.
2. Load & Details: progress of every topic from Jira (utils.roadmap_progress) and its details.
3. Report: the topics laid out as in the slide, and the PowerPoint export.
"""
import base64
import html
import logging
import math
import os
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from utils import roadmap_labels as rl
from utils import roadmap_export as rx
from utils import roadmap_jira_labels as rj
from utils import roadmap_progress as rp
from utils import pptx_preview
from utils.stepper import render_stepper

BASE_KEY = "rr_cfg_base"      # configuration the editors start from (saved file, or defaults after a reset)
VERSION_KEY = "rr_cfg_ver"    # bumped to reset the editors after save / discard / reset
PROGRESS_KEY = "rr_progress"  # {"data": load_topic_progress result, "loaded_at", "project"}
IMPORT_KEY = "rr_import"     # {"labels", "complete", "prefix", "group_pattern", "topic_pattern"} from Jira
PROJECT_KEY = "rr_project_value"  # project key typed in step 2 (kept when the step is left)
STEP_KEY = "rr_step"
STEPS = ["⚙️ Set up", "📥 Load & Details", "📊 Report"]

logger = logging.getLogger(__name__)


@st.cache_data(show_spinner=False, max_entries=8)
def _build_export(config, progress, template_path, template_mtime, title, subtitle, banner):
    """(PowerPoint bytes, SVG preview of its slide or None). template_mtime refreshes the cache on edits."""
    data = rx.build_roadmap_pptx(config, progress, template_path, title, subtitle, banner)
    try:
        svg = pptx_preview.slide_to_svg(data)
    except Exception:  # the preview is a convenience: never block the download
        logger.warning("Slide preview failed", exc_info=True)
        svg = None
    return data, svg


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
        .rr-preview { width: 100%; height: auto; border-radius: 6px; display: block;
                      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25); margin: 0.2rem 0 0.4rem 0; }
        .rr-legend { font-size: 0.85rem; font-weight: 600; margin: -0.3rem 0 0.8rem 0; }
        .rr-legend .rr-swatch { display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%;
                                vertical-align: 0.02rem; margin: 0 0.3rem 0 0.8rem; }
        .rr-text { min-width: 0; padding-top: 2px; }
        .rr-text b { display: block; font-size: 0.95rem; line-height: 1.25; }
        .rr-text span { display: block; font-size: 0.8rem; opacity: 0.7; overflow-wrap: anywhere; margin-top: 2px; }
    </style>
""", unsafe_allow_html=True)

render_stepper(STEPS, STEP_KEY, key="rr_stepper")
step = st.session_state[STEP_KEY]
saved = rl.load_config()
groups = saved["groups"]
loaded = st.session_state.get(PROGRESS_KEY)
progress = loaded["data"] if loaded else {}

# ---------------------------------------------------------------- 1. Set up
if step == STEPS[0]:
    # First option of the step; filled further down, once the tables (with unsaved edits) have been read
    import_box = st.container()
    st.markdown(
        "**Group labels** cluster big overarching topics and go on Initiatives "
        "(`RC2_G<#>_<Group Name>`). **Topic labels** are work packages inside one group and go on "
        "Initiatives or Epics (`RC2_G<#>_T<#>_<Topic Name>`). Each topic can have a subtitle (shown under its "
        "name), a due date and a status (On track, At risk, Late) that colours the date box under its Harvey ball. "
        "Topics appear in the order of their **Order** number; groups in table order."
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
            topics_df = pd.DataFrame(rl.topics_to_rows(base_group), columns=["Order", "Topic", "Label", "Subtitle", "Due date", "Status"])
            topics_df["Due date"] = pd.to_datetime(topics_df["Due date"])
            tdf = st.data_editor(
                topics_df,
                num_rows="dynamic", width="stretch", hide_index=True, key=f"rr_topics_{ver}_{idx}",
                column_config={
                    "Order": st.column_config.NumberColumn(
                        "Order", min_value=1, step=1, format="%d", width="small",
                        help="Position of the topic in its group. Change a number and the table is sorted "
                             "right away; save to keep the new order. Topics without a number go last."),
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
    if any([id(r) for r in rl.sort_by_order(rows)] != [id(r) for r in rows] for rows in topic_rows):
        # An order number changed: show the tables sorted and renumbered right away. The draft keeps
        # every unsaved edit, so it becomes the editors' new starting point (nothing is saved).
        st.session_state[BASE_KEY] = draft
        st.session_state[VERSION_KEY] += 1
        st.rerun()
    with import_box:
        st.subheader("🔎 Import labels from Jira")
        st.caption("Finds the group and topic labels used in Jira that start with the prefix, and adds the "
                   "ones that are not in the tables yet. A topic goes to the group with the same group number "
                   "(G<#>). Nothing is saved until you click Save configuration.")
        c_prefix, c_group, c_topic = st.columns([1, 2, 2])
        prefix = c_prefix.text_input("Search prefix", value=rj.DEFAULT_PREFIX, key="rr_imp_prefix")
        group_pattern = c_group.text_input(
            "Group label pattern", value=rj.DEFAULT_GROUP_PATTERN, key="rr_imp_group",
            help="Regular expression; its first group in brackets is the group number.")
        topic_pattern = c_topic.text_input(
            "Topic label pattern", value=rj.DEFAULT_TOPIC_PATTERN, key="rr_imp_topic",
            help="Regular expression; its first group in brackets is the group number, the second the topic number.")
        try:
            group_rx = rj.compile_pattern(group_pattern, 1, "group")
            topic_rx = rj.compile_pattern(topic_pattern, 2, "topic")
        except ValueError as e:
            group_rx = topic_rx = None
            st.error(str(e))
        if st.button("🔎 Search Jira", disabled=group_rx is None):
            server, token = st.session_state.get("jira_server"), st.session_state.get("jira_token")
            if not server or not token:
                st.error("Configure and test the Jira connection first on the Configuration page.")
            else:
                try:
                    with st.spinner("Reading the labels from Jira..."):
                        labels, complete = rj.fetch_labels(
                            server, token, st.session_state.get("jira_auth_method", "Personal Access Token (Bearer PAT)"),
                            st.session_state.get("jira_email", ""), prefix)
                except (rj.JiraLabelsError, requests.RequestException) as e:
                    st.error(f"The labels could not be read from Jira: {e}")
                else:
                    st.session_state[IMPORT_KEY] = {"labels": labels, "complete": complete}

        found = st.session_state.get(IMPORT_KEY)
        if found and group_rx is not None:
            plan = rj.plan_import(draft, found["labels"], group_rx, topic_rx)
            st.caption(f"{len(found['labels'])} labels found in Jira starting with the prefix · "
                       f"{plan['known']} already in the tables.")
            if not found["complete"]:
                st.warning("Jira returned too many labels to read them all; narrow the search prefix.")
            if plan["new_groups"] or plan["new_topics"]:
                rows = [{"Type": "Group", "Label": g["label"], "Name": g["name"], "Group": g["label"]}
                        for g in plan["new_groups"]] + [
                       {"Type": "Topic", "Label": t["label"], "Name": t["name"], "Group": t["group_label"]}
                       for t in plan["new_topics"]]
                st.markdown(f"**New in Jira** ({len(rows)})")
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                if st.button(f"➕ Add {len(rows)} new label(s) to the tables", type="primary"):
                    st.session_state[BASE_KEY] = rj.apply_import(draft, plan)
                    st.session_state[VERSION_KEY] += 1
                    st.session_state.pop(IMPORT_KEY, None)
                    st.toast("Labels added to the tables. Review the names and save the configuration.")
                    st.rerun()
            else:
                st.success("Every group and topic label found in Jira is already in the tables.")
            if plan["orphans"]:
                st.warning("Topic labels without a group (no group label with the same number): "
                           + ", ".join(f"`{x}`" for x in plan["orphans"]))
            if plan["not_in_jira"]:
                st.info("In the tables but not used in Jira yet: " + ", ".join(f"`{x}`" for x in plan["not_in_jira"]))
            if plan["other"]:
                st.caption("Ignored (match neither pattern): " + ", ".join(f"`{x}`" for x in plan["other"]))

    errors, warnings = rl.validate_config(draft)
    dirty = draft != rl.load_config()

    for e in errors:
        st.error(e)
    for w in warnings:
        st.warning(w)
    n_topics = sum(len(g["topics"]) for g in draft["groups"])
    st.caption(f"{len(draft['groups'])} groups · {n_topics} topics"
               + (" · unsaved changes: save them before changing step, or they are lost" if dirty else " · saved"))

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

# ---------------------------------------------------------------- 2. Load & Details
elif step == STEPS[1]:
    with st.container(border=True):
        col_project, col_load = st.columns([3, 1], vertical_alignment="bottom")
        with col_project:
            project = st.text_input(
                "Jira project key", key="rr_project",
                value=st.session_state.get(PROJECT_KEY) if PROJECT_KEY in st.session_state
                else os.getenv("RELEASE_PLAN_JIRA_PROJECT", "") or os.getenv("JIRA_PROJECT_KEY", ""),
                help="Only Epics of this project are counted. Leave empty to search all projects.")
            st.session_state[PROJECT_KEY] = project
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
                st.session_state[PROGRESS_KEY] = {"data": data, "project": project.strip(),
                                                  "loaded_at": datetime.now().strftime("%d.%m.%Y %H:%M")}

    loaded = st.session_state.get(PROGRESS_KEY)
    progress = loaded["data"] if loaded else {}

    if not progress:
        st.info("Load the progress from Jira to see the details per topic.")
    else:
        st.caption(f"Loaded {loaded['loaded_at']} · project {loaded['project'] or 'all'}. "
                   "Go to Report to see the slide view and export it.")
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

# ---------------------------------------------------------------- 3. Report
else:
    if loaded:
        st.caption(f"Loaded {loaded['loaded_at']} · project {loaded['project'] or 'all'}.")
    else:
        st.info("Load the progress from Jira in step 2 to fill the Harvey balls.")
    st.markdown(f'<div class="rr-banner">{html.escape(st.session_state.get("rr_exp_banner", rx.DEFAULT_BANNER))}</div>', unsafe_allow_html=True)
    if any(t.get("due") for g in groups for t in g["topics"]):
        st.markdown('<div class="rr-legend">Due date:' + "".join(
            f'<span class="rr-swatch" style="background:{color}"></span>{label}'
            for label, color in rl.DUE_STATUS.values()) + '</div>',
            unsafe_allow_html=True)
    if not groups:
        st.warning("No group labels configured. Add them in step 1, Set up.")
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
        st.info("Load the progress from Jira in step 2 first; the export uses the loaded data.")
    else:
        with st.container(border=True):
            st.caption(f"Fills the 'Project KPIs by initiative' slide of {os.path.basename(template_path)} "
                       "with the configured groups, topics and Harvey balls.")
            exp_title = st.text_input("Slide title", value=rx.DEFAULT_TITLE, key="rr_exp_title")
            exp_subtitle = st.text_input("Subtitle", value=rx.DEFAULT_SUBTITLE, key="rr_exp_subtitle")
            exp_banner = st.text_input("Banner", value=rx.DEFAULT_BANNER, key="rr_exp_banner")
            try:
                pptx_bytes, preview_svg = _build_export(saved, progress, template_path, os.path.getmtime(template_path),
                                                        exp_title, exp_subtitle, exp_banner)
            except rx.TemplateError as e:
                st.error(f"The template could not be used: {e}")
            else:
                st.markdown("**👁️ Slide preview**")
                if preview_svg:
                    encoded = base64.b64encode(preview_svg.encode("utf-8")).decode("ascii")
                    st.markdown(f'<img class="rr-preview" alt="Slide preview" '
                                f'src="data:image/svg+xml;base64,{encoded}"/>', unsafe_allow_html=True)
                    st.caption("Drawn in the browser with its own fonts: line breaks can differ slightly "
                               "from PowerPoint.")
                else:
                    st.info("The preview could not be drawn; the PowerPoint can still be downloaded.")
                st.download_button(
                    "⬇️ Download PowerPoint", data=pptx_bytes, type="primary",
                    file_name=f"Roadmap_Reporting_{datetime.now():%Y%m%d}.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
