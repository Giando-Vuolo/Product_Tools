"""Roadmap Reporting: configuration of the Jira group labels and topic labels.

Two reporting levels (see "Project Milestone Tracking"):
- Group label: a big overarching topic; it sits on one or more Initiatives.
  Naming convention: RC2_G<#>_<Group Name>
- Topic label: a work package inside one group; it sits on Initiatives or Epics.
  Naming convention: RC2_G<#>_T<#>_<Topic Name>

The configuration is stored locally in ``data/roadmap_labels.json`` as
``{"groups": [{"name", "label", "topics": [{"name", "label", "subtitle", "due", "status"}]}]}``; list order
is report order. ``subtitle`` is a free text shown under the topic name in the report and the slide.
``due`` is the Topic's due date as ``YYYY-MM-DD``, or "" when it has none, and ``status`` its due-date
status chosen by hand: "on_track", "at_risk", "late", or "" when not set.
"""
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

CONFIG_FILE = Path("data/roadmap_labels.json")

GROUP_LABEL_RE = re.compile(r"^RC2_G(\d+)_(?!T\d+_)\S+$")
TOPIC_LABEL_RE = re.compile(r"^RC2_G(\d+)_T(\d+)_\S+$")

# Initial configuration, taken from the "Project Milestone Tracking" document
DEFAULT_CONFIG = {
    "groups": [
        {"name": "New vehicle architecture", "label": "RC2_G1_NewVehicleArchitecture", "topics": [
            {"name": "New Vehicle Selection", "label": "RC2_G1_T1_NewVehicleSelection"},
            {"name": "Connect to GVF", "label": "RC2_G1_T2_ConnectToGVF"},
            {"name": "Adapt new Data Model", "label": "RC2_G1_T3_AdaptNewDataModel"},
            {"name": "Connect to OTA via REST", "label": "RC2_G1_T4_ConnectToOTAviaREST"},
        ]},
        {"name": "Architecture Roadmap", "label": "RC2_G2_ArchitectureRoadmap", "topics": [
            {"name": "Clean up Logs", "label": "RC2_G2_T1_CleanUpLogs"},
            {"name": "Consolidate Databases", "label": "RC2_G2_T2_ConsolidateDatabases"},
            {"name": "Reduce Queues & Triggers", "label": "RC2_G2_T3_ReduceQueuesAndTriggers"},
            {"name": "Simplify Data Model", "label": "RC2_G2_T4_SimplifyDataModel"},
            {"name": "Reduce number of Containers", "label": "RC2_G2_T5_ReduceNumberOfContainers"},
            {"name": "Rework Data Model", "label": "RC2_G2_T6_ReworkDataModel"},
        ]},
        {"name": "Enrichment of existing functions", "label": "RC2_G3_EnrichmentOfExistingFunctions", "topics": [
            {"name": "Module 1: Productivity Features", "label": "RC2_G3_T1_Module1_ProductivityFeatures"},
            {"name": "Module 1: Process & Functional enhancements",
             "label": "RC2_G3_T2_Module1_ProcessAndFunctionalEnhancements"},
            {"name": "Module 2: Productivity Features", "label": "RC2_G3_T3_Module2_ProductivityFeatures"},
            {"name": "Module 2: Process & Functional enhancements",
             "label": "RC2_G3_T4_Module2_ProcessAndFunctionalEnhancements"},
            {"name": "Cross Module: Product improvements", "label": "RC2_G3_T5_CrossModule_ProductImprovements"},
        ]},
        {"name": "New Markets & Brands", "label": "RC2_G4_NewMarketsAndBrands", "topics": [
            {"name": "China", "label": "RC2_G4_T1_China"},
            {"name": "Scout", "label": "RC2_G4_T2_Scout"},
        ]},
    ]
}


def _clean_text(value):
    """Stripped free text; empty for None and for NaN coming from an editable table."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _clean(value):
    return str(value or "").strip()


STATUS_ON_TRACK, STATUS_AT_RISK, STATUS_LATE = "on_track", "at_risk", "late"
DUE_STATUS = {  # key -> (label, legend colour)
    STATUS_ON_TRACK: ("On track", "#AEE1B8"),
    STATUS_AT_RISK: ("At risk", "#F9DB99"),
    STATUS_LATE: ("Late", "#F2A3A2"),
}


NO_STATUS_COLOR = "#C9D3DC"   # due-date box of a topic without status
DUE_TEXT_COLOR = "#0F2A33"    # date inside the box (dark, readable on the pastel colours)


def due_box_color(status):
    return DUE_STATUS[status][1] if status in DUE_STATUS else NO_STATUS_COLOR


def normalize_status(value):
    """Status key from a key or a label (any case), or "" when empty or unknown."""
    text = str(value or "").strip().lower()
    if text in ("nan", "none"):
        return ""
    for key, (label, _) in DUE_STATUS.items():
        if text in (key, label.lower()):
            return key
    return ""


def normalize_due(value):
    """Due date as YYYY-MM-DD, or "" when empty or not a date (accepts date, datetime, Timestamp, str)."""
    if value is None or value == "":
        return ""
    try:
        if value != value:  # NaN / NaT
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return ""


def normalize_config(data):
    """Return a well-formed config: stripped strings, rows without name and label dropped."""
    groups = []
    for g in (data or {}).get("groups") or []:
        name, label = _clean(g.get("name")), _clean(g.get("label"))
        if not name and not label:
            continue
        topics = []
        for t in g.get("topics") or []:
            tname, tlabel = _clean(t.get("name")), _clean(t.get("label"))
            if tname or tlabel:
                topics.append({"name": tname, "label": tlabel, "subtitle": _clean_text(t.get("subtitle")),
                               "due": normalize_due(t.get("due")),
                               "status": normalize_status(t.get("status"))})
        groups.append({"name": name, "label": label, "topics": topics})
    return {"groups": groups}


def load_config(path=CONFIG_FILE):
    """Saved configuration, or the default one when nothing valid is saved yet."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return normalize_config(data)
    except (OSError, ValueError, AttributeError, TypeError):
        return normalize_config(DEFAULT_CONFIG)


def save_config(config, path=CONFIG_FILE):
    """Write the configuration atomically (normalized first)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(normalize_config(config), indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def validate_config(config):
    """(errors, warnings) for a configuration.

    Errors block saving: missing name or label, a label used twice, a group name used twice.
    Warnings flag labels that do not follow the naming convention or whose G<#> does not
    match their group's.
    """
    errors, warnings = [], []
    seen_labels = {}
    seen_groups = set()
    for gi, g in enumerate(config.get("groups", []), 1):
        gname = g["name"] or f"Group #{gi}"
        if not g["name"]:
            errors.append(f"Group #{gi} has no name.")
        elif g["name"].lower() in seen_groups:
            errors.append(f"Group name '{g['name']}' is used twice.")
        seen_groups.add(g["name"].lower())
        if not g["label"]:
            errors.append(f"Group '{gname}' has no label.")
        group_match = GROUP_LABEL_RE.match(g["label"]) if g["label"] else None
        if g["label"] and not group_match:
            warnings.append(f"Group label '{g['label']}' does not follow RC2_G<#>_<Group Name>.")
        for ti, t in enumerate(g["topics"], 1):
            tname = t["name"] or f"Topic #{ti} of '{gname}'"
            if not t["name"]:
                errors.append(f"Topic #{ti} of '{gname}' has no name.")
            if not t["label"]:
                errors.append(f"Topic '{tname}' has no label.")
                continue
            if t.get("status") and not t.get("due"):
                warnings.append(f"Topic '{tname}' has a status but no due date; the status is not shown.")
            topic_match = TOPIC_LABEL_RE.match(t["label"])
            if not topic_match:
                warnings.append(f"Topic label '{t['label']}' does not follow RC2_G<#>_T<#>_<Topic Name>.")
            elif group_match and topic_match.group(1) != group_match.group(1):
                warnings.append(f"Topic label '{t['label']}' is in group '{gname}' "
                                f"but its prefix says G{topic_match.group(1)}.")
        for label, owner in [(g["label"], f"group '{gname}'")] + [
                (t["label"], f"topic '{t['name'] or t['label']}'") for t in g["topics"]]:
            if not label:
                continue
            key = label.lower()
            if key in seen_labels:
                errors.append(f"Label '{label}' is used by {seen_labels[key]} and {owner}.")
            else:
                seen_labels[key] = owner
    return errors, warnings


def groups_to_rows(config):
    """Group rows for an editable table: [{"Group", "Label"}]."""
    return [{"Group": g["name"], "Label": g["label"]} for g in config.get("groups", [])]


def topics_to_rows(group):
    """Topic rows of one group for an editable table: [{"Topic", "Label", "Subtitle", "Due date", "Status"}].

    Due date is a date or None; Status is the status label or None.
    """
    return [{"Topic": t["name"], "Label": t["label"], "Subtitle": t.get("subtitle", ""),
             "Due date": date.fromisoformat(t["due"]) if t.get("due") else None,
             "Status": DUE_STATUS[t["status"]][0] if t.get("status") in DUE_STATUS else None}
            for t in group.get("topics", [])]


def build_config(group_rows, topic_rows_per_group):
    """Config from edited table rows: group_rows[i] owns topic_rows_per_group[i]."""
    return normalize_config({"groups": [
        {"name": g.get("Group"), "label": g.get("Label"),
         "topics": [{"name": t.get("Topic"), "label": t.get("Label"), "subtitle": t.get("Subtitle"),
                     "due": t.get("Due date"),
                     "status": t.get("Status")} for t in topics]}
        for g, topics in zip(group_rows, topic_rows_per_group)
    ]})
