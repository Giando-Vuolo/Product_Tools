"""Preview of a PowerPoint slide as SVG, drawn in Python (no PowerPoint or LibreOffice needed).

Covers what the report slides use: background, master/layout decoration, placeholders (position and
text style inherited from the layout and master), rectangles, rounded rectangles, ellipses, pies,
lines, pictures (PNG/JPEG/GIF/SVG), groups, solid and linear gradient fills, theme colours with their
modifiers, and text with wrapping. Fonts are approximated with the browser's fonts, so line breaks can
differ slightly from PowerPoint. Charts, tables, OLE objects and vector images (EMF/WMF) are skipped.
"""
import base64
import colorsys
import io
import math
from html import escape

from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"a": A, "p": P, "r": R}

PX_PER_EMU = 96 / 914400          # SVG user units are CSS pixels (a 13.33in slide is 1280 wide)
PX_PER_PT = 96 / 72
# Character widths of Helvetica/Arial in 1/1000 em (printable ASCII from the space), to wrap text
_WIDTHS = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
           556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
           1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
           667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
           333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
           556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
OTHER_CHAR_WIDTH = 556
BOLD_FACTOR = 1.08                # bold glyphs are about this much wider
FALLBACK_FONTS = "Arial, Helvetica, sans-serif"
WEB_IMAGES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/svg+xml"}
_SCHEME_DEFAULT_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}


def _q(tag):
    prefix, name = tag.split(":")
    return f"{{{NS[prefix]}}}{name}"


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _num(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def text_width_pt(text, size_pt, bold=False):
    """Estimated width in points of a text in Helvetica/Arial (used to wrap text)."""
    em = sum(_WIDTHS[ord(c) - 32] if 32 <= ord(c) < 127 else OTHER_CHAR_WIDTH for c in text) / 1000
    return em * size_pt * (BOLD_FACTOR if bold else 1)


# ---------------------------------------------------------------- colours

def _hex_to_rgb(value):
    value = (value or "000000").strip()[-6:]
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _apply_mods(rgb, el):
    """Apply the DrawingML colour modifiers (lumMod, lumOff, tint, shade, alpha) of a colour element."""
    r, g, b = (c / 255 for c in rgb)
    alpha = 1.0
    for mod in el:
        name = etree.QName(mod).localname
        val = _f(mod.get("val"), 100000) / 100000
        if name in ("lumMod", "lumOff", "satMod"):
            h, light, s = colorsys.rgb_to_hls(r, g, b)
            if name == "lumMod":
                light *= val
            elif name == "lumOff":
                light += val
            else:
                s *= val
            r, g, b = colorsys.hls_to_rgb(h, min(1, max(0, light)), min(1, max(0, s)))
        elif name == "tint":
            r, g, b = (c + (1 - c) * (1 - val) for c in (r, g, b))
        elif name == "shade":
            r, g, b = (c * val for c in (r, g, b))
        elif name == "alpha":
            alpha = val
    return "#%02X%02X%02X" % tuple(round(min(1, max(0, c)) * 255) for c in (r, g, b)), alpha


class _Theme:
    def __init__(self, master, layout, slide):
        theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
        self.colors = {}
        scheme = theme.find(".//a:clrScheme", NS)
        for el in scheme if scheme is not None else []:
            child = el[0] if len(el) else None
            if child is None:
                continue
            if etree.QName(child).localname == "sysClr":
                self.colors[etree.QName(el).localname] = child.get("lastClr", "000000")
            else:
                self.colors[etree.QName(el).localname] = child.get("val", "000000")
        fonts = theme.find(".//a:fontScheme", NS)
        self.fonts = {}
        if fonts is not None:
            for kind, key in (("majorFont", "+mj-lt"), ("minorFont", "+mn-lt")):
                latin = fonts.find(f"a:{kind}/a:latin", NS)
                if latin is not None:
                    self.fonts[key] = latin.get("typeface")
        self.line_widths = [_f(ln.get("w"), 9525) for ln in theme.findall(".//a:lnStyleLst/a:ln", NS)]
        # colour map: the slide's override, else the layout's, else the master's
        self.map = dict(_SCHEME_DEFAULT_MAP)
        cmap = master.element.find(".//p:clrMap", NS)
        if cmap is not None:
            self.map.update(cmap.attrib)
        for part in (layout, slide):
            ovr = part.element.find("p:clrMapOvr/a:overrideClrMapping", NS)
            if ovr is not None:
                self.map.update(ovr.attrib)

    def color(self, holder, placeholder_color=None):
        """(#RRGGBB, alpha) of the first colour element inside holder (a solidFill, gs, fillRef...)."""
        if holder is None:
            return None
        for el in holder:
            name = etree.QName(el).localname
            if name == "srgbClr":
                return _apply_mods(_hex_to_rgb(el.get("val")), el)
            if name == "schemeClr":
                key = el.get("val")
                if key == "phClr":
                    if placeholder_color is None:
                        return None
                    return _apply_mods(_hex_to_rgb(placeholder_color[0]), el)
                key = self.map.get(key, key)
                return _apply_mods(_hex_to_rgb(self.colors.get(key, "000000")), el)
            if name == "sysClr":
                return _apply_mods(_hex_to_rgb(el.get("lastClr", "000000")), el)
            if name == "prstClr":
                named = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000",
                         "blue": "0000FF", "yellow": "FFFF00", "gray": "808080"}
                return _apply_mods(_hex_to_rgb(named.get(el.get("val"), "000000")), el)
        return None


# ---------------------------------------------------------------- renderer

class _Renderer:
    def __init__(self, prs, slide):
        self.prs, self.slide = prs, slide
        self.layout = slide.slide_layout
        self.master = self.layout.slide_master
        self.theme = _Theme(self.master, self.layout, slide)
        self.defs, self.out, self._ids = [], [], 0
        self.default_text = prs.part._element.find("p:defaultTextStyle", NS)

    def uid(self, prefix):
        self._ids += 1
        return f"{prefix}{self._ids}"

    # ------------------------------------------------ fills and lines
    def paint(self, holder, style_ref=None):
        """SVG paint (fill value, opacity) from an spPr-like element; style_ref is the p:style fillRef."""
        if holder is not None:
            for el in holder:
                name = etree.QName(el).localname
                if name == "noFill":
                    return "none", 1
                if name == "solidFill":
                    c = self.theme.color(el)
                    return (c[0], c[1]) if c else ("none", 1)
                if name == "gradFill":
                    return self.gradient(el, style_ref), 1
        if style_ref is not None and _f(style_ref.get("idx")) > 0:
            c = self.theme.color(style_ref)
            if c:
                return c[0], c[1]
        return "none", 1

    def gradient(self, grad, style_ref):
        stops = []
        ph = self.theme.color(style_ref) if style_ref is not None else None
        for gs in grad.findall("a:gsLst/a:gs", NS):
            c = self.theme.color(gs, ph)
            if c:
                stops.append((_f(gs.get("pos")) / 1000, c))
        if not stops:
            return "none"
        gid = self.uid("g")
        ang = math.radians(_f(grad.find("a:lin", NS).get("ang") if grad.find("a:lin", NS) is not None else 0) / 60000)
        x2, y2 = 0.5 + math.cos(ang) / 2, 0.5 + math.sin(ang) / 2
        stop_xml = "".join(f'<stop offset="{_num(pos)}%" stop-color="{c}" stop-opacity="{_num(a)}"/>'
                           for pos, (c, a) in stops)
        self.defs.append(f'<linearGradient id="{gid}" x1="{_num(1 - x2)}" y1="{_num(1 - y2)}" '
                         f'x2="{_num(x2)}" y2="{_num(y2)}">{stop_xml}</linearGradient>')
        return f"url(#{gid})"

    def stroke(self, sp_pr, style):
        """(colour, opacity, width px) or None for the outline of a shape."""
        ln = sp_pr.find("a:ln", NS) if sp_pr is not None else None
        ref = style.find("a:lnRef", NS) if style is not None else None
        width = None
        if ln is not None:
            if ln.find("a:noFill", NS) is not None:
                return None
            if ln.get("w"):
                width = _f(ln.get("w"))
            fill = ln.find("a:solidFill", NS)
            if fill is not None:
                c = self.theme.color(fill)
                if c:
                    return c[0], c[1], (width if width is not None else 12700) * PX_PER_EMU
        if ref is not None and _f(ref.get("idx")) > 0:
            c = self.theme.color(ref)
            if c:
                if width is None:
                    idx = int(_f(ref.get("idx"))) - 1
                    widths = self.theme.line_widths
                    width = widths[min(idx, len(widths) - 1)] if widths else 9525
                return c[0], c[1], width * PX_PER_EMU
        return None

    # ------------------------------------------------ placeholders
    def _ph(self, el):
        ph = el.find("./*/p:nvPr/p:ph", NS)
        if ph is None:
            return None
        return ph.get("type", "body"), ph.get("idx")

    def _find_ph(self, part, ph):
        """Placeholder element on a layout/master matching (type, idx)."""
        if ph is None:
            return None
        ptype, idx = ph
        by_type = None
        for sp in part.element.iter(_q("p:sp")):
            other = self._ph(sp)
            if other is None:
                continue
            if idx is not None and other[1] == idx and part is not self.master:
                return sp
            if by_type is None and (other[0] == ptype or
                                    (ptype in ("ctrTitle",) and other[0] == "title") or
                                    (ptype in ("subTitle", "obj") and other[0] == "body")):
                by_type = sp
        return by_type

    def inherited(self, el):
        """[layout element, master element] the placeholder el inherits from (missing ones are None)."""
        ph = self._ph(el)
        if ph is None:
            return []
        layout_el = self._find_ph(self.layout, ph)
        master_ph = self._ph(layout_el) if layout_el is not None else ph
        return [layout_el, self._find_ph(self.master, master_ph)]

    def xfrm(self, el, chain):
        for cand in [el, *chain]:
            if cand is None:
                continue
            x = cand.find("./p:spPr/a:xfrm", NS)
            if x is not None and x.find("a:off", NS) is not None:
                return x
        return None

    # ------------------------------------------------ shapes
    def render_tree(self, tree, part, on_slide):
        for el in tree:
            name = etree.QName(el).localname
            if name not in ("sp", "pic", "grpSp", "cxnSp"):
                continue
            nv = el.find("./*/p:cNvPr", NS)
            if nv is not None and nv.get("hidden") in ("1", "true"):
                continue
            if not on_slide and self._ph(el) is not None:
                continue     # layout/master placeholders only hold prompt text
            if name == "grpSp":
                self.render_group(el, part, on_slide)
            elif name == "pic":
                self.render_picture(el, part)
            else:
                self.render_shape(el)

    def render_group(self, el, part, on_slide):
        x = el.find("p:grpSpPr/a:xfrm", NS)
        if x is None:
            return self.render_tree(el, part, on_slide)
        off, ext = x.find("a:off", NS), x.find("a:ext", NS)
        choff, chext = x.find("a:chOff", NS), x.find("a:chExt", NS)
        sx = _f(ext.get("cx")) / _f(chext.get("cx"), 1) if chext is not None and _f(chext.get("cx")) else 1
        sy = _f(ext.get("cy")) / _f(chext.get("cy"), 1) if chext is not None and _f(chext.get("cy")) else 1
        tx = _f(off.get("x")) - _f(choff.get("x") if choff is not None else 0) * sx
        ty = _f(off.get("y")) - _f(choff.get("y") if choff is not None else 0) * sy
        self.out.append(f'<g transform="translate({_num(tx * PX_PER_EMU)} {_num(ty * PX_PER_EMU)}) '
                        f'scale({sx:.5f} {sy:.5f})">')
        self.render_tree(el, part, on_slide)
        self.out.append("</g>")

    def box(self, x):
        off, ext = x.find("a:off", NS), x.find("a:ext", NS)
        return (_f(off.get("x")) * PX_PER_EMU, _f(off.get("y")) * PX_PER_EMU,
                _f(ext.get("cx") if ext is not None else 0) * PX_PER_EMU,
                _f(ext.get("cy") if ext is not None else 0) * PX_PER_EMU)

    def transform(self, x, bx, by, bw, bh, geometry=True):
        parts = []
        rot = _f(x.get("rot")) / 60000
        if rot:
            parts.append(f"rotate({_num(rot)} {_num(bx + bw / 2)} {_num(by + bh / 2)})")
        if geometry and (x.get("flipH") in ("1", "true") or x.get("flipV") in ("1", "true")):
            fx = -1 if x.get("flipH") in ("1", "true") else 1
            fy = -1 if x.get("flipV") in ("1", "true") else 1
            cx, cy = bx + bw / 2, by + bh / 2
            parts.append(f"translate({_num(cx)} {_num(cy)}) scale({fx} {fy}) translate({_num(-cx)} {_num(-cy)})")
        return f' transform="{" ".join(parts)}"' if parts else ""

    def render_shape(self, el):
        chain = self.inherited(el)
        x = self.xfrm(el, chain)
        if x is None:
            return
        bx, by, bw, bh = self.box(x)
        sp_pr = el.find("p:spPr", NS)
        style = el.find("p:style", NS)
        geom = sp_pr.find("a:prstGeom", NS) if sp_pr is not None else None
        prst = geom.get("prst") if geom is not None else ("rect" if sp_pr is not None and
                                                          sp_pr.find("a:custGeom", NS) is None else None)
        fill, opacity = self.paint(sp_pr, style.find("a:fillRef", NS) if style is not None else None)
        line = self.stroke(sp_pr, style)
        tf = self.transform(x, bx, by, bw, bh)
        paint = f'fill="{fill}"' + (f' fill-opacity="{_num(opacity)}"' if opacity < 1 else "")
        if line:
            paint += f' stroke="{line[0]}" stroke-width="{_num(line[2])}"'
            if line[1] < 1:
                paint += f' stroke-opacity="{_num(line[1])}"'
        else:
            paint += ' stroke="none"'
        if prst and (fill != "none" or line):
            self.out.append(self.geometry(prst, geom, bx, by, bw, bh, paint, tf, x))
        tx_body = el.find("p:txBody", NS)
        if tx_body is not None:
            self.render_text(el, tx_body, chain, style, bx, by, bw, bh, self.transform(x, bx, by, bw, bh, False))

    def geometry(self, prst, geom, x, y, w, h, paint, tf, xfrm):
        adj = {gd.get("name"): gd.get("fmla", "") for gd in geom.findall("a:avLst/a:gd", NS)} if geom is not None else {}

        def val(name, default):
            text = adj.get(name, "")
            return _f(text.split()[-1], default) if text.startswith("val") else default

        if prst == "ellipse":
            return (f'<ellipse cx="{_num(x + w / 2)}" cy="{_num(y + h / 2)}" rx="{_num(w / 2)}" '
                    f'ry="{_num(h / 2)}" {paint}{tf}/>')
        if prst == "roundRect":
            r = min(w, h) * val("adj", 16667) / 100000
            return (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
                    f'rx="{_num(r)}" {paint}{tf}/>')
        if prst in ("pie", "chord"):
            start = val("adj1", 0) / 60000
            end = val("adj2", 16200000 if prst == "pie" else 2700000) / 60000
            sweep = (end - start) % 360 or 360
            cx, cy, rx, ry = x + w / 2, y + h / 2, w / 2, h / 2
            if sweep >= 359.99:
                return f'<ellipse cx="{_num(cx)}" cy="{_num(cy)}" rx="{_num(rx)}" ry="{_num(ry)}" {paint}{tf}/>'
            p1 = (cx + rx * math.cos(math.radians(start)), cy + ry * math.sin(math.radians(start)))
            p2 = (cx + rx * math.cos(math.radians(start + sweep)), cy + ry * math.sin(math.radians(start + sweep)))
            centre = f"M{_num(cx)} {_num(cy)} L" if prst == "pie" else "M"
            return (f'<path d="{centre}{_num(p1[0])} {_num(p1[1])} A{_num(rx)} {_num(ry)} 0 '
                    f'{1 if sweep > 180 else 0} 1 {_num(p2[0])} {_num(p2[1])} Z" {paint}{tf}/>')
        if prst in ("line", "straightConnector1", "bentConnector1"):
            x1, y1, x2, y2 = x, y, x + w, y + h
            if xfrm.get("flipH") in ("1", "true"):
                x1, x2 = x2, x1
            if xfrm.get("flipV") in ("1", "true"):
                y1, y2 = y2, y1
            rot = _f(xfrm.get("rot")) / 60000
            rt = f' transform="rotate({_num(rot)} {_num(x + w / 2)} {_num(y + h / 2)})"' if rot else ""
            return f'<line x1="{_num(x1)}" y1="{_num(y1)}" x2="{_num(x2)}" y2="{_num(y2)}" {paint}{rt}/>'
        # rect and anything not drawn exactly: its bounding box
        return f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" {paint}{tf}/>'

    def render_picture(self, el, part):
        x = self.xfrm(el, self.inherited(el))
        if x is None:
            return
        blip = el.find(".//a:blip", NS)
        if blip is None:
            return
        # Office keeps vector icons as an SVG beside (or instead of) the bitmap: prefer the SVG
        svg_blip = blip.find(".//{http://schemas.microsoft.com/office/drawing/2016/SVG/main}svgBlip")
        rid = (svg_blip.get(_q("r:embed")) if svg_blip is not None else None) or blip.get(_q("r:embed"))
        if not rid:
            return
        try:
            image = part.related_part(rid)
        except KeyError:
            return
        ctype = (image.content_type or "").lower()
        if ctype not in WEB_IMAGES:
            return
        bx, by, bw, bh = self.box(x)
        crop = el.find(".//a:srcRect", NS)
        cl, ct, cr, cb = ((_f(crop.get(k)) / 100000 for k in ("l", "t", "r", "b")) if crop is not None
                          else (0, 0, 0, 0))
        iw, ih = bw / max(1e-6, 1 - cl - cr), bh / max(1e-6, 1 - ct - cb)
        data = base64.b64encode(image.blob).decode()
        self.out.append(
            f'<svg x="{_num(bx)}" y="{_num(by)}" width="{_num(bw)}" height="{_num(bh)}" overflow="hidden"'
            f'{self.transform(x, bx, by, bw, bh)}>'
            f'<image x="{_num(-iw * cl)}" y="{_num(-ih * ct)}" width="{_num(iw)}" height="{_num(ih)}" '
            f'preserveAspectRatio="none" href="data:{ctype};base64,{data}"/></svg>')

    # ------------------------------------------------ text
    def _lst_level(self, holder, level):
        if holder is None:
            return None
        return holder.find(f"a:lvl{level + 1}pPr", NS)

    def _style_levels(self, el, tx_body, chain, level):
        """pPr-like elements from the most to the least specific for one paragraph level."""
        levels = [self._lst_level(tx_body.find("a:lstStyle", NS), level)]
        for cand in chain:
            if cand is not None:
                levels.append(self._lst_level(cand.find("p:txBody/a:lstStyle", NS), level))
        styles = self.master.element.find("p:txStyles", NS)
        ph = self._ph(el)
        if ph is not None and styles is not None:
            kind = "titleStyle" if ph[0] in ("title", "ctrTitle") else (
                "bodyStyle" if ph[0] in ("body", "subTitle", "obj") else "otherStyle")
            levels.append(self._lst_level(styles.find(f"p:{kind}", NS), level))
        else:
            levels.append(self._lst_level(self.default_text, level))
        return [lv for lv in levels if lv is not None]

    def _body_attr(self, tx_body, chain, name, default):
        for body in [tx_body.find("a:bodyPr", NS)] + [
                c.find("p:txBody/a:bodyPr", NS) for c in chain if c is not None]:
            if body is not None and body.get(name) is not None:
                return body.get(name)
        return default

    def _run_props(self, rpr, levels, font_ref_color):
        """Effective size (pt), bold, italic, colour, alpha and font of a run."""
        props = {"sz": None, "b": None, "i": None, "color": None, "font": None, "u": None}
        sources = [rpr] + [lv.find("a:defRPr", NS) for lv in levels]
        for i, src in enumerate(sources):
            if src is None:
                continue
            for key in ("sz", "b", "i", "u"):
                if props[key] is None and src.get(key) is not None:
                    props[key] = src.get(key)
            if props["color"] is None:
                fill = src.find("a:solidFill", NS)
                if fill is not None:
                    props["color"] = self.theme.color(fill)
            if props["font"] is None:
                latin = src.find("a:latin", NS)
                if latin is not None and latin.get("typeface"):
                    props["font"] = latin.get("typeface")
            if i == 0 and props["color"] is None and font_ref_color is not None:
                props["color"] = font_ref_color   # shape style font colour beats the defaults
        font = props["font"] or "+mn-lt"
        font = self.theme.fonts.get(font, font)
        color = props["color"] or ("#000000", 1)
        return {"size": _f(props["sz"], 1800) / 100, "bold": props["b"] in ("1", "true"),
                "italic": props["i"] in ("1", "true"), "color": color[0], "alpha": color[1], "font": font,
                "underline": props["u"] not in (None, "none")}

    def render_text(self, el, tx_body, chain, style, bx, by, bw, bh, tf):
        paragraphs = tx_body.findall("a:p", NS)
        if not any("".join(t.text or "" for t in p.iter(_q("a:t"))).strip() for p in paragraphs):
            return
        font_ref = style.find("a:fontRef", NS) if style is not None else None
        font_ref_color = self.theme.color(font_ref) if font_ref is not None else None
        ins = {k: _f(self._body_attr(tx_body, chain, k, d)) * PX_PER_EMU
               for k, d in (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720))}
        wrap = self._body_attr(tx_body, chain, "wrap", "square") != "none"
        anchor = self._body_attr(tx_body, chain, "anchor", "t")
        scale = 1.0
        autofit = tx_body.find("a:bodyPr/a:normAutofit", NS)
        if autofit is not None and autofit.get("fontScale"):
            scale = _f(autofit.get("fontScale"), 100000) / 100000
        avail = max(1.0, bw - ins["lIns"] - ins["rIns"])

        lines = []      # (align, indent px, [(text, props)], line height px, space before px)
        for p in paragraphs:
            ppr = p.find("a:pPr", NS)
            level = int(_f(ppr.get("lvl") if ppr is not None else 0))
            levels = self._style_levels(el, tx_body, chain, level)

            def para_attr(name, default):
                for src in [ppr] + levels:
                    if src is not None and src.get(name) is not None:
                        return src.get(name)
                return default

            def para_child(path):
                for src in [ppr] + levels:
                    found = src.find(path, NS) if src is not None else None
                    if found is not None:
                        return found
                return None

            align = para_attr("algn", "l")
            indent = _f(para_attr("marL", 0)) * PX_PER_EMU
            ln_pct = para_child("a:lnSpc/a:spcPct")
            ln_factor = _f(ln_pct.get("val"), 100000) / 100000 if ln_pct is not None else 1.0
            before_pts = para_child("a:spcBef/a:spcPts")
            before = _f(before_pts.get("val")) / 100 * PX_PER_PT if before_pts is not None else 0

            runs = []
            for child in p:
                name = etree.QName(child).localname
                if name in ("r", "fld"):
                    t = child.find("a:t", NS)
                    runs.append((t.text if t is not None and t.text else "",
                                 self._run_props(child.find("a:rPr", NS), levels, font_ref_color)))
                elif name == "br":
                    runs.append(("\n", self._run_props(child.find("a:rPr", NS), levels, font_ref_color)))
            if not runs:
                end = self._run_props(p.find("a:endParaRPr", NS), levels, font_ref_color)
                runs = [("", end)]
            for i, line in enumerate(self._wrap(runs, avail - indent, scale, wrap)):
                size = max((pr["size"] for _, pr in line), default=runs[0][1]["size"]) * scale * PX_PER_PT
                lines.append((align, indent, line, size * 1.2 * ln_factor, before if i == 0 and lines else 0))

        total = sum(h + b for _, _, _, h, b in lines)
        inner_top, inner_h = by + ins["tIns"], bh - ins["tIns"] - ins["bIns"]
        y = inner_top + {"ctr": (inner_h - total) / 2, "b": inner_h - total}.get(anchor, 0)
        out = [f"<g{tf}>"] if tf else []
        for align, indent, line, height, before in lines:
            y += before
            baseline = y + height * 0.8
            left = bx + ins["lIns"] + indent
            right = bx + bw - ins["rIns"]
            x, text_anchor = {"ctr": ((left + right) / 2, "middle"), "r": (right, "end")}.get(align, (left, "start"))
            spans = []
            for text, pr in line:
                if not text:
                    continue
                attrs = (f'font-size="{_num(pr["size"] * scale * PX_PER_PT)}" fill="{pr["color"]}" '
                         f'font-family="{escape(repr(pr["font"])[1:-1], quote=True)}, {FALLBACK_FONTS}"')
                if pr["alpha"] < 1:
                    attrs += f' fill-opacity="{_num(pr["alpha"])}"'
                if pr["bold"]:
                    attrs += ' font-weight="bold"'
                if pr["italic"]:
                    attrs += ' font-style="italic"'
                if pr["underline"]:
                    attrs += ' text-decoration="underline"'
                spans.append(f'<tspan {attrs}>{escape(text)}</tspan>')
            if spans:
                out.append(f'<text x="{_num(x)}" y="{_num(baseline)}" text-anchor="{text_anchor}" '
                           f'xml:space="preserve">{"".join(spans)}</text>')
            y += height
        if tf:
            out.append("</g>")
        self.out.extend(out)

    @staticmethod
    def _width(text, pr, scale):
        return text_width_pt(text, pr["size"] * scale, pr["bold"]) * PX_PER_PT

    def _wrap(self, runs, avail, scale, wrap):
        """Split a paragraph's runs into lines that fit the available width (word wrapping)."""
        lines, current, width = [], [], 0.0
        for text, pr in runs:
            if text == "\n":
                lines.append(current)
                current, width = [], 0.0
                continue
            for i, word in enumerate(text.split(" ")):
                piece = (" " if i > 0 and current else "") + word
                piece_w = self._width(piece, pr, scale)
                if wrap and current and width + piece_w > avail:
                    lines.append(current)
                    current, width = [], 0.0
                    piece, piece_w = word, self._width(word, pr, scale)
                if current and current[-1][1] is pr:
                    current[-1] = (current[-1][0] + piece, pr)
                else:
                    current.append((piece, pr))
                width += piece_w
        lines.append(current)
        return [line for line in lines if any(t for t, _ in line)] or [[("", runs[0][1])]]

    # ------------------------------------------------ slide
    def background(self, w, h):
        for part in (self.slide, self.layout, self.master):
            bg = part.element.find("p:cSld/p:bg", NS)
            if bg is None:
                continue
            bg_pr, ref = bg.find("p:bgPr", NS), bg.find("p:bgRef", NS)
            if bg_pr is not None:
                blip = bg_pr.find("a:blipFill/a:blip", NS)
                if blip is not None:
                    try:
                        image = part.part.related_part(blip.get(_q("r:embed")))
                        if (image.content_type or "").lower() in WEB_IMAGES:
                            data = base64.b64encode(image.blob).decode()
                            return (f'<image width="{_num(w)}" height="{_num(h)}" preserveAspectRatio="none" '
                                    f'href="data:{image.content_type};base64,{data}"/>')
                    except KeyError:
                        pass
                fill, opacity = self.paint(bg_pr)
            elif ref is not None:
                c = self.theme.color(ref)
                fill, opacity = (c[0], c[1]) if c else ("#FFFFFF", 1)
            else:
                continue
            if fill != "none":
                return f'<rect width="{_num(w)}" height="{_num(h)}" fill="{fill}" fill-opacity="{_num(opacity)}"/>'
        return f'<rect width="{_num(w)}" height="{_num(h)}" fill="#FFFFFF"/>'

    def render(self):
        w, h = self.prs.slide_width * PX_PER_EMU, self.prs.slide_height * PX_PER_EMU
        self.out.append(self.background(w, h))
        show_master = self.slide.element.get("showMasterSp") not in ("0", "false")
        if show_master and self.layout.element.get("showMasterSp") not in ("0", "false"):
            self.render_tree(self.master.element.find("p:cSld/p:spTree", NS), self.master.part, False)
        if show_master:
            self.render_tree(self.layout.element.find("p:cSld/p:spTree", NS), self.layout.part, False)
        self.render_tree(self.slide.element.find("p:cSld/p:spTree", NS), self.slide.part, True)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(w)} {_num(h)}" '
                f'width="{_num(w)}" height="{_num(h)}" role="img" aria-label="Slide preview">'
                f'<defs>{"".join(self.defs)}</defs>{"".join(self.out)}</svg>')


def slide_to_svg(pptx, slide_index=0):
    """SVG markup of one slide of a presentation (bytes, a path or a file-like object)."""
    source = io.BytesIO(pptx) if isinstance(pptx, (bytes, bytearray)) else pptx
    prs = Presentation(source)
    if not 0 <= slide_index < len(prs.slides):
        raise IndexError(f"The presentation has no slide {slide_index + 1}.")
    return _Renderer(prs, prs.slides[slide_index]).render()


def slide_count(pptx):
    source = io.BytesIO(pptx) if isinstance(pptx, (bytes, bytearray)) else pptx
    return len(Presentation(source).slides)
