import io

import pandas as pd
import pytest
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfReader
from utils.slide_templates import apply_pdf_slide_template
from utils.quarterly_planner_helpers import build_quarterly_progress_slide_pdf


@pytest.fixture
def template_path(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = "Template sample slide"
    path = tmp_path / "Template.pptx"
    prs.save(path)
    return str(path)


def test_pdf_frame_keeps_content_and_jira_links(template_path):
    df = pd.DataFrame([{"Key": "EPIC-1", "Summary": "A test epic", "Completion": "50%"}])
    pdf = build_quarterly_progress_slide_pdf(df, "Test", "#123456", template_path=None,
                                            jira_server="https://jira.example.test")
    assert apply_pdf_slide_template(pdf, None) is pdf
    reader = PdfReader(io.BytesIO(apply_pdf_slide_template(io.BytesIO(pdf), template_path)))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(13.333 * 72, abs=0.001)
    assert "A test epic" in page.extract_text()
    annotations = [a.get_object() for a in page["/Annots"]]
    assert annotations[0]["/A"]["/URI"] == "https://jira.example.test/browse/EPIC-1"
    assert all(0 <= float(value) <= float(page.mediabox.width) for value in annotations[0]["/Rect"][::2])


def test_template_selector_uses_local_files_and_built_in(template_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from utils import slide_templates

    monkeypatch.setattr(slide_templates, "list_quarterly_pptx_templates", lambda: [template_path])
    monkeypatch.setattr(slide_templates, "find_quarterly_pptx_template", lambda: template_path)
    at = AppTest.from_string("""
import streamlit as st
from utils.slide_templates import render_slide_template_selector
config = st.session_state.setdefault("config", {})
render_slide_template_selector(config, "test_selector")
""").run()
    assert not at.exception
    assert at.session_state["config"]["template_path"] == template_path
    at.selectbox[0].select("Built-in design").run()
    assert at.session_state["config"]["template_path"] is None
    assert any("assets/templates/" in caption.value for caption in at.caption)
    monkeypatch.setattr(slide_templates, "list_quarterly_pptx_templates", lambda: [])
    monkeypatch.setattr(slide_templates, "find_quarterly_pptx_template", lambda: None)
    at.run()
    assert not at.exception
    assert any("No local slide templates" in message.value for message in at.info)

