"""Cycle time counts only in the sprint that resolved the issue (utils/kpi_helpers.fetch_sprint_kpi_data)."""
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from utils import kpi_helpers as kh

S10 = {"id": 10, "name": "Sprint 10", "startDate": "2026-10-05T08:00:00.000Z", "endDate": "2026-10-16T17:00:00.000Z"}
S11 = {"id": 11, "name": "Sprint 11", "startDate": "2026-10-19T08:00:00.000Z", "endDate": "2026-10-30T17:00:00.000Z"}
SPRINTS = {10: S10, 11: S11}


def _issue(key, sprints, resolved, in_progress):
    return {
        "key": key,
        "fields": {
            "summary": key, "status": {"name": "Done"}, "issuetype": {"name": "Story"}, "labels": [],
            "resolution": {"name": "Done"}, "resolutiondate": resolved,
            "customfield_10016": 3, "customfield_10020": sprints,
        },
        "changelog": {"histories": [{"created": in_progress, "items": [{"field": "status", "toString": "In Progress"}]}]},
    }


ISSUES = [
    # Delivered in Sprint 10: 1 business day
    _issue("A-1", [S10], "2026-10-07T10:00:00.000Z", "2026-10-06T10:00:00.000Z"),
    # Started in Sprint 10, carried over and delivered in Sprint 11: 17 business days
    _issue("A-2", [S10, S11], "2026-10-29T10:00:00.000Z", "2026-10-06T10:00:00.000Z"),
]


def _fetch(sprint_id):
    def fake_get(url, *args, **kwargs):
        resp = MagicMock(status_code=200)
        jql = (kwargs.get("params") or {}).get("jql", "")
        if url.endswith("/field"):
            resp.json.return_value = [{"name": "Story Points", "id": "customfield_10016"},
                                      {"name": "Sprint", "id": "customfield_10020"}]
        elif url.endswith("/search") and "Bug" in jql:
            resp.json.return_value = {"total": 0}
        elif url.endswith("/search"):
            # Jira's "sprint = N" returns every issue whose Sprint field contains N
            resp.json.return_value = {"issues": [
                i for i in ISSUES if any(s["id"] == sprint_id for s in i["fields"]["customfield_10020"])]}
        elif "/agile/1.0/sprint/" in url:
            resp.json.return_value = SPRINTS[sprint_id]
        else:
            resp.status_code = 404
        return resp

    with patch.object(kh.requests, "get", side_effect=fake_get):
        return kh.fetch_sprint_kpi_data("https://jira.example", "token", "Bearer", "", str(sprint_id), [])


class CycleTimeSprintTests(unittest.TestCase):
    def test_carried_over_issue_does_not_count_in_starting_sprint(self):
        res = _fetch(10)
        df = res["df"].set_index("Key")
        self.assertEqual(df.loc["A-1", "Cycle Time (Days)"], 1.0)
        self.assertFalse(df.loc["A-2", "Resolved"])
        self.assertTrue(pd.isna(df.loc["A-2", "Cycle Time (Days)"]))
        self.assertTrue(pd.isna(df.loc["A-2", "Resolved At"]))
        self.assertEqual(kh.compute_sprint_metrics(res)["cycle_time"], "1.0")

    def test_carried_over_issue_counts_in_resolving_sprint(self):
        res = _fetch(11)
        df = res["df"].set_index("Key")
        self.assertEqual(list(df.index), ["A-2"])
        self.assertTrue(df.loc["A-2", "Resolved"])
        self.assertEqual(df.loc["A-2", "Cycle Time (Days)"], 17.0)
        self.assertEqual(kh.compute_sprint_metrics(res)["cycle_time"], "17.0")


if __name__ == "__main__":
    unittest.main()
