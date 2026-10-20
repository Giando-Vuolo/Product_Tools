import os
import sys
import unittest

import pandas as pd
from reportlab.platypus import Table

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.styles import getSampleStyleSheet
from utils.sprint_review_helpers import (
    resolve_custom_bug_column, get_overview_custom_bug_value,
    add_custom_bug_display_column, build_bugs_table_data,
)

LABELS = ["Severity_A", "Severity_B", "Severity_C"]


def _styles():
    ss = getSampleStyleSheet()["Normal"]
    return {k: ss for k in ("header", "header_center", "body", "body_bold", "body_center")}


def _bugs_df():
    return pd.DataFrame([
        {"Epic": "E1", "Key": "AB-1", "Summary": "s1", "Status": "Done", "Fix Version": "1.2.3", "Labels": "Frontend_Team Severity_A"},
        {"Epic": "E1", "Key": "AB-2", "Summary": "s2", "Status": "Done", "Fix Version": "", "Labels": "Backend_Team"},
    ])


def _cell_text(cell):
    return getattr(cell, "text", None) or cell.getPlainText()


class ResolveTests(unittest.TestCase):
    def test_enabled_despite_stale_flag(self):
        cfg = {"custom_bug_column": {"enabled": False, "name": "Prio", "labels": LABELS}}
        self.assertEqual(resolve_custom_bug_column(cfg), (True, "Prio", LABELS))

    def test_empty_labels_disabled(self):
        cfg = {"custom_bug_column": {"enabled": True, "name": "X", "labels": []}}
        self.assertFalse(resolve_custom_bug_column(cfg)[0])

    def test_missing_key(self):
        self.assertEqual(resolve_custom_bug_column({}), (False, "Custom", []))


class OverviewValueTests(unittest.TestCase):
    def test_bug_match(self):
        self.assertEqual(get_overview_custom_bug_value("Bug", "x Severity_B", LABELS), "Severity_B")

    def test_first_in_config_order(self):
        self.assertEqual(get_overview_custom_bug_value("Bug", "Severity_C Severity_A", LABELS), "Severity_A")

    def test_non_bug_empty(self):
        self.assertEqual(get_overview_custom_bug_value("Task", "Severity_A", LABELS), "")

    def test_no_match_empty(self):
        for lab in ("Frontend", "", None, float("nan")):
            self.assertEqual(get_overview_custom_bug_value("Bug", lab, LABELS), "")

    def test_case_insensitive_trim(self):
        self.assertEqual(get_overview_custom_bug_value(" bug ", "severity_a", LABELS), "Severity_A")


class DisplayColumnTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({
            "Select": [False] * 3, "Key": ["A", "B", "C"], "Type": ["Bug", "Task", "Bug"],
            "Labels": ["Severity_B", "Severity_A", "foo"],
        })

    def test_order_and_values(self):
        out = add_custom_bug_display_column(self.df, "Severity", LABELS)
        cols = list(out.columns)
        self.assertEqual(cols.index("Severity"), cols.index("Type") + 1)
        self.assertEqual(cols.index("Labels"), cols.index("Severity") + 1)
        self.assertEqual(list(out["Severity"]), ["Severity_B", "", ""])

    def test_index_preserved_and_no_mutation(self):
        sub = self.df.iloc[[2, 0]]
        out = add_custom_bug_display_column(sub, "Prio", LABELS)
        self.assertEqual(list(out.index), [2, 0])
        self.assertEqual(list(out["Prio"]), ["", "Severity_B"])
        self.assertNotIn("Prio", sub.columns)
        self.assertNotIn("Prio", self.df.columns)

    def test_unchanged_cases(self):
        for name, labels in (("Labels", LABELS), ("", LABELS), ("  ", LABELS), ("S", [])):
            out = add_custom_bug_display_column(self.df, name, labels)
            self.assertEqual(list(out.columns), list(self.df.columns))


class BugsTableTests(unittest.TestCase):
    def test_enabled(self):
        rows, widths = build_bugs_table_data(_bugs_df(), ("Severity", LABELS), _styles())
        self.assertEqual([_cell_text(c) for c in rows[0]],
                         ["Epic", "Key", "Summary", "Status", "Fix Version", "Severity", "Team"])
        self.assertTrue(all(len(r) == 7 for r in rows))
        self.assertEqual(widths, [130, 75, 205, 50, 59, 70, 95])
        self.assertEqual(_cell_text(rows[1][5]), "Severity_A")
        self.assertEqual(_cell_text(rows[2][5]), "-")
        Table(rows, colWidths=widths).wrap(800, 600)

    def test_disabled(self):
        rows, widths = build_bugs_table_data(_bugs_df(), None, _styles())
        self.assertTrue(all(len(r) == 6 for r in rows))
        self.assertEqual(widths, [130, 75, 275, 50, 59, 95])
        self.assertEqual(_cell_text(rows[0][5]), "Team")
        Table(rows, colWidths=widths).wrap(800, 600)

    def test_planned_bugs_like(self):
        df = _bugs_df().assign(Epic=["-", "No Epic"])
        rows, widths = build_bugs_table_data(df, ("Prio", LABELS), _styles())
        self.assertEqual(_cell_text(rows[0][5]), "Prio")
        self.assertEqual(len(rows[0]), len(widths))


if __name__ == "__main__":
    unittest.main()
