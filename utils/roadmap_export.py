"""Roadmap Reporting: PowerPoint export based on the "Project KPIs by initiative" slide of Template QP.

The template slide is kept as it is (layout, banner, columns, group headers and icons) and only
its example items are replaced: for every Topic one Harvey ball (the template's own ellipse + pie
shapes, so colours and sizes match) and one text box (name in the column's accent colour, then
progress, tickets and Epics). Columns follow the configured group labels; when there are not
exactly as many groups as template columns the columns are resized and repeated or removed.
"""
import copy
import io
from datetime import date

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from utils.pptx_preview import text_width_pt
from utils.quarterly_planner_helpers import find_quarterly_pptx_template
from utils.roadmap_labels import DUE_STATUS, DUE_TEXT_COLOR, due_box_color

SLIDE_TITLE_HINT = "project kpis by initiative"
FULL_CIRCLE = 21600000          # DrawingML angles: 60000ths of a degree
TWELVE_O_CLOCK = 16200000
DEFAULT_TITLE = "ReCall2 | Project KPIs by initiative"
DEFAULT_SUBTITLE = ("Progress per topic from the tickets under its Epics: closed & released 100%, "
                    "closed 90%, in progress 50%, to do 0%.")
DEFAULT_BANNER = "Product Vision Q3/2026 – Q4/2027"
MIN_HEADING_PT = 10               # title and subtitle shrink down to this size to stay on one line

_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
       "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


class TemplateError(Exception):
    pass


def find_template():
    return find_quarterly_pptx_template()


def _find_kpi_slide(prs):
    for slide in prs.slides:
        title = slide.shapes.title
        if title is not None and SLIDE_TITLE_HINT in title.text_frame.text.lower():
            return slide
    if len(prs.slides) >= 3:
        return prs.slides[2]
    raise TemplateError("The template has no 'Project KPIs by initiative' slide.")


def _keep_only(prs, keep):
    for slide_id in list(prs.slides._sldIdLst):
        if prs.slides.get(int(slide_id.id)) is not keep:
            prs.part.drop_rel(slide_id.rId)
            prs.slides._sldIdLst.remove(slide_id)


def _geom(shape):
    el = shape._element.find(".//a:prstGeom", _NS)
    return el.get("prst") if el is not None else None


def _set_text(shape, text):
    """Replace the text of a shape, keeping the formatting of its first run."""
    tf = shape.text_frame
    first_para = tf.paragraphs[0]
    runs = first_para.runs
    if runs:
        runs[0].text = text
        for extra in runs[1:]:
            extra._r.getparent().remove(extra._r)
    else:
        first_para.add_run().text = text
    for para in tf.paragraphs[1:]:
        para._p.getparent().remove(para._p)


def _inherited_run_attr(shape, attr):
    """attr (sz, b) of the first run of a placeholder, else from its layout and master styles."""
    rpr = shape._element.find(".//a:p/a:r/a:rPr", _NS)
    if rpr is not None and rpr.get(attr) is not None:
        return rpr.get(attr)
    sources = []
    try:
        layout_ph = shape._base_placeholder  # the layout placeholder it inherits from
    except AttributeError:
        layout_ph = None
    for ph in (layout_ph, getattr(layout_ph, "_base_placeholder", None) if layout_ph is not None else None):
        if ph is not None:
            sources.append(ph._element.find(".//a:lstStyle/a:lvl1pPr/a:defRPr", _NS))
    master = shape.part.slide_layout.slide_master.element
    style = "titleStyle" if shape.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE) \
        else "bodyStyle"
    sources.append(master.find(f".//p:txStyles/p:{style}/a:lvl1pPr/a:defRPr", _NS))
    for src in sources:
        if src is not None and src.get(attr) is not None:
            return src.get(attr)
    return None


def _fit_one_line(shape, min_pt=MIN_HEADING_PT):
    """Shrink the font of a one-line placeholder (title, subtitle) until its text fits on one line."""
    text = shape.text_frame.text
    size = int(_inherited_run_attr(shape, "sz") or 1800) / 100
    bold = _inherited_run_attr(shape, "b") in ("1", "true")
    body = shape._element.find(".//a:bodyPr", _NS)
    insets = sum(int(body.get(k, 91440)) if body is not None else 91440 for k in ("lIns", "rIns"))
    width_pt = (shape.width - insets) / 12700 / WIDTH_SAFETY
    needed = text_width_pt(text, size, bold)
    if not text or needed <= width_pt:
        return
    new_size = max(min_pt, int(size * width_pt / needed * 2) / 2)   # half-point steps
    for run in shape.text_frame.paragraphs[0].runs:
        run.font.size = Pt(new_size)


def _move(el, left=None, top=None, width=None, height=None):
    off = el.find(".//a:xfrm/a:off", _NS)
    ext = el.find(".//a:xfrm/a:ext", _NS)
    if left is not None:
        off.set("x", str(int(left)))
    if top is not None:
        off.set("y", str(int(top)))
    if width is not None:
        ext.set("cx", str(int(width)))
    if height is not None:
        ext.set("cy", str(int(height)))


def _classify(slide):
    """Template parts of the slide, found by geometry so renamed shapes still work."""
    parts = {"banner": None, "columns": [], "headers": [], "icons": [], "items": [], "note": None}
    for shape in slide.shapes:
        if shape.is_placeholder:
            continue
        top, height, width = shape.top or 0, shape.height or 0, shape.width or 0
        if shape.shape_type == MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT:
            parts["items"].append(shape)  # think-cell data of the example items
        elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            parts["icons"].append(shape)
        elif _geom(shape) == "roundRect" and width > Inches(10):
            parts["banner"] = shape
        elif _geom(shape) == "roundRect" and height > Inches(3):
            parts["columns"].append(shape)
        elif _geom(shape) == "roundRect" and shape.has_text_frame and shape.text_frame.text.strip() \
                and height < Inches(1):
            parts["headers"].append(shape)
        elif shape.has_text_frame and top < Inches(1.5):
            parts["note"] = shape
        elif top >= Inches(2.5):
            parts["items"].append(shape)
    parts["columns"].sort(key=lambda s: s.left)
    parts["headers"].sort(key=lambda s: s.left)
    if not parts["columns"] or len(parts["columns"]) != len(parts["headers"]):
        raise TemplateError("The KPI slide of the template does not have one header per column.")
    return parts


def _column_samples(parts):
    """Per template column: (ellipse, pie, text box) elements of its first example item."""
    samples = []
    for col in parts["columns"]:
        inside = [s for s in parts["items"]
                  if s.shape_type != MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT
                  and col.left <= s.left < col.left + col.width]
        inside.sort(key=lambda s: (s.top, s.left))
        ellipse = next((s for s in inside if _geom(s) == "ellipse"), None)
        pie = next((s for s in inside if _geom(s) == "pie"), None)
        text = next((s for s in inside if s.has_text_frame and s.text_frame.text.strip()), None)
        if ellipse is None or pie is None or text is None:
            raise TemplateError("A column of the KPI slide has no example item to copy the style from.")
        samples.append({"ellipse": copy.deepcopy(ellipse._element), "pie": copy.deepcopy(pie._element),
                        "text": copy.deepcopy(text._element), "ball_top": ellipse.top, "ball_w": ellipse.width,
                        "ball_dx": ellipse.left - col.left, "text_dx": text.left - col.left,
                        "text_right_margin": col.left + col.width - (text.left + text.width),
                        "text_dy": text.top - ellipse.top})
    return samples


def _icons_of(header, icons):
    """Pictures sitting just left of a header (the group icon)."""
    return [p for p in icons if abs(p.top - header.top) < Inches(0.3) and 0 <= header.left - p.left < Inches(1)]


def _add_element(slide, element):
    """Append a copied shape element with a fresh id."""
    el = copy.deepcopy(element)
    c_nv_pr = el.find(".//p:cNvPr", _NS)
    c_nv_pr.set("id", str(slide.shapes._next_shape_id))
    for ext in c_nv_pr.findall("a:extLst", _NS):
        c_nv_pr.remove(ext)
    slide.shapes._spTree.append(el)
    return el


def _set_pie(el, pct):
    """Set the pie angles: from 12 o'clock, clockwise, pct of the full circle."""
    av_lst = el.find(".//a:prstGeom/a:avLst", _NS)
    if av_lst is None:
        av_lst = etree.SubElement(el.find(".//a:prstGeom", _NS), f"{{{_NS['a']}}}avLst")
    end = (TWELVE_O_CLOCK + round(FULL_CIRCLE * pct / 100)) % FULL_CIRCLE
    for name, value in (("adj1", TWELVE_O_CLOCK), ("adj2", end)):
        gd = next((g for g in av_lst.findall("a:gd", _NS) if g.get("name") == name), None)
        if gd is None:
            gd = etree.SubElement(av_lst, f"{{{_NS['a']}}}gd", name=name)
        gd.set("fmla", f"val {value}")


def _set_fill_like(el, source):
    """Give el the fill of source (used to draw a full Harvey ball with the pie's colour)."""
    fill = source.find(".//p:spPr/a:solidFill", _NS)
    if fill is None:
        return
    sp_pr = el.find(".//p:spPr", _NS)
    for tag in ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill"):
        for old in sp_pr.findall(tag, _NS):
            sp_pr.remove(old)
    geom = sp_pr.find("a:prstGeom", _NS)
    geom.addnext(copy.deepcopy(fill))


def _fill_text(el, name, note, scale=1.0):
    """Name in the first paragraph, note in the second (formatting of the sample kept, sizes scaled)."""
    paras = el.findall(".//p:txBody/a:p", _NS)
    for para, text in zip(paras, [name, note]):
        runs = para.findall("a:r", _NS)
        for br in para.findall("a:br", _NS):
            para.remove(br)
        if runs:
            runs[0].find("a:t", _NS).text = text
            for extra in runs[1:]:
                para.remove(extra)
    for para in paras[2 if note else 1:]:
        para.getparent().remove(para)
    if scale != 1.0:
        for rpr in el.findall(".//p:txBody//a:rPr", _NS) + el.findall(".//p:txBody//a:endParaRPr", _NS):
            if rpr.get("sz"):
                rpr.set("sz", str(max(100, round(int(rpr.get("sz")) * scale))))
    body = el.find(".//a:bodyPr", _NS)
    if body is not None:  # the box is sized to its text here: no autofit shrinking or growing
        for fit in list(body):
            if etree.QName(fit).localname in ("normAutofit", "spAutoFit", "noAutofit"):
                body.remove(fit)


def _sample_sizes(text_el):
    """(name pt, note pt) of the sample text box (first run of its first two paragraphs)."""
    sizes = []
    for para in text_el.findall(".//p:txBody/a:p", _NS)[:2]:
        rpr = para.find("a:r/a:rPr", _NS)
        sizes.append(int(rpr.get("sz")) / 100 if rpr is not None and rpr.get("sz") else None)
    sizes += [None, None]
    return sizes[0] or 11.0, sizes[1] or 8.5


def _line_count(text, size_pt, bold, width_emu):
    """Lines a text takes when word-wrapped in width_emu (estimated with Helvetica widths)."""
    width = max(1.0, width_emu / 12700 / WIDTH_SAFETY)
    lines, current = 1, 0.0
    space = text_width_pt(" ", size_pt, bold)
    for word in (text or "").split():
        w = text_width_pt(word, size_pt, bold)
        if current and current + space + w > width:
            lines, current = lines + 1, w
        else:
            current += (space if current else 0) + w
        while current > width:          # a single word longer than the line
            lines, current = lines + 1, current - width
    return lines


# Topic element: Harvey ball, the percentage under it, the due date in a rounded box under that;
# name and subtitle to the right.
BALL = Inches(0.30)
PCT_H = Inches(0.13)
BOX_W, BOX_H = Inches(0.56), Inches(0.15)
V_GAP = Inches(0.015)
BLOCK_H = BALL + V_GAP + PCT_H + 2 * V_GAP + BOX_H
MAX_STEP = Inches(0.72)           # distance between topics when there is room
ITEM_GAP = Inches(0.08)           # minimum free space between two topics
MIN_SCALE = 0.6                   # smallest size factor for crowded columns (balls, boxes and fonts)
SCALE_STEP = 0.05
LINE_HEIGHT = 1.2                 # line height as a share of the font size
WIDTH_SAFETY = 1.08               # template fonts can be wider than the Helvetica estimate
PCT_PT, DUE_PT = 8, 7
PCT_COLOR = "#FFFFFF"


def _column_geometry(sample, left, col_width, scale):
    """(centre of the ball column, text left, text width) of a column for a size factor."""
    ball, box_w = BALL * scale, BOX_W * scale
    center = left + max(sample["ball_dx"] + ball / 2, box_w / 2 + Inches(0.07))
    text_left = max(left + sample["text_dx"], center + box_w / 2 + Inches(0.1))
    return center, text_left, left + col_width - sample["text_right_margin"] - text_left


def _topic_size(topic, sample, scale, text_width, title_pt, note_pt):
    """(block height, text height) of one topic: the taller of ball+percentage+date and its text."""
    marker = (BALL + V_GAP + PCT_H + (2 * V_GAP + BOX_H if topic.get("due") else 0)) * scale
    text_pt = _line_count(topic["name"], title_pt * scale, True, text_width) * title_pt * scale * LINE_HEIGHT
    if topic.get("subtitle"):
        text_pt += (_line_count(topic["subtitle"], note_pt * scale, False, text_width)
                    * note_pt * scale * LINE_HEIGHT)
    text_h = Pt(text_pt)
    return max(marker, sample["text_dy"] * scale + text_h), text_h


def _fit_column(topics, sample, left, col_width, avail, title_pt, note_pt, scale=None):
    """Size factor and vertical layout so a column's topics fit without overlapping.

    Without scale: full size when they fit; otherwise balls, boxes and fonts shrink step by step down
    to MIN_SCALE. With scale: that size factor is used as given (the same one for every column, so all
    Harvey balls are equal). Gaps tighten when the topics still do not fit.
    Returns (scale, geometry, text heights, tops).
    """
    fixed = scale is not None
    scale = scale if fixed else 1.0
    while True:
        geometry = _column_geometry(sample, left, col_width, scale)
        sizes = [_topic_size(t, sample, scale, geometry[2], title_pt, note_pt) for t in topics]
        blocks = [b for b, _ in sizes]
        gap = ITEM_GAP * scale
        if fixed or sum(blocks) + gap * (len(blocks) - 1) <= avail or scale <= MIN_SCALE + 1e-9:
            break
        scale = round(scale - SCALE_STEP, 2)
    advances = [max(b + gap, MAX_STEP) for b in blocks]
    if blocks and sum(advances[:-1]) + blocks[-1] > avail:
        advances = [b + gap for b in blocks]
        if len(blocks) > 1 and sum(advances[:-1]) + blocks[-1] > avail:   # still too tall: tighten the gaps
            gap = max(0, (avail - sum(blocks)) / (len(blocks) - 1))
            advances = [b + gap for b in blocks]
    tops, y = [], 0
    for adv in advances:
        tops.append(y)
        y += adv
    return scale, geometry, [h for _, h in sizes], tops


def _place(el, left, top, size):
    """Move and resize a square shape (the Harvey ball parts)."""
    off, ext = el.find(".//a:xfrm/a:off", _NS), el.find(".//a:xfrm/a:ext", _NS)
    off.set("x", str(int(left)))
    off.set("y", str(int(top)))
    ext.set("cx", str(int(size)))
    ext.set("cy", str(int(size)))


def _add_box(slide, left, top, width, height, fill_hex, text, text_hex, size, typeface):
    """Rounded box (pill) with centred text: the due date coloured by status."""
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, int(left), int(top), int(width), int(height))
    box.adjustments[0] = 0.5
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor.from_string(fill_hex.lstrip("#"))
    box.line.fill.background()
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, attr, 0)
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    if text:
        run = para.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = True
        run.font.color.rgb = RGBColor.from_string(text_hex.lstrip("#"))
        if typeface:
            run.font.name = typeface
    return box


def _typeface(sample_text_el):
    latin = sample_text_el.find(".//a:rPr/a:latin", _NS)
    return latin.get("typeface") if latin is not None else None


def _add_run_box(slide, left, top, width, height, runs, typeface, align=PP_ALIGN.LEFT):
    """Text box with one paragraph of (text, size pt, hex colour, bold) runs."""
    box = slide.shapes.add_textbox(int(left), int(top), int(width), int(height))
    tf = box.text_frame
    tf.word_wrap = False
    for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, attr, 0)
    para = tf.paragraphs[0]
    para.alignment = align
    for text, size, color, bold in runs:
        run = para.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
        if typeface:
            run.font.name = typeface
    return box


def build_roadmap_pptx(config, progress, template_path=None, title=DEFAULT_TITLE, subtitle=DEFAULT_SUBTITLE,
                       banner=DEFAULT_BANNER):
    """PowerPoint bytes with the KPI slide filled from the configuration and loaded progress.

    Each topic: Harvey ball, its percentage under it and, under that, the due date in a rounded box
    coloured by the configured status; name and subtitle to the right. A legend is added under the
    columns when any topic has a due date.
    """
    template_path = template_path or find_template()
    if not template_path:
        raise TemplateError("No slide template found in assets/templates/ (expected 'Template QP.pptx').")
    prs = Presentation(template_path)
    slide = _find_kpi_slide(prs)
    _keep_only(prs, slide)
    parts = _classify(slide)
    samples = _column_samples(parts)

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            _set_text(shape, title)
            _fit_one_line(shape)
        elif shape.placeholder_format.type == PP_PLACEHOLDER.BODY:
            _set_text(shape, subtitle)
            _fit_one_line(shape)
    if parts["banner"] is not None:
        _set_text(parts["banner"], banner)
    if parts["note"] is not None:  # the template's top-right "Mock data" note is not used
        parts["note"]._element.getparent().remove(parts["note"]._element)
    for shape in parts["items"]:
        shape._element.getparent().remove(shape._element)

    groups = config.get("groups", [])
    template_cols = parts["columns"]
    n_template = len(template_cols)
    span_left = template_cols[0].left
    span_right = template_cols[-1].left + template_cols[-1].width
    gap = template_cols[1].left - (template_cols[0].left + template_cols[0].width) if n_template > 1 else Inches(0.1)
    n = max(1, len(groups))
    col_width = (span_right - span_left - gap * (n - 1)) / n

    # Column frame per group: template column i (repeating the last ones cyclically when there are more groups)
    # Original geometry, read before anything moves
    geo = [{"col_left": c.left, "col_width": c.width, "head_left": h.left, "head_width": h.width}
           for c, h in zip(template_cols, parts["headers"])]
    frames = []
    for i in range(n):
        src = i % n_template
        col_el, head_el = template_cols[src]._element, parts["headers"][src]._element
        icon_els = [p._element for p in _icons_of(parts["headers"][src], parts["icons"])]
        if i >= n_template:
            col_el, head_el = _add_element(slide, col_el), _add_element(slide, head_el)
            icon_els = [_add_element(slide, e) for e in icon_els]
        frames.append((src, col_el, head_el, icon_els))
    for src in range(n, n_template):  # fewer groups than template columns
        for shape in [template_cols[src], parts["headers"][src], *_icons_of(parts["headers"][src], parts["icons"])]:
            shape._element.getparent().remove(shape._element)

    col_bottom = template_cols[0].top + template_cols[0].height

    def column_layout(i, src, scale=None):
        sample, header = samples[src], parts["headers"][src]
        topics = groups[i]["topics"] if i < len(groups) else []
        top0 = min(sample["ball_top"], header.top + header.height + Inches(0.1))
        left = span_left + i * (col_width + gap)
        return top0, _fit_column(topics, sample, left, col_width, col_bottom - Inches(0.06) - top0,
                                 *_sample_sizes(sample["text"]), scale=scale)

    # One size for the whole slide: the one the most crowded column needs, so all Harvey balls are equal
    slide_scale = min((column_layout(i, src)[1][0] for i, (src, *_) in enumerate(frames)), default=1.0)

    for i, (src, col_el, head_el, icon_els) in enumerate(frames):
        left = span_left + i * (col_width + gap)
        g = geo[src]
        head_dx = g["head_left"] - g["col_left"]
        head_right = g["col_left"] + g["col_width"] - (g["head_left"] + g["head_width"])
        _move(col_el, left=left, width=col_width)
        _move(head_el, left=left + head_dx, width=max(Inches(0.5), col_width - head_dx - head_right))
        for icon_el in icon_els:
            off = icon_el.find(".//a:xfrm/a:off", _NS)
            off.set("x", str(int(left + int(off.get("x")) - g["col_left"])))
        if i < len(groups):
            for shape in slide.shapes:
                if shape._element is head_el:
                    _set_text(shape, groups[i]["name"])
                    break

        sample = samples[src]
        topics = groups[i]["topics"] if i < len(groups) else []
        typeface = _typeface(sample["text"])
        top0, (scale, (center, text_left, text_width), text_heights, tops) = column_layout(i, src, slide_scale)
        ball_d, box_w, box_h, pct_h, v_gap = (int(v * scale) for v in (BALL, BOX_W, BOX_H, PCT_H, V_GAP))
        for topic, dy, text_h in zip(topics, tops, text_heights):
            info = progress.get(topic["label"]) if progress else None
            pct = info["progress"] if info else None
            y = top0 + dy
            ball_left = center - ball_d / 2
            ball = _add_element(slide, sample["ellipse"])
            _place(ball, ball_left, y, ball_d)
            if pct is not None and pct >= 99.5:
                fill = _add_element(slide, sample["ellipse"])
                _place(fill, ball_left, y, ball_d)
                _set_fill_like(fill, sample["pie"])
            elif pct is not None and pct >= 0.5:
                pie = _add_element(slide, sample["pie"])
                _place(pie, ball_left, y, ball_d)
                _set_pie(pie, pct)
            pct_top = y + ball_d + v_gap
            _add_run_box(slide, center - box_w / 2, pct_top, box_w, pct_h,
                         [("–" if pct is None else f"{pct:.0f}%", round(PCT_PT * scale, 1), PCT_COLOR, True)],
                         typeface, PP_ALIGN.CENTER)
            if topic.get("due"):
                _add_box(slide, center - box_w / 2, pct_top + pct_h + 2 * v_gap, box_w, box_h,
                         due_box_color(topic.get("status")), f"{date.fromisoformat(topic['due']):%d.%m.%y}",
                         DUE_TEXT_COLOR, round(DUE_PT * scale, 1), typeface)
            text = _add_element(slide, sample["text"])
            _move(text, left=text_left, top=y + int(sample["text_dy"] * scale), width=text_width, height=text_h)
            _fill_text(text, topic["name"], topic.get("subtitle", ""), scale)

    if any(t.get("due") for g in groups for t in g["topics"]):
        typeface = _typeface(samples[0]["text"])
        legend_top = col_bottom + Inches(0.07)
        x = span_left
        _add_run_box(slide, x, legend_top, Inches(0.8), Inches(0.2), [("Due date:", 9, "#FFFFFF", True)], typeface)
        x += Inches(0.8)
        ball = Inches(0.12)
        for label, color in DUE_STATUS.values():
            dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, int(x), int(legend_top + Inches(0.045)), int(ball), int(ball))
            dot.fill.solid()
            dot.fill.fore_color.rgb = RGBColor.from_string(color.lstrip("#"))
            dot.line.fill.background()
            dot.shadow.inherit = False
            label_w = Inches(0.1 + 0.075 * len(label))
            _add_run_box(slide, x + ball + Inches(0.05), legend_top, label_w, Inches(0.2),
                         [(label, 9, "#FFFFFF", False)], typeface)
            x += ball + Inches(0.05) + label_w + Inches(0.12)

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
