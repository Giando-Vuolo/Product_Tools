import io
import os
import tempfile
import unittest
from unittest import mock

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from utils import roadmap_export as rx
from utils import roadmap_labels as rl

COLORS = ["C2FE06", "008C82", "19C9FF", "C882BE"]


def _make_template(path):
    """Minimal stand-in for Template QP: 3 slides, the third one with the KPI design."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    layout = prs.slide_layouts[5]  # Title Only
    prs.slides.add_slide(layout).shapes.title.text = "Cover"
    prs.slides.add_slide(layout).shapes.title.text = "Overview"
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = "ReCall2 | Project KPIs by initiative"
    note = slide.shapes.add_textbox(Inches(8.7), Inches(0.74), Inches(4), Inches(0.3))
    note.text_frame.text = "Mock data for illustration only"
    banner = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.42), Inches(1.65), Inches(12.45), Inches(0.27))
    banner.text_frame.text = "Product Vision"
    for i, color in enumerate(COLORS):
        left = Inches(0.45 + i * 3.13)
        slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(2.08), Inches(3.03), Inches(4.71))
        head = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + Inches(0.68), Inches(2.11),
                                      Inches(2.22), Inches(0.52))
        head.text_frame.text = f"Group {i}"
        for row in range(2):
            top = Inches(2.8 + row * 0.7)
            slide.shapes.add_shape(MSO_SHAPE.OVAL, left + Inches(0.13), top, Inches(0.33), Inches(0.33))
            pie = slide.shapes.add_shape(MSO_SHAPE.PIE, left + Inches(0.13), top, Inches(0.33), Inches(0.33))
            pie.fill.solid()
            pie.fill.fore_color.rgb = RGBColor.from_string(color)
            box = slide.shapes.add_textbox(left + Inches(0.6), top - Inches(0.02), Inches(2.19), Inches(0.57))
            box.text_frame.text = "Example item"
            run = box.text_frame.paragraphs[0].runs[0]
            run.font.color.rgb = RGBColor.from_string(color)
            run.font.size = Pt(11)
            box.text_frame.add_paragraph().text = "Example note"
    prs.save(path)


def _progress(config, value=50):
    return {t["label"]: {"epics": [{"key": "E-1"}], "tickets": [{}, {}], "progress": value}
            for g in config["groups"] for t in g["topics"]}


def _texts(slide):
    return [s.text_frame.text for s in slide.shapes if s.has_text_frame]


def _shapes(slide, prst):
    return [s for s in slide.shapes if rx._geom(s) == prst]


class _TemplateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.template = os.path.join(self.tmp.name, "Template QP.pptx")
        _make_template(self.template)
        self.config = rl.normalize_config(rl.DEFAULT_CONFIG)

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, config=None, progress=None, **kwargs):
        config = config or self.config
        data = rx.build_roadmap_pptx(config, _progress(config) if progress is None else progress,
                                     self.template, **kwargs)
        return Presentation(io.BytesIO(data))


class SyntheticTemplateTests(_TemplateCase):
    def test_keeps_only_the_kpi_slide_and_fills_texts(self):
        prs = self._build(title="My title", banner="Vision 2027")
        self.assertEqual(len(prs.slides), 1)
        texts = _texts(prs.slides[0])
        self.assertIn("My title", texts)
        self.assertIn("Vision 2027", texts)
        self.assertFalse(any("Mock data" in t or "Jira data as of" in t for t in texts))
        self.assertNotIn("Example item\nExample note", texts)
        for group in self.config["groups"]:
            self.assertIn(group["name"], texts)

    def test_one_ball_and_text_per_topic(self):
        prs = self._build()
        slide = prs.slides[0]
        n_topics = sum(len(g["topics"]) for g in self.config["groups"])
        self.assertEqual(len(_shapes(slide, "ellipse")), n_topics)
        self.assertEqual(len(_shapes(slide, "pie")), n_topics)
        self.assertIn("China", _texts(slide))
        self.assertEqual(_texts(slide).count("50%"), n_topics)

    def test_pie_angle_follows_progress(self):
        prs = self._build(progress=_progress(self.config, 25))
        pie = _shapes(prs.slides[0], "pie")[0]
        adj = {gd.get("name"): gd.get("fmla") for gd in pie._element.iter("{%s}gd" % rx._NS["a"])}
        self.assertEqual(adj["adj1"], f"val {rx.TWELVE_O_CLOCK}")
        self.assertEqual(adj["adj2"], f"val {(rx.TWELVE_O_CLOCK + rx.FULL_CIRCLE // 4) % rx.FULL_CIRCLE}")

    def test_full_and_empty_and_missing_progress_have_no_pie(self):
        for value in (100, 0, None):
            prs = self._build(progress=_progress(self.config, value))
            self.assertEqual(len(_shapes(prs.slides[0], "pie")), 0, value)
        prs = self._build(progress={})
        self.assertIn("–", _texts(prs.slides[0]))

    def test_column_colour_is_kept(self):
        prs = self._build()
        china = next(s for s in prs.slides[0].shapes if s.has_text_frame and s.text_frame.text.startswith("China"))
        self.assertEqual(str(china.text_frame.paragraphs[0].runs[0].font.color.rgb), COLORS[3])

    def test_fewer_and_more_groups_than_columns(self):
        for n in (2, 6):
            groups = [{"name": f"G{i}", "label": f"RC2_G{i}_X",
                       "topics": [{"name": f"T{i}", "label": f"RC2_G{i}_T1_X"}]} for i in range(n)]
            config = {"groups": groups}
            slide = self._build(config=config).slides[0]
            columns = [s for s in _shapes(slide, "roundRect") if s.height > Inches(3)]
            self.assertEqual(len(columns), n)
            lefts = sorted(c.left for c in columns)
            self.assertEqual(len(set(lefts)), n)
            self.assertLessEqual(lefts[-1] + columns[0].width, Inches(0.45 + 3 * 3.13 + 3.03) + 2)
            self.assertEqual(len(_shapes(slide, "ellipse")), n)

    def test_unique_shape_ids(self):
        slide = self._build().slides[0]
        ids = [s.shape_id for s in slide.shapes]
        self.assertEqual(len(ids), len(set(ids)))

    def test_missing_template_raises(self):
        with mock.patch.object(rx, "find_template", return_value=None), self.assertRaises(rx.TemplateError):
            rx.build_roadmap_pptx(self.config, {})


class TopicElementTests(_TemplateCase):
    def _config(self, **china):
        config = rl.normalize_config(rl.DEFAULT_CONFIG)
        config["groups"][3]["topics"][0].update(china)  # China: first topic of the last column
        return config

    def _shape(self, slide, text):
        return next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text == text)

    def _fill(self, shape):
        return shape._element.find(".//p:spPr/a:solidFill/a:srgbClr", rx._NS).get("val")

    def _china(self, slide):
        """China's ball, percentage, title box (the first ball of the last column)."""
        balls = sorted((s for s in _shapes(slide, "ellipse")), key=lambda s: (s.left, s.top))
        ball = balls[-2]
        title = next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text.startswith("China"))
        return ball, title

    def test_layout_ball_percentage_box_and_text(self):
        config = self._config(due="2027-01-01", status="on_track", subtitle="Phase 1 deployed to production")
        progress = _progress(config, 89)
        slide = self._build(config=config, progress=progress).slides[0]
        ball, title = self._china(slide)
        pct = next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text == "89%"
                   and abs(s.left + s.width / 2 - (ball.left + ball.width / 2)) < Inches(0.02)
                   and s.top >= ball.top + ball.height and s.top - (ball.top + ball.height) < Inches(0.05))
        box = next(s for s in _shapes(slide, "roundRect") if s.has_text_frame and s.text_frame.text == "01.01.27"
                   and s.top >= pct.top + pct.height)
        self.assertLess(abs(box.left + box.width / 2 - (ball.left + ball.width / 2)), Inches(0.02))
        self.assertEqual(self._fill(box), "AEE1B8")
        self.assertEqual(str(box.text_frame.paragraphs[0].runs[0].font.color.rgb), rl.DUE_TEXT_COLOR.lstrip("#"))
        self.assertGreater(title.left, ball.left + ball.width)
        self.assertEqual(title.text_frame.text, "China\nPhase 1 deployed to production")
        column = [s for s in _shapes(slide, "roundRect") if s.height > Inches(3)][-1]
        self.assertGreaterEqual(box.left, column.left)

    def test_box_colour_follows_configured_status_not_progress(self):
        for status, color in [("late", "F2A3A2"), ("at_risk", "F9DB99"), ("on_track", "AEE1B8"),
                              ("", rl.NO_STATUS_COLOR.lstrip("#"))]:
            config = self._config(due="2020-01-01", status=status)
            slide = self._build(config=config, progress=_progress(config, 0)).slides[0]
            self.assertEqual(self._fill(self._shape(slide, "01.01.20")), color, status or "no status")

    def test_no_box_without_due_date_and_no_subtitle_paragraph(self):
        slide = self._build().slides[0]
        self.assertFalse([s for s in _shapes(slide, "roundRect") if s.has_text_frame
                          and s.text_frame.text.count(".") == 2])
        _, title = self._china(slide)
        self.assertEqual(title.text_frame.text, "China")
        self.assertNotIn("Due date:", _texts(slide))

    def test_legend_has_one_ball_per_status(self):
        slide = self._build(config=self._config(due="2026-11-01", status="late")).slides[0]
        self.assertIn("Due date:", _texts(slide))
        balls = [s for s in _shapes(slide, "ellipse") if s.top > Inches(6.8)]
        self.assertEqual(sorted(self._fill(s) for s in balls), sorted(["AEE1B8", "F9DB99", "F2A3A2"]))
        self.assertTrue(all(abs(b.width - b.height) < 2 for b in balls))
        for label, _ in rl.DUE_STATUS.values():
            self.assertIn(label, _texts(slide))

    def test_six_topics_do_not_overlap_and_fit_in_column(self):
        config = rl.normalize_config(rl.DEFAULT_CONFIG)
        for t in config["groups"][1]["topics"]:  # Architecture Roadmap: 6 topics
            t.update(due="2027-01-01", status="late")
        slide = self._build(config=config).slides[0]
        column = sorted((s for s in _shapes(slide, "roundRect") if s.height > Inches(3)), key=lambda s: s.left)[1]
        boxes = sorted((s for s in _shapes(slide, "roundRect") if s.has_text_frame
                        and s.text_frame.text == "01.01.27"), key=lambda s: s.top)
        balls = sorted((s for s in _shapes(slide, "ellipse")
                        if column.left <= s.left < column.left + column.width), key=lambda s: s.top)
        self.assertEqual(len(boxes), 6)
        for box, next_ball in zip(boxes, balls[1:]):
            self.assertLessEqual(box.top + box.height, next_ball.top)
        self.assertLessEqual(boxes[-1].top + boxes[-1].height, column.top + column.height)

    def test_due_dates_do_not_move_the_columns(self):
        def lefts(slide):
            return sorted(c.left for c in _shapes(slide, "roundRect") if c.height > Inches(3))
        plain = lefts(self._build().slides[0])
        config = rl.normalize_config(rl.DEFAULT_CONFIG)
        for g in config["groups"]:
            for t in g["topics"]:
                t.update(due="2026-11-01", status="late")
        self.assertEqual(lefts(self._build(config=config).slides[0]), plain)


@unittest.skipUnless(rx.find_template(), "local Template QP.pptx not available")
class RealTemplateTests(unittest.TestCase):
    def test_real_template_builds(self):
        config = rl.normalize_config(rl.DEFAULT_CONFIG)
        prs = Presentation(io.BytesIO(rx.build_roadmap_pptx(config, _progress(config, 40))))
        self.assertEqual(len(prs.slides), 1)
        n_topics = sum(len(g["topics"]) for g in config["groups"])
        self.assertEqual(len(_shapes(prs.slides[0], "pie")), n_topics)


if __name__ == "__main__":
    unittest.main()
