"""Interactive 3-D clearance viewer (pyqtgraph.opengl).

View ▸ 3-D clearance view. Shows the frame and wheels as a solid model you can
orbit/zoom, with every clearance drawn as a gap line between the two closest
surface points — green where it meets its threshold, red where it fails — plus a
side list of the measured values. Degrades gracefully if pyqtgraph / PyOpenGL
are not installed.
"""
from __future__ import annotations

import numpy as np

from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt


def available() -> bool:
    try:
        import pyqtgraph.opengl  # noqa: F401
        import OpenGL  # noqa: F401
        return True
    except Exception:
        return False


def ensure_gl_format() -> None:
    """Request an OpenGL >= 2.1 surface so pyqtgraph.opengl's version gate passes.

    Many Mesa drivers report a 4.x compatibility context whose default
    QSurfaceFormat version is < (2, 1); pyqtgraph then refuses to initialise even
    though the hardware is fine. Setting the default format version fixes it. Must
    run before the first GL widget is created.
    """
    fmt = QtGui.QSurfaceFormat.defaultFormat()
    if fmt.version() < (2, 1):
        fmt.setVersion(2, 1)
        fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        QtGui.QSurfaceFormat.setDefaultFormat(fmt)


OK = (0.20, 0.65, 0.25, 1.0)
FAIL = (0.85, 0.15, 0.15, 1.0)
FRAME = (0.62, 0.66, 0.72, 1.0)


class View3DWidget(QtWidgets.QWidget):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        import pyqtgraph.opengl as gl
        self.gl = gl
        self.doc = doc
        ensure_gl_format()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            self.view = gl.GLViewWidget()
            self.view.setBackgroundColor(QtGui.QColor("#101418"))
        except Exception as exc:                 # no usable OpenGL context
            raise RuntimeError(f"OpenGL is not available: {exc}") from exc
        lay.addWidget(self.view, 1)

        side = QtWidgets.QVBoxLayout()
        self.show_fail_only = QtWidgets.QCheckBox("Problems only")
        self.show_fail_only.toggled.connect(self.rebuild)
        side.addWidget(self.show_fail_only)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Clearance", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._focus_selected)
        side.addWidget(self.table, 1)
        hint = QtWidgets.QLabel("Drag to orbit · wheel to zoom · right-drag to pan")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        side.addWidget(hint)
        host = QtWidgets.QWidget()
        host.setLayout(side)
        host.setFixedWidth(260)
        lay.addWidget(host)

        self._items: list = []
        self._scene = None
        # live updates: rebuild shortly after the design changes (debounced)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.rebuild)
        self._connect(doc)
        self.rebuild()

    def _connect(self, doc: Document) -> None:
        try:
            doc.changed.connect(self._schedule)
        except (TypeError, RuntimeError):
            pass

    def _schedule(self, *_):
        # only recompute when actually visible, to avoid background cost
        if self.isVisible():
            self._timer.start()
        else:
            self._dirty = True

    # -- build --------------------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_dirty", False):
            self._dirty = False
            self.rebuild()

    def set_document(self, doc: Document) -> None:
        if self.doc is not None and self.doc is not doc:
            try:
                self.doc.changed.disconnect(self._schedule)
            except (TypeError, RuntimeError):
                pass
        self.doc = doc
        self._connect(doc)
        self.rebuild()

    def _clear(self) -> None:
        for it in self._items:
            self.view.removeItem(it)
        self._items.clear()

    def rebuild(self) -> None:
        from ..render import scene3d
        self._clear()
        g = self.doc.geometry
        self._scene = sc = scene3d.build(g)
        gl = self.gl
        # frame + wheels mesh
        if sc.triangles:
            verts = np.array([v for tri in sc.triangles for v in tri], dtype=np.float32)
            faces = np.arange(len(verts), dtype=np.int32).reshape(-1, 3)
            mesh = gl.GLMeshItem(vertexes=verts, faces=faces, smooth=False, drawEdges=False,
                                 color=FRAME, shader="shaded", glOptions="opaque")
            self.view.addItem(mesh)
            self._items.append(mesh)
        # chainring circles
        for circ in sc.circles:
            pts = self._circle_pts(circ["center"], circ["r"])
            item = gl.GLLinePlotItem(pos=pts, color=circ["color"], width=2, antialias=True, mode="line_strip")
            self.view.addItem(item)
            self._items.append(item)
        for seg in sc.segments3:
            item = gl.GLLinePlotItem(pos=np.array([seg["a"], seg["b"]], dtype=np.float32),
                                     color=seg["color"], width=4, antialias=True)
            self.view.addItem(item)
            self._items.append(item)
        # clearance gap lines + markers
        self._lines = [cl for cl in sc.clearances if not (self.show_fail_only.isChecked() and cl.ok)]
        for cl in self._lines:
            col = OK if cl.ok else FAIL
            line = gl.GLLinePlotItem(pos=np.array([cl.p, cl.q], dtype=np.float32), color=col, width=4,
                                     antialias=True)
            self.view.addItem(line)
            self._items.append(line)
            try:
                txt = gl.GLTextItem(pos=np.array(cl.mid, dtype=np.float32), text=f"{cl.value:.1f}", color=col)
                self.view.addItem(txt)
                self._items.append(txt)
            except Exception:
                pass
        self._center_view(sc.bounds)
        self._fill_table()

    def _circle_pts(self, center, r, n: int = 48):
        cx, cy, cz = center
        a = np.linspace(0, 2 * np.pi, n)
        return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a), np.full(n, cz)]).astype(np.float32)

    def _center_view(self, bounds) -> None:
        (x0, y0, z0), (x1, y1, z1) = bounds
        cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
        span = max(x1 - x0, y1 - y0, z1 - z0, 100.0)
        self.view.opts["center"] = QtGui.QVector3D(cx, cy, cz)
        self.view.setCameraPosition(distance=span * 1.8, elevation=18, azimuth=-70)

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._lines))
        for r, cl in enumerate(self._lines):
            a = QtWidgets.QTableWidgetItem(cl.label)
            v = QtWidgets.QTableWidgetItem(f"{cl.value:.1f}{'°' if cl.unit == 'deg' else ' mm'}")
            colour = QtGui.QColor("#2f9e44") if cl.ok else QtGui.QColor("#e03131")
            v.setForeground(QtGui.QBrush(colour))
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, v)

    def _focus_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        if not rows or self._scene is None:
            return
        cl = self._lines[min(rows)]
        self.view.opts["center"] = QtGui.QVector3D(*cl.mid)
        self.view.update()
