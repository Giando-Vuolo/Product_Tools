"""Roadmap Reporting: progress of each Topic from the tickets under its Epics.

Tickets counted for a Topic: every child of the Epics that carry the Topic label
(linked through "Epic Link", or "parent" on Jira Cloud). Each ticket scores:

- 100 %: resolved and in a released fix version, or in the "not release relevant" version
- 90 %:  resolved but no fix version released yet
- 50 %:  not resolved and not in a To Do status (in progress)
- 0 %:   To Do

The Topic progress is the plain average: every ticket weighs the same.
"""
import logging
import os

import requests

from utils.jira_helpers import get_jira_auth_headers, map_jira_status

logger = logging.getLogger(__name__)

NOT_RELEASE_RELEVANT = os.getenv("ROADMAP_NOT_RELEASE_RELEVANT", "DIGI:HUB Not release relevant").strip()

BUCKET_RELEASED = "Closed & released"
BUCKET_CLOSED = "Closed, not released"
BUCKET_PROGRESS = "In progress"
BUCKET_TODO = "To do"
BUCKET_SCORES = {BUCKET_RELEASED: 100, BUCKET_CLOSED: 90, BUCKET_PROGRESS: 50, BUCKET_TODO: 0}

# Fallback ids of the Epic Link custom field when the field list cannot be read
EPIC_LINK_FALLBACKS = ["customfield_10014", "customfield_10000", "customfield_10008", "customfield_10009"]
PAGE_SIZE = 500


def ticket_bucket(fields, not_release_relevant=NOT_RELEASE_RELEVANT):
    """Scoring bucket of one Jira issue from its fields (status, resolution, fixVersions)."""
    if fields.get("resolution"):
        nrr = (not_release_relevant or "").strip().lower()
        for version in fields.get("fixVersions") or []:
            if version.get("released") or (nrr and str(version.get("name", "")).strip().lower() == nrr):
                return BUCKET_RELEASED
        return BUCKET_CLOSED
    status = fields.get("status") or {}
    category = str((status.get("statusCategory") or {}).get("key", "")).lower()
    if category == "new" or (not category and map_jira_status(status.get("name")) == "To Do"):
        return BUCKET_TODO
    return BUCKET_PROGRESS


def average_progress(tickets):
    """Average score (0-100) of the tickets, or None when there are none."""
    if not tickets:
        return None
    return sum(BUCKET_SCORES[t["bucket"]] for t in tickets) / len(tickets)


def bucket_counts(tickets):
    counts = {b: 0 for b in BUCKET_SCORES}
    for t in tickets:
        counts[t["bucket"]] += 1
    return counts


def _quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def epics_jql(labels, project_key=""):
    project_key = (project_key or "").strip()
    project = f"project = {_quote(project_key)} AND " if project_key else ""
    return f"{project}issuetype = Epic AND labels in ({', '.join(_quote(l) for l in labels)}) ORDER BY key"


def children_jql(epic_keys):
    keys = ", ".join(_quote(k) for k in epic_keys)
    return f'"Epic Link" in ({keys}) OR parent in ({keys}) ORDER BY key'


class JiraError(Exception):
    pass


class _Jira:
    def __init__(self, server, token, auth_type, email):
        self.base = server.rstrip("/")
        self.headers, self.auth = get_jira_auth_headers(token, auth_type, email)

    def get(self, path, params=None):
        resp = requests.get(f"{self.base}{path}", headers=self.headers, auth=self.auth, params=params, timeout=30)
        if resp.status_code != 200:
            try:
                messages = resp.json().get("errorMessages") or []
            except ValueError:
                messages = []
            raise JiraError("; ".join(messages) or f"HTTP {resp.status_code}")
        return resp.json()

    def search(self, jql, fields):
        """Every issue matching the JQL (follows the pages)."""
        issues, start = [], 0
        while True:
            page = self.get("/rest/api/2/search",
                            {"jql": jql, "fields": ",".join(fields), "startAt": start, "maxResults": PAGE_SIZE})
            batch = page.get("issues") or []
            issues.extend(batch)
            start += len(batch)
            if not batch or start >= int(page.get("total", 0)):
                return issues

    def epic_link_field(self):
        try:
            for field in self.get("/rest/api/2/field"):
                if str(field.get("name", "")).strip().lower() == "epic link":
                    return [field.get("id")]
        except (JiraError, requests.RequestException):
            logger.warning("Could not read the Jira field list; using fallback Epic Link ids", exc_info=True)
        return EPIC_LINK_FALLBACKS


def _epic_of(fields, epic_link_ids):
    for fid in epic_link_ids:
        value = fields.get(fid)
        if value:
            return value.get("key") if isinstance(value, dict) else str(value)
    parent = fields.get("parent") or {}
    return parent.get("key")


def load_topic_progress(server, token, auth_type, email, config, project_key="", not_release_relevant=NOT_RELEASE_RELEVANT):
    """Progress of every configured Topic.

    Returns {topic label: {"epics": [{"key", "summary"}], "tickets": [{"key", "summary", "status",
    "epic", "fix_versions", "bucket"}], "progress": float | None}}. Raises JiraError when Jira fails.
    """
    labels = [t["label"] for g in config.get("groups", []) for t in g["topics"] if t["label"]]
    result = {label: {"epics": [], "tickets": [], "progress": None} for label in labels}
    if not labels:
        return result
    jira = _Jira(server, token, auth_type, email)
    by_lower = {label.lower(): label for label in labels}

    epics = jira.search(epics_jql(labels, project_key), ["summary", "labels"])
    topics_of_epic = {}
    for epic in epics:
        fields = epic.get("fields") or {}
        for label in fields.get("labels") or []:
            topic = by_lower.get(str(label).lower())
            if topic:
                result[topic]["epics"].append({"key": epic["key"], "summary": fields.get("summary", "")})
                topics_of_epic.setdefault(epic["key"], []).append(topic)

    epic_keys = list(topics_of_epic)
    if epic_keys:
        link_ids = jira.epic_link_field()
        fields_wanted = ["summary", "status", "resolution", "fixVersions", "parent", *link_ids]
        seen = set()
        for start in range(0, len(epic_keys), 100):   # keep the JQL short
            for issue in jira.search(children_jql(epic_keys[start:start + 100]), fields_wanted):
                fields = issue.get("fields") or {}
                epic_key = _epic_of(fields, link_ids)
                if epic_key not in topics_of_epic or (issue["key"], epic_key) in seen:
                    continue
                seen.add((issue["key"], epic_key))
                ticket = {
                    "key": issue["key"],
                    "summary": fields.get("summary", ""),
                    "status": (fields.get("status") or {}).get("name", ""),
                    "epic": epic_key,
                    "fix_versions": ", ".join(v.get("name", "") for v in fields.get("fixVersions") or []),
                    "bucket": ticket_bucket(fields, not_release_relevant),
                }
                for topic in topics_of_epic[epic_key]:
                    result[topic]["tickets"].append(ticket)

    for data in result.values():
        data["progress"] = average_progress(data["tickets"])
    return result
