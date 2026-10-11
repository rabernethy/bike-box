"""Mitre (coping) templates: full-scale wrap-around templates and cut lists.

Each template is a :class:`Scene` drawn at 1:1 in millimetres:

* the unrolled tube surface as a rectangle (width = perimeter) with a glue
  tab; the cut line; the waste side (toward the tube end, at the top) shaded
  and hatched;
* quadrant reference lines labelled with the tube faces they align with
  (e.g. TOP / DRIVE SIDE / BOTTOM / NON-DRIVE SIDE), long/short point marks,
  5 mm graduations and the centre-to-centre end line;
* a data block (tube, receivers, section, angle, offset, hole saw, phase)
  and a 50 x 50 mm calibration square.

The template reads correctly when wrapped **printed side out with the top
edge toward the tube end**: quadrant lines are placed for that orientation
(``MitreCut.wrap_reversed`` flips the drawing for ends that need it).

``save_mitre_pdf`` prints at true scale and tiles templates bigger than the
printable area across pages with overlap and registration marks;
``save_mitre_svg`` / ``save_mitre_dxf`` lay all templates out at 1:1.
"""
from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from ..geometry.mitre import MitreCut, cut_lengths
from ..geometry.solver import Geometry
from ..geometry.vec import V
from ..model import params as P
from ..model.units import fmt_len
from ..render.scene import Z_CENTERLINE, Z_FRAME, Z_GRID, Z_NOTE, Z_OVER, Polyline, Scene, Style, Text

G, S = "Manufacturing", "Mitre templates"
P.register([
    P.ParamDef("mitre_template_body", "Template length past the cut", G, S, P.FLOAT, 40.0, "mm", 10, 300, 1,
               help="How far the template extends along the tube body beyond the deepest point of the cut"),
    P.ParamDef("mitre_glue_tab", "Glue tab width", G, S, P.FLOAT, 12.0, "mm", 0, 50, 1),
    P.ParamDef("mitre_page_size", "Page size", G, S, P.CHOICE, "A4",
               choices=(("A4", "A4"), ("A3", "A3"), ("Letter", "US Letter"), ("Legal", "US Legal"),
                        ("Tabloid", "Tabloid / ledger")), morph=False),
    P.ParamDef("mitre_landscape", "Landscape pages", G, S, P.BOOL, True, morph=False),
    P.ParamDef("mitre_page_margin", "Printer margin", G, S, P.FLOAT, 10.0, "mm", 0, 40, 0.5,
               help="Unprinted border kept clear on every page"),
    P.ParamDef("mitre_tile_overlap", "Tile overlap", G, S, P.FLOAT, 15.0, "mm", 5, 60, 1,
               help="Overlap between pages when a template is bigger than the page"),
])

PAGE_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0),
    "Letter": (215.9, 279.4), "Legal": (215.9, 355.6), "Tabloid": (279.4, 431.8),
}
HEADER_MM = 10.0            # page header strip inside the printable area

INK = "#000000"
REF = "#1f5fbf"
GREY = "#8c8c8c"
_LAYER_EXTENT = "mitre_extent"
_LAYER_FILL = "mitre_waste_fill"

# short receiver tags for the cut list
_TAGS = {"bb": "BB", "ht": "HT", "st": "ST", "tt": "TT", "dt": "DT", "cs": "CS", "ss": "SS", "ss_mono": "WB"}


def _f(mm: float, units: str) -> str:
    return fmt_len(mm, units, 3 if units == "in" else 1, suffix=True)


def _deg(a: float) -> str:
    return f"{0.0 if abs(a) < 0.05 else a:.1f}°"


def _text(sc: Scene, x: float, y: float, s: str, size: float = 3.0, anchor: str = "lb", bold: bool = False,
          color: str = INK, angle: float = 0.0, layer: str = "mitre_text") -> Text:
    # non-annotative: model mm == paper mm at 1:1, and the anchor counts toward the bounds
    return sc.add(Text(layer, Z_NOTE, Style(color, 0.25), "", V(x, y), s, size, angle, anchor, False,
                       bold=bold))


def _text_width(s: str, size: float) -> float:
    return max((len(line) for line in s.split("\n")), default=0) * size * 0.64


def _hatch(xs: np.ndarray, ys: np.ndarray, y_top: float, x0: float, x1: float,
           spacing: float = 3.0) -> list[list[V]]:
    """45° hatch segments filling the region between the curve y = f(x) and ``y_top``."""
    if x1 - x0 < 1e-6:
        return []
    step = spacing * math.sqrt(2.0)
    xx = np.linspace(x0, x1, max(int((x1 - x0) / 0.25), 8) + 1)
    f = np.interp(xx, xs, ys)
    segs: list[list[V]] = []
    c = x0 - y_top + step / 2
    while c < x1 - float(f.min()):
        y = xx - c
        q = np.minimum(y - f, y_top - y)
        ins = q >= 0
        if ins.any():
            edges = np.flatnonzero(np.diff(ins.astype(np.int8)))
            starts = ([0] if ins[0] else []) + [int(i) + 1 for i in edges if not ins[i]]
            ends = [int(i) for i in edges if ins[i]] + ([len(xx) - 1] if ins[-1] else [])
            for s0, s1 in zip(starts, ends):
                xa, xb = xx[s0], xx[s1]
                if s0 > 0:                  # refine the boundary crossings
                    xa = xx[s0 - 1] + (xx[s0] - xx[s0 - 1]) * (-q[s0 - 1]) / (q[s0] - q[s0 - 1])
                if s1 < len(xx) - 1:
                    xb = xx[s1] + (xx[s1 + 1] - xx[s1]) * q[s1] / (q[s1] - q[s1 + 1])
                if xb - xa > 0.2:
                    segs.append([V(xa, xa - c), V(xb, xb - c)])
        c += step
    return segs


def _extrema(vals: Sequence[float], kind: str, tol: float = 0.05) -> list[int]:
    """Indices of the cut's long (``min``) or short (``max``) points; plateaus collapse to their middle."""
    n = len(vals) - 1                       # last point repeats the first
    v = list(vals[:n])
    target = min(v) if kind == "min" else max(v)
    near = [abs(x - target) <= tol for x in v]
    if all(near):
        return []
    start = next(i for i in range(n) if not near[i])      # rotate so runs don't wrap
    out, run = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if near[i]:
            run.append(i)
        elif run:
            out.append(run[len(run) // 2])
            run = []
    if run:
        out.append(run[len(run) // 2])
    return out[:4]


# --------------------------------------------------------------------------
# template scene
# --------------------------------------------------------------------------
def mitre_template_scene(cut: MitreCut, title: str = "", units: str = "mm", *, body: float = 40.0,
                         tab: float = 12.0) -> Scene:
    """Full-scale (1:1, mm) wrap-around template for one cut.

    Paper x runs around the tube (0 .. perimeter, then the glue tab), paper y
    runs along it: ``y = -v``, so the tube end is at the top and the body at
    the bottom."""
    sc = Scene()
    sc.background = "#ffffff"
    Pm = cut.perimeter
    rev = cut.wrap_reversed

    def X(u: float) -> float:
        return Pm - u if rev else u

    curve = [V(X(u), -v) for u, v in cut.points]
    y_top = -cut.long_point + 12.0
    y_bot = -cut.short_point - body

    # waste: shaded and hatched between the cut line and the tube end
    waste = curve + [V(curve[-1].x, y_top), V(curve[0].x, y_top)]
    sc.add(Polyline(_LAYER_FILL, Z_GRID, Style(None, 0.0, fill="#ececec"), "", waste, True))
    order = sorted(range(len(curve)), key=lambda i: curve[i].x)
    xs = np.array([curve[i].x for i in order])
    ys = np.array([curve[i].y for i in order])
    hatch = Style(GREY, 0.13)
    for seg in _hatch(xs, ys, y_top, 0.0, Pm):
        sc.add(Polyline("mitre_hatch", Z_GRID + 1, hatch, "", seg))

    # outline, glue tab, graduations
    outline = Style(INK, 0.3)
    sc.poly([V(0, y_bot), V(Pm, y_bot), V(Pm, y_top), V(0, y_top)], outline, "mitre_outline", Z_FRAME,
            closed=True)
    if tab > 0:
        sc.poly([V(Pm, y_top), V(Pm + tab, y_top), V(Pm + tab, y_bot), V(Pm, y_bot)],
                Style(INK, 0.2, dash=(2.0, 1.2)), "mitre_outline", Z_FRAME)
        tab_curve = [V(p.x + Pm, p.y) for p in sorted(curve, key=lambda p: p.x) if p.x <= tab]
        if len(tab_curve) > 1:
            sc.poly(tab_curve, Style(INK, 0.25), "mitre_cut", Z_FRAME)
        _text(sc, Pm + tab / 2, (y_top + y_bot) / 2, "GLUE / OVERLAP", 2.2, "cm", color=GREY, angle=90)
    tick = Style(GREY, 0.15)
    n_ticks = int(Pm // 5)
    for i in range(1, n_ticks + 1):
        u = i * 5.0
        if u >= Pm - 0.5:
            break
        h = 3.0 if i % 2 == 0 else 1.5
        sc.line(V(X(u), y_bot), V(X(u), y_bot + h), tick, "mitre_ticks", Z_FRAME)

    # reference (quadrant) lines, labelled along the line inside the body region
    names = [cut.ref_name, cut.side_name, cut.opp_name, cut.nside_name, cut.ref_name]
    dash = Style(REF, 0.2, dash=(2.5, 1.5))
    for q in range(5):
        x = X(q * Pm / 4)
        sc.line(V(x, y_bot), V(x, y_top), dash, "mitre_ref", Z_CENTERLINE)
        label = names[q] + (" (u = 0)" if q % 4 == 0 else "")
        right_edge = x > Pm - 1e-6
        _text(sc, x - 0.6 if right_edge else x + 0.6, y_bot + 4.0, label, 2.2, "lb" if right_edge else "lt",
              bold=True, color=REF, angle=90.0, layer="mitre_ref")

    # centre-to-centre end point line (v = 0)
    if y_bot < 0.0 < y_top:
        sc.line(V(0, 0), V(Pm, 0), Style("#7a7a7a", 0.15, dash=(4.0, 1.0, 1.0, 1.0)), "mitre_ref", Z_CENTERLINE)
        _text(sc, Pm - 1.0, 0.5, "c-c end point", 1.8, "rb", color="#7a7a7a", layer="mitre_ref")

    # the cut line
    sc.poly(curve, Style(INK, 0.5), "mitre_cut", Z_OVER)

    # long / short points
    mark = Style(INK, 0.0, fill=INK)
    vals = [p[1] for p in cut.points]
    if cut.short_point - cut.long_point > 0.3:
        for i in _extrema(vals, "min"):
            p = curve[i]
            sc.add(Polyline("mitre_marks", Z_OVER, mark, "", [p, p + V(-1.1, 2.2), p + V(1.1, 2.2)], True))
            _text(sc, p.x, p.y + 2.8, "LONG", 2.0, "cb", layer="mitre_marks")
        for i in _extrema(vals, "max"):
            p = curve[i]
            sc.add(Polyline("mitre_marks", Z_OVER, mark, "", [p, p + V(-1.1, -2.2), p + V(1.1, -2.2)], True))
            _text(sc, p.x, p.y - 2.8, "SHORT", 2.0, "ct", layer="mitre_marks")

    # region labels
    _text(sc, 0.0, y_top + 1.5, "▲ TUBE END: waste side shaded", 2.6, "lb", bold=True)
    i_short = max(range(len(vals)), key=lambda i: vals[i])
    if curve[i_short].y < y_top - 7 and Pm > 24:
        xw = min(max(curve[i_short].x, 10.0), Pm - 10.0)
        _text(sc, xw, (float(np.interp(xw, xs, ys)) + y_top) / 2, "WASTE", 2.4, "cm", color="#555555")
    _text(sc, X(Pm / 8), y_bot + min(body * 0.6, 16.0), "KEEP", 2.4, "cm", color="#555555")

    # data block (left column) and calibration square (right of it)
    def fl(mm: float) -> str:
        return _f(mm, units)

    lines: list[tuple[str, float, bool]] = []
    if title:
        lines.append((title, 3.6, True))
    lines.append((cut.label, 3.0, True))
    lines.append((f"Tube: {cut.tube_label or cut.tube} ({cut.tube}), {cut.end_label or 'end ' + cut.end}", 2.4, False))
    lines.append(("Receivers: " + ", ".join(cut.receiver_labels or cut.receivers), 2.4, False))
    if abs(cut.od - cut.width) < 1e-6:
        lines.append((f"Section: OD {fl(cut.od)}, wall {fl(cut.wall)}", 2.4, False))
    else:
        lines.append((f"Section: {fl(cut.od)} deep × {fl(cut.width)} wide", 2.4, False))
        lines.append((f"   {cut.profile}, wall {fl(cut.wall)}", 2.4, False))
    lines.append((f"Perimeter: {fl(Pm)}", 2.4, False))
    lines.append((f"Joint angle: {_deg(cut.angle)}   Offset: {fl(cut.offset)}", 2.4, False))
    if cut.offset_dir:
        lines.append((f"   (receiver axis toward {cut.offset_dir.lower()})", 2.4, False))
    lines.append((f"Hole saw: Ø{fl(cut.holesaw_diameter)}, {_deg(cut.holesaw_angle)} from square", 2.4, False))
    lines.append((f"Hole-saw offset: {fl(cut.holesaw_offset)}", 2.4, False))
    lines.append((f"Phase: {_deg(cut.phase)}   Saw axis: {_deg(cut.saw_rotation)} from {cut.ref_name}", 2.4, False))
    lines.append((f"Long point {fl(cut.long_point)}, short point {fl(cut.short_point)}", 2.4, False))
    lines.append(("   from the c-c end point (+ toward the body)", 2.4, False))
    lines.append(("Wrap print side out, top edge to the tube end;", 2.4, False))
    lines.append((f"align {cut.ref_name} with the tube's {cut.ref_name.lower()} face.", 2.4, False))
    for note in cut.notes:
        for k, part in enumerate(textwrap.wrap(note, 44)):
            lines.append((("• " if k == 0 else "  ") + part, 2.2, False))
    y = y_bot - 5.0
    y_text_top = y
    text_w = 0.0
    for s_, size, bold in lines:
        _text(sc, 0.0, y, s_, size, "lt", bold)
        text_w = max(text_w, _text_width(s_, size))
        y -= size * 1.6
    y_text_bottom = y

    # calibration square
    xc = text_w + 6.0
    yc = y_text_top
    cal = Style(INK, 0.3)
    sc.poly([V(xc, yc - 50), V(xc + 50, yc - 50), V(xc + 50, yc), V(xc, yc)], cal, "mitre_calibration",
            Z_FRAME, closed=True)
    for i in range(1, 5):
        sc.line(V(xc + 10 * i, yc - 50), V(xc + 10 * i, yc - 47), Style(INK, 0.15), "mitre_calibration", Z_FRAME)
        sc.line(V(xc, yc - 10 * i), V(xc + 3, yc - 10 * i), Style(INK, 0.15), "mitre_calibration", Z_FRAME)
    _text(sc, xc + 25, yc - 25, "50 mm", 3.0, "cm", bold=True, layer="mitre_calibration")
    _text(sc, xc + 25, yc - 51.5, "print at 100% — verify 50 mm", 2.2, "ct", layer="mitre_calibration")

    # invisible extent rectangle so Scene.bounds() covers text and margins
    x_max = max(Pm + tab, text_w, xc + 50) + 3
    y_min = min(y_text_bottom, yc - 55) - 3
    y_max = y_top + 6
    sc.poly([V(-3, y_min), V(x_max, y_min), V(x_max, y_max), V(-3, y_max)], Style(None, 0.0), _LAYER_EXTENT,
            Z_GRID, closed=True)
    return sc


def template_size(scene: Scene) -> tuple[float, float]:
    x0, y0, x1, y1 = scene.bounds()
    return x1 - x0, y1 - y0


def _scenes(cuts: Sequence[MitreCut], title: str, units: str, design=None) -> list[Scene]:
    body = float(design.get("mitre_template_body", 40.0)) if design is not None else 40.0
    tab = float(design.get("mitre_glue_tab", 12.0)) if design is not None else 12.0
    return [mitre_template_scene(c, title, units, body=body, tab=tab) for c in cuts]


# --------------------------------------------------------------------------
# PDF (true scale, tiled)
# --------------------------------------------------------------------------
@dataclass
class Placement:
    index: int                      # template index
    x: float                        # position in the printable area (mm, y down from the header)
    y: float
    window: tuple[float, float, float, float] | None = None   # template-local window (tiles), y down
    tile: tuple[int, int, int, int] | None = None              # (row, col, rows, cols)


def page_dimensions(page_size: str | tuple[float, float] = "A4", landscape: bool = True) -> tuple[float, float]:
    """(width, height) of the page in mm."""
    if isinstance(page_size, str):
        key = next((k for k in PAGE_SIZES_MM if k.lower() == page_size.lower()), "A4")
        w, h = PAGE_SIZES_MM[key]
    else:
        w, h = float(page_size[0]), float(page_size[1])
    w, h = min(w, h), max(w, h)
    return (h, w) if landscape else (w, h)


def plan_pages(sizes: Sequence[tuple[float, float]], area_w: float, area_h: float, gap: float = 6.0,
               overlap: float = 15.0) -> list[list[Placement]]:
    """Shelf-pack templates that fit; tile the others (one tile per page)."""
    pages: list[list[Placement]] = []
    cur: list[Placement] = []
    x = y = row_h = 0.0
    for i, (w, h) in enumerate(sizes):
        if w <= area_w + 1e-6 and h <= area_h + 1e-6:
            if cur and x + w > area_w + 1e-6:
                x, y, row_h = 0.0, y + row_h + gap, 0.0
            if cur and y + h > area_h + 1e-6:
                pages.append(cur)
                cur, x, y, row_h = [], 0.0, 0.0, 0.0
            cur.append(Placement(i, x, y))
            x += w + gap
            row_h = max(row_h, h)
            continue
        if cur:
            pages.append(cur)
            cur, x, y, row_h = [], 0.0, 0.0, 0.0
        sx, sy = area_w - overlap, area_h - overlap
        nx = 1 if w <= area_w else math.ceil((w - overlap) / sx)
        ny = 1 if h <= area_h else math.ceil((h - overlap) / sy)
        for r in range(ny):
            for c in range(nx):
                x0, y0 = c * sx, r * sy
                win = (x0, y0, min(x0 + area_w, w), min(y0 + area_h, h))
                pages.append([Placement(i, 0.0, 0.0, win, (r, c, ny, nx))])
    if cur:
        pages.append(cur)
    return pages


def _registration_scene(bounds, size: tuple[float, float], area_w: float, area_h: float,
                        overlap: float) -> Scene:
    """Registration marks and trim lines through the middle of every overlap strip
    (template coordinates)."""
    x0, y0, x1, y1 = bounds
    w, h = size
    sx, sy = area_w - overlap, area_h - overlap
    nx = 1 if w <= area_w else math.ceil((w - overlap) / sx)
    ny = 1 if h <= area_h else math.ceil((h - overlap) / sy)
    xs = [c * sx + overlap / 2 for c in range(1, nx)]          # local, y down
    ys = [r * sy + overlap / 2 for r in range(1, ny)]
    col_mid = [min(c * sx + area_w / 2, (c * sx + min(c * sx + area_w, w)) / 2) for c in range(nx)]
    row_mid = [min(r * sy + area_h / 2, (r * sy + min(r * sy + area_h, h)) / 2) for r in range(ny)]
    sc = Scene()
    trim = Style("#d02020", 0.15, dash=(3.0, 2.0))
    st = Style("#d02020", 0.2)

    def M(lx, ly):
        return V(x0 + lx, y1 - ly)

    for lx in xs:
        sc.line(M(lx, 0), M(lx, h), trim, "mitre_reg", Z_NOTE)
    for ly in ys:
        sc.line(M(0, ly), M(w, ly), trim, "mitre_reg", Z_NOTE)
    pts = [(lx, ly) for lx in xs for ly in row_mid + ys] + [(lx, ly) for ly in ys for lx in col_mid]
    seen = set()
    for k, (lx, ly) in enumerate(pts):
        key = (round(lx, 3), round(ly, 3))
        if key in seen:
            continue
        seen.add(key)
        c = M(lx, ly)
        sc.circle(c, 3.0, st, "mitre_reg", Z_NOTE)
        sc.line(c + V(-6, 0), c + V(6, 0), st, "mitre_reg", Z_NOTE)
        sc.line(c + V(0, -6), c + V(0, 6), st, "mitre_reg", Z_NOTE)
        _text(sc, c.x + 3.5, c.y + 3.5, f"R{len(seen)}", 2.0, "lb", color="#d02020", layer="mitre_reg")
    return sc


def _ensure_app():
    from ..qt import QtGui
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


def save_mitre_pdf(cuts: Sequence[MitreCut], path, page_size: str | tuple[float, float] = "A4",
                   landscape: bool = True, title: str = "", *, units: str = "mm", margin: float = 10.0,
                   overlap: float = 15.0, dpi: int = 1200, design=None) -> int:
    """Write the templates to a PDF at true scale.  Returns the number of pages.

    Templates that fit are packed several to a page; larger ones are tiled
    with ``overlap`` mm of overlap and numbered registration marks."""
    from ..qt import QtCore, QtGui
    from ..render.qt_render import QtSceneRenderer

    _ensure_app()
    if design is not None:
        margin = float(design.get("mitre_page_margin", margin))
        overlap = float(design.get("mitre_tile_overlap", overlap))
    scenes = _scenes(cuts, title, units, design)
    bounds = [s.bounds() for s in scenes]
    sizes = [(b[2] - b[0], b[3] - b[1]) for b in bounds]
    pw, ph = page_dimensions(page_size, landscape)
    area_w, area_h = pw - 2 * margin, ph - 2 * margin - HEADER_MM
    overlap = min(overlap, 0.45 * min(area_w, area_h))
    plan = plan_pages(sizes, area_w, area_h, 6.0, overlap) or [[]]

    writer = QtGui.QPdfWriter(str(path))
    writer.setResolution(dpi)
    writer.setTitle(title or "Mitre templates")
    writer.setCreator("FrameWright")
    size = QtGui.QPageSize(QtCore.QSizeF(min(pw, ph), max(pw, ph)), QtGui.QPageSize.Unit.Millimeter)
    orient = QtGui.QPageLayout.Orientation.Landscape if pw > ph else QtGui.QPageLayout.Orientation.Portrait
    writer.setPageLayout(QtGui.QPageLayout(size, orient, QtCore.QMarginsF(0, 0, 0, 0),
                                           QtGui.QPageLayout.Unit.Millimeter))
    k = dpi / 25.4                          # device px per mm: 1:1
    painter = QtGui.QPainter(writer)
    reg_cache: dict[int, Scene] = {}
    try:
        for pi, page in enumerate(plan):
            if pi:
                writer.newPage()
            info = ""
            for pl in page:
                sc, b = scenes[pl.index], bounds[pl.index]
                x0, _, _, y1 = b
                xf = QtGui.QTransform()
                if pl.window is None:
                    xf.translate(k * (margin + pl.x), k * (margin + HEADER_MM + pl.y))
                else:
                    wx0, wy0, wx1, wy1 = pl.window
                    xf.translate(k * (margin - wx0), k * (margin + HEADER_MM - wy0))
                    painter.setClipRect(QtCore.QRectF(k * margin, k * (margin + HEADER_MM),
                                                      k * (wx1 - wx0), k * (wy1 - wy0)))
                xf.scale(k, -k)
                xf.translate(-x0, -y1)
                r = QtSceneRenderer(painter, xf, k, k)
                r.draw(sc)
                if pl.window is not None:
                    if pl.index not in reg_cache:
                        reg_cache[pl.index] = _registration_scene(b, sizes[pl.index], area_w, area_h, overlap)
                    r.draw(reg_cache[pl.index])
                    painter.setClipping(False)
                    row, col, rows, cols = pl.tile
                    c = cuts[pl.index]
                    info = (f"{c.tube}.{c.end}: tile row {row + 1}/{rows}, column {col + 1}/{cols} — trim on the "
                            f"red dashed line and match the R marks ({overlap:.0f} mm overlap)")
            hdr = _page_header(pw, margin, f"{title + ' — ' if title else ''}Mitre templates — page "
                                            f"{pi + 1}/{len(plan)}", info)
            hx = QtGui.QTransform()
            hx.scale(k, -k)
            QtSceneRenderer(painter, hx, k, k).draw(hdr)
    finally:
        painter.end()
    return len(plan)


def _page_header(pw: float, margin: float, line1: str, line2: str) -> Scene:
    """Header strip in page coordinates (x mm from the left, y = -mm from the top)."""
    sc = Scene()
    _text(sc, margin, -(margin + 3.5), line1, 3.0, "lm", bold=True)
    if line2:
        _text(sc, margin, -(margin + 7.5), line2, 2.2, "lm")
    x1 = pw - margin
    y = -(margin + 6.0)
    st = Style(INK, 0.25)
    sc.line(V(x1 - 50, y), V(x1, y), st, "mitre_text", Z_NOTE)
    for x in (x1 - 50, x1):
        sc.line(V(x, y - 1.5), V(x, y + 1.5), st, "mitre_text", Z_NOTE)
    _text(sc, x1 - 25, y + 1.0, "50 mm scale check", 2.2, "cb")
    return sc


# --------------------------------------------------------------------------
# SVG / DXF (all templates at 1:1)
# --------------------------------------------------------------------------
def _stack(scenes: Sequence[Scene]) -> list[tuple[Scene, tuple[float, float, float, float]]]:
    out = []
    for sc in scenes:
        b = sc.bounds()
        sc.hidden_layers.add(_LAYER_EXTENT)
        out.append((sc, b))
    return out


def save_mitre_svg(cuts: Sequence[MitreCut], path, title: str = "", *, units: str = "mm", gap: float = 10.0,
                   margin: float = 10.0, design=None) -> None:
    """All templates stacked vertically at 1:1 in one SVG (millimetre user units)."""
    from .svg import SvgWriter
    items = _stack(_scenes(cuts, title, units, design))
    width = max([b[2] - b[0] for _, b in items] + [50.0]) + 2 * margin
    height = sum(b[3] - b[1] for _, b in items) + gap * max(len(items) - 1, 0) + 2 * margin
    sw = SvgWriter(1.0)
    y = margin
    for sc, b in items:
        sw.ox, sw.oy = margin - b[0], y + b[3]
        sw.add_scene(sc)
        y += b[3] - b[1] + gap
    Path(path).write_text(sw.document(width, height, "#ffffff", title or "Mitre templates"), encoding="utf-8")


_DXF_TEXT = {"→": "->", "—": "-", "–": "-", "×": "x", "Ø": "%%c", "±": "%%p", "▲": "^", "•": "-"}


def save_mitre_dxf(cuts: Sequence[MitreCut], path, title: str = "", *, units: str = "mm", gap: float = 10.0,
                   design=None) -> None:
    """All templates stacked downward at 1:1 in one R12 DXF (mm); fills are omitted, hatching kept."""
    from .dxf import DxfWriter
    dw = DxfWriter(1.0, annot=1.0)
    y = 0.0
    for sc, b in _stack(_scenes(cuts, title, units, design)):
        sc.hidden_layers.add(_LAYER_FILL)
        for prim in sc.prims:
            if isinstance(prim, Text):
                for a, r in _DXF_TEXT.items():
                    prim.text = prim.text.replace(a, r)
        dw.ox, dw.oy = -b[0], -y - b[3]
        dw.add_scene(sc)
        y += b[3] - b[1] + gap
    Path(path).write_text(dw.document(), encoding="ascii", errors="replace")


# --------------------------------------------------------------------------
# cut list
# --------------------------------------------------------------------------
def cut_list_rows(g: Geometry, cuts: Sequence[MitreCut], units: str = "mm") -> list[list[str]]:
    """Header + one row per tube: tube, qty, section, c-c length, long-to-long,
    short-to-short, minimum stock, joint angles and phase."""
    lengths = cut_lengths(g, list(cuts))
    rows = [["Tube", "Qty", "OD × wall", "C-C length", "Long-to-long", "Short-to-short", "Min stock",
             "Angles", "Phase"]]
    by: dict[str, dict[str, MitreCut]] = {}
    for c in cuts:
        by.setdefault(c.tube, {})[c.end] = c
    for name, info in lengths.items():
        tube = g.tubes[name]
        dec = 3 if units == "in" else 1

        def L(mm):
            return fmt_len(mm, units, dec)
        ods = sorted({round(tube.od_a, 3), round(tube.od_b, 3)})
        od = "–".join(L(o) for o in ods)
        if abs(tube.w_b - tube.od_b) > 1e-6:
            od += f" × {L(tube.w_b)} ({tube.profile})"
        angles = " / ".join(f"{_TAGS.get(c.receivers[0], c.receivers[0].upper())} {_deg(c.angle)}"
                            for e, c in sorted(by[name].items()))
        rows.append([info["label"], str(info["count"]), f"{od} × {L(info['wall'])}", L(info["cc"]),
                     L(info["long_to_long"]), L(info["short_to_short"]), L(info["min_stock"]), angles,
                     _deg(info["phase"])])
    return rows
