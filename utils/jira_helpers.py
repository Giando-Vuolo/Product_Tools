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
        
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,fixVersions,parent,customfield_10000,customfield_10008,customfield_10009,customfield_10014,assignee,issuetype,labels"
    }

    try:
        if auth:
            response = requests.get(url, headers=headers, params=params, auth=auth, timeout=15)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=15)

        if response.status_code != 200:
            err_msg = f"Jira API connection failed ({response.status_code}): {response.text}"
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
            
            labels = " ".join(fields.get("labels", []))
            
            row = {
                "Key": key,
                "Summary": summary,
                "Status": status,
                "Fix Version": fix_version,
                "Assignee": assignee,
                "Labels": labels
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
    for epic_key in epic_keys:
        relation_jql = f'parent = "{epic_key}"' if epic_link_field == "Parent" else f'"Epic Link" = "{epic_key}"'
        params = {"jql": relation_jql, "maxResults": 1000, "fields": "status"}
        try:
            response = requests.get(
                f"{server.rstrip('/')}/rest/api/2/search",
                headers=headers,
                params=params,
                auth=auth,
                timeout=15
            )
            if response.status_code != 200:
                completion_by_epic[epic_key] = "-"
                continue

            issues = response.json().get("issues", [])
            if not issues:
                completion_by_epic[epic_key] = "-"
                continue

            scores = []
            for issue in issues:
                status_name = ((issue.get("fields") or {}).get("status") or {}).get("name", "To Do")
                normalized_status = map_jira_status(status_name)
                scores.append(100 if normalized_status == "Done" else 0 if normalized_status == "To Do" else 50)
            completion_by_epic[epic_key] = f"{round(sum(scores) / len(scores))}%"
        except Exception:
            completion_by_epic[epic_key] = "-"

    return completion_by_epic

def build_quarterly_epic_progress_table(server, token, committed_label, quarter_label, title, position, auth_type, email):
    escaped_quarter_label = quarter_label.replace('"', '\\"')
    escaped_committed_label = committed_label.replace('"', '\\"')
    jql = (
        'project = RECALLTWO AND issuetype = Epic '
        f'AND labels in ({escaped_committed_label}) '
        f'AND labels in ({escaped_quarter_label})'
    )
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
        return None

    if not res_df.empty:
        res_df["Status"] = res_df["Raw Status"].apply(map_epic_status_for_completion_table)
        completion_by_epic = fetch_epic_completion(
            server,
            token,
            res_df["Key"].dropna().astype(str).tolist(),
            "Epic Link",
            auth_type=auth_type,
            email=email
        )
        res_df["Completion"] = res_df["Key"].map(completion_by_epic).fillna("-")

    cols_to_keep = ["Key", "Summary", "Completion", "Epic", "Status", "Fix Version", "Assignee", "Labels"]
    extra_df = res_df[[column for column in cols_to_keep if column in res_df.columns]].copy()
    extra_df.insert(0, "Select", False)
    if "Labels" not in extra_df.columns:
        extra_df["Labels"] = ""
    return {
        "title": title,
        "df": extra_df,
        "position": position,
        "hidden_cols": ["Epic", "Fix Version", "Assignee", "Labels"],
        "sort_by_team": True,
        "table_type": "quarterly_epic_progress"
    }
