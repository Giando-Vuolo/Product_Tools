import unittest
from unittest import mock

from utils import roadmap_jira_labels as rj
from utils import roadmap_labels as rl

GROUP_RX = rj.compile_pattern(rj.DEFAULT_GROUP_PATTERN, 1, "group")
TOPIC_RX = rj.compile_pattern(rj.DEFAULT_TOPIC_PATTERN, 2, "topic")


def _cfg(*groups):
    return rl.normalize_config({"groups": [
        {"name": n, "label": l, "topics": [{"name": tn, "label": tl} for tn, tl in topics]}
        for n, l, topics in groups]})


class NameTests(unittest.TestCase):
    def test_names_from_labels(self):
        self.assertEqual(rj.name_from_label("RC2_G1_T2_ConnectToGVF", TOPIC_RX), "Connect To GVF")
        self.assertEqual(rj.name_from_label("RC2_G3_T1_Module1_ProductivityFeatures", TOPIC_RX),
                         "Module1 Productivity Features")
        self.assertEqual(rj.name_from_label("RC2_G4_NewMarketsAndBrands", GROUP_RX), "New Markets And Brands")

    def test_name_falls_back_to_label(self):
        self.assertEqual(rj.name_from_label("RC2_G1_T2_", TOPIC_RX), "RC2_G1_T2_")


class PatternTests(unittest.TestCase):
    def test_invalid_regex(self):
        with self.assertRaisesRegex(ValueError, "not a valid regular expression"):
            rj.compile_pattern("RC2_G(", 1, "group")

    def test_missing_capture_groups(self):
        with self.assertRaisesRegex(ValueError, "capture group"):
            rj.compile_pattern(r"^RC2_G\d+_T(\d+)_", 2, "topic")


class PlanTests(unittest.TestCase):
    CONFIG = _cfg(("Architecture", "RC2_G2_ArchitectureRoadmap", [("Logs", "RC2_G2_T1_CleanUpLogs"),
                                                                   ("Old", "RC2_G2_T4_SimplifyDataModel")]))

    def test_classifies_labels(self):
        labels = ["rc2_g2_t1_cleanuplogs", "RC2_G2_ArchitectureRoadmap", "RC2_G2_T8_Build", "RC2_G2_T7_Planning",
                  "RC2_G5_NewGroup", "RC2_G5_T1_First", "RC2_G9_T1_Orphan", "RC2_GSB", "RC2_grooming"]
        plan = rj.plan_import(self.CONFIG, labels, GROUP_RX, TOPIC_RX)
        self.assertEqual(plan["known"], 2)  # case-insensitive
        self.assertEqual([g["label"] for g in plan["new_groups"]], ["RC2_G5_NewGroup"])
        self.assertEqual([(t["label"], t["group_label"]) for t in plan["new_topics"]],
                         [("RC2_G2_T7_Planning", "RC2_G2_ArchitectureRoadmap"),
                          ("RC2_G2_T8_Build", "RC2_G2_ArchitectureRoadmap"),
                          ("RC2_G5_T1_First", "RC2_G5_NewGroup")])
        self.assertEqual(plan["orphans"], ["RC2_G9_T1_Orphan"])
        self.assertEqual(plan["not_in_jira"], ["RC2_G2_T4_SimplifyDataModel"])
        self.assertEqual(plan["other"], ["RC2_GSB", "RC2_grooming"])

    def test_apply_adds_without_touching_existing(self):
        config = rl.normalize_config({"groups": [{"name": "Architecture", "label": "RC2_G2_ArchitectureRoadmap",
                                                  "topics": [{"name": "Logs", "label": "RC2_G2_T1_CleanUpLogs",
                                                              "due": "2026-11-01", "status": "late"}]}]})
        plan = rj.plan_import(config, ["RC2_G2_T7_Planning", "RC2_G5_NewGroup", "RC2_G5_T1_First"],
                              GROUP_RX, TOPIC_RX)
        new = rj.apply_import(config, plan)
        self.assertEqual([g["label"] for g in new["groups"]], ["RC2_G2_ArchitectureRoadmap", "RC2_G5_NewGroup"])
        topics = new["groups"][0]["topics"]
        self.assertEqual(topics[0], config["groups"][0]["topics"][0])  # due date and status kept
        self.assertEqual([t["label"] for t in topics], ["RC2_G2_T1_CleanUpLogs", "RC2_G2_T7_Planning"])
        self.assertEqual(new["groups"][1]["topics"][0]["name"], "First")
        self.assertEqual(rl.validate_config(new)[0], [])


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def _fake_suggestions(all_labels, limit):
    calls = []

    def get(url, headers=None, auth=None, params=None, timeout=None):
        q = params["fieldValue"].lower()
        calls.append(params["fieldValue"])
        hits = [l for l in all_labels if l.lower().startswith(q)][:limit]
        return _Resp({"results": [{"value": f'"{l}"' if "+" in l else l, "displayName": l} for l in hits]})
    return get, calls


class FetchTests(unittest.TestCase):
    LABELS = ["RC2_G1_A", "RC2_G1_T1_X", "RC2_G2_B", "RC2_G2_T1_Y", "RC2_G2_T2_Z", "RC2_G+", "RC2_GSB"]

    def test_narrows_full_queries_until_everything_is_found(self):
        get, calls = _fake_suggestions(self.LABELS, limit=3)
        with mock.patch.object(rj.requests, "get", side_effect=get):
            labels, complete = rj.fetch_labels("https://jira", "t", "Bearer", "", "RC2_G", limit=3)
        self.assertTrue(complete)
        self.assertEqual(sorted(labels, key=str.lower), sorted(self.LABELS, key=str.lower))
        self.assertIn("RC2_G1", calls)

    def test_stops_at_the_safety_limit(self):
        get, _ = _fake_suggestions(self.LABELS, limit=3)
        with mock.patch.object(rj.requests, "get", side_effect=get):
            labels, complete = rj.fetch_labels("https://jira", "t", "Bearer", "", "RC2_G", limit=3, max_queries=2)
        self.assertFalse(complete)
        self.assertTrue(labels)

    def test_errors(self):
        with self.assertRaises(rj.JiraLabelsError):
            rj.fetch_labels("https://jira", "t", "Bearer", "", "  ")
        with mock.patch.object(rj.requests, "get", return_value=_Resp({}, 401)):
            with self.assertRaisesRegex(rj.JiraLabelsError, "401"):
                rj.fetch_labels("https://jira", "t", "Bearer", "", "RC2_G")


if __name__ == "__main__":
    unittest.main()
