import pandas as pd
import requests
import os
import re
from datetime import datetime
import numpy as np
from html.parser import HTMLParser

def get_auth_headers(server, token, auth_type, email):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "X-Atlassian-Token": "no-check"
    }
    auth = None
    token_clean = token.strip()
    if token_clean.lower().startswith("bearer "):
        token_clean = token_clean[7:].strip()

    if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
        auth = (email.strip(), token_clean)
    else:
        headers["Authorization"] = f"Bearer {token_clean}"
    return headers, auth

def extract_sprint_dates(sprint_string):
    if not sprint_string:
        return None, None
    
    start_match = re.search(r'startDate=([^,]+)', sprint_string)
    end_match = re.search(r'endDate=([^,]+)', sprint_string)
    
    start_date = None
    end_date = None
    try:
        if start_match and start_match.group(1) != "<null>":
            start_date = pd.to_datetime(start_match.group(1)).tz_localize(None)
        if end_match and end_match.group(1) != "<null>":
            end_date = pd.to_datetime(end_match.group(1)).tz_localize(None)
    except Exception:
        pass
    
    return start_date, end_date

def calculate_business_days(start_dt, end_dt):
    if pd.isna(start_dt) or pd.isna(end_dt): return None
    if start_dt > end_dt: return 0.0
    
    bdays = pd.bdate_range(start_dt.date(), end_dt.date())
    
    if len(bdays) == 0:
        return 0.0
        
    if len(bdays) == 1:
        diff = (end_dt - start_dt).total_seconds() / 86400.0
        return round(diff, 2)
        
    first_day_end = pd.Timestamp(start_dt.date()) + pd.Timedelta(days=1)
    first_day_frac = (first_day_end - start_dt).total_seconds() / 86400.0
    
    last_day_start = pd.Timestamp(end_dt.date())
    last_day_frac = (end_dt - last_day_start).total_seconds() / 86400.0
    
    middle_days = len(bdays) - 2
    
    total = first_day_frac + middle_days + last_day_frac
    return round(total, 2)

def get_story_points_field_id(server, headers, auth):
    url = f"{server.rstrip('/')}/rest/api/2/field"
    try:
        resp = requests.get(url, headers=headers, auth=auth, timeout=10) if auth else requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            for f in resp.json():
                name_lower = f.get("name", "").lower().strip()
                if name_lower in ["story points", "story point estimate"]:
                    return f.get("id")
    except Exception:
        pass
    return os.getenv("JIRA_STORY_POINTS_FIELD", "customfield_10016")

def fetch_exact_sprint_report(server, headers, auth, sprint_id):
    try:
        sprint_url = f"{server.rstrip('/')}/rest/agile/1.0/sprint/{sprint_id}"
        sprint_resp = requests.get(sprint_url, headers=headers, auth=auth, timeout=10) if auth else requests.get(sprint_url, headers=headers, timeout=10)
        board_id = sprint_resp.json().get("originBoardId")
        if not board_id:
            return None, None, []
            
        report_url = f"{server.rstrip('/')}/rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId={board_id}&sprintId={sprint_id}"
        report_resp = requests.get(report_url, headers=headers, auth=auth, timeout=10) if auth else requests.get(report_url, headers=headers, timeout=10)
        
        contents = report_resp.json().get("contents", {})
        
        completed_initial = contents.get("completedIssuesInitialEstimateSum", {}).get("value", 0)
        not_completed_initial = contents.get("issuesNotCompletedInitialEstimateSum", {}).get("value", 0)
        punted_initial = contents.get("puntedIssuesInitialEstimateSum", {}).get("value", 0)
        outside_initial = contents.get("issuesCompletedInAnotherSprintInitialEstimateSum", {}).get("value", 0)
        
        total_committed = (completed_initial or 0) + (not_completed_initial or 0) + (punted_initial or 0) + (outside_initial or 0)
        total_achieved = contents.get("completedIssuesEstimateSum", {}).get("value", 0)
        added_keys = list(contents.get("issueKeysAddedDuringSprint", {}).keys())
        
        return total_committed, total_achieved, added_keys
    except Exception as e:
        return None, None, []

def get_sprint_field_id(server, headers, auth):
    url = f"{server.rstrip('/')}/rest/api/2/field"
    try:
        resp = requests.get(url, headers=headers, auth=auth, timeout=10) if auth else requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            for f in resp.json():
                if f.get("name", "").lower().strip() == "sprint":
                    return f.get("id")
    except Exception:
        pass
    return "customfield_10020"

def fetch_sprint_kpi_data(server, token, auth_type, email, sprint_query, selected_types):
    if not server or not token or not sprint_query:
        return {"error": "Server, Token, or Sprint query is missing."}

    headers, auth = get_auth_headers(server, token, auth_type, email)
    
    if sprint_query.isdigit():
        jql = f"sprint = {sprint_query}"
    else:
        jql = f"sprint = '{sprint_query}'"
        
    if selected_types:
        types_str = ", ".join([f"'{t}'" for t in selected_types])
        jql += f" AND issuetype in ({types_str})"
        
    sp_field = get_story_points_field_id(server, headers, auth)
    sprint_field = get_sprint_field_id(server, headers, auth)
    
    sev_a_label = os.getenv("JIRA_SEVERITY_A_LABEL", "Sev-A")
    sev_b_label = os.getenv("JIRA_SEVERITY_B_LABEL", "Sev-B")
    in_prog_status = os.getenv("JIRA_STATUS_IN_PROGRESS", "In Progress").lower()
    
    fields = f"key,summary,status,issuetype,labels,resolution,created,resolutiondate,{sp_field},{sprint_field},customfield_10016,customfield_10024,customfield_10020,customfield_10008,customfield_10015"
    
    url = f"{server.rstrip('/')}/rest/api/2/search"
    params = {
        "jql": jql,
        "maxResults": 200,
        "fields": fields,
        "expand": "changelog"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, auth=auth, timeout=30) if auth else requests.get(url, headers=headers, params=params, timeout=30)
            
        if response.status_code != 200:
            return {"error": f"Jira API Error {response.status_code}: {response.text}"}
            
        data = response.json()
        issues = data.get("issues", [])
        
        if not issues:
            return {"df": pd.DataFrame()}
            
        rows = []
        sprint_start = None
        sprint_end = None
        
        for issue in issues:
            key = issue.get("key")
            fields_data = issue.get("fields", {})
            
            issuetype = fields_data.get("issuetype", {}).get("name", "")
            status_name = fields_data.get("status", {}).get("name", "")
            resolution = fields_data.get("resolution")
            
            if resolution and resolution.get("name"):
                status_name = f"{status_name} [{resolution.get('name')}]"
            
            story_points = fields_data.get(sp_field)
            if story_points is None:
                story_points = fields_data.get("customfield_10016")
            if story_points is None:
                story_points = fields_data.get("customfield_10024")
                
            try:
                story_points = float(story_points) if story_points is not None else 0
            except:
                story_points = 0
                
            raw_labels = fields_data.get("labels", [])
            labels_str = ", ".join(raw_labels) if isinstance(raw_labels, list) else ""
            labels = [l.lower() for l in raw_labels]
            
            is_sev_a = sev_a_label.lower() in labels
            is_sev_b = sev_b_label.lower() in labels
            
            res_date_str = fields_data.get("resolutiondate")
            res_date = pd.to_datetime(res_date_str).tz_localize(None) if res_date_str else None

            changelog = issue.get("changelog", {}).get("histories", [])
            last_in_progress = None
            changelog = sorted(changelog, key=lambda x: x.get("created", ""))
            
            for history in changelog:
                created_str = history.get("created")
                if not created_str: continue
                dt = pd.to_datetime(created_str).tz_localize(None)
                
                if res_date and dt > res_date:
                    continue

                for item in history.get("items", []):
                    if item.get("field") == "status":
                        to_str = item.get("toString", "").lower()
                        if to_str == in_prog_status:
                            last_in_progress = dt

            is_achieved_in_sprint = False
            if resolution is not None:
                if sprint_end and res_date:
                    if res_date <= sprint_end:
                        is_achieved_in_sprint = True
                else:
                    is_achieved_in_sprint = True

            cycle_time_end = res_date if is_achieved_in_sprint else None
            
            if last_in_progress is None and cycle_time_end is not None:
                if sprint_start and sprint_start <= cycle_time_end:
                    last_in_progress = sprint_start
                    
            cycle_time_days = None
            if last_in_progress and cycle_time_end and last_in_progress <= cycle_time_end:
                cycle_time_days = calculate_business_days(last_in_progress, cycle_time_end)

            server_clean = server.rstrip('/') if server else ""
            jira_url = f"{server_clean}/browse/{key}" if server_clean else key

            rows.append({
                "Key": key,
                "Jira URL": jira_url,
                "Type": issuetype,
                "Status": status_name,
                "Labels": labels_str,
                "Resolved": is_achieved_in_sprint,
                "Story Points": story_points,
                "Is Bug": issuetype.lower() == "bug",
                "Is Sev A": is_sev_a,
                "Is Sev B": is_sev_b,
                "Last In Progress": last_in_progress,
                "Resolved At": cycle_time_end,
                "Cycle Time (Days)": cycle_time_days
            })
            
        df = pd.DataFrame(rows)
        
        most_common_id = None
        sprint_name = None
        if sprint_start is None and issues:
            from collections import Counter
            sprint_ids = []
            sprint_map = {}
            for issue in issues:
                s_data = issue.get("fields", {}).get(sprint_field)
                if not s_data:
                    s_data = issue.get("fields", {}).get("customfield_10020")
                if not s_data:
                    s_data = issue.get("fields", {}).get("customfield_10008")
                if not s_data:
                    s_data = issue.get("fields", {}).get("customfield_10015")
                    
                if s_data and isinstance(s_data, list):
                    for s_val in s_data:
                        s_id = None
                        if isinstance(s_val, str):
                            id_match = re.search(r'id=(\d+)', s_val)
                            s_id = id_match.group(1) if id_match else s_val
                        elif isinstance(s_val, dict):
                            s_id = str(s_val.get("id"))
                            
                        if s_id:
                            sprint_ids.append(s_id)
                            sprint_map[s_id] = s_val
            
            if sprint_ids:
                most_common_id = Counter(sprint_ids).most_common(1)[0][0]
                try:
                    sprint_url = f"{server.rstrip('/')}/rest/agile/1.0/sprint/{most_common_id}"
                    s_resp = requests.get(sprint_url, headers=headers, auth=auth, timeout=10) if auth else requests.get(sprint_url, headers=headers, timeout=10)
                    if s_resp.status_code == 200:
                        s_json = s_resp.json()
                        s_str = s_json.get("startDate")
                        e_str = s_json.get("endDate")
                        if s_json.get("name"):
                            sprint_name = s_json.get("name")
                        if s_str: sprint_start = pd.to_datetime(s_str).tz_localize(None)
                        if e_str: sprint_end = pd.to_datetime(e_str).tz_localize(None)
                except Exception:
                    pass
                    
                if sprint_start is None or sprint_name is None:
                    best_sprint = sprint_map.get(most_common_id)
                    if isinstance(best_sprint, str):
                        if not sprint_name:
                            name_match = re.search(r'name=([^,]+)', best_sprint)
                            if name_match: sprint_name = name_match.group(1)
                        if sprint_start is None:
                            sprint_start, sprint_end = extract_sprint_dates(best_sprint)
                    elif isinstance(best_sprint, dict):
                        if not sprint_name:
                            sprint_name = best_sprint.get("name")
                        s_str = best_sprint.get("startDate")
                        e_str = best_sprint.get("endDate")
                        if s_str and sprint_start is None:
                            try: sprint_start = pd.to_datetime(s_str).tz_localize(None)
                            except: pass
                        if e_str and sprint_end is None:
                            try: sprint_end = pd.to_datetime(e_str).tz_localize(None)
                            except: pass
                            
        base_link = os.getenv("JIRA_VERSION_LINK_BASE", "")
        main_project = ""
        if "/projects/" in base_link:
            parts = base_link.split("/projects/")
            if len(parts) > 1:
                main_project = parts[1].split("/")[0]
                
        project_keys_set = set([issue["key"].split("-")[0] for issue in issues])
        if main_project:
            project_keys_set.add(main_project)
        project_keys = list(project_keys_set)
        
        releases_count = 0
        if sprint_start and sprint_end and project_keys:
            released_version_ids = set()
            for p_key in project_keys:
                ver_url = f"{server.rstrip('/')}/rest/api/2/project/{p_key}/versions"
                try:
                    v_resp = requests.get(ver_url, headers=headers, auth=auth, timeout=10) if auth else requests.get(ver_url, headers=headers, timeout=10)
                    if v_resp.status_code == 200:
                        for v in v_resp.json():
                            if v.get("released") and v.get("releaseDate"):
                                r_date = pd.to_datetime(v.get("releaseDate")).tz_localize(None)
                                if sprint_start.date() <= r_date.date() <= sprint_end.date():
                                    released_version_ids.add(v.get("id"))
                except Exception:
                    pass
            releases_count = len(released_version_ids)
                            
        global_open_bugs = 0
        global_critical_bugs = 0
        search_url = f"{server.rstrip('/')}/rest/api/2/search"
        projects_jql = ", ".join([f'"{pk}"' for pk in project_keys])
        
        if sprint_start is not None and sprint_end is not None and pd.notna(sprint_start) and pd.notna(sprint_end):
            sprint_start_str = sprint_start.strftime('%Y-%m-%d %H:%M')
            sprint_end_str = sprint_end.strftime('%Y-%m-%d %H:%M')
            jql_all_bugs = f'project in ({projects_jql}) AND issuetype = "Bug" AND labels in ("{sev_a_label}", "{sev_b_label}") AND created <= "{sprint_end_str}" AND (resolution is EMPTY OR resolutiondate >= "{sprint_start_str}")'
            jql_crit_bugs = f'project in ({projects_jql}) AND issuetype = "Bug" AND labels = "{sev_a_label}" AND created <= "{sprint_end_str}" AND (resolution is EMPTY OR resolutiondate >= "{sprint_start_str}")'
        else:
            jql_all_bugs = f'project in ({projects_jql}) AND issuetype = "Bug" AND resolution is EMPTY AND labels in ("{sev_a_label}", "{sev_b_label}")'
            jql_crit_bugs = f'project in ({projects_jql}) AND issuetype = "Bug" AND resolution is EMPTY AND labels = "{sev_a_label}"'

        params_all_bugs = {"jql": jql_all_bugs, "maxResults": 0}
        try:
            resp_all = requests.get(search_url, headers=headers, params=params_all_bugs, auth=auth, timeout=10) if auth else requests.get(search_url, headers=headers, params=params_all_bugs, timeout=10)
            if resp_all.status_code == 200:
                global_open_bugs = resp_all.json().get("total", 0)
        except Exception:
            pass
            
        params_crit_bugs = {"jql": jql_crit_bugs, "maxResults": 0}
        try:
            resp_crit = requests.get(search_url, headers=headers, params=params_crit_bugs, auth=auth, timeout=10) if auth else requests.get(search_url, headers=headers, params=params_crit_bugs, timeout=10)
            if resp_crit.status_code == 200:
                global_critical_bugs = resp_crit.json().get("total", 0)
        except Exception:
            pass
            
        gh_committed, gh_achieved, gh_added_keys = None, None, []
        if most_common_id:
            gh_committed, gh_achieved, gh_added_keys = fetch_exact_sprint_report(server, headers, auth, most_common_id)
                            
        return {
            "df": df,
            "gh_added_keys": gh_added_keys,
            "releases_count": releases_count,
            "global_open_bugs": global_open_bugs,
            "global_critical_bugs": global_critical_bugs,
            "sprint_start": sprint_start,
            "sprint_end": sprint_end,
            "sprint_name": sprint_name or sprint_query,
            "error": None
        }
    except Exception as e:
        import traceback
        return {"error": f"Exception during fetch: {e}\n{traceback.format_exc()}"}

def upload_confluence_attachment(server_url, auth, headers, page_id, file_path, file_name):
    base_url = server_url.rstrip("/")
    if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
        base_url = base_url + "/wiki"

    upload_headers = {
        "Accept": "application/json",
        "X-Atlassian-Token": "no-check"
    }
    if headers and "Authorization" in headers:
        upload_headers["Authorization"] = headers["Authorization"]

    check_url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
    params = {"filename": file_name}
    
    try:
        resp = requests.get(check_url, headers=upload_headers, params=params, auth=auth, timeout=15)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                attachment_id = results[0]["id"]
                update_url = f"{base_url}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data"
                with open(file_path, "rb") as f:
                    files = {"file": (file_name, f, "image/png")}
                    u_resp = requests.post(update_url, headers=upload_headers, files=files, auth=auth, timeout=15)
                    if u_resp.status_code != 200:
                        raise Exception(f"Failed to update attachment {file_name}")
                return
    except Exception:
        pass

    create_url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
    with open(file_path, "rb") as f:
        files = {"file": (file_name, f, "image/png")}
        c_resp = requests.post(create_url, headers=upload_headers, files=files, auth=auth, timeout=15)
        if c_resp.status_code not in (200, 201):
            raise Exception(f"Failed to upload attachment {file_name}")

def sort_df_chronologically(df, sprint_col):
    if df.empty:
        return df
    sprint_nums = []
    for val in df[sprint_col].astype(str):
        match = re.search(r'\d+', val)
        if match:
            sprint_nums.append(int(match.group()))
        else:
            sprint_nums.append(None)
    if all(x is not None for x in sprint_nums):
        df_copy = df.copy()
        df_copy["_sort_key"] = sprint_nums
        return df_copy.sort_values(by="_sort_key", ascending=True).drop(columns=["_sort_key"]).reset_index(drop=True)
        
    date_col = None
    for col in df.columns:
        if "date" in col.lower():
            date_col = col
            break
    if date_col:
        dates = []
        for val in df[date_col].astype(str):
            match = re.search(r'\d{4}-\d{2}-\d{2}', val)
            if match:
                dates.append(pd.to_datetime(match.group()))
            else:
                dates.append(pd.NaT)
        if not all(pd.isna(x) for x in dates):
            df_copy = df.copy()
            df_copy["_sort_key"] = dates
            return df_copy.sort_values(by="_sort_key", ascending=True).drop(columns=["_sort_key"]).reset_index(drop=True)
    return df.reset_index(drop=True)

def format_sprint_label(label, max_len=12):
    s = str(label).strip()
    if len(s) <= max_len:
        return s
    return "..." + s[-(max_len - 3):]

def generate_and_save_kpi_charts(df_hist):
    if df_hist is None or df_hist.empty:
        return []

    import altair as alt
    
    df_plot = df_hist.copy()
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

    def find_column(df_target, patterns):
        cols = list(df_target.columns)
        for p in patterns:
            p_lower = p.lower()
            for c in cols:
                if p_lower == c.lower().strip():
                    return c
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

    df_plot = sort_df_chronologically(df_plot, sprint_col)
    df_plot["Sprint Display"] = df_plot[sprint_col].apply(lambda x: format_sprint_label(x, 12))
    df_plot = df_plot.tail(5)

    df_plot["Committed SP"] = extract_numeric_col(df_plot, ["committed sp (at start)", "committed sp", "committed"])
    df_plot["Delivered SP"] = extract_numeric_col(df_plot, ["delivered sp (total)", "delivered sp", "delivered", "achieved"])
    df_plot["Delivery %"] = extract_numeric_col(df_plot, ["delivery %", "delivery", "pct", "entrega", "cumplimiento"])
    
    if "Committed SP" in df_plot.columns and "Delivered SP" in df_plot.columns:
        calc_pct = (df_plot["Delivered SP"] / df_plot["Committed SP"] * 100).round(1)
        df_plot["Delivery %"] = df_plot["Delivery %"].fillna(calc_pct)

    df_plot["Avg Cycle Time (Days)"] = extract_numeric_col(df_plot, ["avg cycle time (days)", "avg cycle time", "cycle time"])
    df_plot["Open Bugs (Sev A+B)"] = extract_numeric_col(df_plot, ["open bugs (sev a+b)", "open bugs"])
    df_plot["Critical Bugs (Sev A)"] = extract_numeric_col(df_plot, ["critical bugs (sev a)", "critical bugs"])

    saved_files = []

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
        text_sp = bars_sp.mark_text(align='center', baseline='bottom', dy=-5).encode(text=alt.Text("Story Points:Q", format=".0f"))
        chart_sp = (bars_sp + text_sp).properties(width=500, height=280)
        path_sp = "temp_velocity_chart.png"
        chart_sp.save(path_sp)
        saved_files.append((path_sp, "velocity_chart.png"))

    df_pct = df_plot[["Sprint Display", "Delivery %"]].dropna(subset=["Delivery %"])
    if not df_pct.empty:
        bars_pct = alt.Chart(df_pct).mark_bar(color="#ab47bc").encode(
            x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0), sort=None),
            y=alt.Y("Delivery %:Q", title="Delivery %"),
            tooltip=["Sprint Display", "Delivery %"]
        )
        text_pct = bars_pct.mark_text(align='center', baseline='bottom', dy=-5, color='#ab47bc').encode(text=alt.Text("Delivery %:Q", format=".1f"))
        chart_pct = (bars_pct + text_pct).properties(width=500, height=280)
        path_pct = "temp_delivery_chart.png"
        chart_pct.save(path_pct)
        saved_files.append((path_pct, "delivery_chart.png"))

    df_ct = df_plot[["Sprint Display", "Avg Cycle Time (Days)"]].dropna(subset=["Avg Cycle Time (Days)"])
    if not df_ct.empty:
        bars_ct = alt.Chart(df_ct).mark_bar(color="#ffa726").encode(
            x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0), sort=None),
            y=alt.Y("Avg Cycle Time (Days):Q", title="Days"),
            tooltip=["Sprint Display", "Avg Cycle Time (Days)"]
        )
        text_ct = bars_ct.mark_text(align='center', baseline='bottom', dy=-5, color='#ffa726').encode(text=alt.Text("Avg Cycle Time (Days):Q", format=".1f"))
        chart_ct = (bars_ct + text_ct).properties(width=500, height=280)
        path_ct = "temp_cycle_time_chart.png"
        chart_ct.save(path_ct)
        saved_files.append((path_ct, "cycle_time_chart.png"))

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
        text_bugs = bars_bugs.mark_text(align='center', baseline='bottom', dy=-5).encode(text=alt.Text("Count:Q", format=".0f"))
        chart_bugs = (bars_bugs + text_bugs).properties(width=500, height=280)
        path_bugs = "temp_bugs_chart.png"
        chart_bugs.save(path_bugs)
        saved_files.append((path_bugs, "bugs_chart.png"))

    return saved_files

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.in_cell = False
        self.table_count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table_count += 1
        if self.table_count == 1:
            if tag in ('td', 'th'):
                self.in_cell = True
                self.current_cell = []
            elif tag == 'tr':
                self.current_row = []

    def handle_endtag(self, tag):
        if self.table_count == 1:
            if tag in ('td', 'th'):
                self.in_cell = False
                self.current_row.append(''.join(self.current_cell).strip())
            elif tag == 'tr':
                if self.current_row:
                    self.rows.append(self.current_row)

    def handle_data(self, data):
        if self.table_count == 1 and self.in_cell:
            self.current_cell.append(data)

def parse_confluence_html_table(html_body):
    if not html_body or '<table' not in html_body:
        return None
    try:
        parser = TableParser()
        parser.feed(html_body)
        if not parser.rows or len(parser.rows) < 2:
            return None
        headers = parser.rows[0]
        data_rows = parser.rows[1:]
        valid_rows = [r for r in data_rows if len(r) == len(headers)]
        return pd.DataFrame(valid_rows, columns=headers)
    except Exception:
        return None

def fetch_confluence_kpi_history(server_url, auth_type, token, email, space_key, page_title):
    if not server_url or not token or not space_key or not page_title:
        return None
        
    base_url = server_url.rstrip("/")
    if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
        base_url = base_url + "/wiki"
        
    headers = {"Accept": "application/json"}
    auth = None
    if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud (Email + API Token)"]:
        if not email:
            return None
        auth = (email, token)
    else:
        headers["Authorization"] = f"Bearer {token}"
        
    find_url = f"{base_url}/rest/api/content"
    params = {"title": page_title, "spaceKey": space_key, "expand": "body.storage"}
    
    try:
        resp = requests.get(find_url, headers=headers, params=params, auth=auth, timeout=15) if auth else requests.get(find_url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        results = resp.json().get("results", [])
        if not results:
            return None
        html_body = results[0].get("body", {}).get("storage", {}).get("value", "")
        return parse_confluence_html_table(html_body)
    except Exception:
        return None

def publish_kpis_to_confluence(server_url, auth_type, token, email, space_key, page_title, sprint_val, sprint_name, metrics):
    if not server_url or not token or not space_key or not page_title:
        raise Exception("Required configuration fields (URL, Token, Space Key, Page Title) cannot be empty.")
        
    base_url = server_url.rstrip("/")
    if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
        base_url = base_url + "/wiki"
        
    headers, auth = get_auth_headers(server_url, token, auth_type, email)
        
    find_url = f"{base_url}/rest/api/content"
    params = {"title": page_title, "spaceKey": space_key, "expand": "version,body.storage"}
    
    resp = requests.get(find_url, headers=headers, params=params, auth=auth, timeout=15) if auth else requests.get(find_url, headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"Failed to query Confluence page ({resp.status_code}): {resp.text}")
        
    results = resp.json().get("results", [])
    
    display_sprint = sprint_name if sprint_name else sprint_val

    new_row_single = f"""
    <tr>
        <td>{display_sprint}</td>
        <td>{metrics.get('dates', '')}</td>
        <td>{metrics.get('total_sp', '')}</td>
        <td>{metrics.get('achieved_sp', '')}</td>
        <td>{metrics.get('sprint_pct', '')}</td>
        <td>{metrics.get('releases', '')}</td>
        <td>{metrics.get('open_bugs', '')}</td>
        <td>{metrics.get('crit_bugs', '')}</td>
        <td>{metrics.get('resolved_bugs', '')}</td>
        <td>{metrics.get('cycle_time', '')}</td>
    </tr>
    """

    new_row_double = f"""
    <tr>
        <td>{sprint_val}</td>
        <td>{sprint_name}</td>
        <td>{metrics.get('dates', '')}</td>
        <td>{metrics.get('total_sp', '')}</td>
        <td>{metrics.get('achieved_sp', '')}</td>
        <td>{metrics.get('sprint_pct', '')}</td>
        <td>{metrics.get('releases', '')}</td>
        <td>{metrics.get('open_bugs', '')}</td>
        <td>{metrics.get('crit_bugs', '')}</td>
        <td>{metrics.get('resolved_bugs', '')}</td>
        <td>{metrics.get('cycle_time', '')}</td>
    </tr>
    """

    base_table = f"""
    <table class="wrapped">
        <colgroup><col/><col/><col/><col/><col/><col/><col/><col/><col/><col/></colgroup>
        <tbody>
            <tr>
                <th>Sprint</th>
                <th>Target Dates</th>
                <th>Committed SP (at Start)</th>
                <th>Delivered SP (Total)</th>
                <th>Delivery %</th>
                <th>Releases</th>
                <th>Open Bugs (Sev A+B)</th>
                <th>Critical Bugs (Sev A)</th>
                <th>Resolved Bugs</th>
                <th>Avg Cycle Time (Days)</th>
            </tr>
            {new_row_single}
        </tbody>
    </table>
    """

    image_markup = """
    <p><strong>Historical KPI Evolution</strong></p>
    <table class="wrapped">
        <tbody>
            <tr>
                <td style="text-align: center;">
                    <h4>Committed vs Delivered Story Points</h4>
                    <p style="font-size: 12px; color: #555;"><em>Compares total SP committed at start vs total SP actually delivered.</em><br/>
                    <span style="font-size: 11px;"><b>Calculation:</b> Committed SP strictly excludes scope creep (tickets added mid-sprint). Delivered SP includes all resolved tickets on or before the sprint's End Date.</span></p>
                    <ac:image ac:original-height="280" ac:original-width="500">
                        <ri:attachment ri:filename="velocity_chart.png" />
                    </ac:image>
                </td>
                <td style="text-align: center;">
                    <h4>Delivery % Trend</h4>
                    <p style="font-size: 12px; color: #555;"><em>Measures ability to complete committed workload.</em><br/>
                    <span style="font-size: 11px;"><b>Calculation:</b> (Delivered SP / Committed SP) * 100. Can exceed 100% if scope creep tickets are completed.</span></p>
                    <ac:image ac:original-height="280" ac:original-width="500">
                        <ri:attachment ri:filename="delivery_chart.png" />
                    </ac:image>
                </td>
            </tr>
            <tr>
                <td style="text-align: center;">
                    <h4>Average Cycle Time (Days)</h4>
                    <p style="font-size: 12px; color: #555;"><em>Tracks the average working time to complete an issue.</em><br/>
                    <span style="font-size: 11px;"><b>Calculation:</b> The mean of business days from the last 'In Progress' transition until 'Resolved', clamped to the sprint start date.</span></p>
                    <ac:image ac:original-height="280" ac:original-width="500">
                        <ri:attachment ri:filename="cycle_time_chart.png" />
                    </ac:image>
                </td>
                <td style="text-align: center;">
                    <h4>Open &amp; Critical Bugs Trend</h4>
                    <p style="font-size: 12px; color: #555;"><em>Monitors unresolved high-priority bugs at the end of each sprint.</em><br/>
                    <span style="font-size: 11px;"><b>Calculation:</b> Uses JQL to count all project bugs (Sev A+B) created before the sprint ended that remained unresolved, or were resolved after the sprint started.</span></p>
                    <ac:image ac:original-height="280" ac:original-width="500">
                        <ri:attachment ri:filename="bugs_chart.png" />
                    </ac:image>
                </td>
            </tr>
        </tbody>
    </table>
    """
    
    if results:
        page_id = results[0]["id"]
        current_version = results[0]["version"]["number"]
        current_body = results[0]["body"]["storage"]["value"]
        
        is_double_header = "<th>Sprint Name</th>" in current_body and "<th>Sprint</th>" in current_body
        row_to_insert = new_row_double if is_double_header else new_row_single
        
        if "</tbody>" in current_body:
            new_body = current_body.replace("</tbody>", f"{row_to_insert}</tbody>", 1)
        elif "</table>" in current_body:
            new_body = current_body.replace("</table>", f"{row_to_insert}</table>", 1)
        else:
            new_body = current_body + "<br/>" + base_table

        # Always update the charts section to ensure the latest titles and descriptions are visible
        new_body = re.sub(r'<br/>\s*<p><strong>Historical KPI Evolution</strong></p>.*?</table>', '', new_body, flags=re.DOTALL)
        new_body = re.sub(r'<p><strong>Historical KPI Evolution</strong></p>.*?</table>', '', new_body, flags=re.DOTALL)
        new_body = new_body.strip() + "<br/>" + image_markup
        
        update_url = f"{base_url}/rest/api/content/{page_id}"
        update_payload = {
            "id": page_id,
            "type": "page",
            "title": page_title,
            "space": {"key": space_key},
            "body": {"storage": {"value": new_body, "representation": "storage"}},
            "version": {"number": current_version + 1}
        }
        
        update_headers = headers.copy()
        update_headers["Content-Type"] = "application/json"
        
        u_resp = requests.put(update_url, headers=update_headers, json=update_payload, auth=auth, timeout=15) if auth else requests.put(update_url, headers=update_headers, json=update_payload, timeout=15)
        if u_resp.status_code != 200:
            raise Exception(f"Failed to update Confluence page ({u_resp.status_code}): {u_resp.text}")
            
    else:
        create_url = f"{base_url}/rest/api/content"
        new_body = f"<p>Sprint KPIs Overview</p>{base_table}<br/>{image_markup}"
        create_payload = {
            "type": "page",
            "title": page_title,
            "space": {"key": space_key},
            "body": {"storage": {"value": new_body, "representation": "storage"}}
        }
        
        create_headers = headers.copy()
        create_headers["Content-Type"] = "application/json"
        
        c_resp = requests.post(create_url, headers=create_headers, json=create_payload, auth=auth, timeout=15) if auth else requests.post(create_url, headers=create_headers, json=create_payload, timeout=15)
        if c_resp.status_code not in (200, 201):
            raise Exception(f"Failed to create new Confluence page ({c_resp.status_code}): {c_resp.text}")
        
        page_id = c_resp.json().get("id")

    df_hist = parse_confluence_html_table(new_body)
    if df_hist is not None:
        try:
            saved_files = generate_and_save_kpi_charts(df_hist)
            for temp_path, target_filename in saved_files:
                try:
                    upload_confluence_attachment(
                        server_url=server_url,
                        auth=auth,
                        headers=headers,
                        page_id=page_id,
                        file_path=temp_path,
                        file_name=target_filename
                    )
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
        except Exception as chart_ex:
            raise Exception(f"KPI table uploaded, but failed to generate/upload charts: {chart_ex}")
        
    return f"{base_url}/pages/viewpage.action?pageId={page_id}"
