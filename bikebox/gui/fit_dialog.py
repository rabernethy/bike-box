"""Fit advisor: rider measurements, fitting scheme, recommendations, apply."""
from __future__ import annotations

import json

from ..model import params as P
from ..model.units import fmt_value
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document
from .param_panel import ParamPage

Qt = QtCore.Qt


class FitAdvisorDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        from ..fit import advisor
        self.A = advisor
        self.doc = doc
        self.setWindowTitle("Fit advisor")
        self.resize(1150, 720)
        lay = QtWidgets.QHBoxLayout(self)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)
        self.body = ParamPage(doc, "Rider & fit")
        split.addWidget(self.body)
        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Fitting scheme:"))
        self.scheme = QtWidgets.QComboBox()
        row.addWidget(self.scheme, 1)
        b = QtWidgets.QPushButton("Edit formulas…")
        b.clicked.connect(self.edit_scheme)
        row.addWidget(b)
        rv.addLayout(row)
        self.desc = QtWidgets.QLabel()
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: gray")
        rv.addWidget(self.desc)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Apply", "Recommendation", "Value", "Range", "Current"])
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        rv.addWidget(self.table, 2)
        brow = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Apply checked recommendations")
        b.clicked.connect(self.apply)
        brow.addWidget(b)
        self.show_rider = QtWidgets.QCheckBox("Show rider on drawing")
        self.show_rider.setChecked(bool(doc.design["show_rider"]))
        self.show_rider.toggled.connect(lambda v: doc.set_param("show_rider", v))
        brow.addWidget(self.show_rider)
        brow.addStretch(1)
        rv.addLayout(brow)
        rv.addWidget(QtWidgets.QLabel("Current fit:"))
        self.fit_table = QtWidgets.QTableWidget(0, 2)
        self.fit_table.setHorizontalHeaderLabels(["Measure", "Value"])
        self.fit_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.fit_table.verticalHeader().setVisible(False)
        rv.addWidget(self.fit_table, 1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        rv.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        split.addWidget(right)
        split.setSizes([420, 700])
        self._load_schemes()
        self.scheme.currentIndexChanged.connect(lambda _i: self.refresh())
        doc.changed.connect(self._on_changed)
        self.refresh()

    def _load_schemes(self):
        schemes = self.A.load_schemes(self.doc.design)
        if isinstance(schemes, dict):
            schemes = list(schemes.values())
        self.schemes = schemes
        cur = self.scheme.currentText()
        self.scheme.blockSignals(True)
        self.scheme.clear()
        for s in schemes:
            self.scheme.addItem(s.get("name", "Scheme"))
        i = self.scheme.findText(cur)
        self.scheme.setCurrentIndex(max(i, 0))
        self.scheme.blockSignals(False)

    def _on_changed(self, keys):
        self.body.refresh()
        self.refresh()

    def _current_scheme(self):
        i = self.scheme.currentIndex()
        return self.schemes[i] if 0 <= i < len(self.schemes) else None

    def refresh(self):
        sch = self._current_scheme()
        if sch is None:
            return
        self.desc.setText(sch.get("description", ""))
        try:
            self.recs = self.A.evaluate(sch, self.doc.design)
        except Exception as exc:
            self.recs = []
            self.desc.setText(f"Formula error: {exc}")
        units = self.doc.design["units"]
        g = self.doc.geometry
        try:
            from ..fit.rider import solve_pose
            angles = solve_pose(g).angles
        except Exception:
            angles = {}
        current = dict(g.v)
        current.update(angles)
        current.setdefault("knee_extension", angles.get("knee_extension_bdc", float("nan")))
        current.setdefault("max_standover", g.v.get("standover", float("nan")))
        current.setdefault("bar_width", self.doc.design.f("bar_width"))
        self.table.setRowCount(len(self.recs))
        for r, rec in enumerate(self.recs):
            chk = QtWidgets.QTableWidgetItem()
            if rec.param:
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(Qt.CheckState.Unchecked)
            else:
                chk.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(rec.label))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(fmt_value(rec.value, rec.unit, units)))
            rng = ("" if rec.low is None or rec.high is None else
                   f"{fmt_value(rec.low, rec.unit, units)} – {fmt_value(rec.high, rec.unit, units)}")
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(rng))
            val = current.get(rec.key)
            if val is None and rec.param and P.has(rec.param) and P.get(rec.param).kind == P.FLOAT:
                val = self.doc.design.f(rec.param)
            cur = fmt_value(float(val), rec.unit, units) if isinstance(val, (int, float)) else ""
            item = QtWidgets.QTableWidgetItem(cur)
            if isinstance(val, (int, float)) and rec.low is not None and rec.high is not None and val == val:
                ok = rec.low - 1e-6 <= val <= rec.high + 1e-6
                item.setForeground(QtGui.QBrush(QtGui.QColor("#1d8a3a" if ok else "#c77700")))
            self.table.setItem(r, 4, item)
        try:
            rows = self.A.fit_report(self.doc.geometry)
        except Exception as exc:
            rows = [("error", str(exc))]
        self.fit_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.fit_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.fit_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))

    def apply(self):
        keys = []
        for r, rec in enumerate(self.recs):
            it = self.table.item(r, 0)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                keys.append(rec.key)
        if not keys:
            return
        tmp = self.doc.design.copy()
        self.A.apply(self.recs, tmp, keys)
        changes = {k: v for k, v in tmp.values.items() if self.doc.design.values.get(k) != v}
        self.doc.set_params(changes, "Apply fit recommendations")

    def edit_scheme(self):
        sch = self._current_scheme() or {}
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Edit fitting scheme (JSON)")
        dlg.resize(760, 600)
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel("Formulas use rider measurements and design values as variables. Saving stores "
                                     "a custom scheme in this design file."))
        ed = QtWidgets.QPlainTextEdit(json.dumps(sch, indent=2))
        ed.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        v.addWidget(ed, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        v.addWidget(bb)
        bb.rejected.connect(dlg.reject)

        def save():
            try:
                new = json.loads(ed.toPlainText())
                self.A.evaluate(new, self.doc.design)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(dlg, "Invalid scheme", str(exc))
                return
            custom = dict(self.doc.design.extras.get("fit_formulas") or {})
            name = new.get("name") or "Custom scheme"
            if not str(name).endswith("(custom)") and name in [s.get("name") for s in self.schemes
                                                                if s is not sch or True]:
                name = f"{name} (custom)"
                new["name"] = name
            custom[name] = new
            self.doc.set_extra("fit_formulas", custom, "Edit fitting scheme")
            self._load_schemes()
            self.scheme.setCurrentIndex(max(self.scheme.findText(name), 0))
            dlg.accept()
        bb.accepted.connect(save)
        dlg.exec()

    def done(self, r):
        try:
            self.doc.changed.disconnect(self._on_changed)
        except (TypeError, RuntimeError):
            pass
        super().done(r)
