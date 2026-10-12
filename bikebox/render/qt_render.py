"""Render a :class:`Scene` with QPainter (screen, PNG, PDF, printer)."""
from __future__ import annotations

import math
from functools import lru_cache

from ..qt import QtCore, QtGui
from .scene import (Arc, AngleDim, Circle, Gradient, Image, LinearDim, Polyline, Prim, Scene, Style, Text,
                    explode_dimension)

QPointF, QRectF, Qt = QtCore.QPointF, QtCore.QRectF, QtCore.Qt
QColor, QPen, QBrush, QPainterPath, QFont, QTransform = (QtGui.QColor, QtGui.QPen, QtGui.QBrush,
                                                       QtGui.QPainterPath, QtGui.QFont, QtGui.QTransform)

_CAP = {"round": Qt.PenCapStyle.RoundCap, "flat": Qt.PenCapStyle.FlatCap, "square": Qt.PenCapStyle.SquareCap}
_JOIN = {"round": Qt.PenJoinStyle.RoundJoin, "miter": Qt.PenJoinStyle.MiterJoin, "bevel": Qt.PenJoinStyle.BevelJoin}


@lru_cache(maxsize=256)
def _color(spec: str) -> QColor:
    c = QColor(spec)
    return c if c.isValid() else QColor("#000000")


@lru_cache(maxsize=32)
def _image(path: str):
    img = QtGui.QImage(path)
    return None if img.isNull() else img


class QtSceneRenderer:
    """Draw a scene through a model->device transform.

    ``px_per_mm`` is device pixels per model millimetre at the current zoom.
    ``paper_px_per_mm`` is device pixels per *paper* millimetre, used for line
    widths and annotative text (on screen this is a fixed UI scale; on paper
    it is the device resolution).
    """

    def __init__(self, painter: QtGui.QPainter, model_to_device: QTransform, px_per_mm: float,
                 paper_px_per_mm: float, hairline: bool = False):
        self.p = painter
        self.xf = model_to_device
        self.px_per_mm = px_per_mm
        self.paper = paper_px_per_mm
        self.annot = paper_px_per_mm / max(px_per_mm, 1e-9)    # model mm per paper mm
        self.hairline = hairline

    # helpers ---------------------------------------------------------------------
    def _pen(self, st: Style) -> QPen:
        if not st.stroke or st.width < 0:
            return QPen(Qt.PenStyle.NoPen)
        c = QColor(_color(st.stroke))
        if st.opacity < 1:
            c.setAlphaF(st.opacity)
        pen = QPen(c)
        w = st.width * self.paper
        pen.setWidthF(max(w, 0.6 if not self.hairline else 0.0))
        pen.setCapStyle(_CAP.get(st.cap, Qt.PenCapStyle.RoundCap))
        pen.setJoinStyle(_JOIN.get(st.join, Qt.PenJoinStyle.RoundJoin))
        if st.dash:
            pen.setDashPattern([max(v / max(st.width, 0.05), 0.5) for v in st.dash])
        if st.width == 0:
            return QPen(Qt.PenStyle.NoPen)
        return pen

    def _brush(self, st: Style) -> QBrush:
        f = st.fill
        if f is None:
            return QBrush(Qt.BrushStyle.NoBrush)
        if isinstance(f, Gradient):
            p0 = self.xf.map(QPointF(*f.p0))
            p1 = self.xf.map(QPointF(*f.p1))
            grad = QtGui.QLinearGradient(p0, p1)
            for pos, col in f.stops:
                c = QColor(_color(col))
                if st.opacity < 1:
                    c.setAlphaF(st.opacity)
                grad.setColorAt(max(0.0, min(1.0, pos)), c)
            return QBrush(grad)
        c = QColor(_color(f))
        if st.opacity < 1:
            c.setAlphaF(st.opacity)
        return QBrush(c)

    def _map(self, v) -> QPointF:
        return self.xf.map(QPointF(v.x, v.y))

    # main ----------------------------------------------------------------------------
    def draw(self, scene: Scene, prims=None) -> None:
        p = self.p
        p.save()
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        for prim in (scene.visible() if prims is None else prims):
            self.draw_prim(prim)
        p.restore()

    def draw_prim(self, prim: Prim) -> None:
        p = self.p
        if isinstance(prim, (LinearDim, AngleDim)):
            for sub in explode_dimension(prim, self.annot):
                self.draw_prim(sub)
            return
        st = prim.style
        if isinstance(prim, Polyline):
            if len(prim.pts) < 2:
                return
            path = QPainterPath()
            path.moveTo(self._map(prim.pts[0]))
            for v in prim.pts[1:]:
                path.lineTo(self._map(v))
            if prim.closed:
                path.closeSubpath()
                for hole in prim.holes:
                    if len(hole) > 2:
                        path.moveTo(self._map(hole[0]))
                        for v in hole[1:]:
                            path.lineTo(self._map(v))
                        path.closeSubpath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                p.setBrush(self._brush(st))
            else:
                p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            p.setPen(self._pen(st))
            p.drawPath(path)
        elif isinstance(prim, Circle):
            c = self._map(prim.c)
            r = prim.r * self.px_per_mm
            p.setPen(self._pen(st))
            p.setBrush(self._brush(st))
            p.drawEllipse(c, r, r)
        elif isinstance(prim, Arc):
            c = self._map(prim.c)
            r = prim.r * self.px_per_mm
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            p.setPen(self._pen(st))
            p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            # model y-up -> device y-down: Qt angles are CCW on screen already
            p.drawArc(rect, int(round(prim.start * 16)), int(round(prim.span * 16)))
        elif isinstance(prim, Text):
            self._text(prim)
        elif isinstance(prim, Image):
            img = _image(prim.path)
            if img is None:
                return
            p.save()
            p.setOpacity(st.opacity)
            o = self._map(prim.origin)
            p.translate(o)
            p.rotate(-prim.rotation)
            k = prim.mm_per_px * self.px_per_mm
            p.scale(-k if prim.flip else k, k)
            p.drawImage(QPointF(0, 0), img)
            p.restore()

    def _text(self, t: Text) -> None:
        if not t.text:
            return
        p = self.p
        size_px = (t.size * self.paper) if t.annotative else (t.size * self.px_per_mm)
        if size_px < 1.5:
            return
        font = QFont(t.font)
        font.setPixelSize(max(1, int(round(size_px * 1.38))))   # cap-height ≈ 0.72 em
        font.setBold(t.bold)
        font.setItalic(t.italic)
        p.save()
        p.setFont(font)
        fm = QtGui.QFontMetricsF(font)
        lines = t.text.split("\n")
        w = max(fm.horizontalAdvance(s) for s in lines)
        line_h = fm.height()
        h = line_h * len(lines)
        pos = self._map(t.pos)
        p.translate(pos)
        p.rotate(-t.angle)
        ax, ay = (t.anchor + "m")[0], (t.anchor + "m")[1]
        x = {"l": 0.0, "c": -w / 2, "r": -w}.get(ax, -w / 2)
        y_top = {"t": 0.0, "m": -h / 2, "b": -h}.get(ay, -h / 2)
        if t.box:
            pad = 0.25 * line_h
            p.setPen(QPen(_color(t.style.stroke or "#000"), 0.6))
            p.setBrush(QBrush(QColor(255, 255, 255, 225)))
            p.drawRect(QRectF(x - pad, y_top - pad, w + 2 * pad, h + 2 * pad))
        col = _color(t.style.stroke or "#000000")
        p.setPen(QPen(col))
        for i, s in enumerate(lines):
            lw = fm.horizontalAdvance(s)
            lx = x + {"l": 0.0, "c": (w - lw) / 2, "r": w - lw}.get(ax, (w - lw) / 2)
            p.drawText(QPointF(lx, y_top + fm.ascent() + i * line_h), s)
        p.restore()


def fit_transform(bounds, width_px: float, height_px: float, margin_px: float = 20.0) -> tuple[QTransform, float]:
    """Model->device transform that fits ``bounds`` into a device rectangle."""
    x0, y0, x1, y1 = bounds
    bw = max(x1 - x0, 1.0)
    bh = max(y1 - y0, 1.0)
    k = min((width_px - 2 * margin_px) / bw, (height_px - 2 * margin_px) / bh)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    xf = QTransform()
    xf.translate(width_px / 2, height_px / 2)
    xf.scale(k, -k)
    xf.translate(-cx, -cy)
    return xf, k


def render_image(scene: Scene, width: int = 1600, height: int = 1000, bounds=None, scale_ui: float = 2.0,
                 background: str | None = None) -> QtGui.QImage:
    img = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(_color(background or scene.background))
    b = bounds or _pad(scene.bounds(), 30)
    xf, k = fit_transform(b, width, height)
    painter = QtGui.QPainter(img)
    QtSceneRenderer(painter, xf, k, scale_ui * 1.6).draw(scene)
    painter.end()
    return img


def _pad(b, m):
    return (b[0] - m, b[1] - m, b[2] + m, b[3] + m)
