"""Interactive drawing canvas: zoom/pan, drag handles, dimension dragging,
measurement, notes, user dimensions and photo calibration."""
from __future__ import annotations

import itertools
import math

from ..geometry import dimensions as DIM
from ..geometry.solver import Geometry, solve
from ..geometry.vec import V, cosd, project_on_line, sind
from ..model.units import fmt_len
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..render.bike_scene import build_scene
from ..render.qt_render import QtSceneRenderer
from ..render.scene import AngleDim, LinearDim, Scene, _dim_line
from .document import Document

Qt = QtCore.Qt
QPointF = QtCore.QPointF

HANDLES = [
    ("saddle", "Saddle (drag: height, Shift: free)"),
    ("bar", "Handlebar (drag: stem length/spacers)"),
    ("ht_top", "Head tube top (drag: stack & reach)"),
    ("rear_axle", "Rear axle (drag: chainstay & BB drop, Shift: length only)"),
    ("st_top", "Seat tube top (drag: seat tube length)"),
    ("front_axle", "Front axle (drag: front centre)"),
    ("pedal", "Pedal (drag: crank angle)"),
    ("tt_ht", "Top tube / head tube junction (drag along the head tube)"),
    ("dt_ht", "Down tube / head tube junction (drag along the head tube)"),
    ("tt_st", "Top tube / seat tube junction (drag along the seat tube)"),
    ("ss_top", "Seat stay junction (drag along the tube it attaches to)"),
]
_drag_ids = itertools.count(1000)


class BikeCanvas(QtWidgets.QWidget):
    status = Signal(str)
    edit_dimension = Signal(str)          # dimension id (catalogue)
    tool_finished = Signal()

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.zoom = 0.5                   # px per mm
        self.center = V(250, 300)          # model point at widget centre
        self._fitted = False
        self.ui_scale = 1.0
        self.show_handles = True
        self.reverse_wheel = False
        self.zoom_locked = False
        self.tool = "select"
        self._scene: Scene | None = None
        self._geom: Geometry | None = None
        self._ghost_geoms: list[tuple[Geometry, str]] = []
        self._cache: QtGui.QPixmap | None = None
        self._drag = None
        self._hover: str | None = None
        self._pan_last: QPointF | None = None
        self._space = False
        self._tool_pts: list[V] = []
        self._mouse_model = V()
        doc.changed.connect(self._on_changed)

    # -- transforms ---------------------------------------------------------------
    def model_to_device(self) -> QtGui.QTransform:
        xf = QtGui.QTransform()
        xf.translate(self.width() / 2, self.height() / 2)
        xf.scale(self.zoom, -self.zoom)
        xf.translate(-self.center.x, -self.center.y)
        return xf

    def to_model(self, p: QPointF) -> V:
        return V(self.center.x + (p.x() - self.width() / 2) / self.zoom,
                 self.center.y - (p.y() - self.height() / 2) / self.zoom)

    def to_device(self, v: V) -> QPointF:
        return QPointF(self.width() / 2 + (v.x - self.center.x) * self.zoom,
                       self.height() / 2 - (v.y - self.center.y) * self.zoom)

    # -- scene ----------------------------------------------------------------------
    def _on_changed(self, keys) -> None:
        self._scene = None
        self._cache = None
        self.update()

    def set_ghosts(self, ghosts: list[tuple[Geometry, str]]) -> None:
        self._ghost_geoms = ghosts
        self._on_changed({"ghosts"})

    def scene(self) -> Scene:
        if self._scene is None:
            self._geom = self.doc.geometry
            self._scene = build_scene(self._geom, ghosts=self._ghost_geoms)
        return self._scene

    def fit(self) -> None:
        if self.zoom_locked:
            return
        sc = self.scene()
        x0, y0, x1, y1 = sc.bounds()
        if x1 - x0 < 1:
            return
        m = 40
        self.zoom = min((self.width() - 2 * m) / (x1 - x0), (self.height() - 2 * m) / (y1 - y0))
        self.zoom = max(self.zoom, 0.02)
        self.center = V((x0 + x1) / 2, (y0 + y1) / 2)
        self._cache = None
        self.update()
        self._emit_zoom()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        before = self.to_model(anchor)
        self.zoom = max(0.02, min(self.zoom * factor, 60.0))
        after = self.to_model(anchor)
        self.center = self.center + (before - after)
        self._cache = None
        self.update()
        self._emit_zoom()

    def _emit_zoom(self):
        self.status.emit(f"Zoom {self.zoom * 100 / 3.78:.0f}% of full size")

    # -- painting ---------------------------------------------------------------------
    def resizeEvent(self, e) -> None:
        self._cache = None
        if not self._fitted and self.width() > 50:
            self._fitted = True
            QtCore.QTimer.singleShot(0, self.fit)
        super().resizeEvent(e)

    def _render_cache(self) -> QtGui.QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QtGui.QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        sc = self.scene()
        pm.fill(QtGui.QColor(sc.background))
        p = QtGui.QPainter(pm)
        QtSceneRenderer(p, self.model_to_device(), self.zoom, 3.2 * self.ui_scale).draw(sc)
        p.end()
        return pm

    def paintEvent(self, e) -> None:
        if self._cache is None:
            self._cache = self._render_cache()
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self._paint_overlay(p)
        p.end()

    def _paint_overlay(self, p: QtGui.QPainter) -> None:
        g = self._geom or self.doc.geometry
        if self.show_handles and self.tool == "select":
            for name, q in self._extra_ends():
                c = self.to_device(q)
                hot = name == self._hover or (self._drag and self._drag.get("point") == name)
                p.setPen(QtGui.QPen(QtGui.QColor("#ff8c00" if hot else "#00a060"), 1.6))
                p.setBrush(QtGui.QBrush(QtGui.QColor(0, 160, 96, 60)))
                r = 7 if hot else 5
                p.drawPolygon(QtGui.QPolygonF([c + QPointF(0, -r), c + QPointF(r, 0), c + QPointF(0, r),
                                               c + QPointF(-r, 0)]))
            for name, _ in HANDLES:
                if name not in g.p:
                    continue
                c = self.to_device(g.p[name])
                hot = name == self._hover or (self._drag and self._drag.get("point") == name)
                p.setPen(QtGui.QPen(QtGui.QColor("#ff8c00" if hot else "#1e78ff"), 1.6))
                p.setBrush(QtGui.QBrush(QtGui.QColor(255, 140, 0, 110) if hot else QtGui.QColor(30, 120, 255, 45)))
                r = 7 if hot else 5
                p.drawEllipse(c, r, r)
        if self.tool == "add_tube":
            q, _spec, label = self._snap_spec(self._mouse_model)
            p.setPen(QtGui.QPen(QtGui.QColor("#00a060"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            c = self.to_device(q)
            p.drawEllipse(c, 5, 5)
            p.drawText(c + QPointF(8, 14), label)
            if self._tool_pts:
                pen = QtGui.QPen(QtGui.QColor(0, 160, 96, 140), max(25.4 * self.zoom, 2))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(self.to_device(self._tool_pts[0]), c)
            return
        if self.tool in ("measure", "user_dim", "user_angle", "calibrate") and self._tool_pts:
            pen = QtGui.QPen(QtGui.QColor("#e0006e"), 1.4, Qt.PenStyle.DashLine)
            p.setPen(pen)
            pts = self._tool_pts + [self._snap_spec(self._mouse_model)[0]]
            for a, b in zip(pts, pts[1:]):
                p.drawLine(self.to_device(a), self.to_device(b))
            for a in pts:
                p.drawEllipse(self.to_device(a), 3, 3)
            if self.tool in ("measure", "calibrate") and len(pts) >= 2:
                a, b = pts[-2], pts[-1]
                units = self.doc.design["units"]
                txt = (f"{fmt_len(a.dist(b), units, suffix=True)}   Δx {fmt_len(b.x - a.x, units)}  "
                       f"Δy {fmt_len(b.y - a.y, units)}   ∠ {(b - a).angle():.1f}°")
                p.setPen(QtGui.QColor("#e0006e"))
                p.drawText(self.to_device(b) + QPointF(10, -10), txt)
        if self.tool != "select":
            snap, spec, label = self._snap_spec(self._mouse_model)
            if isinstance(spec, str) or (isinstance(spec, dict) and "tube" in spec):
                p.setPen(QtGui.QPen(QtGui.QColor("#00a060"), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                c = self.to_device(snap)
                p.drawRect(QtCore.QRectF(c.x() - 5, c.y() - 5, 10, 10))
                p.drawText(c + QPointF(8, 14), label)

    # -- hit testing -------------------------------------------------------------------
    def _extra_ends(self):
        """(handle name, point) for both ends of every extra tube."""
        g = self.doc.geometry
        out = []
        for name, tb in g.tubes.items():
            if tb.kind == "extra" and name.startswith("x"):
                from .extra_tubes import tube_index
                i = tube_index(name)
                if i is not None:
                    out += [(f"xt:{i}:a", tb.a), (f"xt:{i}:b", tb.b)]
        return out

    def _hit_handle(self, pos: QPointF) -> str | None:
        g = self.doc.geometry
        best, bd = None, 9.0
        for name, _ in HANDLES:
            if name in g.p:
                d = _dist(self.to_device(g.p[name]), pos)
                if d < bd:
                    best, bd = name, d
        for name, q in self._extra_ends():
            d = _dist(self.to_device(q), pos)
            if d < bd:
                best, bd = name, d
        return best

    def _hit_dimension(self, pos: QPointF):
        sc = self.scene()
        m = self.to_model(pos)
        tol = 7 / self.zoom
        best, bd = None, tol
        for prim in sc.prims:
            if isinstance(prim, LinearDim):
                d1, d2, *_ = _dim_line(prim)
                ab = d2 - d1
                L2 = ab.dot(ab) or 1e-9
                t = max(0.0, min(1.0, (m - d1).dot(ab) / L2))
                d = m.dist(d1 + ab * t)
            elif isinstance(prim, AngleDim):
                r = m.dist(prim.vertex)
                d = abs(r - prim.radius)
                ang = (m - prim.vertex).angle()
                rel = (ang - prim.start) % 360
                span = prim.span % 360 if prim.span >= 0 else (-prim.span) % 360
                if prim.span < 0:
                    rel = (prim.start - ang) % 360
                if rel > span + 5:
                    continue
            else:
                continue
            if d < bd:
                best, bd = prim, d
        return best

    def _hit_note(self, pos: QPointF):
        m = self.to_model(pos)
        for note in self.doc.design.extras.get("notes") or []:
            try:
                q = V(float(note["x"]), float(note["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            size = float(note.get("size", 3.5)) * 3.2 * 1.4 / self.zoom
            w = max(len(str(note.get("text", ""))), 2) * size * 0.6
            if q.x - 4 / self.zoom <= m.x <= q.x + w and q.y - 4 / self.zoom <= m.y <= q.y + size * 1.3:
                return note
        return None

    SNAP_TUBES = ("tt", "dt", "st", "ht", "ss", "cs", "fork", "st2", "tt2", "boom", "mid", "ss_mono")

    def _snap_spec(self, m: V):
        """(point, end-point spec, label) for tube drawing: a named frame point,
        a position along a tube (so the new tube follows the geometry), or
        free X/Y from the BB."""
        p, name = self._snap(m)
        if name:
            return p, name, name
        g = self.doc.geometry
        tol = 10 / self.zoom
        best = None
        candidates = list(self.SNAP_TUBES) + [n for n in g.tubes if n.startswith("x")]  # incl. extra tubes
        for tname in candidates:
            tb = g.tubes.get(tname)
            if tb is None:
                continue
            pts = tb.points()
            acc = 0.0
            L = tb.length or 1.0
            for i in range(len(pts) - 1):
                a_, b_ = pts[i], pts[i + 1]
                ab = b_ - a_
                seg = ab.length()
                if seg < 1e-9:
                    continue
                t = max(0.0, min(1.0, (m - a_).dot(ab) / (seg * seg)))
                q = a_ + ab * t
                dist = q.dist(m)
                if dist < tol and (best is None or dist < best[0]):
                    best = (dist, q, tname, (acc + seg * t) / L)
                acc += seg
        if best is not None:
            _, q, tname, pos = best
            pos = round(pos, 3)
            return q, {"tube": tname, "pos": pos}, f"{tname} @ {pos:.2f}"
        return m, {"x": round(m.x, 1), "y": round(m.y, 1)}, f"{m.x:.0f}, {m.y:.0f}"

    def _hit_extra_tube(self, pos: QPointF) -> str | None:
        g = self.doc.geometry
        m = self.to_model(pos)
        from ..geometry.vec import point_segment_distance
        for name, tb in g.tubes.items():
            if tb.kind != "extra" or not name.startswith("x"):
                continue
            pts = tb.points()
            d = min(point_segment_distance(m, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            if d < max(tb.od_b / 2, 4 / self.zoom) + 3 / self.zoom:
                return name
        return None

    def _snap(self, m: V) -> tuple[V, str | None]:
        g = self.doc.geometry
        best, bn, bd = m, None, 12 / self.zoom
        for name, q in g.p.items():
            d = q.dist(m)
            if d < bd:
                best, bn, bd = q, name, d
        return best, bn

    # -- mouse ---------------------------------------------------------------------
    def wheelEvent(self, e) -> None:
        if self.zoom_locked:
            return
        dy = e.angleDelta().y()
        if self.reverse_wheel:
            dy = -dy
        if dy:
            self.zoom_by(1.15 ** (dy / 120.0), e.position())

    def mousePressEvent(self, e) -> None:
        pos = e.position()
        m = self.to_model(pos)
        if e.button() in (Qt.MouseButton.MiddleButton,) or (e.button() == Qt.MouseButton.LeftButton and self._space):
            self._pan_last = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._pan_last = pos
            self._right_press = pos
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.tool != "select":
            self._tool_click(m, e)
            return
        name = self._hit_handle(pos) if self.show_handles else None
        if name:
            self._drag = {"kind": "point", "point": name, "design": self.doc.design.copy(),
                          "geom": self.doc.geometry, "id": next(_drag_ids), "start": m}
            return
        note = self._hit_note(pos)
        if note is not None:
            self._drag = {"kind": "note", "note_id": note.get("id"), "id": next(_drag_ids),
                          "start": m, "orig": (float(note["x"]), float(note["y"]))}
            return
        dim = self._hit_dimension(pos)
        if dim is not None:
            self._drag = {"kind": "dim", "prim": dim, "id": next(_drag_ids)}
            return
        self._pan_last = pos
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        m = self.to_model(pos)
        self._mouse_model = m
        units = self.doc.design["units"]
        if self._pan_last is not None:
            d = pos - self._pan_last
            self._pan_last = pos
            self.center = self.center - V(d.x() / self.zoom, -d.y() / self.zoom)
            self._cache = None
            self.update()
            return
        if self._drag:
            self._drag_move(m, e.modifiers())
            return
        hov = self._hit_handle(pos) if (self.show_handles and self.tool == "select") else None
        if hov != self._hover:
            self._hover = hov
            self.setToolTip(dict(HANDLES).get(hov, "") if hov else "")
        self.status.emit(f"X {fmt_len(m.x, units)}  Y {fmt_len(m.y, units)}  (from BB)")
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.RightButton and getattr(self, "_right_press", None) is not None:
            moved = _dist(self._right_press, e.position()) > 4
            self._right_press = None
            self._pan_last = None
            if not moved:
                self._context_menu(e.position())
            return
        self._pan_last = None
        self._drag = None
        self.unsetCursor()
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        xt = self._hit_extra_tube(e.position())
        if xt is not None and self._hit_dimension(e.position()) is None:
            from . import extra_tubes as XT
            idx = XT.tube_index(xt)
            if idx is not None:
                XT.edit_tube(self.doc, idx, self)
                return
        dim = self._hit_dimension(e.position())
        if dim is not None and dim.tag.startswith("dim:"):
            self.edit_dimension.emit(dim.tag[4:])
            return
        note = self._hit_note(e.position())
        if note is not None:
            text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "Edit note", "Text:", str(note.get("text", "")))
            if ok:
                notes = [dict(n) for n in self.doc.design.extras.get("notes") or []]
                for n in notes:
                    if n.get("id") == note.get("id"):
                        n["text"] = text
                self.doc.set_extra("notes", notes, "Edit note")

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k == Qt.Key.Key_Space:
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif k == Qt.Key.Key_Escape:
            self._tool_pts = []
            self.set_tool("select")
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.25)
        elif k == Qt.Key.Key_Minus:
            self.zoom_by(0.8)
        elif k == Qt.Key.Key_F:
            self.fit()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.unsetCursor()
        super().keyReleaseEvent(e)

    # -- dragging --------------------------------------------------------------------
    def _drag_move(self, m: V, mods) -> None:
        dr = self._drag
        doc = self.doc
        units = doc.design["units"]
        if dr["kind"] == "dim":
            prim = dr["prim"]
            if isinstance(prim, LinearDim):
                p1, p2 = prim.p1, prim.p2
                if prim.mode == "horizontal":
                    hi, lo = max(p1.y, p2.y), min(p1.y, p2.y)
                    off = max(m.y - hi, 0.0) if m.y >= (hi + lo) / 2 else min(m.y - lo, 0.0)
                elif prim.mode == "vertical":
                    hi, lo = max(p1.x, p2.x), min(p1.x, p2.x)
                    off = max(m.x - hi, 0.0) if m.x >= (hi + lo) / 2 else min(m.x - lo, 0.0)
                else:
                    nrm = (p2 - p1).norm().perp()
                    off = (m - p1).dot(nrm)
            else:
                off = m.dist(prim.vertex)
            if prim.tag.startswith("dim:"):
                offs = dict(doc.design.extras.get("dimension_offsets") or {})
                offs[prim.tag[4:]] = round(off, 1)
                doc.set_extra("dimension_offsets", offs, "Move dimension", dr["id"])
            elif prim.tag.startswith("udim:"):
                uid = prim.tag[5:]
                uds = [dict(u) for u in doc.design.extras.get("user_dimensions") or []]
                for u in uds:
                    if str(u.get("id")) == uid:
                        u["offset"] = round(off, 1)
                doc.set_extra("user_dimensions", uds, "Move dimension", dr["id"])
            return
        if dr["kind"] == "note":
            notes = [dict(n) for n in doc.design.extras.get("notes") or []]
            dx, dy = m.x - dr["start"].x, m.y - dr["start"].y
            for n in notes:
                if n.get("id") == dr["note_id"]:
                    n["x"], n["y"] = round(dr["orig"][0] + dx, 1), round(dr["orig"][1] + dy, 1)
            doc.set_extra("notes", notes, "Move note", dr["id"])
            return
        if dr["point"].startswith("xt:"):
            self._drag_extra_end(dr, m)
            return
        changes, msg = drag_point_changes(dr["point"], m, dr["design"], dr["geom"],
                                          bool(mods & Qt.KeyboardModifier.ShiftModifier))
        if changes:
            doc.set_params(changes, f"Drag {dr['point']}", dr["id"])
            self.status.emit(msg.format(**{k: (fmt_len(v, units) if isinstance(v, float) else v)
                                           for k, v in changes.items()}))

    def _drag_extra_end(self, dr, m: V) -> None:
        """Slide an extra tube end: along its host tube (keeping surface/side
        settings), onto another tube, onto a frame point, or free."""
        _, idx, end = dr["point"].split(":")
        idx = int(idx)
        tubes = [dict(t) for t in self.doc.design.extras.get("extra_tubes") or []]
        if not 0 <= idx < len(tubes):
            return
        old = tubes[idx].get(end)
        q, spec, label = self._snap_spec(m)
        if isinstance(spec, dict) and "tube" in spec and isinstance(old, dict) and "tube" in old:
            for k in ("surface", "side"):
                if k in old:
                    spec[k] = old[k]
            if old.get("tube") == spec["tube"] and "s" in old:
                L = self.doc.geometry.tubes[spec["tube"]].length
                s_mm = spec["pos"] * L
                spec = {k: v for k, v in spec.items() if k != "pos"}
                spec["s"] = round(L - s_mm if old.get("from") == "b" else s_mm, 1)
                if old.get("from") == "b":
                    spec["from"] = "b"
        tubes[idx][end] = spec
        self.doc.set_extra("extra_tubes", tubes, "Move extra tube end", dr["id"])
        self.status.emit(f"{tubes[idx].get('name', 'tube')} {'start' if end == 'a' else 'end'}: {label}")

    # -- tools ------------------------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._tool_pts = []
        self.setCursor(Qt.CursorShape.CrossCursor if tool != "select" else Qt.CursorShape.ArrowCursor)
        hints = {"measure": "Measure: click two points (snaps to frame points). Esc to finish.",
                 "note": "Note: click where the note should go.",
                 "user_dim": "User dimension: click two points.",
                 "user_angle": "Angle dimension: click three points (vertex second).",
                 "calibrate": "Photo scale: click two points a known distance apart on the photo.",
                 "move_photo": "Photo: drag to move the photo underlay.",
                 "add_tube": "Add tube: click the start, then the end (snaps to frame points and along tubes)."}
        self.status.emit(hints.get(tool, "Ready"))
        self.update()

    def _tool_click(self, m: V, e) -> None:
        # snap to frame points, positions along tubes (incl. extra tubes), or free X/Y
        snap, pt_spec, _label = self._snap_spec(m)
        doc = self.doc
        if self.tool == "note":
            text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "Add note", "Note text:")
            if ok and text.strip():
                notes = list(doc.design.extras.get("notes") or [])
                notes.append({"id": f"n{len(notes) + 1}_{abs(hash(text)) % 9999}", "x": round(m.x, 1),
                              "y": round(m.y, 1), "text": text, "size": 3.5, "color": "#b03000"})
                doc.set_extra("notes", notes, "Add note")
            self.set_tool("select")
            self.tool_finished.emit()
            return
        if self.tool == "move_photo":
            return
        if self.tool == "add_tube":
            q, spec, _label = self._snap_spec(m)
            self._tool_pts.append(q)
            self._tube_specs = (getattr(self, "_tube_specs", []) if len(self._tool_pts) > 1 else []) + [spec]
            if len(self._tool_pts) < 2:
                self.update()
                return
            a_spec, b_spec = self._tube_specs[0], self._tube_specs[-1]
            self._tool_pts = []
            self._tube_specs = []
            self.set_tool("select")
            from .extra_tubes import new_tube_dialog
            new_tube_dialog(doc, a_spec, b_spec, self)
            self.tool_finished.emit()
            return
        self._tool_pts.append(snap)
        self._tool_specs = getattr(self, "_tool_specs", [])
        if len(self._tool_pts) == 1:
            self._tool_specs = []
        self._tool_specs.append(pt_spec)
        need = {"measure": 2, "user_dim": 2, "user_angle": 3, "calibrate": 2}.get(self.tool, 2)
        if len(self._tool_pts) < need:
            self.update()
            return
        pts, specs = self._tool_pts, self._tool_specs
        if self.tool == "user_dim":
            kinds = ["Aligned", "Horizontal", "Vertical"]
            kind, ok = QtWidgets.QInputDialog.getItem(self, "User dimension", "Type:", kinds, 0, False)
            if ok:
                uds = list(doc.design.extras.get("user_dimensions") or [])
                uds.append({"id": f"u{len(uds) + 1}", "kind": kind.lower(), "points": specs, "offset": 30,
                            "label": ""})
                doc.set_extra("user_dimensions", uds, "Add user dimension")
        elif self.tool == "user_angle":
            uds = list(doc.design.extras.get("user_dimensions") or [])
            uds.append({"id": f"u{len(uds) + 1}", "kind": "angle3", "points": specs, "offset": 40, "label": ""})
            doc.set_extra("user_dimensions", uds, "Add angle dimension")
        elif self.tool == "calibrate":
            ph = dict(doc.design.extras.get("photo") or {})
            if ph:
                measured = pts[0].dist(pts[1])
                real, ok = QtWidgets.QInputDialog.getDouble(self, "Calibrate photo",
                                                            "Real distance between the points (mm):", 1000.0,
                                                            1.0, 100000.0, 1)
                if ok and measured > 1e-6:
                    k = real / measured
                    ph["mm_per_px"] = float(ph.get("mm_per_px", 1.0)) * k
                    # keep the first clicked point fixed
                    ox, oy = float(ph.get("x", 0)), float(ph.get("y", 0))
                    ph["x"] = pts[0].x + (ox - pts[0].x) * k
                    ph["y"] = pts[0].y + (oy - pts[0].y) * k
                    doc.set_extra("photo", ph, "Calibrate photo")
        elif self.tool == "measure":
            self._tool_pts = [pts[-1]]
            self._tool_specs = [specs[-1]]
            self.update()
            return
        self._tool_pts = []
        self.set_tool("select")
        self.tool_finished.emit()

    def _context_menu(self, pos: QPointF) -> None:
        menu = QtWidgets.QMenu(self)
        m = self.to_model(pos)
        menu.addAction("Fit to window", self.fit)
        menu.addSeparator()
        menu.addAction("Add note here…", lambda: (self.set_tool("note"), self._tool_click(m, None)))
        menu.addAction("Add user dimension", lambda: self.set_tool("user_dim"))
        menu.addAction("Add angle dimension", lambda: self.set_tool("user_angle"))
        menu.addAction("Measure", lambda: self.set_tool("measure"))
        dim = self._hit_dimension(pos)
        if dim is not None:
            menu.addSeparator()
            if dim.tag.startswith("dim:"):
                did = dim.tag[4:]
                menu.addAction(f"Edit '{DIM.BY_ID[did].label}'…", lambda: self.edit_dimension.emit(did))
                menu.addAction("Hide this dimension", lambda: self._hide_dim(did))
                menu.addAction("Reset position", lambda: self._reset_dim(did))
            elif dim.tag.startswith("udim:"):
                uid = dim.tag[5:]
                menu.addAction("Delete user dimension", lambda: self._delete_udim(uid))
        note = self._hit_note(pos)
        if note is not None:
            menu.addSeparator()
            menu.addAction("Delete note", lambda: self._delete_note(note.get("id")))
        xt = self._hit_extra_tube(pos)
        if xt is not None:
            from . import extra_tubes as XT
            idx = XT.tube_index(xt)
            if idx is not None:
                menu.addSeparator()
                menu.addAction(f"Edit extra tube '{xt.split('_', 1)[1]}'…", lambda: XT.edit_tube(self.doc, idx, self))
                menu.addAction("Delete extra tube", lambda: XT.delete_tube(self.doc, idx))
        menu.addSeparator()
        menu.addAction("Add tube here (click start and end)", lambda: self.set_tool("add_tube"))
        menu.exec(self.mapToGlobal(pos.toPoint()))

    def _hide_dim(self, did: str) -> None:
        ids = DIM.visible_ids(self.doc.geometry)
        if did in ids:
            ids.remove(did)
        self.doc.set_extra("visible_dimensions", ids, "Hide dimension")

    def _reset_dim(self, did: str) -> None:
        offs = dict(self.doc.design.extras.get("dimension_offsets") or {})
        offs.pop(did, None)
        self.doc.set_extra("dimension_offsets", offs, "Reset dimension")

    def _delete_udim(self, uid: str) -> None:
        uds = [u for u in self.doc.design.extras.get("user_dimensions") or [] if str(u.get("id")) != uid]
        self.doc.set_extra("user_dimensions", uds, "Delete user dimension")

    def _delete_note(self, nid) -> None:
        notes = [n for n in self.doc.design.extras.get("notes") or [] if n.get("id") != nid]
        self.doc.set_extra("notes", notes, "Delete note")


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def drag_point_changes(name: str, m: V, d0, g0: Geometry, shift: bool) -> tuple[dict, str]:
    """Parameter changes that move point ``name`` of the baseline design to ``m``."""
    # On a tall bike the rider (saddle, cranks/pedal) is drawn lifted onto the
    # upper frame, but the parameters below are measured from the real (lower)
    # BB at the origin.  Undo the lift so the drag math stays in frame coords.
    if d0["frame_type"] == "tall" and name in ("saddle", "pedal"):
        m = m - (g0.p.get("crank_bb", g0.p["bb"]) - g0.p["bb"])
    if name == "saddle":
        if d0["saddle_mode"] == "xy":
            return {"saddle_x": m.x, "saddle_y": m.y}, "Saddle X {saddle_x}  Y {saddle_y}"
        if shift:
            ang = math.degrees(math.atan2(m.y, -m.x))
            return ({"seat_angle_source": "custom", "seat_angle_eff": round(ang, 2), "saddle_height": m.length()},
                    "Saddle height {saddle_height}, seat angle {seat_angle_eff}°")
        sa = d0.f("seat_tube_angle") if d0["seat_angle_source"] == "seat_tube" else d0.f("seat_angle_eff")
        dirn = V(-cosd(sa), sind(sa))
        return {"saddle_height": max(m.dot(dirn), 100.0)}, "Saddle height {saddle_height}"
    if name == "bar":
        vm, hm = d0["front_v_mode"], d0["front_h_mode"]
        out = {}
        if vm == "bar_y":
            out["bar_y"] = m.y
        if hm == "bar_x":
            out["bar_x"] = m.x
        if out:
            return out, "Handlebar " + "  ".join(f"{k} {{{k}}}" for k in out)
        delta = m - g0.p["bar"]
        a = d0.f("stem_angle")
        stem_dir = g0.n * cosd(a) + g0.u * sind(a)
        # solve delta = ds*stem_dir + dh*u for stem length (ds) and spacer height (dh)
        det = stem_dir.x * g0.u.y - stem_dir.y * g0.u.x
        if abs(det) < 1e-9:
            return {}, ""
        ds = (delta.x * g0.u.y - delta.y * g0.u.x) / det
        dh = (stem_dir.x * delta.y - stem_dir.y * delta.x) / det
        if d0["stem_type"] == "quill":
            return ({"stem_length": max(d0.f("stem_length") + ds, 0.0),
                     "quill_height": max(d0.f("quill_height") + dh, 0.0)}, "Stem {stem_length}, quill {quill_height}")
        return ({"stem_length": max(d0.f("stem_length") + ds, 0.0), "spacers": max(d0.f("spacers") + dh, 0.0)},
                "Stem {stem_length}, spacers {spacers}")
    if name == "ht_top":
        return ({"front_v_mode": "stack", "front_h_mode": "reach", "stack": m.y, "reach": m.x},
                "Stack {stack}  Reach {reach}")
    if name == "rear_axle":
        cs = m.length()
        if shift:
            return {"cs_mode": "length", "chainstay_length": max(cs, abs(g0.v["bb_drop"]) + 1)}, "Chainstay {chainstay_length}"
        return ({"cs_mode": "length", "bb_mode": "drop", "chainstay_length": max(cs, abs(m.y) + 1), "bb_drop": m.y},
                "Chainstay {chainstay_length}  BB drop {bb_drop}")
    if name == "st_top":
        L = project_on_line(m, g0.p["st_bottom"], g0.s)
        if d0["st_length_mode"] == "cc":
            return {"st_extension": L - g0.v["seat_tube_cc"]}, "Seat tube extension {st_extension}"
        return {"seat_tube_length": max(L, 100.0)}, "Seat tube {seat_tube_length}"
    if name == "front_axle":
        dx = m.x - g0.p["front_axle"].x
        hm = d0["front_h_mode"]
        if hm == "front_center":
            fy = g0.p["front_axle"].y
            return {"front_center": math.hypot(m.x, fy)}, "Front centre {front_center}"
        key = {"reach": "reach", "ett": "top_tube_effective", "wheelbase": "wheelbase", "bar_x": "bar_x"}[hm]
        return {key: d0.f(key) + dx}, f"{key} {{{key}}}"
    if name == "pedal":
        return {"crank_angle": round(m.angle(), 1)}, "Crank angle {crank_angle}"
    if name in ("tt_ht", "dt_ht"):
        T, B = g0.p["ht_top"], g0.p["ht_bottom"]
        if name == "tt_ht":
            off = (T - m).dot(g0.u)
            key, stick = "tt_ht_offset", "ht_top_stickout"
        else:
            off = (m - B).dot(g0.u)
            key, stick = "dt_ht_offset", "ht_bottom_stickout"
        if d0["ht_junction_mode"] == "stickout":
            # exact: solve with that centre-line offset and read back the stick-out it implies
            probe = d0.copy()
            probe.update({"ht_junction_mode": "centerline", "tt_ht_offset": g0.v["tt_ht_offset"],
                          "dt_ht_offset": g0.v["dt_ht_offset"], key: off})
            return {stick: solve(probe).v[stick]}, f"Head tube stick-out {{{stick}}}"
        return {key: off}, f"Junction offset {{{key}}}"
    if name == "tt_st":
        P0, s = g0.p["st_bottom"], g0.s
        t = project_on_line(m, P0, s)
        t_top = project_on_line(g0.p["st_top"], P0, s)
        if d0["st_length_mode"] == "cc":
            return ({"seat_tube_length": t, "st_extension": t_top - t},
                    "Seat tube (c-c) {seat_tube_length}, extension {st_extension}")
        if d0["tt_mode"] == "st_extension":
            return {"st_extension": t_top - t}, "Seat tube extension {st_extension}"
        q = P0 + s * t
        J = g0.p["tt_ht"]
        return {"top_tube_angle": round(math.degrees(math.atan2(J.y - q.y, J.x - q.x)), 2)}, "Top tube angle {top_tube_angle}"
    if name == "ss_top":
        J = g0.p["stoker_tt_st"] if "stoker_tt_st" in g0.p else g0.p["tt_st"]
        if d0["ss_attach"] == "top_tube" and "tt" in g0.tubes:
            tt_dir = (g0.p["tt_ht"] - g0.p["tt_st"]).norm()
            return {"ss_offset": max((m - J).dot(tt_dir), -150.0)}, "Seat stay offset {ss_offset}"
        s_axis = (g0.p["stoker_st_top"] - g0.p["stoker_bb"]).norm() if "stoker_bb" in g0.p else g0.s
        return {"ss_offset": (J - m).dot(s_axis)}, "Seat stay offset {ss_offset}"
    return {}, ""
