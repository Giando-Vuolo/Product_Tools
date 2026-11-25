import unittest
from unittest import mock

from utils import roadmap_progress as rp

NRR = "DIGI:HUB Not release relevant"


def _fields(resolution=None, versions=(), category="indeterminate", status="In Progress"):
    return {
        "resolution": {"name": resolution} if resolution else None,
        "fixVersions": [{"name": n, "released": r} for n, r in versions],
        "status": {"name": status, "statusCategory": {"key": category}},
    }


class TicketBucketTests(unittest.TestCase):
    def test_closed_in_released_version_is_100(self):
        f = _fields("Done", [("R33.0.0", True)], "done", "Closed")
        self.assertEqual(rp.ticket_bucket(f, NRR), rp.BUCKET_RELEASED)

    def test_closed_in_any_released_version_is_100(self):
        f = _fields("Done", [("R35.0.0", False), ("R34.0.0", True)], "done", "Closed")
        self.assertEqual(rp.ticket_bucket(f, NRR), rp.BUCKET_RELEASED)

    def test_closed_not_release_relevant_is_100(self):
        f = _fields("Done", [("digi:hub not release relevant ", False)], "done", "Closed")
        self.assertEqual(rp.ticket_bucket(f, NRR), rp.BUCKET_RELEASED)

    def test_closed_in_unreleased_version_is_90(self):
        f = _fields("Done", [("R36.0.0", False)], "done", "Closed")
        self.assertEqual(rp.ticket_bucket(f, NRR), rp.BUCKET_CLOSED)

    def test_closed_without_version_is_90(self):
        self.assertEqual(rp.ticket_bucket(_fields("Done", [], "done", "Closed"), NRR), rp.BUCKET_CLOSED)

    def test_unresolved_in_progress_is_50_even_if_released(self):
        f = _fields(None, [("R33.0.0", True)], "indeterminate", "In Review")
        self.assertEqual(rp.ticket_bucket(f, NRR), rp.BUCKET_PROGRESS)

    def test_to_do_category_is_0(self):
        self.assertEqual(rp.ticket_bucket(_fields(None, [], "new", "Open"), NRR), rp.BUCKET_TODO)

    def test_to_do_by_name_without_category(self):
        f = {"resolution": None, "status": {"name": "Backlog"}}
        self.assertEqual(rp.ticket_bucket(f, NRR), rp.BUCKET_TODO)


class AverageTests(unittest.TestCase):
    def test_every_ticket_weighs_the_same(self):
        tickets = [{"bucket": b} for b in (rp.BUCKET_RELEASED, rp.BUCKET_CLOSED, rp.BUCKET_PROGRESS, rp.BUCKET_TODO)]
        self.assertEqual(rp.average_progress(tickets), 60)

    def test_no_tickets_is_none(self):
        self.assertIsNone(rp.average_progress([]))

    def test_bucket_counts(self):
        counts = rp.bucket_counts([{"bucket": rp.BUCKET_TODO}, {"bucket": rp.BUCKET_TODO}])
        self.assertEqual(counts[rp.BUCKET_TODO], 2)
        self.assertEqual(counts[rp.BUCKET_RELEASED], 0)


class JqlTests(unittest.TestCase):
    def test_epics_jql_with_project(self):
        self.assertEqual(rp.epics_jql(["A", 'B"x'], "RECALLTWO"),
                         'project = "RECALLTWO" AND issuetype = Epic AND labels in ("A", "B\\"x") ORDER BY key')

    def test_children_jql(self):
        self.assertEqual(rp.children_jql(["E-1"]), '"Epic Link" in ("E-1") OR parent in ("E-1") ORDER BY key')


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


CONFIG = {"groups": [{"name": "G1", "label": "RC2_G1_X", "topics": [
    {"name": "T1", "label": "RC2_G1_T1_A"}, {"name": "T2", "label": "RC2_G1_T2_B"}, {"name": "T3", "label": "RC2_G1_T3_C"}]}]}


def _fake_get(url, headers=None, auth=None, params=None, timeout=None):
    if url.endswith("/field"):
        return _Resp([{"id": "customfield_123", "name": "Epic Link"}])
    jql = params["jql"]
    if "issuetype = Epic" in jql:
        return _Resp({"total": 2, "issues": [
            {"key": "E-1", "fields": {"summary": "Epic 1", "labels": ["rc2_g1_t1_a", "other"]}},
            {"key": "E-2", "fields": {"summary": "Epic 2", "labels": ["RC2_G1_T1_A", "RC2_G1_T2_B"]}},
        ]})
    children = [
        {"key": "S-1", "fields": {**_fields("Done", [("R1", True)], "done"), "customfield_123": "E-1"}},
        {"key": "S-2", "fields": {**_fields(None, [], "new"), "customfield_123": "E-1"}},
        {"key": "S-3", "fields": {**_fields("Done", [("R9", False)], "done"), "customfield_123": "E-2"}},
        {"key": "S-4", "fields": {**_fields(None, [], "indeterminate"), "parent": {"key": "E-2"}}},
    ]
    start = params["startAt"]
    return _Resp({"total": len(children), "issues": children[start:start + 2]})


class LoadTopicProgressTests(unittest.TestCase):
    def test_groups_tickets_by_topic_and_paginates(self):
        with mock.patch.object(rp, "PAGE_SIZE", 2), mock.patch.object(rp.requests, "get", side_effect=_fake_get):
            result = rp.load_topic_progress("https://jira", "tok", "Bearer", "", CONFIG, "P")
        t1, t2, t3 = result["RC2_G1_T1_A"], result["RC2_G1_T2_B"], result["RC2_G1_T3_C"]
        self.assertEqual([e["key"] for e in t1["epics"]], ["E-1", "E-2"])
        self.assertEqual(sorted(t["key"] for t in t1["tickets"]), ["S-1", "S-2", "S-3", "S-4"])
        self.assertEqual(t1["progress"], (100 + 0 + 90 + 50) / 4)
        self.assertEqual(sorted(t["key"] for t in t2["tickets"]), ["S-3", "S-4"])
        self.assertEqual(t2["progress"], 70)
        self.assertEqual(t3, {"epics": [], "tickets": [], "progress": None})

    def test_jira_error_is_raised(self):
        with mock.patch.object(rp.requests, "get", return_value=_Resp({"errorMessages": ["bad jql"]}, 400)):
            with self.assertRaisesRegex(rp.JiraError, "bad jql"):
                rp.load_topic_progress("https://jira", "tok", "Bearer", "", CONFIG)

    def test_no_topics_makes_no_calls(self):
        with mock.patch.object(rp.requests, "get") as get:
            self.assertEqual(rp.load_topic_progress("https://jira", "t", "Bearer", "", {"groups": []}), {})
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
