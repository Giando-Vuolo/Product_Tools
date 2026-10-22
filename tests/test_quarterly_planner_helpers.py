import os
import unittest

import pandas as pd

from utils.quarterly_planner_helpers import (
    build_delivery_roadmap_timeline,
    get_quarterly_team_label,
    parse_quarter_to_date,
    prepare_quarterly_progress_for_presentation,
)


class QuarterlyPlannerHelpersTests(unittest.TestCase):
    def test_parse_quarter_to_date_uses_q_format(self):
        self.assertEqual(parse_quarter_to_date("Q1 - 26").year, 2026)
        self.assertEqual(parse_quarter_to_date("Q1 - 26").month, 1)
        self.assertEqual(parse_quarter_to_date("bad value").year, pd.Timestamp.today().year)

    def test_team_label_resolution_uses_env_order(self):
        old = os.environ.get("TEAM_LABELS")
        os.environ["TEAM_LABELS"] = "Backend_Team,Frontend_Team"
        try:
            self.assertEqual(get_quarterly_team_label("Frontend_Team Backend_Team"), "Backend_Team")
            self.assertEqual(get_quarterly_team_label("Billing"), "-")
        finally:
            if old is None:
                os.environ.pop("TEAM_LABELS", None)
            else:
                os.environ["TEAM_LABELS"] = old

    def test_prepare_quarterly_progress_for_presentation_adds_columns_and_sorts(self):
        old = os.environ.get("TEAM_LABELS")
        os.environ["TEAM_LABELS"] = "Backend_Team,Frontend_Team"
        try:
            df = pd.DataFrame(
                [
                    {"Key": "PR-2", "Summary": "Second", "Status": "Done", "Completion": 100, "Labels": "Frontend_Team"},
                    {"Key": "PR-1", "Summary": "First", "Status": "In Progress", "Completion": 45, "Labels": "Backend_Team"},
                ]
            )
            out = prepare_quarterly_progress_for_presentation(df)

            self.assertIn("Presentation update", out.columns)
            self.assertEqual(list(out["Key"]), ["PR-1", "PR-2"])
            self.assertEqual(out.loc[0, "Team"], "Backend_Team")
        finally:
            if old is None:
                os.environ.pop("TEAM_LABELS", None)
            else:
                os.environ["TEAM_LABELS"] = old

    def test_delivery_roadmap_timeline_builds_dates_and_chart(self):
        df = pd.DataFrame(
            [
                {
                    "Summary": "Alpha",
                    "Include in delivery roadmap": True,
                    "Delivery month": "Jan 2026",
                    "Delivery timing": "Mid",
                    "Release version": "v2.0",
                    "Presentation update": "Ship after validation",
                    "Completion": 70,
                    "Status": "In Progress",
                }
            ]
        )

        roadmap, fig = build_delivery_roadmap_timeline(df)

        self.assertEqual(len(roadmap), 1)
        self.assertIsNotNone(fig)
        self.assertEqual(str(roadmap.iloc[0]["Release"]), "v2.0")
        self.assertTrue(pd.notna(roadmap.iloc[0]["Milestone date"]))


if __name__ == "__main__":
    unittest.main()
