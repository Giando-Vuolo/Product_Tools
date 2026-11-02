"""Sprint KPIs with the Jira source switched off (utils/kpi_helpers.without_jira_kpis)."""
import unittest

from utils import kpi_helpers as kh


class WithoutJiraKpisTests(unittest.TestCase):
    def setUp(self):
        self.metrics = {
            "dates": "2026-10-05 to 2026-10-16", "total_sp": "20", "achieved_sp": "18", "sprint_pct": "90.0%",
            "releases": "1", "open_bugs": "3", "crit_bugs": "1", "resolved_bugs": "2", "cycle_time": "2.5",
            "items": {name: "5" for name in kh.ITEM_KPIS},
            "quality": {"Bugs": "4"},
        }

    def test_blanks_jira_kpis_but_keeps_dates_and_quality(self):
        blanked = kh.without_jira_kpis(self.metrics)
        self.assertEqual(blanked["dates"], "2026-10-05 to 2026-10-16")
        for key in kh.BASE_METRIC_KEYS:
            if key != "dates":
                self.assertEqual(blanked[key], "", key)
        self.assertEqual(blanked["items"], {name: "" for name in kh.ITEM_KPIS})
        self.assertEqual(blanked["quality"], {"Bugs": "4"})

    def test_original_metrics_are_not_modified(self):
        kh.without_jira_kpis(self.metrics)
        self.assertEqual(self.metrics["total_sp"], "20")
        self.assertEqual(self.metrics["items"][kh.ITEMS_COMMITTED_KPI], "5")

    def test_table_row_has_empty_jira_columns(self):
        row = kh.metrics_to_table_row("Sprint 10", kh.without_jira_kpis(self.metrics))
        self.assertEqual(row["Sprint"], "Sprint 10")
        self.assertEqual(row["Target Dates"], "2026-10-05 to 2026-10-16")
        self.assertEqual(row["Committed SP (at Start)"], "")
        self.assertEqual(row["Avg Cycle Time (Days)"], "")
        self.assertEqual(row["Bugs"], "4")


if __name__ == "__main__":
    unittest.main()
