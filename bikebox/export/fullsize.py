"""Full-size (1:1) tiled PDF of the whole frame.

Prints the bike drawing at life size across as many pages as needed, with a
small overlap and crop marks so the sheets tape together into a 1:1 template
you can lay tubes on. Separate from the scaled drawing sheet in export.drawing.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..geometry.solver import Geometry
from ..qt import QtCore, QtGui
from ..render.bike_scene import build_scene
from ..render.qt_render import QtSceneRenderer

# page sizes in portrait (w, h) mm
PAGE_MM = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "Letter": (215.9, 279.4), "Tabloid": (279.4, 431.8)}


def tiling(bounds, page="A4", margin=10.0, overlap=8.0, landscape=True) -> dict:
    """Page grid for the given model bounds (minx,miny,maxx,maxy) in mm."""
    minx, miny, maxx, maxy = bounds
    pad = 10.0
    minx -= pad; miny -= pad; maxx += pad; maxy += pad
    pw, ph = PAGE_MM.get(page, PAGE_MM["A4"])
    if landscape:
        pw, ph = ph, pw
    step_w = max(pw - 2 * margin - overlap, 20.0)
    step_h = max(ph - 2 * margin - overlap, 20.0)
    cols = max(1, math.ceil((maxx - minx) / step_w))
    rows = max(1, math.ceil((maxy - miny) / step_h))
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy, "pw": pw, "ph": ph,
            "margin": margin, "step_w": step_w, "step_h": step_h, "cols": cols, "rows": rows}


def save_fullsize_pdf(g: Geometry, path, page="A4", margin=10.0, overlap=8.0, landscape=True,
                      dpi: int = 300, include_wheels: bool = False) -> Path:
    path = Path(path)
    scene = build_scene(g)
    if not include_wheels:                            # frame-only template: far fewer pages
        scene.hidden_layers = set(scene.hidden_layers) | {"wheels", "ground"}
    T = tiling(scene.bounds(), page, margin, overlap, landscape)
    k = dpi / 25.4                                    # device px per mm (1:1)
    writer = QtGui.QPdfWriter(str(path))
    writer.setResolution(dpi)
    writer.setPageSize(QtGui.QPageSize(QtCore.QSizeF(T["pw"], T["ph"]), QtGui.QPageSize.Unit.Millimeter))
    writer.setTitle((g.design.get("title") or "frame") + " (full size)")
    p = QtGui.QPainter(writer)
    first = True
    for r in range(T["rows"]):
        for c in range(T["cols"]):
            if not first:
                writer.newPage()
            first = False
            tile_x0 = T["minx"] + c * T["step_w"]
            tile_ytop = T["maxy"] - r * T["step_h"]
            xf = QtGui.QTransform()
            xf.translate(margin * k, margin * k)
            xf.scale(k, -k)
            xf.translate(-tile_x0, -tile_ytop)
            p.save()
            p.setClipRect(QtCore.QRectF(margin * k, margin * k,
                                        (T["pw"] - 2 * margin) * k, (T["ph"] - 2 * margin) * k))
            QtSceneRenderer(p, xf, k, k, hairline=True).draw(scene)
            p.restore()
            _marks(p, T, k, r, c)
    p.end()
    return path


def _marks(p: QtGui.QPainter, T: dict, k: float, r: int, c: int) -> None:
    """Crop marks at the printable corners + a tile label, in device pixels."""
    m = T["margin"] * k
    x1 = (T["pw"] - T["margin"]) * k
    y1 = (T["ph"] - T["margin"]) * k
    pen = QtGui.QPen(QtGui.QColor("#888"))
    pen.setWidthF(max(0.3 * k, 1.0))
    p.setPen(pen)
    L = 5 * k
    for (x, y) in ((m, m), (x1, m), (m, y1), (x1, y1)):
        p.drawLine(QtCore.QPointF(x - L, y), QtCore.QPointF(x + L, y))
        p.drawLine(QtCore.QPointF(x, y - L), QtCore.QPointF(x, y + L))
    f = p.font()
    f.setPointSizeF(8)
    p.setFont(f)
    p.drawText(QtCore.QPointF(m + 3, m + 12), f"row {r + 1}/{T['rows']}  col {c + 1}/{T['cols']}  ·  1:1")
