"""Roadmap Reporting: find the group and topic labels that exist in Jira and add the new ones to the setup.

Jira Server has no "list all labels" call, so labels are read from the JQL autocomplete of the
labels field, which returns at most a few suggestions per query (15 on Jira Server). When a query
comes back full, it is narrowed by one more character (RC2_G -> RC2_G1, RC2_G2, ...) until every
label starting with the search prefix has been seen.

Labels are then classified with two regular expressions whose first group is the group number
(G<#>) and, for topics, whose second group is the topic number (T<#>). A topic belongs to the
group with the same group number.
"""
import re
import string
from concurrent.futures import ThreadPoolExecutor

import requests

from utils.jira_helpers import get_jira_auth_headers
from utils.roadmap_labels import GROUP_LABEL_RE, TOPIC_LABEL_RE, normalize_config

DEFAULT_PREFIX = "RC2_G"
DEFAULT_GROUP_PATTERN = GROUP_LABEL_RE.pattern
DEFAULT_TOPIC_PATTERN = TOPIC_LABEL_RE.pattern
SUGGESTION_LIMIT = 15          # a query returning this many suggestions may have been cut off
MAX_QUERIES = 300              # safety stop for the narrowing
PARALLEL_QUERIES = 8           # queries of one narrowing level sent at the same time
# Characters tried when narrowing a full query (suggestions are case-insensitive; labels have no spaces)
_NARROW_CHARS = string.digits + string.ascii_uppercase + "_-.+#&/"


class JiraLabelsError(Exception):
    pass


# ---------------------------------------------------------------- Jira

def fetch_labels(server, token, auth_type, email, prefix, limit=SUGGESTION_LIMIT, max_queries=MAX_QUERIES,
                 workers=PARALLEL_QUERIES):
    """(sorted labels starting with prefix, complete?) from the Jira labels autocomplete.

    Queries are sent level by level (prefix, then prefix + one character for each full answer, ...),
    the queries of a level in parallel. complete is False when the safety stop was reached before every
    full query could be narrowed. Raises JiraLabelsError when Jira refuses a request.
    """
    prefix = (prefix or "").strip()
    if not prefix:
        raise JiraLabelsError("Enter a search prefix, e.g. RC2_G.")
    headers, auth = get_jira_auth_headers(token, auth_type, email)
    url = f"{server.rstrip('/')}/rest/api/2/jql/autocompletedata/suggestions"

    def suggest(query):
        resp = requests.get(url, headers=headers, auth=auth, timeout=20,
                            params={"fieldName": "labels", "fieldValue": query})
        if resp.status_code != 200:
            raise JiraLabelsError(f"Jira answered HTTP {resp.status_code} to the labels search.")
        return resp.json().get("results") or []

    found, level, queries = {}, [prefix], 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while level:
            if queries + len(level) > max_queries:
                level = level[:max(0, max_queries - queries)]
                truncated = True
            else:
                truncated = False
            queries += len(level)
            next_level = []
            for query, results in zip(level, pool.map(suggest, level)):
                for item in results:
                    label = str(item.get("value", "")).strip().strip('"')
                    if label.lower().startswith(prefix.lower()):
                        found.setdefault(label.lower(), label)
                if len(results) >= limit:
                    next_level.extend(query + ch for ch in _NARROW_CHARS)
            if truncated or (next_level and queries >= max_queries):
                return sorted(found.values(), key=str.lower), False
            level = next_level
    return sorted(found.values(), key=str.lower), True


# ---------------------------------------------------------------- classification

def compile_pattern(pattern, needed_groups, what):
    """Compiled regex, checking it has the capture groups the import needs."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"The {what} pattern is not a valid regular expression: {e}") from e
    if rx.groups < needed_groups:
        need = "the group number" if needed_groups == 1 else "the group number and the topic number"
        raise ValueError(f"The {what} pattern needs {needed_groups} capture group(s) in brackets: {need}.")
    return rx


def name_from_label(label, rx):
    """Readable name from a label: the part after the matched numbers, CamelCase and _ split into words.

    RC2_G1_T2_ConnectToGVF -> "Connect To GVF"; RC2_G3_T1_Module1_ProductivityFeatures ->
    "Module1 Productivity Features". Names are only a starting point: they can be edited.
    """
    m = rx.match(label)
    if not m or not m.lastindex:
        return label
    rest = label[m.end(m.lastindex):].lstrip("_-. ")
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", rest.replace("_", " "))
    return re.sub(r"\s+", " ", words).strip() or label


def _number(m, index):
    try:
        return int(m.group(index))
    except (TypeError, ValueError, IndexError):
        return None


def plan_import(config, labels, group_rx, topic_rx):
    """What the Jira labels add to the configuration (nothing is changed here).

    Returns {"new_groups": [{"label", "name", "number"}], "new_topics": [{"label", "name", "group_number",
    "topic_number", "group_label"}], "orphans": [labels of topics whose group is nowhere],
    "known": int, "not_in_jira": [configured labels Jira did not return], "other": [labels matching
    neither pattern]}.
    """
    config = normalize_config(config)
    configured = {g["label"].lower() for g in config["groups"]} | {
        t["label"].lower() for g in config["groups"] for t in g["topics"]}
    group_of_number = {}
    for g in config["groups"]:
        m = group_rx.match(g["label"])
        if m and _number(m, 1) is not None:
            group_of_number.setdefault(_number(m, 1), g["label"])

    plan = {"new_groups": [], "new_topics": [], "orphans": [], "known": 0, "not_in_jira": [], "other": []}
    topics = []
    for label in labels:
        topic_m, group_m = topic_rx.match(label), group_rx.match(label)
        if label.lower() in configured:
            plan["known"] += 1
        elif topic_m:
            topics.append((label, topic_m))
        elif group_m:
            number = _number(group_m, 1)
            plan["new_groups"].append({"label": label, "name": name_from_label(label, group_rx), "number": number})
            if number is not None:
                group_of_number.setdefault(number, label)
        else:
            plan["other"].append(label)
    for label, m in topics:
        g_num, t_num = _number(m, 1), _number(m, 2)
        group_label = group_of_number.get(g_num)
        if group_label is None:
            plan["orphans"].append(label)
        else:
            plan["new_topics"].append({"label": label, "name": name_from_label(label, topic_rx),
                                       "group_number": g_num, "topic_number": t_num, "group_label": group_label})
    in_jira = {label.lower() for label in labels}
    plan["not_in_jira"] = sorted(label for label in configured_labels(config) if label.lower() not in in_jira)
    plan["new_groups"].sort(key=lambda g: (g["number"] is None, g["number"] or 0, g["label"].lower()))
    plan["new_topics"].sort(key=lambda t: (t["group_number"], t["topic_number"] is None, t["topic_number"] or 0))
    return plan


def configured_labels(config):
    return [g["label"] for g in config["groups"] if g["label"]] + [
        t["label"] for g in config["groups"] for t in g["topics"] if t["label"]]


def apply_import(config, plan):
    """New configuration with the plan's new groups appended (by number) and each new topic appended
    to its group (by topic number). Existing groups and topics are left as they are."""
    config = normalize_config(config)
    groups = [dict(g, topics=list(g["topics"])) for g in config["groups"]]
    for g in plan["new_groups"]:
        groups.append({"name": g["name"], "label": g["label"], "topics": []})
    by_label = {g["label"].lower(): g for g in groups}
    for t in plan["new_topics"]:
        group = by_label.get(t["group_label"].lower())
        if group is not None:
            group["topics"].append({"name": t["name"], "label": t["label"]})
    return normalize_config({"groups": groups})
