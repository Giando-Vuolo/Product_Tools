import streamlit as st
import pandas as pd
import requests
import os
import re
from datetime import datetime
import numpy as np
from html.parser import HTMLParser
import altair as alt

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
    """Extract start and end dates from Jira's raw sprint custom field string."""
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
    """
    Calculates exact fractional business days between two dates, mirroring EazyBI's DateDiffWorkdays.
    Uses a 24-hour clock that pauses on weekends.
    """
    if pd.isna(start_dt) or pd.isna(end_dt): return None
    if start_dt > end_dt: return 0.0
    
    bdays = pd.bdate_range(start_dt.date(), end_dt.date())
    
    if len(bdays) == 0:
        return 0.0
        
    if len(bdays) == 1:
        diff = (end_dt - start_dt).total_seconds() / 86400.0
        return round(diff, 2)
        
    # First day fraction
    first_day_end = pd.Timestamp(start_dt.date()) + pd.Timedelta(days=1)
    first_day_frac = (first_day_end - start_dt).total_seconds() / 86400.0
    
    # Last day fraction
    last_day_start = pd.Timestamp(end_dt.date())
    last_day_frac = (end_dt - last_day_start).total_seconds() / 86400.0
    
    # Middle days
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
    
    # Fallback to env or default
    return os.getenv("JIRA_STORY_POINTS_FIELD", "customfield_10016")

def fetch_exact_sprint_report(server, headers, auth, sprint_id):
    """Fetches exact committed and completed story points directly from Jira's Greenhopper Sprint Report API."""
    try:
        sprint_url = f"{server.rstrip('/')}/rest/agile/1.0/sprint/{sprint_id}"
        sprint_resp = requests.get(sprint_url, headers=headers, auth=auth, timeout=10) if auth else requests.get(sprint_url, headers=headers, timeout=10)
        board_id = sprint_resp.json().get("originBoardId")
        if not board_id:
            return None, None
            
        report_url = f"{server.rstrip('/')}/rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId={board_id}&sprintId={sprint_id}"
        report_resp = requests.get(report_url, headers=headers, auth=auth, timeout=10) if auth else requests.get(report_url, headers=headers, timeout=10)
        
        contents = report_resp.json().get("contents", {})
        
        # Initial Committed SP
        completed_initial = contents.get("completedIssuesInitialEstimateSum", {}).get("value", 0)
        not_completed_initial = contents.get("issuesNotCompletedInitialEstimateSum", {}).get("value", 0)
        punted_initial = contents.get("puntedIssuesInitialEstimateSum", {}).get("value", 0)
        outside_initial = contents.get("issuesCompletedInAnotherSprintInitialEstimateSum", {}).get("value", 0)
        
        total_committed = (completed_initial or 0) + (not_completed_initial or 0) + (punted_initial or 0) + (outside_initial or 0)
        
        # Achieved SP (at sprint end)
        total_achieved = contents.get("completedIssuesEstimateSum", {}).get("value", 0)
        
        # Keys added during sprint (scope creep)
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

def fetch_sprint_kpi_dataset():
    st.session_state.kpi_loading = True
    st.session_state.kpi_error = ""
    
    server = st.session_state.get("jira_server", "")
    token = st.session_state.get("jira_token", "")
    auth_type = st.session_state.get("jira_auth_method", "")
    email = st.session_state.get("jira_email", "")
    sprint_query = st.session_state.get("kpi_sprint_query", "")
    
    if not server or not token or not sprint_query:
        st.session_state.kpi_error = "Server, Token, or Sprint query is missing."
        st.session_state.kpi_loading = False
        return

    headers, auth = get_auth_headers(server, token, auth_type, email)
    
    if sprint_query.isdigit():
        jql = f"sprint = {sprint_query}"
    else:
        jql = f"sprint = '{sprint_query}'"
        
    selected_types = st.session_state.get("kpi_selected_types", [])
    if selected_types:
        types_str = ", ".join([f"'{t}'" for t in selected_types])
        jql += f" AND issuetype in ({types_str})"
        
    sp_field = get_story_points_field_id(server, headers, auth)
    sprint_field = get_sprint_field_id(server, headers, auth)
    
    sev_a_label = os.getenv("JIRA_SEVERITY_A_LABEL", "Sev-A")
    sev_b_label = os.getenv("JIRA_SEVERITY_B_LABEL", "Sev-B")
    in_prog_status = os.getenv("JIRA_STATUS_IN_PROGRESS", "In Progress").lower()
    acc_test_status = os.getenv("JIRA_STATUS_ACCEPTANCE_TEST", "Acceptance Test").lower()
    
    # Add common fallback custom fields just in case the dynamic fetch misses it
    fields = f"key,summary,status,issuetype,labels,resolution,created,resolutiondate,{sp_field},{sprint_field},customfield_10016,customfield_10024,customfield_10020,customfield_10008,customfield_10015"
    
    url = f"{server.rstrip('/')}/rest/api/2/search"
    params = {
        "jql": jql,
        "maxResults": 200,
        "fields": fields,
        "expand": "changelog"
    }
    
    try:
        if auth:
            response = requests.get(url, headers=headers, params=params, auth=auth, timeout=30)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
        if response.status_code != 200:
            st.session_state.kpi_error = f"Jira API Error {response.status_code}: {response.text}"
            st.session_state.kpi_loading = False
            return
            
        data = response.json()
        issues = data.get("issues", [])
        
        if not issues:
            st.session_state.kpi_data = pd.DataFrame()
            st.session_state.kpi_loading = False
            return
            
        rows = []
        sprint_start = None
        sprint_end = None
        
        for issue in issues:
            key = issue.get("key")
            fields_data = issue.get("fields", {})
            
            # Try to extract sprint dates from the sprint field
            issuetype = fields_data.get("issuetype", {}).get("name", "")
            status_name = fields_data.get("status", {}).get("name", "")
            resolution = fields_data.get("resolution")
            is_resolved = resolution is not None
            
            # Check dynamic field, then fallbacks
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
            
            # Resolve date and Achieved logic
            res_date_str = fields_data.get("resolutiondate")
            res_date = pd.to_datetime(res_date_str).tz_localize(None) if res_date_str else None

            # Changelog for cycle time
            changelog = issue.get("changelog", {}).get("histories", [])
            
            last_in_progress = None
            
            # Sort chronologically
            changelog = sorted(changelog, key=lambda x: x.get("created", ""))
            
            for history in changelog:
                created_str = history.get("created")
                if not created_str: continue
                dt = pd.to_datetime(created_str).tz_localize(None)
                
                # Consider transitions up to resolution date
                if res_date and dt > res_date:
                    continue

                for item in history.get("items", []):
                    if item.get("field") == "status":
                        to_str = item.get("toString", "").lower()
                        if to_str == in_prog_status:
                            last_in_progress = dt

            # For Sprint KPIs, an issue is only 'achieved' if it was resolved before the sprint ended
            # If the sprint is still active (no sprint_end or sprint_end is in the future), we use its current resolution status
            is_achieved_in_sprint = False
            if resolution is not None:
                if sprint_end and res_date:
                    if res_date <= sprint_end:
                        is_achieved_in_sprint = True
                else:
                    is_achieved_in_sprint = True

            # EazyBI matching Cycle Time: 
            # DateDiffWorkdays(Transition to status last date In Progress before resolution, Resolved at)
            cycle_time_end = res_date if is_achieved_in_sprint else None
            
            if last_in_progress is None and cycle_time_end is not None:
                # Using sprint_start as a proxy for when work ACTUALLY started if they skipped In Progress
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
                "First In Progress": last_in_progress,
                "Resolved At": cycle_time_end,
                "Cycle Time (Days)": cycle_time_days
            })
            
        df = pd.DataFrame(rows)
        
        most_common_id = None
        sprint_name = None
        # Robustly detect the sprint dates by finding the most common sprint across all returned issues
        if sprint_start is None and issues:
            from collections import Counter
            sprint_ids = []
            sprint_map = {}
            for issue in issues:
                # Try the dynamically fetched field first, then fallbacks
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
                
                # 1. Try fetching exact sprint data from Agile API for maximum reliability
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
                except Exception as e:
                    pass
                    
                # 2. Fallback to regex parsing the string
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
                            
                # 3. Log debug info if STILL failing
                if sprint_start is None:
                    st.session_state.kpi_error += f"\n⚠️ [Debug] Could not parse dates for sprint ID {most_common_id}. Raw string: {sprint_map[most_common_id]}"
            else:
                st.session_state.kpi_error += f"\n⚠️ [Debug] sprint_ids is empty. We couldn't find ANY Sprint data in the tickets. Checked fields: {sprint_field}, 10020, 10008, 10015."
                    
        # Find all project keys involved in this sprint (plus the main project from env)
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
        
        # Now fetch releases in the project(s) if we have sprint dates
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
                            
        # Now fetch global open bugs for the projects
        global_open_bugs = 0
        global_critical_bugs = 0
        search_url = f"{server.rstrip('/')}/rest/api/2/search"
        
        projects_jql = ", ".join([f'"{pk}"' for pk in project_keys])
        
        # Query 1: All Open Sev A + Sev B Bugs
        jql_all_bugs = f'project in ({projects_jql}) AND issuetype = "Bug" AND resolution is EMPTY AND labels in ("{sev_a_label}", "{sev_b_label}")'
        params_all_bugs = {"jql": jql_all_bugs, "maxResults": 0}
        try:
            resp_all = requests.get(search_url, headers=headers, params=params_all_bugs, auth=auth, timeout=10) if auth else requests.get(search_url, headers=headers, params=params_all_bugs, timeout=10)
            if resp_all.status_code == 200:
                global_open_bugs = resp_all.json().get("total", 0)
            else:
                st.session_state.kpi_error += f"\nWarning: Query 1 failed ({resp_all.status_code}): {resp_all.text}"
        except Exception as e:
            st.session_state.kpi_error += f"\nWarning: Query 1 Exception: {str(e)}"
            
        # Query 2: All Critical Open Sev A Bugs
        jql_crit_bugs = f'project in ({projects_jql}) AND issuetype = "Bug" AND resolution is EMPTY AND labels = "{sev_a_label}"'
        params_crit_bugs = {"jql": jql_crit_bugs, "maxResults": 0}
        try:
            resp_crit = requests.get(search_url, headers=headers, params=params_crit_bugs, auth=auth, timeout=10) if auth else requests.get(search_url, headers=headers, params=params_crit_bugs, timeout=10)
            if resp_crit.status_code == 200:
                global_critical_bugs = resp_crit.json().get("total", 0)
            else:
                st.session_state.kpi_error += f"\nWarning: Query 2 failed ({resp_crit.status_code}): {resp_crit.text}"
        except Exception as e:
            st.session_state.kpi_error += f"\nWarning: Query 2 Exception: {str(e)}"
            
        gh_committed, gh_achieved, gh_added_keys = None, None, []
        if most_common_id:
            gh_committed, gh_achieved, gh_added_keys = fetch_exact_sprint_report(server, headers, auth, most_common_id)
                            
        st.session_state.kpi_data = df
        st.session_state.kpi_gh_added_keys = gh_added_keys
        st.session_state.kpi_releases_count = releases_count
        st.session_state.kpi_global_open_bugs = global_open_bugs
        st.session_state.kpi_global_critical_bugs = global_critical_bugs
        st.session_state.kpi_sprint_start = sprint_start
        st.session_state.kpi_sprint_end = sprint_end
        st.session_state.kpi_sprint_name = sprint_name or sprint_query
        st.session_state.kpi_loading = False
        
    except Exception as e:
        import traceback
        st.session_state.kpi_error = f"Exception during fetch: {e}\n{traceback.format_exc()}"
        st.session_state.kpi_loading = False

def publish_kpis_to_confluence(server_url, auth_type, token, email, space_key, page_title, sprint_val, sprint_name, metrics):
    if not server_url or not token or not space_key or not page_title:
        raise Exception("Required configuration fields (URL, Token, Space Key, Page Title) cannot be empty.")
        
    base_url = server_url.rstrip("/")
    if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
        base_url = base_url + "/wiki"
        
    headers = {"Accept": "application/json"}
    auth = None
    if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud (Email + API Token)"]:
        if not email:
            raise Exception("Username/Email is required for Confluence Basic authentication.")
        auth = (email, token)
    else:
        headers["Authorization"] = f"Bearer {token}"
        
    find_url = f"{base_url}/rest/api/content"
    params = {"title": page_title, "spaceKey": space_key, "expand": "version,body.storage"}
    
    resp = requests.get(find_url, headers=headers, params=params, auth=auth, timeout=15) if auth else requests.get(find_url, headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"Failed to query Confluence page ({resp.status_code}): {resp.text}")
        
    results = resp.json().get("results", [])
    
    display_sprint = sprint_name if sprint_name else sprint_val

    # Standard single Sprint column format (9 columns)
    new_row_single = f"""
    <tr>
        <td>{display_sprint}</td>
        <td>{metrics['dates']}</td>
        <td>{metrics['total_sp']}</td>
        <td>{metrics['achieved_sp']}</td>
        <td>{metrics['sprint_pct']}</td>
        <td>{metrics['releases']}</td>
        <td>{metrics['open_bugs']}</td>
        <td>{metrics['crit_bugs']}</td>
        <td>{metrics['cycle_time']}</td>
    </tr>
    """

    # Double Sprint column format (10 columns - for compatibility with pages containing both Sprint and Sprint Name)
    new_row_double = f"""
    <tr>
        <td>{sprint_val}</td>
        <td>{sprint_name}</td>
        <td>{metrics['dates']}</td>
        <td>{metrics['total_sp']}</td>
        <td>{metrics['achieved_sp']}</td>
        <td>{metrics['sprint_pct']}</td>
        <td>{metrics['releases']}</td>
        <td>{metrics['open_bugs']}</td>
        <td>{metrics['crit_bugs']}</td>
        <td>{metrics['cycle_time']}</td>
    </tr>
    """

    base_table = f"""
    <table class="wrapped">
        <colgroup><col/><col/><col/><col/><col/><col/><col/><col/><col/></colgroup>
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
                <th>Avg Cycle Time (Days)</th>
            </tr>
            {new_row_single}
        </tbody>
    </table>
    """
    
    if results:
        page_id = results[0]["id"]
        current_version = results[0]["version"]["number"]
        current_body = results[0]["body"]["storage"]["value"]
        
        # Check if existing table has 10 columns (contains both Sprint and Sprint Name)
        is_double_header = "<th>Sprint Name</th>" in current_body and "<th>Sprint</th>" in current_body
        row_to_insert = new_row_double if is_double_header else new_row_single

        # Append row to existing table if present
        if "</tbody>" in current_body:
            new_body = current_body.replace("</tbody>", f"{row_to_insert}</tbody>")
        elif "</table>" in current_body:
            new_body = current_body.replace("</table>", f"{row_to_insert}</table>")
        else:
            new_body = current_body + "<br/>" + base_table
            
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
        create_payload = {
            "type": "page",
            "title": page_title,
            "space": {"key": space_key},
            "body": {"storage": {"value": f"<p>Sprint KPIs Overview</p>{base_table}", "representation": "storage"}}
        }
        
        create_headers = headers.copy()
        create_headers["Content-Type"] = "application/json"
        
        c_resp = requests.post(create_url, headers=create_headers, json=create_payload, auth=auth, timeout=15) if auth else requests.post(create_url, headers=create_headers, json=create_payload, timeout=15)
        if c_resp.status_code not in (200, 201):
            raise Exception(f"Failed to create new Confluence page ({c_resp.status_code}): {c_resp.text}")
        
        page_id = c_resp.json().get("id")
        
    return f"{base_url}/pages/viewpage.action?pageId={page_id}"

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag in ('td', 'th'):
            self.in_cell = True
            self.current_cell = []
        elif tag == 'tr':
            self.current_row = []

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.in_cell = False
            self.current_row.append(''.join(self.current_cell).strip())
        elif tag == 'tr':
            if self.current_row:
                self.rows.append(self.current_row)

    def handle_data(self, data):
        if self.in_cell:
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
        return pd.DataFrame(data_rows, columns=headers)
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

def format_sprint_label(label, max_len=12):
    s = str(label).strip()
    if len(s) <= max_len:
        return s
    return "..." + s[-(max_len - 3):]

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

    df_plot["Sprint Display"] = df_plot[sprint_col].apply(lambda x: format_sprint_label(x, 12))

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

    tab1, tab2, tab3 = st.tabs(["📊 Velocity & Delivery %", "⏱️ Cycle Time Trend", "🐛 Bugs & Quality"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Committed vs Delivered Story Points")
            df_sp = df_plot[["Sprint Display", "Committed SP", "Delivered SP"]].dropna(subset=["Committed SP", "Delivered SP"], how="all")
            if not df_sp.empty:
                df_sp_melted = df_sp.melt(id_vars=["Sprint Display"], value_vars=["Committed SP", "Delivered SP"], var_name="Metric", value_name="Story Points")
                chart_sp = alt.Chart(df_sp_melted).mark_bar().encode(
                    x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0)),
                    xOffset="Metric:N",
                    y=alt.Y("Story Points:Q", title="Story Points"),
                    color=alt.Color("Metric:N", legend=alt.Legend(orient="top", title=None), scale=alt.Scale(range=["#42a5f5", "#66bb6a"])),
                    tooltip=["Sprint Display", "Metric", "Story Points"]
                ).properties(height=280)
                st.altair_chart(chart_sp, use_container_width=True)
            else:
                st.info("No Story Points data found in table.")
        with c2:
            st.caption("Delivery % Trend")
            df_pct = df_plot[["Sprint Display", "Delivery %"]].dropna(subset=["Delivery %"])
            if not df_pct.empty:
                chart_pct = alt.Chart(df_pct).mark_bar(color="#ab47bc").encode(
                    x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("Delivery %:Q", title="Delivery %", scale=alt.Scale(domain=[0, 100])),
                    tooltip=["Sprint Display", "Delivery %"]
                ).properties(height=280)
                st.altair_chart(chart_pct, use_container_width=True)
            else:
                st.info("No Delivery % data found in table.")

    with tab2:
        st.caption("Average Cycle Time (Days)")
        df_ct = df_plot[["Sprint Display", "Avg Cycle Time (Days)"]].dropna(subset=["Avg Cycle Time (Days)"])
        if not df_ct.empty:
            chart_ct = alt.Chart(df_ct).mark_bar(color="#ffa726").encode(
                x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Avg Cycle Time (Days):Q", title="Days"),
                tooltip=["Sprint Display", "Avg Cycle Time (Days)"]
            ).properties(height=280)
            st.altair_chart(chart_ct, use_container_width=True)
        else:
            st.info("No Cycle Time data found in table.")

    with tab3:
        st.caption("Open & Critical Bugs Trend")
        df_bugs = df_plot[["Sprint Display", "Open Bugs (Sev A+B)", "Critical Bugs (Sev A)"]].dropna(subset=["Open Bugs (Sev A+B)", "Critical Bugs (Sev A)"], how="all")
        if not df_bugs.empty:
            df_bugs_melted = df_bugs.melt(id_vars=["Sprint Display"], value_vars=["Open Bugs (Sev A+B)", "Critical Bugs (Sev A)"], var_name="Bug Type", value_name="Count")
            chart_bugs = alt.Chart(df_bugs_melted).mark_bar().encode(
                x=alt.X("Sprint Display:N", title=None, axis=alt.Axis(labelAngle=0)),
                xOffset="Bug Type:N",
                y=alt.Y("Count:Q", title="Bugs"),
                color=alt.Color("Bug Type:N", legend=alt.Legend(orient="top", title=None), scale=alt.Scale(range=["#ef5350", "#b71c1c"])),
                tooltip=["Sprint Display", "Bug Type", "Count"]
            ).properties(height=280)
            st.altair_chart(chart_bugs, use_container_width=True)
        else:
            st.info("No Bugs data found in table.")

def render_dashboard():
    df = st.session_state.kpi_data
    if df is None or df.empty:
        st.info("No data found for this sprint.")
        return
        
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
    total_sp = df[~df["Key"].isin(gh_added_keys)]["Story Points"].sum()
    
    # "Delivered SP (Total)": Sum of all resolved issues (including scope creep)
    achieved_sp = df[df["Resolved"] == True]["Story Points"].sum()
    
    if gh_added_keys:
        st.caption("✨ Committed SP accurately excludes scope creep tickets added mid-sprint.")
    
    sprint_pct = (achieved_sp / total_sp * 100) if total_sp > 0 else 0
    
    releases_count = st.session_state.get("kpi_releases_count", 0)
    
    bugs = df[df["Is Bug"] == True]
    resolved_bugs = len(bugs[bugs["Resolved"] == True])
    open_bugs_df = bugs[bugs["Resolved"] == False]
    
    sev_a_open = len(open_bugs_df[open_bugs_df["Is Sev A"] == True])
    sev_b_open = len(open_bugs_df[open_bugs_df["Is Sev B"] == True])
    
    # Overwrite with global counts from session state
    open_critical_bugs = st.session_state.get("kpi_global_critical_bugs", sev_a_open)
    open_bugs = st.session_state.get("kpi_global_open_bugs", sev_a_open + sev_b_open)
    
    if len(df) > 0 and "Cycle Time (Days)" in df.columns:
        avg_cycle_time = df["Cycle Time (Days)"].mean()
        avg_cycle_time = round(avg_cycle_time, 2) if pd.notnull(avg_cycle_time) else 0
    else:
        avg_cycle_time = 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Committed SP (at Start)", f"{total_sp:g}")
        st.metric("Delivered SP (Total)", f"{achieved_sp:g}")
    with col2:
        st.metric("Delivery %", f"{sprint_pct:.1f}%")
        st.metric("Sprint Releases", str(releases_count))
    with col3:
        st.metric("Resolved Bugs", str(resolved_bugs))
        st.metric("Average Cycle Time", f"{avg_cycle_time:.1f} days" if pd.notna(avg_cycle_time) else "N/A")
    with col4:
        st.metric("Project Open Bugs (Sev A + B)", str(open_bugs))
        st.metric("Project Critical Open Bugs (Sev A)", str(open_critical_bugs))
        
    st.divider()
    
    st.markdown("#### 📋 Issue Details (Cycle Times)")
    
    server_clean = st.session_state.get("jira_server", "").rstrip("/")
    if "Jira URL" not in df.columns:
        df["Jira URL"] = df["Key"].apply(lambda k: f"{server_clean}/browse/{k}" if server_clean else k)
    if "Labels" not in df.columns:
        df["Labels"] = ""

    disp_df = df[["Jira URL", "Type", "Status", "Labels", "Story Points", "Resolved", "First In Progress", "Resolved At", "Cycle Time (Days)"]].copy()
    disp_df["First In Progress"] = disp_df["First In Progress"].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notnull(x) else "-")
    disp_df["Resolved At"] = disp_df["Resolved At"].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notnull(x) else "-")
    disp_df = disp_df.rename(columns={
        "Jira URL": "Key",
        "First In Progress": "Start Date",
        "Resolved At": "Resolved Date"
    })
    
    disp_df = disp_df.sort_values(by="Cycle Time (Days)", ascending=False, na_position="last")

    st.dataframe(
        disp_df,
        use_container_width=True,
        column_config={
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
                    date_str = f"{s_start.strftime('%Y-%m-%d')} to {s_end.strftime('%Y-%m-%d')}" if (s_start and s_end) else "Unknown"
                    metrics = {
                        "dates": date_str,
                        "total_sp": f"{total_sp:g}",
                        "achieved_sp": f"{achieved_sp:g}",
                        "sprint_pct": f"{sprint_pct:.1f}%",
                        "releases": str(releases_count),
                        "open_bugs": str(open_bugs),
                        "crit_bugs": str(open_critical_bugs),
                        "cycle_time": f"{avg_cycle_time:.1f}" if pd.notna(avg_cycle_time) else "N/A"
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
