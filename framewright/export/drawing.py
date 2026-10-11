"""BikeCAD-style dimensioned drawing sheets.

A :class:`Sheet` carries a page size (paper mm), the bike :class:`Scene` (model
mm), the model->paper placement (a uniform ``scale`` in paper mm per model mm
plus an ``offset``) and a second *paper-space* :class:`Scene` holding the sheet
furniture (border, title block, tables, scale bar).  The paper scene is drawn
in paper millimetres with **+Y up** and the origin at the bottom-left corner of
the page, matching the model scene's +Y-up convention so the two compose with a
single Y flip at render time.

The sheet renders through :class:`~framewright.render.qt_render.QtSceneRenderer`
onto any paint device (PDF via ``QPdfWriter``, PNG via ``QImage``, a printer via
``QPrinter``) and to SVG through :class:`~framewright.export.svg.SvgWriter`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..geometry.solver import Geometry, solve
from ..model import params as P
from ..model.design import Design
from ..model.units import MM_PER_IN, fmt_angle, fmt_len
from ..render.bike_scene import build_scene
from ..render.scene import Scene, Style, Text, Z_FRAME, Z_NOTE

# --------------------------------------------------------------------------
# page sizes (paper millimetres, landscape: width >= height)
# --------------------------------------------------------------------------
PAGE_SIZES: dict[str, tuple[float, float] | None] = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "Letter": (11.0 * MM_PER_IN, 8.5 * MM_PER_IN),       # 279.4 x 215.9
    "Legal": (14.0 * MM_PER_IN, 8.5 * MM_PER_IN),        # 355.6 x 215.9
    "Tabloid": (17.0 * MM_PER_IN, 11.0 * MM_PER_IN),     # 431.8 x 279.4
    "ARCH C": (24.0 * MM_PER_IN, 18.0 * MM_PER_IN),      # 609.6 x 457.2
    "ARCH D": (36.0 * MM_PER_IN, 24.0 * MM_PER_IN),      # 914.4 x 609.6
    "custom": None,
}

# (value, label) where value = paper mm per model mm
STANDARD_SCALES: tuple[tuple[float, str], ...] = (
    (1.0, "1:1"), (0.5, "1:2"), (0.4, "1:2.5"), (0.25, "1:4"), (0.2, "1:5"),
    (0.125, "1:8"), (0.1, "1:10"), (1.0 / 15.0, "1:15"), (0.05, "1:20"),
)


def scale_label(value: float) -> str:
    """A ``1:N`` style label for a scale value (paper mm per model mm)."""
    for v, lbl in STANDARD_SCALES:
        if abs(v - value) < 1e-9:
            return lbl
    if value <= 0:
        return "1:1"
    n = 1.0 / value
    if value > 1.0:
        return f"{value:g}:1"
    return f"1:{n:.10g}"


# register our own parameters (GUI editors, CSV columns)
P.register([
    P.ParamDef("drawing_company", "Company / builder", "Drawing", "Title block", P.STR, "",
               help="Shown in the drawing title block (falls back to extras['title_block']['company'])",
               morph=False),
    P.ParamDef("drawing_revision", "Revision", "Drawing", "Title block", P.STR, "",
               morph=False),
    P.ParamDef("drawing_approved", "Approved by", "Drawing", "Title block", P.STR, "",
               morph=False),
    P.ParamDef("drawing_page", "Default sheet size", "Drawing", "Sheet", P.CHOICE, "A3",
               choices=tuple((k, k) for k in PAGE_SIZES if k != "custom"), morph=False),
])


@dataclass
class SheetOptions:
    page: str = "A3"
    landscape: bool = True
    scale: float | None = None           # None -> largest standard scale that fits
    margin: float = 10.0                 # paper mm
    border: bool = True
    title_block: bool = True
    geometry_table: bool = True
    tube_table: bool = False
    custom_tables: bool = True
    monochrome: bool = False
    dpi: int = 300
    custom_size: tuple[float, float] = (420.0, 297.0)
    scale_bar: bool = True
    dimensions: bool = True


@dataclass
class Sheet:
    page: str
    page_w: float                        # paper mm
    page_h: float
    scale: float                         # paper mm per model mm
    offset: tuple[float, float]          # model->paper offset (paper mm)
    bike: Scene                          # model-space scene
    paper: Scene                         # paper-space scene (+Y up, origin bottom-left)
    opts: SheetOptions
    index: int = 1
    count: int = 1

    def model_to_paper(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]


# --------------------------------------------------------------------------
# page helpers
# --------------------------------------------------------------------------
def page_size(opts: SheetOptions) -> tuple[float, float]:
    sz = PAGE_SIZES.get(opts.page)
    if sz is None:                       # custom
        w, h = opts.custom_size
    else:
        w, h = sz
    w, h = float(w), float(h)
    if opts.landscape:
        w, h = max(w, h), min(w, h)
    else:
        w, h = min(w, h), max(w, h)
    return w, h


def fit_scale(bounds: tuple[float, float, float, float], avail_w: float, avail_h: float,
              requested: float | None) -> float:
    """Largest standard scale whose scaled model bounds fit, or ``requested``."""
    x0, y0, x1, y1 = bounds
    bw = max(x1 - x0, 1e-6)
    bh = max(y1 - y0, 1e-6)
    if requested is not None:
        return float(requested)
    for v, _ in STANDARD_SCALES:         # largest first
        if bw * v <= avail_w and bh * v <= avail_h:
            return v
    # nothing standard fits: fall back to an exact fit (not a round ratio)
    return min(avail_w / bw, avail_h / bh)


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
def geometry_table(g: Geometry, units: str = "mm") -> list[list[str]]:
    """Standard geometry rows as ``[[label, value], ...]`` (header first)."""
    v = g.v
    L = lambda key: fmt_len(v.get(key, float("nan")), units, suffix=False)
    A = lambda key: fmt_angle(v.get(key, float("nan")))
    rows: list[list[str]] = [["Dimension", f"Value ({units})"]]
    rows += [
        ["Stack", L("stack")],
        ["Reach", L("reach")],
        ["Effective top tube", L("top_tube_effective")],
        ["Seat tube (c-t)", L("seat_tube_ct")],
        ["Head tube length", L("head_tube_length")],
        ["Head tube angle", A("head_tube_angle")],
        ["Seat tube angle", A("seat_tube_angle")],
        ["Chainstay length", L("chainstay_length")],
        ["BB drop", L("bb_drop")],
        ["BB height", L("bb_height")],
        ["Wheelbase", L("wheelbase")],
        ["Front centre", L("front_center")],
        ["Fork axle-to-crown", L("fork_length")],
        ["Fork offset", L("fork_offset")],
        ["Trail", L("trail")],
        ["Standover", L("standover")],
    ]
    return rows


_TUBE_ORDER = ("tt", "dt", "st", "ht", "cs", "ss", "ss_mono", "fork")


def tube_table(g: Geometry, units: str = "mm") -> list[list[str]]:
    """Tube schedule: ``[[tube, OD x wall, material, c-c length, mass], ...]``."""
    rows: list[list[str]] = [["Tube", "OD x wall", "Material", "Length (c-c)", "Mass"]]
    seen: set[str] = set()
    names = [n for n in _TUBE_ORDER if n in g.tubes]
    names += [n for n in g.tubes if n not in seen and n not in names]
    for name in names:
        t = g.tubes.get(name)
        if t is None:
            continue
        seen.add(name)
        od = max(t.od_a, t.od_b, t.w_a, t.w_b)
        wall = min(t.wall_end, t.wall_mid)
        od_s = fmt_len(od, units, suffix=False)
        wall_s = fmt_len(wall, units, suffix=False)
        length = fmt_len(t.chord, units, suffix=False)
        label = t.label + (" (pair)" if t.mirrored else "")
        rows.append([label, f"{od_s} x {wall_s}", str(t.material).capitalize(), length, f"{t.mass():.0f} g"])
    return rows


# --------------------------------------------------------------------------
# paper-space furniture
# --------------------------------------------------------------------------
_LINE = Style("#000000", 0.35, None)
_THIN = Style("#000000", 0.18, None)
_HEAVY = Style("#000000", 0.6, None)


def _rect(sc: Scene, x0: float, y0: float, x1: float, y1: float, style: Style, layer="sheet") -> None:
    from ..geometry.vec import V
    sc.poly([V(x0, y0), V(x1, y0), V(x1, y1), V(x0, y1)], style, layer, Z_FRAME, closed=True)


def _text(sc: Scene, x: float, y: float, s: str, size: float, anchor="lb", bold=False) -> None:
    from ..geometry.vec import V
    sc.add(Text("sheet", Z_NOTE, _LINE, "", V(x, y), s, size, 0.0, anchor, True, "Sans Serif", bold))


def _draw_table(sc: Scene, rows: list[list[str]], x: float, y_top: float, title: str = "",
                col_w: Sequence[float] | None = None, row_h: float = 6.0, size: float = 2.6) -> float:
    """Draw a table with its top-left at ``(x, y_top)`` (paper mm, +Y up).

    Returns the y of the bottom edge."""
    from ..geometry.vec import V
    if not rows:
        return y_top
    ncol = max(len(r) for r in rows)
    if col_w is None:
        widths = [0.0] * ncol
        for r in rows:
            for i, cell in enumerate(r):
                widths[i] = max(widths[i], len(str(cell)))
        col_w = [max(14.0, w * size * 0.62 + 4.0) for w in widths]
    total_w = sum(col_w)
    y = y_top
    if title:
        _text(sc, x, y + 1.5, title, size + 0.6, "lb", bold=True)
        y -= row_h * 0.3
    header = True
    for r in rows:
        y0 = y - row_h
        _rect(sc, x, y0, x + total_w, y, _THIN)
        cx = x
        for i in range(ncol):
            if i:
                sc.line(V(cx, y0), V(cx, y), _THIN, "sheet", Z_FRAME)
            cell = str(r[i]) if i < len(r) else ""
            _text(sc, cx + 1.4, y0 + row_h * 0.3, cell, size, "lb", bold=header)
            cx += col_w[i]
        y = y0
        header = False
    return y


def _title_block(sc: Scene, sheet: "Sheet", design: Design) -> None:
    from ..geometry.vec import V
    opts = sheet.opts
    m = opts.margin
    tb = design.extras.get("title_block") or {}

    def field(key: str, param: str | None = None) -> str:
        if tb.get(key):
            return str(tb[key])
        if param and design.get(param):
            return str(design.get(param))
        return ""

    w = min(190.0, sheet.page_w - 2 * m)
    h = 34.0
    x1 = sheet.page_w - m
    x0 = x1 - w
    y0 = m
    y1 = y0 + h
    _rect(sc, x0, y0, x1, y1, _HEAVY)

    import datetime as _dt
    date = field("date") or _dt.date.today().isoformat()
    title = field("title", "title") or design.title
    company = field("company", "drawing_company")
    designer = field("designer", "designer")
    customer = field("customer", "customer")
    size_lbl = field("size", "frame_size_label")
    dwg_no = field("drawing_number", "drawing_number")
    rev = field("revision", "drawing_revision")
    units = "in" if design.get("units") == "in" else "mm"

    # logo (optional): top-left cell of the block
    logo = tb.get("logo")
    pad = 2.0
    logo_w = 0.0
    if logo and Path(str(logo)).exists():
        from ..render.scene import Image, Z_PHOTO
        lh = h - 2 * pad
        try:
            from ..qt import QtGui
            img = QtGui.QImage(str(logo))
            if not img.isNull() and img.height():
                mm_per_px = lh / img.height()
                logo_w = img.width() * mm_per_px + pad
                sc.add(Image("sheet", Z_PHOTO, Style(None, 0.0, None), "", path=str(logo),
                             origin=V(x0 + pad, y1 - pad), mm_per_px=mm_per_px, rotation=0.0, flip=False))
        except Exception:
            logo_w = 0.0

    lx = x0 + pad + logo_w
    # big title line
    _text(sc, lx, y1 - 7.5, title or "Untitled", 4.0, "lb", bold=True)
    if company:
        _text(sc, lx, y1 - 12.5, company, 2.6, "lb")

    # a grid of labelled fields along the bottom
    cells = [
        ("Designer", designer), ("Customer", customer), ("Size", size_lbl),
        ("Drawing no.", dwg_no), ("Rev", rev), ("Date", date),
        ("Scale", scale_label(sheet.scale)), ("Units", units),
        ("Sheet", f"{sheet.index}/{sheet.count}"),
    ]
    cols = 3
    cw = (x1 - lx) / cols
    rh = 7.5
    for i, (lbl, val) in enumerate(cells):
        r, c = divmod(i, cols)
        cxx = lx + c * cw
        cyy = y0 + 1.0 + r * rh
        _text(sc, cxx + 0.8, cyy + 3.2, lbl, 1.7, "lb")
        _text(sc, cxx + 0.8, cyy + 0.2, val or "-", 2.5, "lb", bold=True)


def _scale_bar(sc: Scene, sheet: "Sheet") -> None:
    from ..geometry.vec import V
    m = sheet.opts.margin
    s = sheet.scale
    # choose a round model length whose bar is roughly 60 paper mm
    target_mm_paper = 60.0
    model_len = target_mm_paper / s
    nice = [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000]
    model_len = min(nice, key=lambda n: abs(n - model_len))
    bar = model_len * s
    x0 = m + 2.0
    y0 = m + 2.0
    seg = bar / 4.0
    for i in range(4):
        st = _HEAVY.with_(fill="#000000" if i % 2 else "#ffffff", width=0.3)
        sc.poly([V(x0 + i * seg, y0), V(x0 + (i + 1) * seg, y0),
                 V(x0 + (i + 1) * seg, y0 + 2.0), V(x0 + i * seg, y0 + 2.0)],
                st, "sheet", Z_FRAME, closed=True)
    _text(sc, x0, y0 + 3.0, "0", 2.0, "cb")
    _text(sc, x0 + bar, y0 + 3.0, f"{model_len:g} mm", 2.0, "cb")
    _text(sc, x0 + bar / 2, y0 - 2.4, scale_label(s), 2.2, "ct", bold=True)


def build_paper_scene(sheet: "Sheet", design: Design, g: Geometry) -> Scene:
    sc = Scene()
    sc.background = "#ffffff"
    opts = sheet.opts
    m = opts.margin
    if opts.border:
        _rect(sc, m, m, sheet.page_w - m, sheet.page_h - m, _HEAVY)
        _rect(sc, m * 0.5, m * 0.5, sheet.page_w - m * 0.5, sheet.page_h - m * 0.5, _THIN)
    units = "in" if design.get("units") == "in" else "mm"

    # tables down the top-left corner
    y = sheet.page_h - m - 4.0
    if opts.geometry_table:
        y = _draw_table(sc, geometry_table(g, units), m + 3.0, y, "Geometry")
        y -= 6.0
    if opts.tube_table:
        y = _draw_table(sc, tube_table(g, units), m + 3.0, y, "Tubing")
        y -= 6.0
    if opts.custom_tables:
        for tbl in (design.extras.get("tables") or []):
            rows = tbl.get("rows") or []
            if not rows:
                continue
            tx = float(tbl.get("x", m + 3.0))
            ty = float(tbl.get("y", y))
            y_bottom = _draw_table(sc, rows, tx, ty, str(tbl.get("title", "")))
            if "y" not in tbl:
                y = y_bottom - 6.0
    if opts.scale_bar:
        _scale_bar(sc, sheet)
    if opts.title_block:
        _title_block(sc, sheet, design)
    return sc


# --------------------------------------------------------------------------
# monochrome
# --------------------------------------------------------------------------
def _apply_monochrome(scene: Scene) -> None:
    from ..render.scene import Gradient
    for prim in scene.prims:
        st = prim.style
        fill = st.fill
        if fill is not None and not isinstance(fill, Gradient) and st.stroke in (None, ""):
            # fill-only glyph (e.g. dimension arrowhead): keep it solid black
            prim.style = st.with_(fill="#000000", stroke=None, opacity=1.0)
        else:
            prim.style = st.with_(stroke="#000000", fill=None, opacity=1.0)


# --------------------------------------------------------------------------
# sheet construction
# --------------------------------------------------------------------------
def _normalize_ghosts(ghosts: Sequence) -> list[tuple[Geometry, str]]:
    out: list[tuple[Geometry, str]] = []
    for item in ghosts or ():
        gg, color = item
        if isinstance(gg, Design):
            gg = solve(gg)
        out.append((gg, color))
    return out


def build_sheet(design: Design, geometry: Geometry | None = None, opts: SheetOptions | None = None,
                ghosts: Sequence = (), index: int = 1, count: int = 1) -> Sheet:
    opts = opts or SheetOptions()
    g = geometry or solve(design)
    bike = build_scene(g, dimensions=opts.dimensions, ghosts=_normalize_ghosts(ghosts))
    if opts.monochrome:
        _apply_monochrome(bike)
        bike.background = "#ffffff"

    page_w, page_h = page_size(opts)
    m = opts.margin
    avail_w = page_w - 2 * m - 6.0
    avail_h = page_h - 2 * m - 6.0
    bounds = bike.bounds()
    scale = fit_scale(bounds, avail_w, avail_h, opts.scale)

    x0, y0, x1, y1 = bounds
    bw = (x1 - x0) * scale
    bh = (y1 - y0) * scale
    # centre the drawing within the page interior
    ox = (page_w - bw) / 2 - x0 * scale
    oy = (page_h - bh) / 2 - y0 * scale

    sheet = Sheet(opts.page, page_w, page_h, scale, (ox, oy), bike, Scene(), opts, index, count)
    sheet.paper = build_paper_scene(sheet, design, g)
    return sheet


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def render_sheet(painter, sheet: Sheet, dpi: float) -> None:
    """Paint ``sheet`` onto a QPainter whose device is the page at ``dpi``."""
    from ..qt import QtGui
    from ..render.qt_render import QtSceneRenderer
    QTransform = QtGui.QTransform

    ppm = dpi / MM_PER_IN                       # device px per paper mm
    page_h_px = sheet.page_h * ppm

    # paper space: paper mm (+Y up, origin bottom-left) -> device (Y down, top-left)
    paper_xf = QTransform()
    paper_xf.translate(0.0, page_h_px)
    paper_xf.scale(ppm, -ppm)
    QtSceneRenderer(painter, paper_xf, ppm, ppm).draw(sheet.paper)

    # model space: model mm -> paper mm (scale/offset) -> device
    ox, oy = sheet.offset
    model_xf = QTransform()
    model_xf.translate(0.0, page_h_px)
    model_xf.scale(ppm, -ppm)
    model_xf.translate(ox, oy)
    model_xf.scale(sheet.scale, sheet.scale)
    QtSceneRenderer(painter, model_xf, sheet.scale * ppm, ppm).draw(sheet.bike)


def _pdf_writer(path, sheet: Sheet):
    from ..qt import QtCore, QtGui
    w = QtGui.QPdfWriter(str(path))
    w.setResolution(sheet.opts.dpi)
    orient = (QtGui.QPageLayout.Orientation.Landscape if sheet.page_w >= sheet.page_h
              else QtGui.QPageLayout.Orientation.Portrait)
    size = QtGui.QPageSize(QtCore.QSizeF(sheet.page_w, sheet.page_h), QtGui.QPageSize.Unit.Millimeter)
    layout = QtGui.QPageLayout(size, orient, QtCore.QMarginsF(0, 0, 0, 0))
    w.setPageLayout(layout)
    return w


def save_pdf(design: Design, path, opts: SheetOptions | None = None, ghosts: Sequence = ()) -> Path:
    """Vector PDF.  A single design is one page."""
    opts = opts or SheetOptions()
    sheet = build_sheet(design, opts=opts, ghosts=ghosts)
    return save_sheets_pdf([sheet], path)


def save_sheets_pdf(sheets: Sequence[Sheet], path) -> Path:
    """Write several :class:`Sheet` objects to a multi-page PDF."""
    from ..qt import QtCore, QtGui
    sheets = list(sheets)
    if not sheets:
        raise ValueError("no sheets to write")
    path = Path(path)
    writer = _pdf_writer(path, sheets[0])
    painter = QtGui.QPainter(writer)
    try:
        for i, sheet in enumerate(sheets):
            if i:
                orient = (QtGui.QPageLayout.Orientation.Landscape if sheet.page_w >= sheet.page_h
                          else QtGui.QPageLayout.Orientation.Portrait)
                size = QtGui.QPageSize(QtCore.QSizeF(sheet.page_w, sheet.page_h),
                                       QtGui.QPageSize.Unit.Millimeter)
                writer.setPageLayout(QtGui.QPageLayout(size, orient, QtCore.QMarginsF(0, 0, 0, 0)))
                writer.newPage()
            render_sheet(painter, sheet, writer.resolution())
    finally:
        painter.end()
    return path


def save_sheet_png(design: Design, path, opts: SheetOptions | None = None, dpi: int = 150) -> Path:
    from ..qt import QtGui
    opts = opts or SheetOptions()
    sheet = build_sheet(design, opts=opts)
    ppm = dpi / MM_PER_IN
    w = max(1, int(round(sheet.page_w * ppm)))
    h = max(1, int(round(sheet.page_h * ppm)))
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QtGui.QColor("#ffffff"))
    painter = QtGui.QPainter(img)
    try:
        render_sheet(painter, sheet, dpi)
    finally:
        painter.end()
    path = Path(path)
    img.save(str(path))
    return path


def save_sheet_svg(design: Design, path, opts: SheetOptions | None = None) -> Path:
    """Vector SVG sheet (bike at scale, furniture at 1:1, single Y flip)."""
    from .svg import SvgWriter
    opts = opts or SheetOptions()
    sheet = build_sheet(design, opts=opts)
    ox, oy = sheet.offset
    sw = SvgWriter(sheet.scale, ox, sheet.page_h - oy)
    sw.add_scene(sheet.bike)
    sw.k, sw.ox, sw.oy = 1.0, 0.0, sheet.page_h
    sw.add_scene(sheet.paper)
    doc = sw.document(sheet.page_w, sheet.page_h, "#ffffff", design.title)
    path = Path(path)
    path.write_text(doc, encoding="utf-8")
    return path


def print_sheet(design: Design, printer, opts: SheetOptions | None = None) -> None:
    """Paint a sheet onto a ``QPrinter``."""
    from ..qt import QtCore, QtGui
    opts = opts or SheetOptions()
    sheet = build_sheet(design, opts=opts)
    try:
        orient = (QtGui.QPageLayout.Orientation.Landscape if sheet.page_w >= sheet.page_h
                  else QtGui.QPageLayout.Orientation.Portrait)
        size = QtGui.QPageSize(QtCore.QSizeF(sheet.page_w, sheet.page_h), QtGui.QPageSize.Unit.Millimeter)
        printer.setPageLayout(QtGui.QPageLayout(size, orient, QtCore.QMarginsF(0, 0, 0, 0)))
    except Exception:
        pass
    painter = QtGui.QPainter(printer)
    try:
        dpi = printer.resolution() if hasattr(printer, "resolution") else opts.dpi
        render_sheet(painter, sheet, dpi)
    finally:
        painter.end()
