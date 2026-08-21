import os
import requests
import re
import pandas as pd

def map_jira_status(status_name):
    if not status_name or not isinstance(status_name, str):
        return "To Do"
    s_clean = status_name.strip().lower()
    if s_clean in ["blocked", "impeded"]:
        return "Blocked"
    elif s_clean in ["resolved", "closed", "done", "acceptance test"]:
        return "Done"
    elif s_clean in ["to do", "todo", "to-do", "backlog", "open", "new", "reopened"]:
        return "To Do"
    else:
        return "In Progress"

def map_epic_status_for_completion_table(status_name):
    status_clean = str(status_name).strip().lower()
    if status_clean in ["done", "closed", "resolved", "complete", "acceptance test"]:
        return "Done"
    if status_clean == "in progress":
        return "In Progress"
    return "To Do"

def get_custom_field_ids(server, headers, auth):
    """Queries Jira fields to find custom field IDs for Target start date and Target end date."""
    target_start_id = None
    target_end_id = None
    url = f"{server.rstrip('/')}/rest/api/2/field"
    try:
        if auth:
            resp = requests.get(url, headers=headers, auth=auth, timeout=10)
        else:
            resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            fields_list = resp.json()
            for f in fields_list:
                name_lower = f.get("name", "").lower().strip()
                field_id = f.get("id")
                if name_lower in ["target start date", "target start", "target_start_date", "target_start"]:
                    target_start_id = field_id
                elif name_lower in ["target end date", "target end", "target_end_date", "target_end", "target enddate"]:
                    target_end_id = field_id
    except Exception as e:
        print(f"[JIRA Helpers] Error fetching fields list: {e}")
    return target_start_id, target_end_id

def fetch_jira_tickets_dataset(server, token, query_val, is_sprint=True, auth_type="Personal Access Token (Bearer PAT)", email="", only_unresolved=False, include_raw_status=False):
    if not server or not token:
        try:
            import streamlit as st
            st.session_state.jira_query_error = "Server URL or Token is missing."
        except:
            pass
        return None
        
    token_clean = token.strip()
    if token_clean.lower().startswith("bearer "):
        token_clean = token_clean[7:].strip()
        
    if is_sprint:
        if query_val.isdigit():
            jql = f"sprint = {query_val}"
        else:
            jql = f"sprint = '{query_val}'"
            
        if only_unresolved:
            jql += " AND resolution is empty"
    else:
        jql = query_val
        
    url = f"{server.rstrip('/')}/rest/api/2/search"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "X-Atlassian-Token": "no-check"
    }

    auth = None
    if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
        auth = (email.strip(), token_clean)
    else:
        headers["Authorization"] = f"Bearer {token_clean}"
        
    # Dynamically find the custom fields for Target start and Target end dates
    target_start_cf, target_end_cf = get_custom_field_ids(server, headers, auth)
    
    requested_fields = ["key", "summary", "status", "fixVersions", "parent", "assignee", "issuetype", "labels", "duedate"]
    if target_start_cf:
        requested_fields.append(target_start_cf)
    if target_end_cf:
        requested_fields.append(target_end_cf)
    
    # Fallback common customfield IDs just in case
    for fb in ["customfield_12115", "customfield_12116", "customfield_10015", "customfield_10016", "customfield_10008", "customfield_10009"]:
        if fb not in requested_fields:
            requested_fields.append(fb)
        
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": ",".join(requested_fields)
    }

    print(f"[DEBUG] fetch_jira_tickets_dataset: url={url}, JQL={jql}")
    try:
        if auth:
            response = requests.get(url, headers=headers, params=params, auth=auth, timeout=15)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=15)

        print(f"[DEBUG] fetch_jira_tickets_dataset: response status_code={response.status_code}")
        with open("data/debug_click.txt", "a") as f:
            f.write(f"fetch_jira_tickets_dataset: response status_code={response.status_code}\n")
        if response.status_code != 200:
            err_msg = f"Jira API connection failed ({response.status_code}): {response.text}"
            with open("data/debug_click.txt", "a") as f:
                f.write(f"fetch_jira_tickets_dataset ERROR: {err_msg}\n")
            print(f"[JIRA Helpers] {err_msg}")
            try:
                import streamlit as st
                st.session_state.jira_query_error = err_msg
            except:
                pass
            return None
            
        try:
            data = response.json()
        except ValueError as json_err:
            err_msg = f"Jira returned a non-JSON response: {json_err}"
            print(f"[JIRA Helpers] {err_msg}")
            try:
                import streamlit as st
                st.session_state.jira_query_error = err_msg
            except:
                pass
            return None
            
        issues = data.get("issues", [])
        with open("data/debug_click.txt", "a") as f:
            f.write(f"fetch_jira_tickets_dataset: issues length = {len(issues) if issues else 0}\n")
        if not issues:
            return pd.DataFrame()
            
        rows = []
        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "N/A")
            summary = fields.get("summary", "Untitled Task")
            
            status_obj = fields.get("status") or {}
            raw_status = status_obj.get("name", "To Do")
            status = map_jira_status(raw_status)
            
            fix_versions = fields.get("fixVersions", [])
            fix_version = fix_versions[0].get("name", "") if fix_versions else ""
            
            assignee_obj = fields.get("assignee") or {}
            assignee = assignee_obj.get("displayName", "Unassigned")
            
            # Use space separator to match Jira's raw label list format (consistent with the rest of the tool)
            labels = " ".join(fields.get("labels", []))

            # Epic detection: check known epic-link custom fields and parent
            epic = "-"
            for cf in ["customfield_10014", "customfield_10000", "customfield_10008", "customfield_10009"]:
                cf_val = fields.get(cf)
                if cf_val:
                    epic = cf_val.get("key", str(cf_val)) if isinstance(cf_val, dict) else str(cf_val)
                    break
            parent = fields.get("parent")
            if parent:
                parent_key = parent.get("key", "")
                parent_summary = (parent.get("fields") or {}).get("summary", "")
                if epic == "-":
                    epic = f"{parent_key} - {parent_summary}" if parent_summary else parent_key

            # Extract start and end planning dates
            due_date = fields.get("duedate")
            target_start = None
            if target_start_cf:
                target_start = fields.get(target_start_cf)
            if not target_start:
                target_start = fields.get("customfield_12115") or fields.get("customfield_10015")
                
            target_end = None
            if target_end_cf:
                target_end = fields.get(target_end_cf)
            if not target_end:
                target_end = fields.get("customfield_12116") or fields.get("customfield_10016") or due_date
            
            row = {
                "Key": key,
                "Summary": summary,
                "Epic": epic,
                "Status": status,
                "Fix Version": fix_version,
                "Assignee": assignee,
                "Labels": labels,
                "Target start date": target_start if target_start else "",
                "Target end date": target_end if target_end else ""
            }
            if include_raw_status:
                row["Raw Status"] = raw_status
            rows.append(row)
            
        return pd.DataFrame(rows)
    except Exception as e:
        err_msg = f"Exception fetching dataset: {e}"
        print(f"[JIRA Helpers] {err_msg}")
        try:
            import streamlit as st
            st.session_state.jira_query_error = err_msg
        except:
            pass
        return None

def fetch_epic_completion(server, token, epic_keys, epic_link_field, auth_type="Personal Access Token (Bearer PAT)", email=""):
    token_clean = token.strip()
    if token_clean.lower().startswith("bearer "):
        token_clean = token_clean[7:].strip()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "X-Atlassian-Token": "no-check"
    }
    auth = None
    if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
        auth = (email.strip(), token_clean)
    else:
        headers["Authorization"] = f"Bearer {token_clean}"

    completion_by_epic = {}
    for k in epic_keys:
        completion_by_epic[k] = "-"

    if not epic_keys:
        return completion_by_epic

    # Build JQL to query all child tickets in one go
    keys_str = ",".join([f'"{k}"' for k in epic_keys])
    relation_jql = f'parent in ({keys_str})' if epic_link_field == "Parent" else f'"Epic Link" in ({keys_str})'
    
    params = {
        "jql": relation_jql,
        "maxResults": 1000,
        "fields": f"status,{'parent' if epic_link_field == 'Parent' else 'customfield_10014,customfield_10000,customfield_10008,customfield_10009'}"
    }

    try:
        response = requests.get(
            f"{server.rstrip('/')}/rest/api/2/search",
            headers=headers,
            params=params,
            auth=auth,
            timeout=15
        )
        if response.status_code != 200:
            return completion_by_epic

        issues = response.json().get("issues", [])
        if not issues:
            return completion_by_epic

        # Group child issues by their Epic key
        epic_issues = {}
        for issue in issues:
            fields = issue.get("fields") or {}
            
            # Find which epic this issue belongs to
            epic_key = None
            if epic_link_field == "Parent":
                parent = fields.get("parent") or {}
                epic_key = parent.get("key")
            else:
                for cf in ["customfield_10014", "customfield_10000", "customfield_10008", "customfield_10009"]:
                    cf_val = fields.get(cf)
                    if cf_val:
                        epic_key = cf_val.get("key", str(cf_val)) if isinstance(cf_val, dict) else str(cf_val)
                        break
            
            if epic_key and epic_key in completion_by_epic:
                if epic_key not in epic_issues:
                    epic_issues[epic_key] = []
                status_name = (fields.get("status") or {}).get("name", "To Do")
                normalized_status = map_jira_status(status_name)
                score = 100 if normalized_status == "Done" else 0 if normalized_status == "To Do" else 50
                epic_issues[epic_key].append(score)

        # Calculate percentage for each Epic
        for epic_key, scores in epic_issues.items():
            if scores:
                completion_by_epic[epic_key] = f"{round(sum(scores) / len(scores))}%"

    except Exception as e:
        with open("data/debug_click.txt", "a") as f:
            f.write(f"fetch_epic_completion EXCEPTION: {e}\n")

    return completion_by_epic

def build_quarterly_epic_progress_table(server, token, committed_label, quarter_label, title, position, auth_type, email, project_key="RECALLTWO"):
    """
    Query committed quarterly epics strictly requiring both configured labels.
    Calculates progress for each Epic from child issues linked via parent or Epic Link.
    """
    escaped_quarter_label = quarter_label.replace('"', '\\"')
    escaped_committed_label = committed_label.replace('"', '\\"')
    
    proj_jql = f'project = "{project_key.strip()}" AND ' if project_key.strip() else ''
    
    jql = (
        f'{proj_jql}issuetype = Epic '
        f'AND labels = "{escaped_committed_label}" '
        f'AND labels = "{escaped_quarter_label}" '
        'ORDER BY priority DESC, updated DESC'
    )
    
    try:
        # Query matching epics
        with open("data/debug_click.txt", "a") as f:
            f.write(f"build_quarterly_epic_progress_table JQL: {jql}\n")
        res_df = fetch_jira_tickets_dataset(
            server,
            token,
            jql,
            is_sprint=False,
            auth_type=auth_type,
            email=email,
            include_raw_status=True
        )
        
        if res_df is None:
            with open("data/debug_click.txt", "a") as f:
                f.write("build_quarterly_epic_progress_table: fetch_jira_tickets_dataset returned None\n")
            return None
    
        cols_to_keep = ["Key", "Summary", "Completion", "Epic", "Status", "Fix Version", "Assignee", "Labels"]
    
        if not res_df.empty:
            # Standardize Statuses
            if "Raw Status" in res_df.columns:
                res_df["Status"] = res_df["Raw Status"].apply(map_epic_status_for_completion_table)
            
            # Calculate individual epic completion percentages
            epic_keys = res_df["Key"].dropna().astype(str).tolist()
            completion_by_epic = fetch_epic_completion(
                server,
                token,
                epic_keys,
                "Epic Link",
                auth_type=auth_type,
                email=email
            )
            res_df["Completion"] = res_df["Key"].map(completion_by_epic).fillna("-")
            extra_df = res_df[[col for col in cols_to_keep if col in res_df.columns]].copy()
        else:
            extra_df = pd.DataFrame(columns=cols_to_keep)
    
        extra_df.insert(0, "Select", False)
        if "Labels" not in extra_df.columns:
            extra_df["Labels"] = ""
    
        result_table = {
            "title": title,
            "df": extra_df,
            "position": position,
            "hidden_cols": ["Epic", "Fix Version", "Assignee", "Labels"],
            "sort_by_team": True,
            "table_type": "quarterly_epic_progress"
        }
        with open("data/debug_click.txt", "a") as f:
            f.write(f"build_quarterly_epic_progress_table success: table title={title}, records count={len(extra_df)}\n")
        return result_table
    except Exception as e:
        import traceback
        with open("data/debug_click.txt", "a") as f:
            f.write(f"build_quarterly_epic_progress_table EXCEPTION: {e}\n{traceback.format_exc()}\n")
        return None
