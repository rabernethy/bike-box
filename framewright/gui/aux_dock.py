"""Dock panel with the auxiliary views (top, rear, front, lean, toe, stays)."""
from __future__ import annotations

from ..qt import QtCore, QtWidgets
from .document import Document
from .scene_view import SceneView

Qt = QtCore.Qt


class AuxViewsPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ..render import aux_views
        self.views = list(aux_views.AUX_VIEWS)
        self.doc: Document | None = None
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabPosition(QtWidgets.QTabWidget.TabPosition.North)
        self.viewers = []
        for title, _fn in self.views:
            v = SceneView(paper_px_per_mm=2.6)
            self.viewers.append(v)
            self.tabs.addTab(v, title)
        lay.addWidget(self.tabs, 3)
        self.values = QtWidgets.QTreeWidget()
        self.values.setHeaderLabels(["Clearance", "Value"])
        self.values.setMaximumWidth(330)
        self.values.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.values, 1)
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self.refresh)

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            try:
                self.doc.changed.disconnect(self._timer.start)
            except (TypeError, RuntimeError):
                pass
        self.doc = doc
        if doc is not None:
            doc.changed.connect(self._timer.start)
        self.refresh()

    def refresh(self) -> None:
        if self.doc is None:
            return
        g = self.doc.geometry
        i = self.tabs.currentIndex()
        if 0 <= i < len(self.views):
            try:
                self.viewers[i].set_scene(self.views[i][1](g), keep_view=True)
            except Exception as exc:
                self.viewers[i].set_scene(None)
                self.viewers[i].setToolTip(str(exc))
        self.values.clear()
        try:
            from ..geometry import clearance as C
            vals = C.clearances(g)
            labels = getattr(C, "LABELS", {})
            bad = {k for k in vals if C.is_problem(g, k)}
        except Exception as exc:
            vals, labels, bad = {"error": str(exc)}, {}, set()
        units = self.doc.design["units"]
        from ..model.units import fmt_len
        for k, v in vals.items():
            label = labels.get(k, k.replace("_", " "))
            if isinstance(v, (int, float)):
                if v == float("inf"):
                    txt = "no contact"
                elif any(w in k for w in ("angle", "phase", "_deg")):
                    txt = f"{v:.1f}°"
                else:
                    txt = fmt_len(v, units, suffix=True)
            else:
                txt = "–" if v is None else str(v)
            it = QtWidgets.QTreeWidgetItem([label, txt])
            it.setToolTip(0, f"{label} [{k}]")
            if k in bad:
                it.setForeground(1, Qt.GlobalColor.red)
            self.values.addTopLevelItem(it)
