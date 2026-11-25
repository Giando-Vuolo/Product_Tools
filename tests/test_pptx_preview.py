import io
import os
import tempfile
import unittest

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.util import Inches, Pt

from tests.test_roadmap_export import _make_template, _progress
from utils import pptx_preview as pv
from utils import roadmap_export as rx
from utils import roadmap_labels as rl

SVG = "{http://www.w3.org/2000/svg}"


def _deck(build):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])   # blank
    build(slide)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _parse(svg):
    return etree.fromstring(svg.encode())


def _texts(root):
    return ["".join(t.itertext()) for t in root.iter(f"{SVG}text")]


class ShapeTests(unittest.TestCase):
    def test_size_shapes_and_colours(self):
        def build(slide):
            rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(1), Inches(2), Inches(1))
            rect.fill.solid()
            rect.fill.fore_color.rgb = RGBColor(0x12, 0x34, 0x56)
            oval = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(4), Inches(1), Inches(1), Inches(1))
            oval.fill.solid()
            oval.fill.fore_color.theme_color = MSO_THEME_COLOR.ACCENT_1
            oval.fill.fore_color.brightness = -0.5
            slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6), Inches(1), Inches(2), Inches(1))
        root = _parse(pv.slide_to_svg(_deck(build)))
        self.assertEqual(root.get("viewBox"), "0 0 960 720")    # 10 x 7.5 in default deck
        fills = [r.get("fill") for r in root.iter(f"{SVG}rect")]
        self.assertIn("#123456", fills)
        self.assertEqual(fills[0], "#FFFFFF")                    # white background first
        ellipse = next(root.iter(f"{SVG}ellipse"))
        self.assertEqual((ellipse.get("cx"), ellipse.get("rx")), ("432", "48"))
        self.assertNotEqual(ellipse.get("fill"), "none")          # theme colour with lumMod resolved
        self.assertTrue(any(r.get("rx") for r in root.iter(f"{SVG}rect")))   # rounded rectangle

    def test_text_wraps_and_keeps_run_style(self):
        def build(slide):
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(2))
            box.text_frame.word_wrap = True
            run = box.text_frame.paragraphs[0].add_run()
            run.text = "A rather long title that cannot fit on one line"
            run.font.size, run.font.bold = Pt(14), True
            run.font.color.rgb = RGBColor(0xC2, 0xFE, 0x06)
            box.text_frame.add_paragraph().text = "a & <b>"
        root = _parse(pv.slide_to_svg(_deck(build)))
        texts = _texts(root)
        self.assertGreater(len(texts), 2)
        self.assertEqual(" ".join(texts[:-1]), "A rather long title that cannot fit on one line")
        self.assertEqual(texts[-1], "a & <b>")
        span = next(root.iter(f"{SVG}tspan"))
        self.assertEqual((span.get("fill"), span.get("font-weight")), ("#C2FE06", "bold"))
        self.assertEqual(span.get("font-size"), "18.67")          # 14 pt in px

    def test_pie_is_an_arc_and_hidden_shapes_are_skipped(self):
        def build(slide):
            pie = slide.shapes.add_shape(MSO_SHAPE.PIE, Inches(1), Inches(1), Inches(1), Inches(1))
            pie.adjustments[0], pie.adjustments[1] = 162, 0   # 270° to 0° (python-pptx: raw / 100000): 12 to 3 o'clock
            hidden = slide.shapes.add_textbox(Inches(3), Inches(1), Inches(1), Inches(1))
            hidden.text_frame.text = "secret"
            hidden._element.nvSpPr.cNvPr.set("hidden", "1")
        svg = pv.slide_to_svg(_deck(build))
        path = next(_parse(svg).iter(f"{SVG}path")).get("d")
        self.assertTrue(path.startswith("M144 144 L144 96 A48 48 0 0 1 192 144"), path)
        self.assertNotIn("secret", svg)

    def test_missing_slide(self):
        with self.assertRaises(IndexError):
            pv.slide_to_svg(_deck(lambda s: None), slide_index=3)


class RoadmapSlideTests(unittest.TestCase):
    def test_exported_slide_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = os.path.join(tmp, "Template QP.pptx")
            _make_template(template)
            config = rl.normalize_config(rl.DEFAULT_CONFIG)
            data = rx.build_roadmap_pptx(config, _progress(config), template, title="My title")
        root = _parse(pv.slide_to_svg(data))
        text = " ".join(_texts(root))
        self.assertIn("My title", text)
        for group in config["groups"]:
            self.assertIn(group["topics"][0]["name"].split()[0], text)
        self.assertTrue(list(root.iter(f"{SVG}path")))            # partial Harvey balls drawn as pies

    @unittest.skipUnless(rx.find_template(), "local Template QP.pptx not available")
    def test_real_template_preview(self):
        config = rl.normalize_config(rl.DEFAULT_CONFIG)
        root = _parse(pv.slide_to_svg(rx.build_roadmap_pptx(config, _progress(config))))
        self.assertEqual(root.get("viewBox"), "0 0 1280 720")
        hrefs = [i.get("href", "")[:30] for i in root.iter(f"{SVG}image")]
        self.assertTrue(any(h.startswith("data:image/svg+xml") for h in hrefs))   # group icons
        self.assertTrue(any(h.startswith("data:image/png") for h in hrefs))       # logo


if __name__ == "__main__":
    unittest.main()
