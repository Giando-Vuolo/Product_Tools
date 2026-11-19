import io
import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pptx import Presentation
from pptx.util import Inches
from streamlit.testing.v1 import AppTest

from utils import release_calendar as rc
from utils import release_overview as ro

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "tests/fixtures/release_calendar/sample.ics").read_text(encoding="utf-8")
TODAY = date(2026, 11, 19)


def _rows():
    return pd.DataFrame([
        {"Version": "33.0.0", "Prod Deploy": date(2026, 8, 20), "Kind": ro.MAJOR, "Box": True,
         "Incidents": ro.MINOR_INCIDENTS, "Highlights": "Multi Context\nNew announcements system"},
        {"Version": "33.1.0", "Prod Deploy": date(2026, 8, 30), "Kind": ro.MINOR, "Box": False,
         "Incidents": "", "Highlights": ""},
        {"Version": "34.1.1", "Prod Deploy": date(2026, 10, 22), "Kind": ro.HOTFIX, "Box": False,
         "Incidents": "", "Highlights": ""},
        {"Version": "35.0.0", "Prod Deploy": date(2026, 11, 25), "Kind": ro.MAJOR, "Box": True,
         "Incidents": "", "Highlights": "Improve virus detection"},
    ], columns=ro.OVERVIEW_COLUMNS)


def _texts(elements):
    return ["\n".join("".join(t for t, _ in p["runs"]) for p in e["paragraphs"]) for e in elements if e["kind"] == "text"]


class HelperTests(unittest.TestCase):
    def test_release_kind(self):
        self.assertEqual(ro.release_kind("33.0.0"), ro.MAJOR)
        self.assertEqual(ro.release_kind("33.1.0"), ro.MINOR)
        self.assertEqual(ro.release_kind("34.1.1"), ro.HOTFIX)
        self.assertEqual(ro.release_kind("34.0.2"), ro.HOTFIX)

    def test_highlights_from_description(self):
        text = "* Spring Boot\n- HTTPS\n\n1. Reports\n* Spring Boot\n" + "\n".join(f"x{i}" for i in range(9))
        self.assertEqual(ro.highlights_from_description(text), ["Spring Boot", "HTTPS", "Reports", "x0", "x1", "x2"])

    def test_month_range(self):
        lo, hi = ro.month_range(date(2026, 8, 19), date(2026, 12, 3))
        self.assertEqual((lo, hi), (pd.Timestamp("2026-08-01"), pd.Timestamp("2027-01-01")))

    def test_overview_rows_from_calendar(self):
        events = rc.events_dataframe(rc.parse_ics(SAMPLE))
        releases = rc.releases_dataframe(events, TODAY)
        rows = ro.overview_rows(releases, events, date(2026, 10, 1), date(2026, 12, 31), TODAY)
        self.assertEqual(rows["Version"].tolist(), ["35.0.0", "36.0.0"])
        self.assertEqual(rows["Kind"].tolist(), [ro.MAJOR, ro.MAJOR])
        self.assertEqual(rows["Box"].tolist(), [True, True])
        self.assertEqual(rows.loc[1, "Highlights"], "Spring Boot\nHTTPS, maybe?\nFunctional: multicountry")
        self.assertTrue(ro.overview_rows(releases.iloc[0:0], events, date(2026, 10, 1), date(2026, 12, 31)).empty)

    def test_box_defaults_to_majors_and_next_release(self):
        releases = pd.DataFrame({"Version": ["34.1.0", "34.1.1", "35.0.0", "35.1.0"],
                                 "Prod Deploy": pd.to_datetime(["2026-10-06", "2026-11-20", "2026-12-01", "2026-12-10"])})
        rows = ro.overview_rows(releases, pd.DataFrame(columns=rc.EVENT_COLUMNS), date(2026, 10, 1),
                                date(2026, 12, 31), TODAY)
        self.assertEqual(rows["Kind"].tolist(), [ro.MINOR, ro.HOTFIX, ro.MAJOR, ro.MINOR])
        self.assertEqual(rows["Box"].tolist(), [False, True, True, False])
        # Traffic light: green for deployed releases, none for upcoming ones
        self.assertEqual(rows["Incidents"].tolist(), [ro.NO_INCIDENTS, "", "", ""])

    def test_default_headline_and_runs(self):
        text = ro.default_headline(_rows(), TODAY)
        self.assertEqual(text, "R33.0.0 was released.\nR35.0.0 is planned for **25 November**.")
        runs = ro.highlight_runs(text.splitlines()[1])
        self.assertEqual(runs, [("R35.0.0", ro.LIME), (" is planned for ", ro.WHITE), ("25 November", ro.LIME),
                                (".", ro.WHITE)])

    def test_spread_keeps_boxes_apart_and_inside(self):
        lefts = ro._spread([12.5, 12.6, 12.7], 2.0)
        self.assertLessEqual(lefts[-1] + 2.0, ro.CONTENT_RIGHT + 1e-9)
        self.assertTrue(all(b - a >= 2.0 + ro.GAP - 1e-9 for a, b in zip(lefts, lefts[1:])))


class PlanTests(unittest.TestCase):
    def setUp(self):
        events = pd.DataFrame([{"Date": date(2026, 9, 19), "Text": "Major recall campaign\n- rolled out"},
                               {"Date": date(2027, 3, 1), "Text": "Outside the range"},
                               {"Date": None, "Text": "No date"}])
        self.elements = ro.plan_overview(_rows(), events, date(2026, 8, 1), date(2026, 12, 31),
                                         "ReCall2 | Overview", "R33.0.0 released.", TODAY)

    def test_content(self):
        texts = _texts(self.elements)
        for expected in ("ReCall2 | Overview", "August", "December", "R33.0.0 (20 August)\nMulti Context\nNew announcements system",
                         "R35.0.0 (25 November)\nImprove virus detection", "R 33.0.0", "R33.1.0", "R34.1.1",
                         "Major recall campaign\nrolled out",
                         ro.MAJOR, ro.UPCOMING, ro.REMARKABLE, ro.MINOR_INCIDENTS):
            self.assertIn(expected, texts)
        self.assertNotIn("Outside the range", texts)
        self.assertNotIn("No date", texts)

    def test_colours_and_bounds(self):
        diamonds = [e for e in self.elements if e["kind"] == "diamond"]
        fills = [d["fill"] for d in diamonds[:4]]
        self.assertEqual(fills, [ro.COLORS[ro.MAJOR], ro.COLORS[ro.MINOR], ro.COLORS[ro.HOTFIX], ro.COLORS[ro.UPCOMING]])
        rects = [e for e in self.elements if e["kind"] == "rect"]
        self.assertEqual([r["line"] for r in rects[:2]], [ro.TEAL, ro.COLORS[ro.UPCOMING]])
        for e in self.elements:
            if e["kind"] in ("rect", "text") and not e.get("rotation"):
                self.assertGreaterEqual(e["x"], 0)
                self.assertLessEqual(e["x"] + e["w"], ro.SLIDE_W)
        incident_dots = [e for e in self.elements if e["kind"] == "circle" and e["fill"] == ro.INCIDENT_COLORS[ro.MINOR_INCIDENTS]]
        self.assertEqual(len(incident_dots), 2)  # in the R33.0.0 box and in the legend

    def test_traffic_light_only_for_deployed_releases(self):
        rows = _rows().assign(Incidents=[ro.MAJOR_INCIDENTS, "", "", ro.MAJOR_INCIDENTS])  # 35.0.0 is upcoming
        els = ro.plan_overview(rows, None, date(2026, 8, 1), date(2026, 12, 31), "T", "", TODAY)
        red = [e for e in els if e["kind"] == "circle" and e["fill"] == ro.INCIDENT_COLORS[ro.MAJOR_INCIDENTS]]
        self.assertEqual(len(red), 2)  # the R33.0.0 box and the legend, not the upcoming R35.0.0 box
        only_upcoming = _rows().assign(Incidents=["", "", "", ro.MAJOR_INCIDENTS])
        texts = _texts(ro.plan_overview(only_upcoming, None, date(2026, 8, 1), date(2026, 12, 31), "T", "", TODAY))
        self.assertNotIn(ro.MAJOR_INCIDENTS, texts)  # no traffic light drawn, so no traffic light legend

    def test_no_incident_legend_without_incidents(self):
        rows = _rows().assign(Incidents="")
        texts = _texts(ro.plan_overview(rows, None, date(2026, 8, 1), date(2026, 12, 31), "T", "", TODAY))
        self.assertNotIn(ro.NO_INCIDENTS, texts)

    def test_pptx_built_in(self):
        prs = Presentation(io.BytesIO(ro.build_overview_pptx(self.elements)))
        self.assertEqual(len(prs.slides), 1)
        texts = [s.text_frame.text for s in prs.slides[0].shapes if s.has_text_frame]
        self.assertIn("R33.0.0 (20 August)\nMulti Context\nNew announcements system", texts)
        self.assertIn(320.0, [s.rotation for s in prs.slides[0].shapes if s.has_text_frame and s.text_frame.text == "R 33.0.0"])

    def test_pptx_template_replaces_its_slides(self):
        import tempfile
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = "Old slide"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Template.pptx")
            prs.save(path)
            out = Presentation(io.BytesIO(ro.build_overview_pptx(self.elements, path)))
        self.assertEqual(len(out.slides), 1)
        texts = [s.text_frame.text for s in out.slides[0].shapes if s.has_text_frame]
        self.assertNotIn("Old slide", texts)
        self.assertIn("ReCall2 | Overview", texts)

    def test_svg(self):
        svg = ro.overview_svg(self.elements)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("R33.0.0 (20 August)", svg)
        self.assertIn("rotate(-40.0", svg)
        escaped = ro.overview_svg(ro.plan_overview(None, None, date(2026, 8, 1), date(2026, 8, 31), "<b>&</b>"))
        self.assertIn("&lt;b&gt;&amp;&lt;/b&gt;", escaped)


class PageTests(unittest.TestCase):
    def test_overview_tab_builds_download(self):
        env = {rc.ENV_ICS_URL: "https://x/overview.ics", "CONFLUENCE_API_TOKEN": "t", "PROJECT_NAME": "ReCall2"}
        for p in (patch.dict(os.environ, env, clear=True),
                  patch("dotenv.load_dotenv", lambda *a, **k: False),
                  patch("requests.sessions.Session.request", side_effect=AssertionError("real network")),
                  patch("utils.release_calendar.fetch_ics", return_value=SAMPLE),
                  patch("utils.slide_templates.list_quarterly_pptx_templates", return_value=[]),
                  patch("utils.slide_templates.find_quarterly_pptx_template", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(str(ROOT / "tools/8_Release_Calendar.py"), default_timeout=30).run()
        at.button(key="rc_load").click().run()
        at.date_input(key="rc_ov_range").set_value((date(2026, 10, 1), date(2027, 1, 31))).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.text_input(key="rc_ov_title").value, "ReCall2 | Overview on current releases")
        self.assertIn("R36.0.0", at.text_area(key="rc_ov_headline_202610_202701").value)
        self.assertTrue(any(k.startswith("rc_ov_hl_") for k in (t.key for t in at.text_area)))
