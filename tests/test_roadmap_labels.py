import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from utils import roadmap_labels as rl

ROOT = Path(__file__).resolve().parent.parent
PAGE = str(ROOT / "tools/9_Roadmap_Reporting.py")


def _cfg(*groups):
    return rl.normalize_config({"groups": [
        {"name": n, "label": l, "topics": [{"name": tn, "label": tl} for tn, tl in topics]}
        for n, l, topics in groups
    ]})


class DefaultConfigTests(unittest.TestCase):
    def test_default_config_is_valid_and_follows_convention(self):
        errors, warnings = rl.validate_config(rl.normalize_config(rl.DEFAULT_CONFIG))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_default_has_four_groups_and_seventeen_topics(self):
        cfg = rl.normalize_config(rl.DEFAULT_CONFIG)
        self.assertEqual(len(cfg["groups"]), 4)
        self.assertEqual(sum(len(g["topics"]) for g in cfg["groups"]), 17)


class PersistenceTests(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(rl.load_config(Path(d) / "none.json"), rl.normalize_config(rl.DEFAULT_CONFIG))

    def test_corrupt_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            p.write_text("{not json", encoding="utf-8")
            self.assertEqual(rl.load_config(p), rl.normalize_config(rl.DEFAULT_CONFIG))

    def test_save_and_load_roundtrip(self):
        cfg = _cfg(("G", "RC2_G1_G", [("T", "RC2_G1_T1_T")]))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "cfg.json"
            rl.save_config(cfg, p)
            self.assertEqual(rl.load_config(p), cfg)

    def test_empty_saved_config_stays_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            rl.save_config({"groups": []}, p)
            self.assertEqual(rl.load_config(p), {"groups": []})


class NormalizeAndBuildTests(unittest.TestCase):
    def test_strips_and_drops_blank_rows(self):
        cfg = rl.normalize_config({"groups": [
            {"name": " A ", "label": " RC2_G1_A ", "topics": [{"name": "", "label": None}, {"name": "x", "label": "y"}]},
            {"name": "", "label": ""},
        ]})
        self.assertEqual(cfg, {"groups": [{"name": "A", "label": "RC2_G1_A", "topics": [{"name": "x", "label": "y", "subtitle": "", "due": "", "status": ""}]}]})

    def test_build_config_pairs_groups_with_topics(self):
        cfg = rl.build_config(
            [{"Group": "A", "Label": "RC2_G1_A"}, {"Group": "B", "Label": "RC2_G2_B"}],
            [[{"Topic": "a1", "Label": "RC2_G1_T1_A1"}], []],
        )
        self.assertEqual(cfg["groups"][0]["topics"], [{"name": "a1", "label": "RC2_G1_T1_A1", "subtitle": "", "due": "", "status": ""}])
        self.assertEqual(cfg["groups"][1]["topics"], [])

    def test_rows_roundtrip(self):
        cfg = rl.normalize_config(rl.DEFAULT_CONFIG)
        rebuilt = rl.build_config(rl.groups_to_rows(cfg), [rl.topics_to_rows(g) for g in cfg["groups"]])
        self.assertEqual(rebuilt, cfg)


class DueDateTests(unittest.TestCase):
    def test_normalize_due_accepts_dates_and_iso_strings(self):
        import datetime as dt
        import pandas as pd
        self.assertEqual(rl.normalize_due(dt.date(2027, 1, 31)), "2027-01-31")
        self.assertEqual(rl.normalize_due(dt.datetime(2027, 1, 31, 10, 0)), "2027-01-31")
        self.assertEqual(rl.normalize_due(pd.Timestamp("2027-01-31")), "2027-01-31")
        self.assertEqual(rl.normalize_due("2027-01-31T00:00:00"), "2027-01-31")

    def test_normalize_due_empty_or_invalid(self):
        import pandas as pd
        for value in (None, "", pd.NaT, float("nan"), "31.01.2027", "soon"):
            self.assertEqual(rl.normalize_due(value), "", value)

    def test_due_date_roundtrips_through_rows_and_file(self):
        import datetime as dt
        cfg = rl.build_config([{"Group": "A", "Label": "RC2_G1_A"}],
                              [[{"Topic": "t", "Label": "RC2_G1_T1_T", "Due date": dt.date(2027, 1, 31)}]])
        self.assertEqual(cfg["groups"][0]["topics"][0]["due"], "2027-01-31")
        self.assertEqual(rl.topics_to_rows(cfg["groups"][0])[0]["Due date"], dt.date(2027, 1, 31))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            rl.save_config(cfg, p)
            self.assertEqual(rl.load_config(p), cfg)

    def test_config_saved_before_due_dates_loads_with_empty_due(self):
        cfg = rl.normalize_config({"groups": [{"name": "A", "label": "L", "topics": [{"name": "t", "label": "T"}]}]})
        self.assertEqual(cfg["groups"][0]["topics"][0]["due"], "")


class TopicOrderTests(unittest.TestCase):
    def _names(self, rows):
        cfg = rl.build_config([{"Group": "A", "Label": "RC2_G1_A"}], [rows])
        return [t["name"] for t in cfg["groups"][0]["topics"]]

    def _row(self, name, order):
        return {"Order": order, "Topic": name, "Label": f"RC2_G1_T1_{name}"}

    def test_rows_are_numbered_in_list_order(self):
        cfg = rl.normalize_config(rl.DEFAULT_CONFIG)
        self.assertEqual([r["Order"] for r in rl.topics_to_rows(cfg["groups"][1])], [1, 2, 3, 4, 5, 6])

    def test_topics_are_saved_sorted_by_order(self):
        rows = [self._row("a", 3), self._row("b", 1), self._row("c", 2)]
        self.assertEqual(self._names(rows), ["b", "c", "a"])

    def test_ties_keep_table_order_and_decimals_work(self):
        rows = [self._row("a", 2), self._row("b", 2), self._row("c", 1.5)]
        self.assertEqual(self._names(rows), ["c", "a", "b"])

    def test_missing_order_goes_last(self):
        rows = [self._row("new", None), self._row("a", 2), self._row("nan", float("nan")), self._row("b", 1)]
        self.assertEqual(self._names(rows), ["b", "a", "new", "nan"])

    def test_order_is_not_saved_and_is_renumbered(self):
        cfg = rl.build_config([{"Group": "A", "Label": "RC2_G1_A"}],
                              [[self._row("a", 10), self._row("b", 5)]])
        self.assertNotIn("order", cfg["groups"][0]["topics"][0])
        self.assertEqual([(r["Order"], r["Topic"]) for r in rl.topics_to_rows(cfg["groups"][0])],
                         [(1, "b"), (2, "a")])


class SubtitleTests(unittest.TestCase):
    def test_subtitle_roundtrips_and_is_cleaned(self):
        cfg = rl.build_config([{"Group": "A", "Label": "RC2_G1_A"}], [[
            {"Topic": "t", "Label": "RC2_G1_T1_T", "Subtitle": "  Phase 1 deployed to production "},
            {"Topic": "u", "Label": "RC2_G1_T2_U", "Subtitle": float("nan")},
        ]])
        topics = cfg["groups"][0]["topics"]
        self.assertEqual(topics[0]["subtitle"], "Phase 1 deployed to production")
        self.assertEqual(topics[1]["subtitle"], "")
        self.assertEqual(rl.topics_to_rows(cfg["groups"][0])[0]["Subtitle"], "Phase 1 deployed to production")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            rl.save_config(cfg, p)
            self.assertEqual(rl.load_config(p), cfg)

    def test_due_box_colour(self):
        self.assertEqual(rl.due_box_color("late"), "#F2A3A2")
        self.assertEqual(rl.due_box_color(""), rl.NO_STATUS_COLOR)


class StatusTests(unittest.TestCase):
    def test_normalize_status_accepts_keys_and_labels(self):
        self.assertEqual(rl.normalize_status("At risk"), rl.STATUS_AT_RISK)
        self.assertEqual(rl.normalize_status("late"), rl.STATUS_LATE)
        self.assertEqual(rl.normalize_status(" ON TRACK "), rl.STATUS_ON_TRACK)
        for value in (None, "", float("nan"), "None", "unknown"):
            self.assertEqual(rl.normalize_status(value), "", value)

    def test_status_roundtrips_through_rows_and_file(self):
        import datetime as dt
        cfg = rl.build_config([{"Group": "A", "Label": "RC2_G1_A"}], [[
            {"Topic": "t", "Label": "RC2_G1_T1_T", "Due date": dt.date(2027, 1, 31), "Status": "At risk"}]])
        topic = cfg["groups"][0]["topics"][0]
        self.assertEqual(topic["status"], rl.STATUS_AT_RISK)
        self.assertEqual(rl.topics_to_rows(cfg["groups"][0])[0]["Status"], "At risk")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            rl.save_config(cfg, p)
            self.assertEqual(rl.load_config(p), cfg)

    def test_status_colours_match_legend(self):
        self.assertEqual([c for _, c in rl.DUE_STATUS.values()], ["#AEE1B8", "#F9DB99", "#F2A3A2"])

    def test_status_without_due_date_warns(self):
        cfg = rl.normalize_config({"groups": [{"name": "A", "label": "RC2_G1_A", "topics": [
            {"name": "t", "label": "RC2_G1_T1_T", "status": "late"}]}]})
        errors, warnings = rl.validate_config(cfg)
        self.assertEqual(errors, [])
        self.assertTrue(any("has a status but no due date" in w for w in warnings))


class ValidationTests(unittest.TestCase):
    def test_missing_name_and_label_are_errors(self):
        errors, _ = rl.validate_config(_cfg(("", "RC2_G1_A", [("T", "")])))
        self.assertTrue(any("has no name" in e for e in errors))
        self.assertTrue(any("has no label" in e for e in errors))

    def test_duplicate_label_across_groups_is_error(self):
        errors, _ = rl.validate_config(_cfg(
            ("A", "RC2_G1_A", [("t", "RC2_G1_T1_X")]),
            ("B", "RC2_G2_B", [("t", "rc2_g1_t1_x")]),
        ))
        self.assertTrue(any("used by" in e for e in errors))

    def test_duplicate_group_name_is_error(self):
        errors, _ = rl.validate_config(_cfg(("A", "RC2_G1_A", []), ("a", "RC2_G2_A", [])))
        self.assertTrue(any("used twice" in e for e in errors))

    def test_convention_warnings(self):
        _, warnings = rl.validate_config(_cfg(
            ("A", "GroupA", [("t", "TopicA")]),
            ("B", "RC2_G2_B", [("t", "RC2_G1_T1_Wrong")]),
        ))
        self.assertTrue(any("RC2_G<#>_<Group Name>" in w for w in warnings))
        self.assertTrue(any("RC2_G<#>_T<#>_<Topic Name>" in w for w in warnings))
        self.assertTrue(any("prefix says G1" in w for w in warnings))

    def test_topic_label_is_not_a_valid_group_label(self):
        _, warnings = rl.validate_config(_cfg(("A", "RC2_G1_T1_A", [])))
        self.assertTrue(any("RC2_G<#>_<Group Name>" in w for w in warnings))


class PageTests(unittest.TestCase):
    """The page is a three-step stepper: Set up, Load & Details, Report. Nothing here calls Jira."""

    def _app(self):
        return AppTest.from_file(PAGE, default_timeout=30).run()

    def _go(self, at, number):
        next(b for b in at.button if b.label.startswith(f"{number}.")).click().run()

    def test_starts_on_set_up(self):
        at = self._app()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.tabs), 0)
        self.assertTrue(any("Group labels" in s.value for s in at.subheader))
        step_buttons = [b.label for b in at.button if b.label[:2] in ("2.", "3.")]
        self.assertEqual(step_buttons, ["2. 📥 Load & Details", "3. 📊 Report"])

    def test_load_and_details_step(self):
        at = self._app()
        self._go(at, 2)
        self.assertFalse(at.exception)
        self.assertTrue(any(b.label == "📥 Load progress from Jira" for b in at.button))
        self.assertFalse(any("Group labels" in s.value for s in at.subheader))
        self.assertTrue(any("Load the progress from Jira" in i.value for i in at.info))

    def test_report_step_and_project_kept(self):
        at = self._app()
        self._go(at, 2)
        at.text_input(key="rr_project").set_value("MYPROJ").run()
        self._go(at, 3)
        self.assertFalse(at.exception)
        self.assertTrue(any("📤 Export" in s.value for s in at.subheader))
        self._go(at, 2)
        self.assertEqual(at.text_input(key="rr_project").value, "MYPROJ")


if __name__ == "__main__":
    unittest.main()
