import os
import requests
import pandas as pd
from dotenv import load_dotenv

env_path = "/Users/fc0kewc/Desktop/PO_Tools/.env"
load_dotenv(dotenv_path=env_path, override=True)

server = os.getenv("JIRA_SERVER", "")
token = os.getenv("JIRA_API_TOKEN", "")
committed_label = os.getenv("COMMITTED_LABEL", "RC2_committed")
quarter_label = os.getenv("QUARTER_LABEL", "RC2_FB_18")
email = ""
auth_type = "Personal Access Token (Bearer PAT)"

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
    token_clean = token.strip()
    if token_clean.lower().startswith("bearer "):
        token_clean = token_clean[7:].strip()
    jql = query_val
    url = f"{server.rstrip('/')}/rest/api/2/search"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "X-Atlassian-Token": "no-check"
    }
    headers["Authorization"] = f"Bearer {token_clean}"
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,fixVersions,parent,customfield_10000,customfield_10008,customfield_10009,customfield_10014,assignee,issuetype,labels"
    }
    response = requests.get(url, headers=headers, params=params, timeout=15)
    issues = response.json().get("issues", [])
    rows = []
    for issue in issues:
        fields = issue.get("fields", {})
        key = issue.get("key", "N/A")
        summary = fields.get("summary", "Untitled Task")
        status_obj = fields.get("status") or {}
        raw_status = status_obj.get("name", "To Do")
        status = map_jira_status(raw_status)
        row = {
            "Key": key,
            "Summary": summary,
            "Status": status,
            "Raw Status": raw_status
        }
        rows.append(row)
    return pd.DataFrame(rows)

def fetch_epic_completion(server, token, epic_keys, epic_link_field, auth_type="Personal Access Token (Bearer PAT)", email=""):
    token_clean = token.strip()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token_clean}",
        "User-Agent": "Mozilla/5.0"
    }
    completion_by_epic = {}
    for epic_key in epic_keys:
        relation_jql = f'"Epic Link" = "{epic_key}"'
        params = {"jql": relation_jql, "maxResults": 1000, "fields": "status"}
        try:
            response = requests.get(
                f"{server.rstrip('/')}/rest/api/2/search",
                headers=headers,
                params=params,
                timeout=15
            )
            if response.status_code != 200:
                print(f"Failed to fetch issues for epic {epic_key}, HTTP {response.status_code}")
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
        except Exception as e:
            print("Error for epic completion:", epic_key, e)
            completion_by_epic[epic_key] = "-"
    return completion_by_epic

def build_quarterly_epic_progress_table(server, token, committed_label, quarter_label, title, position, auth_type, email):
    jql = (
        'project = RECALLTWO AND issuetype = Epic '
        f'AND labels in ({committed_label}) '
        f'AND labels in ({quarter_label})'
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
    if res_df is None or res_df.empty:
        return None

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
    return res_df

print("Running build_quarterly_epic_progress_table...")
res = build_quarterly_epic_progress_table(server, token, committed_label, quarter_label, "Epics", "Before Demo Table", auth_type, email)
if res is not None:
    print("Table built successfully with rows:", len(res))
    print(res.head(5))
else:
    print("Failed to build table or table is empty.")
