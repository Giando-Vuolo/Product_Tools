"""Release Overview slide: a timeline of the releases of the Release Calendar as an editable PowerPoint.

Pure helpers (no Streamlit). The slide is first planned as a list of drawing elements in inches
(``plan_overview``); the same plan is written to PowerPoint (``build_overview_pptx``) and drawn as an
SVG preview for the page (``overview_svg``), so the preview always matches the download.

Release kinds follow the version number: X.0.0 is a major release, X.Y.0 a minor release and X.Y.Z
(Z > 0) a hot fix. Releases whose Prod Deploy is today or later are drawn as upcoming releases.
"""
from __future__ import annotations

import html
import io
import math
import re
import textwrap
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from utils import release_calendar as rc

MAJOR, MINOR, HOTFIX = "Major release", "Minor release", "Hot Fix"
KINDS = (MAJOR, MINOR, HOTFIX)
UPCOMING = "Upcoming Release"
REMARKABLE = "Remarkable Event"
NO_INCIDENTS, MINOR_INCIDENTS, MAJOR_INCIDENTS = "Without incidents", "Minor incidents", "Major incidents"
INCIDENT_LEVELS = ("", NO_INCIDENTS, MINOR_INCIDENTS, MAJOR_INCIDENTS)

# Colours of the corporate dark design
BACKGROUND = "#002D37"
WHITE = "#FFFFFF"
LIME = "#AAFF00"
TEAL = "#00978F"
COLORS = {MAJOR: TEAL, MINOR: "#1B7FA6", HOTFIX: "#8FDDF5", UPCOMING: "#D59BD3", REMARKABLE: "#E6FAF8"}
INCIDENT_COLORS = {NO_INCIDENTS: "#22B14C", MINOR_INCIDENTS: "#F9B21B", MAJOR_INCIDENTS: "#E5202E"}

SLIDE_W, SLIDE_H = 13.333, 7.5
AXIS_LEFT, AXIS_RIGHT, AXIS_Y = 0.62, 12.85, 4.30
CONTENT_LEFT, CONTENT_RIGHT = 0.42, 12.92
BOX_TOP, BOX_BOTTOM = 2.20, 3.75
EVENT_TOP, EVENT_BOTTOM = 5.15, 6.62
LEGEND_Y = 6.86
GAP = 0.15
MAX_BULLETS = 6
OVERVIEW_COLUMNS = ["Version", "Prod Deploy", "Kind", "Box", "Incidents", "Highlights"]

_HIGHLIGHT_RE = re.compile(r"\*\*(.+?)\*\*|(\bR\s?\d+\.\d+(?:\.\d+)?\b)")
_BULLET_RE = re.compile(r"^\s*(?:[-*•·–]|\d+[.)])\s+")


# --------------------------------------------------------------------------- data

def release_kind(version: str) -> str:
    """Major (X.0.0), minor (X.Y.0) or hot fix (X.Y.Z with Z > 0)."""
    parts = rc.version_key(version)
    if len(parts) < 3:
        return MAJOR
    _, minor, patch = parts[:3]
    if patch:
        return HOTFIX
    return MINOR if minor else MAJOR


def highlights_from_description(description: str, limit: int = MAX_BULLETS) -> list:
    """Bullet points from a Prod Deploy description: one per non-empty line, list markers removed."""
    lines = []
    for line in (description or "").splitlines():
        line = _BULLET_RE.sub("", line).strip()
        if line and line not in lines:
            lines.append(line)
    return lines[:limit]


def month_range(start: date, end: date) -> tuple:
    """The whole months covering [start, end]: (first day of start's month, first day after end's month)."""
    lo = pd.Timestamp(start).to_period("M").start_time
    hi = (pd.Timestamp(end).to_period("M") + 1).start_time
    return lo, hi


def overview_rows(releases: pd.DataFrame, events: pd.DataFrame, start: date, end: date,
                  today: Optional[date] = None) -> pd.DataFrame:
    """Releases with a Prod Deploy in the months of [start, end], with the default slide settings.

    A box with highlights is shown for every major release and for the next upcoming release; the
    highlights are the lines of the Prod Deploy description in the calendar.
    """
    today = pd.Timestamp(today or date.today())
    if releases is None or releases.empty:
        return pd.DataFrame(columns=OVERVIEW_COLUMNS)
    lo, hi = month_range(start, end)
    rel = releases[releases["Prod Deploy"].notna() & (releases["Prod Deploy"] >= lo) & (releases["Prod Deploy"] < hi)]
    rel = rel.sort_values("Prod Deploy", kind="stable")
    upcoming = rel[rel["Prod Deploy"] >= today]
    next_version = upcoming.iloc[0]["Version"] if not upcoming.empty else None
    rows = []
    for _, r in rel.iterrows():
        kind = release_kind(r["Version"])
        info = rc.prod_deploy_info(events, r["Version"])
        rows.append({
            "Version": r["Version"], "Prod Deploy": r["Prod Deploy"].date(), "Kind": kind,
            "Box": kind == MAJOR or r["Version"] == next_version, "Incidents": "",
            "Highlights": "\n".join(highlights_from_description(info["description"])),
        })
    return pd.DataFrame(rows, columns=OVERVIEW_COLUMNS)


def _join(items: list) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def default_headline(rows: pd.DataFrame, today: Optional[date] = None) -> str:
    """Two-line summary: the major releases already deployed (minor ones when there are none) and the next one.

    Text between ** ** and release names (R35.0.0) are drawn in lime green on the slide.
    """
    today = pd.Timestamp(today or date.today())
    if rows is None or rows.empty:
        return ""
    dates = pd.to_datetime(rows["Prod Deploy"])
    done = rows[(dates < today) & (rows["Kind"] == MAJOR)]
    if done.empty:
        done = rows[(dates < today) & (rows["Kind"] != HOTFIX)]
    planned = rows[dates >= today]
    lines = []
    if not done.empty:
        names = [f"R{v}" for v in done["Version"].tolist()[-3:]]
        lines.append(f"{_join(names)} {'was' if len(names) == 1 else 'were'} released.")
    if not planned.empty:
        nxt = planned.iloc[0]
        lines.append(f"R{nxt['Version']} is planned for **{_day_month(nxt['Prod Deploy'])}**.")
    return "\n".join(lines)


def _day_month(value) -> str:
    value = pd.Timestamp(value)
    return f"{value.day} {value:%B}"


def highlight_runs(text: str, color: str = WHITE, highlight: str = LIME) -> list:
    """Split a line into (text, colour) runs: release names and **marked** text are highlighted."""
    runs, pos = [], 0
    for m in _HIGHLIGHT_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], color))
        runs.append((m.group(1) or m.group(2), highlight))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], color))
    return [r for r in runs if r[0]]


# --------------------------------------------------------------------------- layout

def _text(x, y, w, h, paragraphs, size, *, bold=False, align="l", anchor="t", rotation=0.0, color=WHITE):
    """paragraphs: list of strings or {"runs": [(text, colour)], "bullet": bool}."""
    paras = [p if isinstance(p, dict) else {"runs": [(p, color)], "bullet": False} for p in paragraphs]
    return {"kind": "text", "x": x, "y": y, "w": w, "h": h, "paragraphs": paras, "size": size, "bold": bold,
            "align": align, "anchor": anchor, "rotation": rotation}


def _estimate_lines(paragraphs: Iterable[str], width_in: float, size_pt: float, indent_in: float = 0.0) -> int:
    chars_per_line = max(8, int((width_in - indent_in) * 72 / (size_pt * 0.5)))
    return sum(max(1, math.ceil(len(p) / chars_per_line)) for p in paragraphs)


def fit_size(title: str, bullets: list, width_in: float, height_in: float, sizes=(12, 11, 10, 9, 8)) -> float:
    """Largest font size for which the title and bullets are estimated to fit the box."""
    for size in sizes:
        lines = _estimate_lines([title], width_in, size + 1) + _estimate_lines(bullets, width_in, size, 0.18)
        if lines * size * 1.2 / 72 <= height_in:
            return size
    return sizes[-1]


def _spread(preferred: list, width: float, left: float = CONTENT_LEFT, right: float = CONTENT_RIGHT) -> list:
    """Left edges near the preferred ones, keeping boxes of `width` apart and inside [left, right]."""
    lefts = []
    for p in preferred:
        lefts.append(max(p, left, (lefts[-1] + width + GAP) if lefts else left))
    limit = right
    for i in range(len(lefts) - 1, -1, -1):
        lefts[i] = min(lefts[i], limit - width)
        limit = lefts[i] - GAP
    return lefts


def _box_width(count: int, widest: float) -> float:
    if count <= 0:
        return widest
    return min(widest, (CONTENT_RIGHT - CONTENT_LEFT - GAP * (count - 1)) / count)


def plan_overview(rows: pd.DataFrame, remarkable: pd.DataFrame, start: date, end: date, title: str,
                  headline: str = "", today: Optional[date] = None) -> list:
    """Drawing elements of the slide, in inches from the top-left corner.

    rows: OVERVIEW_COLUMNS (see overview_rows); remarkable: columns Date, Text.
    """
    today = pd.Timestamp(today or date.today())
    lo, hi = month_range(start, end)
    total_days = max((hi - lo).days, 1)

    def x_of(day) -> float:
        return AXIS_LEFT + (pd.Timestamp(day) - lo).days / total_days * (AXIS_RIGHT - 0.25 - AXIS_LEFT)

    els = [_text(0.42, 0.55, 11.6, 0.62, [title], 30)]
    head_lines = [line for line in (headline or "").splitlines() if line.strip()]
    if head_lines:
        els.append(_text(0.43, 1.17, 12.3, 0.8, [{"runs": highlight_runs(line), "bullet": False} for line in head_lines],
                         17 if len(head_lines) <= 2 else 14))

    # Axis, month separators and month names
    els.append({"kind": "line", "x1": AXIS_LEFT - 0.05, "y1": AXIS_Y, "x2": AXIS_RIGHT, "y2": AXIS_Y,
                "color": WHITE, "width": 3.0, "arrow": True})
    month = lo
    while month < hi:
        nxt = month + pd.offsets.MonthBegin(1)
        if month > lo:
            els.append({"kind": "line", "x1": x_of(month), "y1": AXIS_Y - 0.36, "x2": x_of(month),
                        "y2": AXIS_Y + 0.36, "color": WHITE, "width": 0.75, "arrow": False})
        label = f"{month:%B}" + (f" {month:%Y}" if month.month == 1 or month == lo and lo.year != (hi - pd.Timedelta(days=1)).year else "")
        mid = (x_of(month) + x_of(nxt)) / 2
        els.append(_text(mid - 1.0, AXIS_Y - 0.42, 2.0, 0.3, [label], 16, bold=True, align="c", anchor="b", color=LIME))
        month = nxt

    rows = rows if rows is not None else pd.DataFrame(columns=OVERVIEW_COLUMNS)
    rows = rows[pd.notna(rows["Prod Deploy"])].copy() if not rows.empty else rows
    if not rows.empty:
        rows["Prod Deploy"] = pd.to_datetime(rows["Prod Deploy"])
        rows = rows[(rows["Prod Deploy"] >= lo) & (rows["Prod Deploy"] < hi)].sort_values("Prod Deploy", kind="stable")
    release_xs = []

    # Release boxes above the axis
    boxed = rows[rows["Box"].fillna(False).astype(bool)] if not rows.empty else rows
    width = _box_width(len(boxed), 2.75)
    lefts = _spread([x_of(d) for d in boxed["Prod Deploy"]], width) if not boxed.empty else []
    for (_, r), left in zip(boxed.iterrows(), lefts):
        upcoming = r["Prod Deploy"] >= today
        color = COLORS[UPCOMING] if upcoming else TEAL
        mx = x_of(r["Prod Deploy"])
        title_text = f"R{r['Version']} ({_day_month(r['Prod Deploy'])})"
        bullets = [b.strip() for b in str(r.get("Highlights") or "").splitlines() if b.strip()][:MAX_BULLETS]
        incident = str(r.get("Incidents") or "")
        dot = 0.24 if incident in INCIDENT_COLORS else 0.0
        size = fit_size(title_text, bullets, width - 0.16 - dot, BOX_BOTTOM - BOX_TOP - 0.12)
        els.append({"kind": "rect", "x": left, "y": BOX_TOP, "w": width, "h": BOX_BOTTOM - BOX_TOP,
                    "fill": None, "line": color, "line_width": 1.75})
        paragraphs = [{"runs": [(title_text, WHITE)], "bullet": False, "bold": True, "size": size + 1}]
        paragraphs += [{"runs": [(b, WHITE)], "bullet": True} for b in bullets]
        els.append(_text(left + 0.06, BOX_TOP + 0.05, width - 0.12, BOX_BOTTOM - BOX_TOP - 0.1, paragraphs, size))
        if dot:
            els.append({"kind": "circle", "cx": left + width - 0.08 - dot / 2, "cy": BOX_TOP + 0.08 + dot / 2,
                        "r": dot / 2, "fill": INCIDENT_COLORS[incident], "line": None})
        bx = min(max(mx, left + 0.01), left + width - 0.01)
        els.append({"kind": "line", "x1": bx, "y1": BOX_BOTTOM, "x2": mx, "y2": AXIS_Y - 0.12,
                    "color": color, "width": 1.75, "arrow": False})

    # Release markers and their rotated labels; a label close to the previous one is moved further down
    last_x, level = None, 0
    for _, r in rows.iterrows():
        upcoming = r["Prod Deploy"] >= today
        kind = r["Kind"] if r["Kind"] in KINDS else release_kind(r["Version"])
        color = COLORS[UPCOMING] if upcoming else COLORS[kind]
        mx = x_of(r["Prod Deploy"])
        release_xs.append(mx)
        size = 0.27 if kind == MAJOR else 0.19
        els.append({"kind": "diamond", "cx": mx, "cy": AXIS_Y, "size": size, "fill": color})
        major = kind == MAJOR
        label = f"R {r['Version']}" if major else f"R{r['Version']}"
        level = level + 1 if last_x is not None and mx - last_x < 0.3 and level < 2 else 0
        last_x = mx
        els.append(_rotated_label(mx, AXIS_Y + size / 2 + level * 0.2, label, 15 if major else 9,
                                  WHITE if major else color, major))

    # Remarkable events: marker on the axis, box below it
    events = remarkable if remarkable is not None else pd.DataFrame(columns=["Date", "Text"])
    if not events.empty:
        events = events[pd.notna(events["Date"]) & events["Text"].fillna("").astype(str).str.strip().ne("")].copy()
        events["Date"] = pd.to_datetime(events["Date"])
        events = events[(events["Date"] >= lo) & (events["Date"] < hi)].sort_values("Date", kind="stable")
    ev_width = _box_width(len(events), 2.75)
    ev_lefts = _spread([x_of(d) - ev_width / 2 for d in events["Date"]], ev_width) if not events.empty else []
    for (_, e), left in zip(events.iterrows(), ev_lefts):
        mx = x_of(e["Date"])
        near = [x for x in release_xs if abs(x - mx) < 0.22]
        if near:
            mx = min(near) - 0.24  # just before the release diamond
        lines = [line.strip() for line in str(e["Text"]).splitlines() if line.strip()]
        paragraphs = [{"runs": [(_BULLET_RE.sub("", line), WHITE)], "bullet": bool(_BULLET_RE.match(line))}
                      for line in lines]
        size = fit_size(lines[0], lines[1:], ev_width - 0.16, EVENT_BOTTOM - EVENT_TOP - 0.12, sizes=(13, 12, 11, 10, 9, 8))
        needed = (_estimate_lines(lines[:1], ev_width - 0.16, size)
                  + _estimate_lines(lines[1:], ev_width - 0.16, size, 0.18)) * size * 1.2 / 72 + 0.2
        height = min(EVENT_BOTTOM - EVENT_TOP, max(0.6, needed))
        bx = min(max(mx, left + 0.01), left + ev_width - 0.01)
        els.append({"kind": "line", "x1": mx, "y1": AXIS_Y + 0.12, "x2": bx, "y2": EVENT_TOP,
                    "color": COLORS[REMARKABLE], "width": 1.0, "arrow": False})
        els.append({"kind": "rect", "x": left, "y": EVENT_TOP, "w": ev_width, "h": height,
                    "fill": None, "line": COLORS[REMARKABLE], "line_width": 1.0})
        els.append(_text(left + 0.06, EVENT_TOP + 0.05, ev_width - 0.12, height - 0.1, paragraphs, size))
        els += _remarkable_marker(mx, AXIS_Y, 0.22)

    els += _legend(rows)
    return els


def _rotated_label(mx: float, top: float, text: str, size: float, color: str, bold: bool) -> dict:
    """Label rotated 40° that ends just below-left of the marker, as on the reference slide."""
    angle = math.radians(40)
    width = len(text) * size * 0.62 / 72 + 0.12
    height = size * 1.35 / 72
    # End of the text (right edge, vertical middle) just below-left of the marker
    end_x, end_y = mx - 0.04, top + 0.06
    cx = end_x - width / 2 * math.cos(angle)
    cy = end_y + width / 2 * math.sin(angle) + height / 2 * math.cos(angle)
    el = _text(cx - width / 2, cy - height / 2, width, height, [{"runs": [(text, color)], "bullet": False}], size,
               bold=bold, align="r", anchor="m", rotation=-40.0)
    return el


def _remarkable_marker(cx: float, cy: float, d: float) -> list:
    return [{"kind": "circle", "cx": cx, "cy": cy, "r": d / 2, "fill": COLORS[REMARKABLE], "line": None},
            _text(cx - d / 2, cy - d / 2, d, d, [{"runs": [("!", BACKGROUND)], "bullet": False}], 12, bold=True,
                  align="c", anchor="m")]


def _legend(rows: pd.DataFrame) -> list:
    """Release kinds on the left; incident levels right-aligned when any release has one.
    The font shrinks until everything fits the slide width."""
    used = set(rows["Incidents"].fillna("")) if rows is not None and not rows.empty and "Incidents" in rows else set()
    kinds = [(MAJOR, "diamond", COLORS[MAJOR]), (MINOR, "diamond", COLORS[MINOR]), (HOTFIX, "diamond", COLORS[HOTFIX]),
             (UPCOMING, "diamond", COLORS[UPCOMING]), (REMARKABLE, "remarkable", None)]
    incidents = [(label, "circle", color) for label, color in INCIDENT_COLORS.items()] if used & set(INCIDENT_COLORS) else []
    for size in (11, 10.5, 10, 9.5, 9, 8.5, 8):
        def item_width(label):
            return 0.24 + len(label) * size * 0.52 / 72
        gap, group_gap = 0.2, 0.45
        left_w = sum(item_width(label) for label, _, _ in kinds) + gap * (len(kinds) - 1)
        right_w = sum(item_width(label) for label, _, _ in incidents) + gap * max(len(incidents) - 1, 0)
        if CONTENT_LEFT + left_w + (group_gap + right_w if incidents else 0) <= CONTENT_RIGHT:
            break
    els = []

    def draw(items, x):
        for label, marker, color in items:
            if marker == "diamond":
                els.append({"kind": "diamond", "cx": x + 0.09, "cy": LEGEND_Y, "size": 0.18, "fill": color})
            elif marker == "remarkable":
                els.extend(_remarkable_marker(x + 0.09, LEGEND_Y, 0.19))
            else:
                els.append({"kind": "circle", "cx": x + 0.09, "cy": LEGEND_Y, "r": 0.09, "fill": color, "line": None})
            els.append(_text(x + 0.2, LEGEND_Y - 0.13, item_width(label), 0.26, [label], size, anchor="m"))
            x += item_width(label) + gap

    draw(kinds, CONTENT_LEFT)
    if incidents:
        draw(incidents, CONTENT_RIGHT - right_w)
    return els


# --------------------------------------------------------------------------- PowerPoint

def build_overview_pptx(elements: list, template_path: Optional[str] = None) -> bytes:
    """One editable slide. With a corporate template its dark title-only layout (logo, footer) is used."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Inches, Pt
    from lxml import etree

    from utils.quarterly_planner_helpers import _template_content_layout

    def rgb(hex_value):
        return RGBColor.from_string(hex_value.lstrip("#").upper())

    if template_path:
        prs = Presentation(template_path)
        for slide_id in list(prs.slides._sldIdLst):
            prs.part.drop_rel(slide_id.rId)
            prs.slides._sldIdLst.remove(slide_id)
        layout = _template_content_layout(prs)
    else:
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
        layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    for shape in list(slide.placeholders):  # draw our own title, as the other slide exports do
        shape._element.getparent().remove(shape._element)
    # Scale the plan to the template's slide size (corporate templates are 13.333 x 7.5 in)
    sx = Emu(prs.slide_width).inches / SLIDE_W
    sy = Emu(prs.slide_height).inches / SLIDE_H
    if not template_path:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb(BACKGROUND)

    def X(v):
        return Inches(v * sx)

    def Y(v):
        return Inches(v * sy)

    def line_format(shape, color, width):
        if color:
            shape.line.color.rgb = rgb(color)
            shape.line.width = Pt(width)
        else:
            shape.line.fill.background()

    aligns = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
    anchors = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
    for el in elements:
        kind = el["kind"]
        if kind == "line":
            conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, X(el["x1"]), Y(el["y1"]), X(el["x2"]), Y(el["y2"]))
            conn.line.color.rgb = rgb(el["color"])
            conn.line.width = Pt(el["width"])
            if el.get("arrow"):
                ln = conn.line._get_or_add_ln()
                tail = etree.SubElement(ln, qn("a:tailEnd"))
                tail.set("type", "triangle")
                tail.set("w", "med")
                tail.set("len", "med")
        elif kind in ("rect", "diamond", "circle"):
            if kind == "rect":
                shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, X(el["x"]), Y(el["y"]), X(el["w"]), Y(el["h"]))
            elif kind == "diamond":
                s = el["size"]
                shape = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, X(el["cx"] - s / 2), Y(el["cy"] - s / 2), X(s), Y(s))
            else:
                r = el["r"]
                shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, X(el["cx"] - r), Y(el["cy"] - r), X(2 * r), Y(2 * r))
            if el.get("fill"):
                shape.fill.solid()
                shape.fill.fore_color.rgb = rgb(el["fill"])
            else:
                shape.fill.background()
            line_format(shape, el.get("line"), el.get("line_width", 1.0))
            shape.shadow.inherit = False
        elif kind == "text":
            box = slide.shapes.add_textbox(X(el["x"]), Y(el["y"]), X(el["w"]), Y(el["h"]))
            box.rotation = el["rotation"]
            tf = box.text_frame
            tf.word_wrap = el["rotation"] == 0
            tf.vertical_anchor = anchors[el["anchor"]]
            tf.margin_left = tf.margin_right = Inches(0.04)
            tf.margin_top = tf.margin_bottom = Inches(0.02)
            for i, para in enumerate(el["paragraphs"]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.alignment = aligns[el["align"]]
                if para.get("bullet"):
                    p_pr = p._p.get_or_add_pPr()
                    p_pr.set("marL", str(Inches(0.18)))
                    p_pr.set("indent", str(-Inches(0.18)))
                    bu = etree.SubElement(p_pr, qn("a:buChar"))
                    bu.set("char", "•")
                for text, color in para["runs"]:
                    run = p.add_run()
                    run.text = text
                    run.font.name = "Arial"
                    run.font.size = Pt(para.get("size", el["size"]))
                    run.font.bold = para.get("bold", el["bold"])
                    run.font.color.rgb = rgb(color)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


# --------------------------------------------------------------------------- SVG preview

def overview_svg(elements: list) -> str:
    """Approximate SVG drawing of the slide plan (inches → 96 px), for the page preview."""
    ppi = 96.0
    pt = ppi / 72.0
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SLIDE_W * ppi:.0f} {SLIDE_H * ppi:.0f}" '
             f'width="100%" style="font-family:Arial,Helvetica,sans-serif">',
             f'<rect width="100%" height="100%" fill="{BACKGROUND}"/>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" '
             'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#FFFFFF"/></marker></defs>']
    for el in elements:
        kind = el["kind"]
        if kind == "line":
            arrow = ' marker-end="url(#arrow)"' if el.get("arrow") else ""
            parts.append(f'<line x1="{el["x1"] * ppi:.1f}" y1="{el["y1"] * ppi:.1f}" x2="{el["x2"] * ppi:.1f}" '
                         f'y2="{el["y2"] * ppi:.1f}" stroke="{el["color"]}" stroke-width="{el["width"] * pt:.1f}"{arrow}/>')
        elif kind == "rect":
            parts.append(f'<rect x="{el["x"] * ppi:.1f}" y="{el["y"] * ppi:.1f}" width="{el["w"] * ppi:.1f}" '
                         f'height="{el["h"] * ppi:.1f}" fill="{el.get("fill") or "none"}" '
                         f'stroke="{el.get("line") or "none"}" stroke-width="{el.get("line_width", 1) * pt:.1f}"/>')
        elif kind == "diamond":
            cx, cy, h = el["cx"] * ppi, el["cy"] * ppi, el["size"] * ppi / 2
            parts.append(f'<polygon points="{cx:.1f},{cy - h:.1f} {cx + h:.1f},{cy:.1f} {cx:.1f},{cy + h:.1f} '
                         f'{cx - h:.1f},{cy:.1f}" fill="{el["fill"]}"/>')
        elif kind == "circle":
            parts.append(f'<circle cx="{el["cx"] * ppi:.1f}" cy="{el["cy"] * ppi:.1f}" r="{el["r"] * ppi:.1f}" '
                         f'fill="{el["fill"]}"/>')
        elif kind == "text":
            parts.append(_svg_text(el, ppi, pt))
    parts.append("</svg>")
    return "".join(parts)


def _svg_text(el: dict, ppi: float, pt: float) -> str:
    lines = []  # (runs, size, bold, indent)
    for para in el["paragraphs"]:
        size = para.get("size", el["size"])
        bold = para.get("bold", el["bold"])
        indent = 0.18 if para.get("bullet") else 0.0
        text = "".join(t for t, _ in para["runs"])
        if el["rotation"]:
            wrapped = [text]
        else:
            chars = max(8, int((el["w"] - 0.08 - indent) * 72 / (size * 0.5)))
            wrapped = textwrap.wrap(text, chars) or [""]
        if len(para["runs"]) > 1 and len(wrapped) == 1:
            lines.append((para["runs"], size, bold, indent, para.get("bullet")))
        else:
            color = para["runs"][0][1] if para["runs"] else WHITE
            for j, w in enumerate(wrapped):
                lines.append(([(w, color)], size, bold, indent, para.get("bullet") and j == 0))
    total = sum(s * 1.2 for _, s, _, _, _ in lines) / 72
    x0, y0, w, h = el["x"], el["y"], el["w"], el["h"]
    top = y0 + 0.02 if el["anchor"] == "t" else (y0 + (h - total) / 2 if el["anchor"] == "m" else y0 + h - total)
    anchor = {"l": "start", "c": "middle", "r": "end"}[el["align"]]
    out, y = [], top
    for runs, size, bold, indent, bullet in lines:
        y += size * 1.2 / 72
        base = y - size * 0.25 / 72
        if el["align"] == "l":
            x = x0 + 0.04 + indent
        elif el["align"] == "c":
            x = x0 + w / 2
        else:
            x = x0 + w - 0.04
        spans = "".join(f'<tspan fill="{c}">{html.escape(t)}</tspan>' for t, c in runs)
        weight = ' font-weight="bold"' if bold else ""
        out.append(f'<text x="{x * ppi:.1f}" y="{base * ppi:.1f}" font-size="{size * pt:.1f}" '
                   f'text-anchor="{anchor}"{weight}>{spans}</text>')
        if bullet:
            out.append(f'<text x="{(x0 + 0.06) * ppi:.1f}" y="{base * ppi:.1f}" font-size="{size * pt:.1f}" '
                       f'fill="{runs[0][1]}">•</text>')
    body = "".join(out)
    if el["rotation"]:
        cx, cy = (x0 + w / 2) * ppi, (y0 + h / 2) * ppi
        return f'<g transform="rotate({el["rotation"]:.1f} {cx:.1f} {cy:.1f})">{body}</g>'
    return body
