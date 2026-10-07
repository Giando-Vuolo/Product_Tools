import streamlit as st
import pandas as pd
import requests
import os
import re
from datetime import datetime, timezone
import numpy as np
from html.parser import HTMLParser
import altair as alt

from utils.kpi_helpers import (
    fetch_sprint_kpi_data,
    publish_kpis_to_confluence,
    fetch_confluence_kpi_history,
    sort_df_chronologically,
    format_sprint_label,
    QUALITY_KPIS, configured_quality_kpis, build_code_quality_chart
)

from utils.sonar_helpers import SONAR_KPIS, sonar_configured, fetch_sonar_kpis, format_kpi_value
from utils.sbom_helpers import SBOM_KPI, sbom_configured, fetch_dependency_findings
from utils.vanguard_helpers import VANGUARD_KPI, vanguard_configured, fetch_platform_findings


def fetch_sprint_kpi_dataset():
    st.session_state.kpi_loading = True
    st.session_state.kpi_error = ""
    
    server = st.session_state.get("jira_server", "")
    token = st.session_state.get("jira_token", "")
    auth_type = st.session_state.get("jira_auth_method", "")
    email = st.session_state.get("jira_email", "")
    sprint_query = st.session_state.get("kpi_sprint_query", "")
    selected_types = st.session_state.get("kpi_selected_types", [])
    
    res = fetch_sprint_kpi_data(server, token, auth_type, email, sprint_query, selected_types)
    
    if res.get("error"):
        st.session_state.kpi_error = res["error"]
        st.session_state.kpi_loading = False
        return
        
    quality_kpis = {}
    if sonar_configured():
        try:
            quality_kpis = fetch_sonar_kpis(res.get("sprint_end"))
        except Exception as e:
            st.session_state.kpi_error += f"\nWarning: SonarQube: {str(e)}"
    if sbom_configured():
        try:
            quality_kpis[SBOM_KPI] = fetch_dependency_findings()
        except Exception as e:
            st.session_state.kpi_error += f"\nWarning: SBOM Inventory: {str(e)}"
    st.session_state.kpi_vanguard_fetched_at = None
    if vanguard_configured():
        try:
            quality_kpis[VANGUARD_KPI] = fetch_platform_findings()
            st.session_state.kpi_vanguard_fetched_at = datetime.now(timezone.utc)
        except ValueError as e:
            st.session_state.kpi_error += f"\nWarning: {e}"

    st.session_state.kpi_quality = quality_kpis
    st.session_state.kpi_data = res.get("df", pd.DataFrame())
    st.session_state.kpi_gh_added_keys = res.get("gh_added_keys", [])
    st.session_state.kpi_releases_count = res.get("releases_count", 0)
    st.session_state.kpi_global_open_bugs = res.get("global_open_bugs", 0)
    st.session_state.kpi_global_critical_bugs = res.get("global_critical_bugs", 0)
    st.session_state.kpi_sprint_start = res.get("sprint_start")
    st.session_state.kpi_sprint_end = res.get("sprint_end")
    st.session_state.kpi_sprint_name = res.get("sprint_name")
    st.session_state.kpi_loading = False

def render_confluence_kpi_charts(df_hist):
    if df_hist is None or df_hist.empty:
        st.info("No historical KPI data found on Confluence.")
        return

    df_plot = df_hist.copy()

    # Determine sprint column label for X axis
    sprint_col = None
    for pattern in ["sprint name", "sprint", "target dates"]:
        for c in df_plot.columns:
            if pattern in c.lower():
                sprint_col = c
                break
        if sprint_col:
            break
    if not sprint_col:
        sprint_col = df_plot.columns[0]

    # Dynamically append currently calculated sprint metrics if not already present in the history
    current_metrics = st.session_state.get("current_sprint_metrics")
    if current_metrics:
        sprint_name_val = current_metrics["sprint_name"]
        sprint_exists = False
        for col in df_plot.columns:
            if "sprint" in col.lower():
                if sprint_name_val in df_plot[col].astype(str).values:
                    sprint_exists = True
                    break
        
        if not sprint_exists:
            new_row = {}
            for col in df_plot.columns:
                col_lower = col.lower().strip()
                if col.strip() in QUALITY_KPIS:
                    new_row[col] = current_metrics.get("quality", {}).get(col.strip(), "")
                elif "sprint name" in col_lower:
                    new_row[col] = sprint_name_val
                elif "sprint" in col_lower:
                    new_row[col] = sprint_name_val
                elif "dates" in col_lower or "target dates" in col_lower:
                    new_row[col] = current_metrics["dates"]
                elif "committed sp" in col_lower or "committed" in col_lower:
                    new_row[col] = current_metrics["total_sp"]
                elif "delivered sp" in col_lower or "delivered" in col_lower or "achieved" in col_lower:
                    new_row[col] = current_metrics["achieved_sp"]
                elif "delivery" in col_lower or "pct" in col_lower or "cumplimiento" in col_lower:
                    new_row[col] = current_metrics["sprint_pct"]
                elif "releases" in col_lower:
                    new_row[col] = current_metrics["releases"]
                elif "critical bugs" in col_lower or "crit" in col_lower:
                    new_row[col] = current_metrics["crit_bugs"]
                elif "resolved bugs" in col_lower:
                    new_row[col] = current_metrics.get("resolved_bugs", "")
                elif "open bugs" in col_lower or "bugs" in col_lower:
                    new_row[col] = current_metrics["open_bugs"]
                elif "cycle time" in col_lower:
                    new_row[col] = current_metrics["cycle_time"]
                else:
                    new_row[col] = ""
            df_plot = pd.concat([df_plot, pd.DataFrame([new_row])], ignore_index=True)

    def find_column(df_target, patterns):
        cols = list(df_target.columns)
        # Exact match first
        for p in patterns:
            p_lower = p.lower()
            for c in cols:
                if p_lower == c.lower().strip():
                    return c
        # Substring match fallback
        for p in patterns:
            p_lower = p.lower()
            for c in cols:
                if p_lower in c.lower():
                    return c
        return None

    def extract_numeric_col(df_target, patterns):
        matched_col = find_column(df_target, patterns)
        if matched_col:
            s = df_target[matched_col].astype(str)
            s_clean = s.str.replace("%", "", regex=False).str.replace(",", ".", regex=False).str.strip()
            num = pd.to_numeric(s_clean, errors="coerce")
            return num
        return pd.Series(dtype=float, index=df_target.index)

    # Sort chronologically ascending
    df_plot = sort_df_chronologically(df_plot, sprint_col)

    df_plot["Sprint Display"] = df_plot[sprint_col].apply(lambda x: format_sprint_label(x, 12))

    # Keep at most the last 5 sprints for the chart
    df_plot = df_plot.tail(5)

    df_plot["Committed SP"] = extract_numeric_col(df_plot, ["committed sp (at start)", "committed sp", "committed"])
    df_plot["Delivered SP"] = extract_numeric_col(df_plot, ["delivered sp (total)", "delivered sp", "delivered", "achieved"])
    df_plot["Delivery %"] = extract_numeric_col(df_plot, ["delivery %", "delivery", "pct", "entrega", "cumplimiento"])
    
    # Fallback calculation if Delivery % is NaN or missing in table
    if "Committed SP" in df_plot.columns and "Delivered SP" in df_plot.columns:
        calc_pct = (df_plot["Delivered SP"] / df_plot["Committed SP"] * 100).round(1)
        df_plot["Delivery %"] = df_plot["Delivery %"].fillna(calc_pct)

    df_plot["Avg Cycle Time (Days)"] = extract_numeric_col(df_plot, ["avg cycle time (days)", "avg cycle time", "cycle time"])
    df_plot["Open Bugs (Sev A+B)"] = extract_numeric_col(df_plot, ["open bugs (sev a+b)", "open bugs"])
    df_plot["Critical Bugs (Sev A)"] = extract_numeric_col(df_plot, ["critical bugs (sev a)", "critical bugs"])

    # Render charts in a 2x2 grid layout (2 rows with 2 columns)
    r1_col1, r1_col2 = st.columns(2)
    with r1_col1:
        st.markdown("**Committed vs Delivered Story Points**")
        st.markdown("<small>Compares the total Story Points committed at the beginning of the sprint against the total Story Points actually delivered by the end of the sprint.<br/><b>Calculation:</b> Committed SP strictly excludes scope creep (tickets added mid-sprint). Delivered SP includes all resolved tickets on or before the sprint's End Date.</small>", unsafe_allow_html=True)
        df_sp = df_plot[["Sprint Display", "Committed SP", "Delivered SP"]].dropna(subset=["Committed SP", "Delivered SP"], how="all")
        if not df_sp.empty:
            df_sp_melted = df_sp.melt(id_vars=["Sprint Display"], value_vars=["Committed SP", "Delivered SP"], var_name="Metric", value_name="Story Points")
            bars_sp = alt.Chart(df_sp_melted).mark_bar().encode(
                x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0), sort=None),
                xOffset="Metric:N",
                y=alt.Y("Story Points:Q", title="Story Points"),
                color=alt.Color("Metric:N", legend=alt.Legend(orient="top", title=None), scale=alt.Scale(range=["#42a5f5", "#66bb6a"])),
                tooltip=["Sprint Display", "Metric", "Story Points"]
            )
            text_sp = bars_sp.mark_text(
                align='center',
                baseline='bottom',
                dy=-5
            ).encode(
                text=alt.Text("Story Points:Q", format=".0f")
            )
            chart_sp = (bars_sp + text_sp).properties(height=280)
            st.altair_chart(chart_sp, use_container_width=True)
        else:
            st.info("No Story Points data found in table.")

    with r1_col2:
        st.markdown("**Delivery % Trend**")
        st.markdown("<small>Measures the team's ability to complete their committed workload, indicating predictability and sprint success rate over time.<br/><b>Calculation:</b> (Delivered SP / Committed SP) * 100. Can exceed 100% if scope creep tickets are completed.</small>", unsafe_allow_html=True)
        df_pct = df_plot[["Sprint Display", "Delivery %"]].dropna(subset=["Delivery %"])
        if not df_pct.empty:
            bars_pct = alt.Chart(df_pct).mark_bar(color="#ab47bc").encode(
                x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0), sort=None),
                y=alt.Y("Delivery %:Q", title="Delivery %"),
                tooltip=["Sprint Display", "Delivery %"]
            )
            text_pct = bars_pct.mark_text(
                align='center',
                baseline='bottom',
                dy=-5,
                color='#ab47bc'
            ).encode(
                text=alt.Text("Delivery %:Q", format=".1f")
            )
            chart_pct = (bars_pct + text_pct).properties(height=280)
            st.altair_chart(chart_pct, use_container_width=True)
        else:
            st.info("No Delivery % data found in table.")

    st.markdown("<br/>", unsafe_allow_html=True)

    r2_col1, r2_col2 = st.columns(2)
    with r2_col1:
        st.markdown("**Average Cycle Time (Days)**")
        st.markdown("<small>Tracks the average working time it takes for a team member to complete an issue once they start actively working on it.<br/><b>Calculation:</b> The mathematical mean of business days (excluding weekends) from the last 'In Progress' transition until 'Resolved', clamped to the sprint start date.</small>", unsafe_allow_html=True)
        df_ct = df_plot[["Sprint Display", "Avg Cycle Time (Days)"]].dropna(subset=["Avg Cycle Time (Days)"])
        if not df_ct.empty:
            bars_ct = alt.Chart(df_ct).mark_bar(color="#ffa726").encode(
                x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0), sort=None),
                y=alt.Y("Avg Cycle Time (Days):Q", title="Days"),
                tooltip=["Sprint Display", "Avg Cycle Time (Days)"]
            )
            text_ct = bars_ct.mark_text(
                align='center',
                baseline='bottom',
                dy=-5,
                color='#ffa726'
            ).encode(
                text=alt.Text("Avg Cycle Time (Days):Q", format=".1f")
            )
            chart_ct = (bars_ct + text_ct).properties(height=280)
            st.altair_chart(chart_ct, use_container_width=True)
        else:
            st.info("No Cycle Time data found in table.")

    with r2_col2:
        st.markdown("**Open & Critical Bugs Trend**")
        st.markdown("<small>Monitors the overall health and stability of the project by tracking unresolved high-priority bugs at the end of each sprint.<br/><b>Calculation:</b> Uses JQL to count all project bugs (Sev A+B) created before the sprint ended that remained unresolved, or were resolved after the sprint started.</small>", unsafe_allow_html=True)
        df_bugs = df_plot[["Sprint Display", "Open Bugs (Sev A+B)", "Critical Bugs (Sev A)"]].dropna(subset=["Open Bugs (Sev A+B)", "Critical Bugs (Sev A)"], how="all")
        if not df_bugs.empty:
            df_bugs_melted = df_bugs.melt(id_vars=["Sprint Display"], value_vars=["Open Bugs (Sev A+B)", "Critical Bugs (Sev A)"], var_name="Bug Type", value_name="Count")
            bars_bugs = alt.Chart(df_bugs_melted).mark_bar().encode(
                x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0), sort=None),
                xOffset="Bug Type:N",
                y=alt.Y("Count:Q", title="Bugs"),
                color=alt.Color("Bug Type:N", legend=alt.Legend(orient="top", title=None), scale=alt.Scale(range=["#29b6f6", "#b71c1c"])),
                tooltip=["Sprint Display", "Bug Type", "Count"]
            )
            text_bugs = bars_bugs.mark_text(
                align='center',
                baseline='bottom',
                dy=-5
            ).encode(
                text=alt.Text("Count:Q", format=".0f")
            )
            chart_bugs = (bars_bugs + text_bugs).properties(height=280)
            st.altair_chart(chart_bugs, use_container_width=True)
        else:
            st.info("No Bugs data found in table.")

    for name in QUALITY_KPIS:
        if find_column(df_plot, [name]):
            df_plot[name] = extract_numeric_col(df_plot, [name])
    chart_quality = build_code_quality_chart(df_plot)
    if chart_quality is not None:
        st.markdown("<br/>", unsafe_allow_html=True)
        st.caption("Code Quality Trend (SonarQube, SBOM Inventory, Vanguard)")
        st.altair_chart(chart_quality)
def render_dashboard():
    df = st.session_state.kpi_data
    if df is None or df.empty:
        st.info("No data found for this sprint.")
        return
        
    if "Include" not in df.columns:
        df["Include"] = True

    sort_order_df = df[["Key", "Cycle Time (Days)"]].sort_values(by="Cycle Time (Days)", ascending=False, na_position="last").reset_index(drop=True)
    editor_state = st.session_state.get("kpi_editor", {})
    if "edited_rows" in editor_state:
        for idx_str, edits in editor_state["edited_rows"].items():
            if "Include" in edits:
                row_idx = int(idx_str)
                if row_idx < len(sort_order_df):
                    edited_key = sort_order_df.loc[row_idx, "Key"]
                    df.loc[df["Key"] == edited_key, "Include"] = edits["Include"]
    
    st.session_state.kpi_data = df
    df_calc = df[df["Include"] == True]

    st.markdown("### 📈 Sprint KPIs Overview")
    
    s_start = st.session_state.get("kpi_sprint_start")
    s_end = st.session_state.get("kpi_sprint_end")
    if s_start and s_end:
        st.caption(f"Sprint Target Dates: {s_start.strftime('%Y-%m-%d %H:%M')} to {s_end.strftime('%Y-%m-%d %H:%M')}")
    else:
        st.caption("⚠️ Could not detect Sprint dates. Releases metric will be 0.")
        
    gh_added_keys = st.session_state.get("kpi_gh_added_keys", [])
    
    # "Committed SP (at Start)": Exclude any issue that was added after the sprint started (scope creep)
    # This ensures we respect the user's Issue Type filters (e.g. if they unchecked "Task")
    total_sp = df_calc[~df_calc["Key"].isin(gh_added_keys)]["Story Points"].sum()
    
    # "Delivered SP (Total)": Sum of all resolved issues (including scope creep)
    achieved_sp = df_calc[df_calc["Resolved"] == True]["Story Points"].sum()
    
    if gh_added_keys:
        st.caption("✨ Committed SP accurately excludes scope creep tickets added mid-sprint.")
    
    sprint_pct = (achieved_sp / total_sp * 100) if total_sp > 0 else 0
    
    releases_count = st.session_state.get("kpi_releases_count", 0)
    
    bugs = df_calc[df_calc["Is Bug"] == True]
    resolved_bugs = len(bugs[bugs["Resolved"] == True])
    open_bugs_df = bugs[bugs["Resolved"] == False]
    
    sev_a_open = len(open_bugs_df[open_bugs_df["Is Sev A"] == True])
    sev_b_open = len(open_bugs_df[open_bugs_df["Is Sev B"] == True])
    
    # Overwrite with global counts from session state
    open_critical_bugs = st.session_state.get("kpi_global_critical_bugs", sev_a_open)
    open_bugs = st.session_state.get("kpi_global_open_bugs", sev_a_open + sev_b_open)
    
    if len(df_calc) > 0 and "Cycle Time (Days)" in df_calc.columns:
        avg_cycle_time = df_calc["Cycle Time (Days)"].mean()
        avg_cycle_time = round(avg_cycle_time, 2) if pd.notnull(avg_cycle_time) else 0
    else:
        avg_cycle_time = 0
        
    # Store calculated metrics in session state so charts can include the current un-published sprint
    date_str = f"{s_start.strftime('%Y-%m-%d')} to {s_end.strftime('%Y-%m-%d')}" if (s_start and s_end) else "Unknown"
    quality_kpis = st.session_state.get("kpi_quality") or {}
    st.session_state.current_sprint_metrics = {
        "sprint_name": st.session_state.get("kpi_sprint_name") or st.session_state.get("kpi_sprint_query"),
        "dates": date_str,
        "total_sp": total_sp,
        "achieved_sp": achieved_sp,
        "sprint_pct": f"{sprint_pct:.1f}%",
        "releases": releases_count,
        "open_bugs": open_bugs,
        "crit_bugs": open_critical_bugs,
        "resolved_bugs": resolved_bugs,
        "cycle_time": avg_cycle_time,
        "quality": {name: format_kpi_value(name, quality_kpis.get(name)) for name in QUALITY_KPIS}
    }
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Committed SP (at Start)", f"{total_sp:g}", help="Sums the Story Points of all tickets in the sprint, strictly excluding any tickets identified by Jira as being added after the sprint started (scope creep).")
        st.metric("Delivered SP (Total)", f"{achieved_sp:g}", help="Sums the Story Points of all tickets in the sprint where a resolution date exists and is on or before the sprint's official End Date.")
    with col2:
        st.metric("Delivery %", f"{sprint_pct:.1f}%", help="Calculated as (Delivered SP / Committed SP) * 100. It is possible for this metric to exceed 100% if the team completes scope creep tickets.")
        st.metric("Sprint Releases", str(releases_count))
    with col3:
        st.metric("Resolved Bugs", str(resolved_bugs))
        st.metric("Average Cycle Time", f"{avg_cycle_time:.1f} days" if pd.notna(avg_cycle_time) else "N/A", help="The mathematical mean of business days elapsed from the first time a ticket transitions to 'In Progress' until it reaches a 'Resolved' status.")
    with col4:
        st.metric("Project Open Bugs (Sev A + B)", str(open_bugs), help="Counts all tickets of type 'Bug' with labels Sev-A or Sev-B that were created before the sprint ended, and were either still unresolved or resolved after the sprint started.")
        st.metric("Project Critical Open Bugs (Sev A)", str(open_critical_bugs), help="Same calculation as Open Bugs, but strictly filtered for the Sev-A label.")

    quality_names = configured_quality_kpis()
    if quality_names:
        sources = []
        if sonar_configured():
            sources.append(f"SonarQube ({os.getenv('SONAR_COMPONENT')}) at sprint end")
        if sbom_configured():
            sources.append(f"{SBOM_KPI}: SBOM Inventory today, dev + prod")
        if vanguard_configured():
            captured_at = st.session_state.get("kpi_vanguard_fetched_at")
            if captured_at:
                sources.append(f"Vanguard: open findings, excluding previews, captured {captured_at:%Y-%m-%d %H:%M UTC}")
            else:
                sources.append("Vanguard: current findings not available; calculate KPIs to retry")
        st.caption("Code Quality from " + " · ".join(sources))
        for start in range(0, len(quality_names), 4):
            for col, name in zip(st.columns(4), quality_names[start:start + 4]):
                col.metric(name, format_kpi_value(name, quality_kpis.get(name)) or "N/A")

    st.divider()
    
    st.markdown("#### 📋 Issue Details (Cycle Times)")
    
    server_clean = st.session_state.get("jira_server", "").rstrip("/")
    if "Jira URL" not in df.columns:
        df["Jira URL"] = df["Key"].apply(lambda k: f"{server_clean}/browse/{k}" if server_clean else k)
    if "Labels" not in df.columns:
        df["Labels"] = ""

    disp_df = df[["Include", "Jira URL", "Type", "Status", "Labels", "Story Points", "Resolved", "Last In Progress", "Resolved At", "Cycle Time (Days)"]].copy()
    disp_df["Last In Progress"] = disp_df["Last In Progress"].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notnull(x) else "-")
    disp_df["Resolved At"] = disp_df["Resolved At"].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notnull(x) else "-")
    disp_df = disp_df.rename(columns={
        "Jira URL": "Key",
        "Last In Progress": "Start Date",
        "Resolved At": "Resolved Date"
    })
    
    disp_df = disp_df.sort_values(by="Cycle Time (Days)", ascending=False, na_position="last").reset_index(drop=True)

    st.data_editor(
        disp_df,
        key="kpi_editor",
        use_container_width=True,
        disabled=["Key", "Type", "Status", "Labels", "Story Points", "Resolved", "Start Date", "Resolved Date", "Cycle Time (Days)"],
        column_config={
            "Include": st.column_config.CheckboxColumn("Include", default=True),
            "Key": st.column_config.LinkColumn(
                "Key",
                display_text=r".*/browse/(.*)"
            )
        }
    )
    
    st.divider()
    
    st.markdown("### 🔌 Confluence Publisher")
    st.markdown("Append this sprint's KPIs to a Confluence page. If the page doesn't exist, it will be created.")
    
    # Load defaults from env
    default_conf_server = os.getenv("CONFLUENCE_SERVER", "")
    default_conf_token = os.getenv("CONFLUENCE_API_TOKEN", "")
    default_conf_space = os.getenv("CONFLUENCE_SPACE", "DS")
    default_conf_page = os.getenv("CONFLUENCE_KPI_PAGE", "70_Project KPIs")
    
    conf_server = st.session_state.get("conf_server", default_conf_server)
    conf_token = st.session_state.get("conf_token", default_conf_token)
    
    if not conf_server or not conf_token:
        st.warning("⚠️ **Confluence Connection**: Not configured. Please set CONFLUENCE_SERVER and CONFLUENCE_API_TOKEN in your `.env` file or Home Hub.")
    else:
        col_s, col_p = st.columns(2)
        with col_s:
            space_key = st.text_input("Space Key", value=default_conf_space, key="kpi_conf_space")
        with col_p:
            page_title = st.text_input("Page Title", value=default_conf_page, key="kpi_conf_page")
            
        col_btn1, col_btn2 = st.columns([2, 1])
        with col_btn1:
            append_clicked = st.button("🚀 Append KPIs to Confluence", use_container_width=True)
        with col_btn2:
            fetch_clicked = st.button("🔄 Fetch Confluence History", use_container_width=True)

        auth_type = st.session_state.get("jira_auth_method", "Personal Access Token (Bearer PAT)")
        email = st.session_state.get("jira_email", "")

        if append_clicked:
            with st.spinner("Publishing to Confluence..."):
                try:
                    metrics = {
                        "dates": date_str,
                        "total_sp": f"{total_sp:g}",
                        "achieved_sp": f"{achieved_sp:g}",
                        "sprint_pct": f"{sprint_pct:.1f}%",
                        "releases": str(releases_count),
                        "open_bugs": str(open_bugs),
                        "crit_bugs": str(open_critical_bugs),
                        "resolved_bugs": str(resolved_bugs),
                        "cycle_time": f"{avg_cycle_time:.1f}" if pd.notna(avg_cycle_time) else "N/A",
                        "quality": st.session_state.current_sprint_metrics["quality"]
                    }
                    sprint_query_val = st.session_state.get("kpi_sprint_query", "Current Sprint")
                    sprint_name_val = st.session_state.get("kpi_sprint_name", sprint_query_val)

                    page_url = publish_kpis_to_confluence(
                        server_url=conf_server,
                        auth_type=auth_type,
                        token=conf_token,
                        email=email,
                        space_key=space_key,
                        page_title=page_title,
                        sprint_val=sprint_query_val,
                        sprint_name=sprint_name_val,
                        metrics=metrics
                    )
                    st.success("🎉 **KPIs successfully appended to Confluence!**")
                    st.markdown(f"[👉 Click here to view Confluence Page]({page_url})")

                    # Automatically fetch updated history for charts
                    df_hist = fetch_confluence_kpi_history(conf_server, auth_type, conf_token, email, space_key, page_title)
                    if df_hist is not None:
                        st.session_state["conf_kpi_history"] = df_hist
                except Exception as ex:
                    st.error(f"Failed to publish to Confluence: {str(ex)}")

        if fetch_clicked:
            with st.spinner("Fetching KPI history from Confluence..."):
                df_hist = fetch_confluence_kpi_history(conf_server, auth_type, conf_token, email, space_key, page_title)
                if df_hist is not None and not df_hist.empty:
                    st.session_state["conf_kpi_history"] = df_hist
                    st.success(f"Fetched {len(df_hist)} sprint entries from Confluence!")
                else:
                    st.error("Could not fetch KPI history table from Confluence page.")

        # Render evolution charts if history exists
        df_hist = st.session_state.get("conf_kpi_history")
        if df_hist is not None and not df_hist.empty:
            st.divider()
            st.markdown("#### 📊 Historical KPI Evolution (from Confluence Page)")
            render_confluence_kpi_charts(df_hist)

if "kpi_data" not in st.session_state:
    st.session_state.kpi_data = None
if "kpi_loading" not in st.session_state:
    st.session_state.kpi_loading = False

st.header("📊 Sprint KPIs")
st.markdown("Extract and calculate key performance indicators for a specific Jira Sprint.")

# Ensure we have credentials
if not st.session_state.get("jira_server") or not st.session_state.get("jira_token"):
    st.warning("⚠️ Please configure your Jira credentials in the Home Hub first.")
    st.stop()

col_s, col_b = st.columns([3, 1])
with col_s:
    default_sprint_num = os.getenv("OVERVIEW_SPRINT_NUM", "")
    sprint_val = st.text_input("Enter Sprint Name or ID:", value=default_sprint_num, placeholder="e.g. 142 or 'Sprint 15'", key="kpi_sprint_query")

st.markdown("**Filter Ingested Issue Types**")
st.write("Select which issue types should be loaded into the workspace:")
DEFAULT_INCLUDED_TYPES = os.getenv("DEFAULT_INCLUDED_TYPES", "User Story, Task, Improvement, Bug")
col_cb1, col_cb2, col_cb3, col_cb4, col_cb5, col_cb6, col_cb7 = st.columns(7)
with col_cb1:
    inc_all = st.checkbox("All / Everything", value=False, key="kpi_inc_all")
with col_cb2:
    inc_story = st.checkbox("User Story", value=("User Story" in DEFAULT_INCLUDED_TYPES), key="kpi_inc_story", disabled=inc_all)
with col_cb3:
    inc_task = st.checkbox("Task", value=("Task" in DEFAULT_INCLUDED_TYPES), key="kpi_inc_task", disabled=inc_all)
with col_cb4:
    inc_tech = st.checkbox("Technical Task", value=("Technical Task" in DEFAULT_INCLUDED_TYPES), key="kpi_inc_tech", disabled=inc_all)
with col_cb5:
    inc_subtask = st.checkbox("Sub-task", value=("Sub-task" in DEFAULT_INCLUDED_TYPES), key="kpi_inc_subtask", disabled=inc_all)
with col_cb6:
    inc_improvement = st.checkbox("Improvement", value=("Improvement" in DEFAULT_INCLUDED_TYPES), key="kpi_inc_improvement", disabled=inc_all)
with col_cb7:
    inc_bug = st.checkbox("Bug", value=("Bug" in DEFAULT_INCLUDED_TYPES), key="kpi_inc_bug", disabled=inc_all)

st.markdown("<br/>", unsafe_allow_html=True)
if st.button("🚀 Calculate KPIs", use_container_width=True):
    selected_types = []
    if not inc_all:
        if inc_story: selected_types.append("User Story")
        if inc_task: selected_types.append("Task")
        if inc_tech: selected_types.append("Technical Task")
        if inc_subtask: selected_types.append("Sub-task")
        if inc_improvement: selected_types.append("Improvement")
        if inc_bug: selected_types.append("Bug")
    st.session_state.kpi_selected_types = selected_types
    fetch_sprint_kpi_dataset()

if st.session_state.kpi_loading:
    st.spinner("Fetching data from Jira...")
    
if st.session_state.get("kpi_error"):
    st.error(st.session_state.kpi_error)

if st.session_state.kpi_data is not None:
    render_dashboard()
