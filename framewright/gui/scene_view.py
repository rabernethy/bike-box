"""A small zoom/pan viewer for any Scene (previews, auxiliary views)."""
from __future__ import annotations

from ..geometry.vec import V
from ..qt import QtCore, QtGui, QtWidgets
from ..render.qt_render import QtSceneRenderer
from ..render.scene import Scene

Qt = QtCore.Qt


class SceneView(QtWidgets.QWidget):
    def __init__(self, scene: Scene | None = None, parent=None, paper_px_per_mm: float = 3.0,
                 background: str | None = None):
        super().__init__(parent)
        self._scene = scene
        self.paper = paper_px_per_mm
        self.background = background
        self.zoom = 1.0
        self.center = V()
        self._auto = True
        self._last = None
        self.setMinimumSize(200, 150)

    def set_scene(self, scene: Scene | None, keep_view: bool = False) -> None:
        self._scene = scene
        if not keep_view:
            self._auto = True
        self.update()

    def fit(self) -> None:
        self._auto = True
        self.update()

    def _fit_now(self) -> None:
        if self._scene is None:
            return
        x0, y0, x1, y1 = self._scene.bounds()
        if x1 - x0 < 1e-6:
            return
        m = 18
        self.zoom = max(1e-3, min((self.width() - 2 * m) / (x1 - x0), (self.height() - 2 * m) / (y1 - y0)))
        self.center = V((x0 + x1) / 2, (y0 + y1) / 2)

    def _xf(self) -> QtGui.QTransform:
        xf = QtGui.QTransform()
        xf.translate(self.width() / 2, self.height() / 2)
        xf.scale(self.zoom, -self.zoom)
        xf.translate(-self.center.x, -self.center.y)
        return xf

    def paintEvent(self, e) -> None:
        p = QtGui.QPainter(self)
        bg = self.background or (self._scene.background if self._scene else "#ffffff")
        p.fillRect(self.rect(), QtGui.QColor(bg))
        if self._scene is not None:
            if self._auto:
                self._fit_now()
            QtSceneRenderer(p, self._xf(), self.zoom, self.paper).draw(self._scene)
        p.end()

    def resizeEvent(self, e) -> None:
        if self._auto:
            self.update()
        super().resizeEvent(e)

    def wheelEvent(self, e) -> None:
        self._auto = False
        k = 1.15 ** (e.angleDelta().y() / 120.0)
        pos = e.position()
        before = self._to_model(pos)
        self.zoom = max(1e-3, min(self.zoom * k, 100))
        after = self._to_model(pos)
        self.center = self.center + (before - after)
        self.update()

    def _to_model(self, p) -> V:
        return V(self.center.x + (p.x() - self.width() / 2) / self.zoom,
                 self.center.y - (p.y() - self.height() / 2) / self.zoom)

    def mousePressEvent(self, e) -> None:
        self._last = e.position()

    def mouseMoveEvent(self, e) -> None:
        if self._last is not None:
            self._auto = False
            d = e.position() - self._last
            self._last = e.position()
            self.center = self.center - V(d.x() / self.zoom, -d.y() / self.zoom)
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        self._last = None

    def mouseDoubleClickEvent(self, e) -> None:
        self.fit()
