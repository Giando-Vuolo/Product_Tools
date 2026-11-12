import os
import unittest

import pandas as pd

from utils.quarterly_planner_helpers import (
    build_delivery_roadmap_timeline,
    get_quarterly_team_label,
    parse_quarter_to_date,
    prepare_quarterly_progress_for_presentation,
    normalize_progress_csv,
    ensure_roadmap_columns,
    backlog_roadmap_source,
    build_quarterly_progress_pptx,
    PROGRESS_CSV_TEMPLATE,
    PROGRESS_CSV_COLUMNS,
)
from utils.jira_helpers import quarterly_epics_jql
import io


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


    def test_progress_csv_template_loads(self):
        df = normalize_progress_csv(pd.read_csv(io.StringIO(PROGRESS_CSV_TEMPLATE)))
        self.assertEqual(list(df.columns), PROGRESS_CSV_COLUMNS)
        self.assertEqual(df["Completion"].tolist(), ["100%", "50%", "0%"])

    def test_progress_csv_aliases_and_defaults(self):
        raw = pd.read_csv(io.StringIO("Issue key,Epic Name,Progress,Status\nA-1,X,0.4,Closed\nA-2,Y,,in progress\n"))
        df = normalize_progress_csv(raw)
        self.assertEqual(df["Key"].tolist(), ["A-1", "A-2"])
        self.assertEqual(df["Completion"].tolist(), ["40%", "-"])
        self.assertEqual(df["Status"].tolist(), ["Done", "In Progress"])
        self.assertEqual(df["Parent Link"].tolist(), ["-", "-"])
        self.assertEqual(df["To Do"].tolist(), [0, 0])

    def test_progress_csv_requires_key_and_summary(self):
        with self.assertRaises(ValueError):
            normalize_progress_csv(pd.DataFrame({"Key": ["A-1"]}))

    def test_quarterly_epics_jql(self):
        self.assertEqual(
            quarterly_epics_jql("RECALLTWO", "RC2_committed", "RC2_FB_18"),
            'project = "RECALLTWO" AND issuetype = Epic AND labels = "RC2_committed" AND labels = "RC2_FB_18" ORDER BY priority DESC, updated DESC',
        )
        self.assertTrue(quarterly_epics_jql("", "a", "b").startswith("issuetype = Epic"))

    def test_ensure_roadmap_columns_cleans_csv_roundtrip(self):
        raw = pd.DataFrame({"Key": ["A", "B"], "Include in delivery roadmap": ["True", float("nan")],
                            "Delivery month": [float("nan"), "Jan 2027"], "Delivery timing": [float("nan"), "End"]})
        df = ensure_roadmap_columns(raw)
        self.assertEqual(df["Include in delivery roadmap"].tolist(), [True, False])
        self.assertEqual(df["Delivery month"].tolist(), ["", "Jan 2027"])
        self.assertEqual(df["Release version"].tolist(), ["", ""])
        self.assertEqual(df["Delivery timing"].tolist(), ["Mid", "End"])

    def test_backlog_roadmap_uses_progress_completion(self):
        backlog = pd.DataFrame({"Key": ["A-1", "A-2"], "Epic Name": ["One", "Two"], "Status": ["Done", "To Do"],
                                "Include in delivery roadmap": [True, True], "Delivery month": ["Jan 2027", "Feb 2027"]})
        progress = pd.DataFrame({"Key": ["A-1"], "Completion": ["80%"], "Presentation update": ["Almost there"]})
        source = backlog_roadmap_source(backlog, progress)
        self.assertEqual(source["Summary"].tolist(), ["One", "Two"])
        self.assertEqual(source["Completion"].tolist(), ["80%", "-"])
        self.assertEqual(source["Presentation update"].tolist(), ["Almost there", ""])
        roadmap, fig = build_delivery_roadmap_timeline(source)
        self.assertEqual(len(roadmap), 2)
        self.assertIsNotNone(fig)

    def test_pptx_report_only_and_roadmap_only(self):
        report = prepare_quarterly_progress_for_presentation(pd.read_csv(io.StringIO(PROGRESS_CSV_TEMPLATE)))
        self.assertTrue(build_quarterly_progress_pptx(report, None, "T", "S", "", "", "#1D4ED8"))
        backlog = pd.DataFrame({"Key": ["A-1"], "Epic Name": ["One"], "Status": ["Done"],
                                "Include in delivery roadmap": [True], "Delivery month": ["Jan 2027"]})
        roadmap, _ = build_delivery_roadmap_timeline(backlog_roadmap_source(backlog))
        empty = pd.DataFrame(columns=["Key", "Summary", "Completion", "Status", "Labels"])
        self.assertTrue(build_quarterly_progress_pptx(empty, roadmap, "", "", "Roadmap", "Sub", "#1D4ED8"))

if __name__ == "__main__":
    unittest.main()


class QuarterlyPptxTemplateTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.dir = self._dir.name
        self._env = os.environ.pop("QUARTERLY_PPTX_TEMPLATE", None)

    def tearDown(self):
        self._dir.cleanup()
        os.environ.pop("QUARTERLY_PPTX_TEMPLATE", None)
        if self._env is not None:
            os.environ["QUARTERLY_PPTX_TEMPLATE"] = self._env

    def _touch(self, name):
        path = os.path.join(self.dir, name)
        open(path, "wb").close()
        return path

    def test_no_template(self):
        from utils.quarterly_planner_helpers import find_quarterly_pptx_template
        self.assertIsNone(find_quarterly_pptx_template(self.dir))
        self.assertIsNone(find_quarterly_pptx_template(os.path.join(self.dir, "missing")))

    def test_preferred_name_and_lock_files(self):
        from utils.quarterly_planner_helpers import find_quarterly_pptx_template
        self._touch("~$Template QP.pptx")
        self.assertIsNone(find_quarterly_pptx_template(self.dir))
        other = self._touch("A corporate deck.pptx")
        self.assertEqual(find_quarterly_pptx_template(self.dir), other)
        preferred = self._touch("Template QP.pptx")
        self.assertEqual(find_quarterly_pptx_template(self.dir), preferred)

    def test_env_override(self):
        from utils.quarterly_planner_helpers import find_quarterly_pptx_template
        self._touch("Template QP.pptx")
        chosen = self._touch("Other.pptx")
        os.environ["QUARTERLY_PPTX_TEMPLATE"] = "Other.pptx"
        self.assertEqual(find_quarterly_pptx_template(self.dir), chosen)

    def test_progress_pdf_uses_template_design(self):
        from unittest import mock
        import utils.quarterly_planner_helpers as helpers
        df = pd.DataFrame([{"Key": f"K-{i}", "Summary": "Epic", "Completion": "50%", "Status": "In Progress"} for i in range(13)])
        with mock.patch.object(helpers, "find_quarterly_pptx_template", return_value="t.pptx"), \
             mock.patch.object(helpers, "_template_chrome", return_value={"width": 13.333, "height": 7.5, "logo": None, "texts": [("CONFIDENTIAL", 0.07, 7.3, 0.85, 8, "#000000", False)]}):
            pdf = helpers.build_quarterly_progress_slide_pdf(df, "Title", "#0B2756", "Subtitle")
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf))
        self.assertEqual(len(reader.pages), 2)  # 12 Epics per slide, like the PowerPoint
        self.assertEqual(round(float(reader.pages[0].mediabox.width)), 960)
        text = reader.pages[1].extract_text()
        self.assertIn("Title (cont. 2)", text)
        self.assertIn("CONFIDENTIAL", text)

    def test_without_template_keeps_the_built_in_colours(self):
        from unittest import mock
        import utils.quarterly_planner_helpers as helpers
        from pptx import Presentation
        from pypdf import PdfReader
        df = pd.DataFrame([{"Key": "K-1", "Summary": "Epic", "Completion": "50%", "Status": "In Progress"},
                           {"Key": "K-2", "Summary": "Epic", "Completion": "10%", "Status": "To Do"}])
        with mock.patch.object(helpers, "TEMPLATES_DIR", os.path.join(self.dir, "missing")):
            self.assertIsNone(helpers.find_quarterly_pptx_template())
            pdf = helpers.build_quarterly_progress_slide_pdf(df, "Title", "#0B2756", "Subtitle")
            pptx = helpers.build_quarterly_progress_pptx(df, None, "Title", "Subtitle", "", "", "#0B2756")
        self.assertEqual(round(float(PdfReader(io.BytesIO(pdf)).pages[0].mediabox.width)), 792)  # landscape letter
        table = next(shape for shape in Presentation(io.BytesIO(pptx)).slides[0].shapes if shape.has_table).table
        self.assertEqual(str(table.cell(0, 0).fill.fore_color.rgb), "0B2756")
        self.assertEqual({str(table.cell(1, 0).fill.fore_color.rgb), str(table.cell(2, 0).fill.fore_color.rgb)}, {"FFFFFF", "F1F5F9"})


class ProgressByInitiativeTests(unittest.TestCase):
    def _df(self):
        rows = [{"Parent Link": "INIT-1 - Platform", "Key": f"A-{i}", "Summary": "Epic", "Completion": "50%", "Status": "In Progress"} for i in range(14)]
        rows += [{"Parent Link": "INIT-2 - Customer", "Key": "B-1", "Summary": "Epic", "Completion": "10%", "Status": "To Do"},
                 {"Parent Link": "-", "Key": "C-1", "Summary": "Epic", "Completion": "0%", "Status": "To Do"}]
        return pd.DataFrame(rows)

    def test_slides_per_initiative(self):
        from utils.quarterly_planner_helpers import progress_slides
        slides = progress_slides(self._df(), "Committed Epics Q4 - Status", "ignored", by_initiative=True)
        headings = [[block["heading"] for block in slide["blocks"]] for slide in slides]
        # INIT-1 has 14 Epics: a full slide, then its last 2 share a slide with the small initiatives
        self.assertEqual(headings, [
            ["Initiative: INIT-1 - Platform"],
            ["Initiative: INIT-1 - Platform (cont.)", "Initiative: INIT-2 - Customer", "Initiative: No initiative"],
        ])
        self.assertEqual({slide["title"] for slide in slides}, {"Committed Epics Q4 - Status"})
        self.assertEqual({slide["subtitle"] for slide in slides}, {"Progress grouped by initiative"})
        self.assertEqual([len(b["df"]) for b in slides[1]["blocks"]], [2, 1, 1])
        self.assertTrue(all("Parent Link" not in [c[1] for c in b["columns"]] for s in slides for b in s["blocks"]))

    def test_initiatives_only_share_a_slide_when_they_fit(self):
        from utils.quarterly_planner_helpers import progress_slides
        rows = [{"Parent Link": f"INIT-{g}", "Key": f"K-{g}-{i}", "Summary": "E", "Completion": "0%", "Status": "To Do"}
                for g, size in ((1, 6), (2, 5), (3, 3)) for i in range(size)]
        slides = progress_slides(pd.DataFrame(rows), "T", by_initiative=True)
        # 6+1 rows, then 1.3 gap + 5+1 rows = 14.3 > 13: INIT-2 starts a new slide; INIT-3 fits next to it
        self.assertEqual([[len(b["df"]) for b in slide["blocks"]] for slide in slides], [[6], [5, 3]])

    def test_slides_all_in_one_table(self):
        from utils.quarterly_planner_helpers import progress_slides
        slides = progress_slides(self._df(), "T", "Sub")
        self.assertEqual([len(s["blocks"][0]["df"]) for s in slides], [12, 4])
        self.assertEqual([s["title"] for s in slides], ["T", "T (cont. 2)"])
        self.assertEqual({s["subtitle"] for s in slides}, {"Sub"})
        self.assertEqual({s["blocks"][0]["heading"] for s in slides}, {""})
        self.assertEqual(slides[0]["blocks"][0]["columns"][0][0], "Parent Link")

    def test_pptx_and_pdf_by_initiative(self):
        from pptx import Presentation
        from pypdf import PdfReader
        from utils.quarterly_planner_helpers import build_quarterly_progress_pptx, build_quarterly_progress_slide_pdf
        prs = Presentation(io.BytesIO(build_quarterly_progress_pptx(self._df(), None, "T", "Sub", "", "", "#0B2756", by_initiative=True)))
        self.assertEqual(len(prs.slides), 2)
        second = prs.slides[1]
        texts = [shape.text_frame.text for shape in second.shapes if shape.has_text_frame]
        self.assertIn("Initiative: INIT-2 - Customer", texts)
        self.assertIn("Initiative: No initiative", texts)
        self.assertIn("Progress grouped by initiative", texts)
        self.assertEqual(sum(1 for shape in second.shapes if shape.has_table), 3)
        # The first initiative heading is its own text box, not the slide subtitle
        first_texts = [shape.text_frame.text for shape in prs.slides[0].shapes if shape.has_text_frame]
        self.assertIn("Progress grouped by initiative", first_texts)
        self.assertIn("Initiative: INIT-1 - Platform", first_texts)
        reader = PdfReader(io.BytesIO(build_quarterly_progress_slide_pdf(self._df(), "T", "#0B2756", "Sub", by_initiative=True)))
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("Initiative: No initiative", reader.pages[1].extract_text())
