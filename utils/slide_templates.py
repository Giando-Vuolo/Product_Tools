"""Local slide-template selection and export support."""
import io
import os

import streamlit as st

from utils.quarterly_planner_helpers import (
    find_quarterly_pptx_template, list_quarterly_pptx_templates, _template_chrome,
)


def render_slide_template_selector(config, key):
    templates = list_quarterly_pptx_templates()
    default = find_quarterly_pptx_template()
    if default is not None and default not in templates:
        templates.insert(0, default)
    built_in = "Built-in design"
    options = [built_in] + templates
    selected = config.get("template_path", default) or built_in
    if selected not in options:
        st.warning("The previously selected slide template is no longer available. Choose another template.")
        selected = built_in
    selection = st.selectbox(
        "Slide template", options, index=options.index(selected), key=key,
        format_func=lambda path: os.path.basename(path),
        help="Applies to slide exports and PDF previews. Templates supply slide size, master and layout; "
             "their existing slides are replaced. PDF content is fitted inside the template branding.",
    )
    config["template_path"] = None if selection == built_in else selection
    st.caption(
        "Add .pptx templates to assets/templates/ and refresh this page to see them here. "
        "Create the folder if needed. Templates stay local and are not committed to Git. "
        "For best results, use a 16:9 template with a title-only content layout."
    )
    if not templates:
        st.info("No local slide templates found in assets/templates/. The built-in design is available.")
    return config["template_path"]


def apply_pdf_slide_template(pdf_data, template_path):
    """Fit existing PDF pages into a branded frame, preserving text and hyperlinks."""
    if template_path is None:
        return pdf_data
    if isinstance(pdf_data, io.BytesIO):
        pdf_data = pdf_data.getvalue()
    from pypdf import PdfReader, PdfWriter, Transformation
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.colors import HexColor

    chrome = _template_chrome(template_path)
    width, height = chrome["width"] * 72, chrome["height"] * 72
    if width <= 48 or height <= 100:
        raise ValueError("The selected slide template is too small for the report content.")
    background = io.BytesIO()
    pdf = canvas.Canvas(background, pagesize=(width, height))
    pdf.setFillColor(HexColor("#002D37"))
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    if chrome["logo"]:
        data, left, top, logo_width, logo_height = chrome["logo"]
        pdf.drawImage(ImageReader(io.BytesIO(data)), left * 72, height - (top + logo_height) * 72,
                      logo_width * 72, logo_height * 72, mask="auto")
    for text, left, top, text_width, size, color, right in chrome["texts"]:
        pdf.setFillColor(HexColor(color))
        pdf.setFont("Helvetica", size)
        if right:
            pdf.drawRightString((left + text_width) * 72, height - (top + 0.11) * 72, text)
        else:
            pdf.drawString(left * 72, height - (top + 0.11) * 72, text)
    pdf.save()
    frame_bytes = background.getvalue()
    writer = PdfWriter()
    for source in PdfReader(io.BytesIO(pdf_data)).pages:
        frame = writer.add_page(PdfReader(io.BytesIO(frame_bytes)).pages[0])
        source_writer = PdfWriter()
        source = source_writer.add_page(source)
        source_width, source_height = float(source.mediabox.width), float(source.mediabox.height)
        scale = min((width - 48) / source_width, (height - 100) / source_height)
        x, y = (width - source_width * scale) / 2, 32 + (height - 100 - source_height * scale) / 2
        # Transform the source itself so its link annotations follow the content.
        source.add_transformation(Transformation().scale(scale).translate(x, y))
        for reference in source.get("/Annots", []):
            annotation = reference.get_object()
            if "/Rect" in annotation:
                from pypdf.generic import ArrayObject, FloatObject, NameObject
                annotation[NameObject("/Rect")] = ArrayObject([
                    FloatObject(float(value) * scale + (x if index % 2 == 0 else y))
                    for index, value in enumerate(annotation["/Rect"])
                ])
        source.mediabox.lower_left = (0, 0)
        source.mediabox.upper_right = (width, height)
        source.cropbox.lower_left = (0, 0)
        source.cropbox.upper_right = (width, height)
        frame.merge_page(source)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()

