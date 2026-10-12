"""Multi-design PDF: one sheet per design plus an overlay comparison page.

The overlay page draws every design as a coloured outline aligned at the BB
(the model origin), with a legend and a side-by-side geometry table.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..geometry.solver import Geometry, solve
from ..model.design import Design
from ..render.bike_scene import BikeSceneBuilder
from ..render.scene import Scene, Style, Z_FRAME, Z_GHOST, Z_NOTE
from .drawing import (Sheet, SheetOptions, build_sheet, fit_scale, geometry_table, page_size,
                      save_sheets_pdf, scale_label, _draw_table, _rect, _text)

OVERLAY_COLORS = (
    "#1f6fbf", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17a2b8",
    "#8c564b", "#e377c2", "#bcbd22", "#555555",
)


def _overlay_bike_scene(geoms: Sequence[Geometry]) -> Scene:
    """A scene of coloured frame outlines, all aligned at the BB."""
    sc = Scene()
    sc.background = "#ffffff"
    if not geoms:
        return sc
    builder = BikeSceneBuilder(geoms[0], scene=sc)
    sc.background = "#ffffff"
    for i, g in enumerate(geoms):
        builder.ghost(g, OVERLAY_COLORS[i % len(OVERLAY_COLORS)])
    return sc


def _comparison_table(geoms: Sequence[Geometry], names: Sequence[str], units: str) -> list[list[str]]:
    tables = [geometry_table(g, units) for g in geoms]
    labels = [r[0] for r in tables[0][1:]]
    rows: list[list[str]] = [["Dimension"] + list(names)]
    for i, lbl in enumerate(labels):
        rows.append([lbl] + [t[i + 1][1] if i + 1 < len(t) else "" for t in tables])
    return rows


def _overlay_sheet(designs: Sequence[Design], geoms: Sequence[Geometry], opts: SheetOptions,
                   index: int, count: int) -> Sheet:
    names = [d.title or f"Design {i + 1}" for i, d in enumerate(designs)]
    units = "in" if designs and designs[0].get("units") == "in" else "mm"
    bike = _overlay_bike_scene(geoms)

    page_w, page_h = page_size(opts)
    m = opts.margin
    avail_w = page_w - 2 * m - 6.0
    avail_h = page_h - 2 * m - 6.0
    bounds = bike.bounds()
    scale = fit_scale(bounds, avail_w, avail_h, opts.scale)
    x0, y0, x1, y1 = bounds
    bw = (x1 - x0) * scale
    bh = (y1 - y0) * scale
    ox = (page_w - bw) / 2 - x0 * scale
    oy = (page_h - bh) / 2 - y0 * scale

    sheet = Sheet(opts.page, page_w, page_h, scale, (ox, oy), bike, Scene(), opts, index, count)

    # paper furniture: border, comparison table, legend, title
    paper = sheet.paper
    paper.background = "#ffffff"
    if opts.border:
        _rect(paper, m, m, page_w - m, page_h - m, Style("#000000", 0.6, None))
    _text(paper, m + 3.0, page_h - m - 7.0, "Geometry comparison", 4.0, "lb", bold=True)
    y = page_h - m - 12.0
    y = _draw_table(paper, _comparison_table(geoms, names, units), m + 3.0, y, "")

    # legend
    from ..geometry.vec import V
    y -= 8.0
    for i, name in enumerate(names):
        color = OVERLAY_COLORS[i % len(OVERLAY_COLORS)]
        yy = y - i * 6.0
        paper.line(V(m + 4.0, yy), V(m + 16.0, yy), Style(color, 0.8, None), "sheet", Z_NOTE)
        _text(paper, m + 18.0, yy - 1.4, name, 2.8, "lb")
    _text(paper, page_w - m - 3.0, m + 3.0, f"{len(designs)} designs   {scale_label(scale)}", 2.6, "rb")
    return sheet


def save_multi_pdf(designs: Sequence[Design], path, opts: SheetOptions | None = None,
                   overlay_page: bool = True) -> Path:
    opts = opts or SheetOptions()
    designs = list(designs)
    if not designs:
        raise ValueError("no designs")
    geoms = [solve(d) for d in designs]
    count = len(designs) + (1 if overlay_page else 0)
    sheets: list[Sheet] = []
    for i, d in enumerate(designs):
        sheets.append(build_sheet(d, geometry=geoms[i], opts=opts, index=i + 1, count=count))
    if overlay_page:
        sheets.append(_overlay_sheet(designs, geoms, opts, count, count))
    return save_sheets_pdf(sheets, path)
