"""Live results: key geometry, fit numbers, clearances, warnings and the
analysis report."""
from __future__ import annotations

from ..model.units import fmt_angle, fmt_len
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt

L, A = "len", "ang"
SECTIONS = [
    ("Geometry", [
        ("Stack", "stack", L), ("Reach", "reach", L), ("Stack / reach", "_ratio", None),
        ("Effective top tube", "top_tube_effective", L), ("Top tube (c-c)", "top_tube_cc", L),
        ("Top tube angle", "top_tube_angle", A), ("Head tube length", "head_tube_length", L),
        ("Head tube angle", "head_tube_angle", A), ("Seat tube angle", "seat_tube_angle", A),
        ("Seat tube (c-t)", "seat_tube_ct", L), ("Seat tube (c-c)", "seat_tube_cc", L),
        ("Seat tube extension", "st_extension", L), ("Down tube (c-c)", "down_tube_cc", L),
        ("Chainstay", "chainstay_length", L), ("Rear centre (horiz.)", "rear_center_h", L),
        ("Front centre", "front_center", L), ("Wheelbase", "wheelbase", L), ("BB drop", "bb_drop", L),
        ("BB height", "bb_height", L), ("Fork axle-to-crown", "fork_length", L), ("Fork offset", "fork_offset", L),
        ("Trail", "trail", L), ("Mechanical trail", "mech_trail", L), ("Wheel flop", "wheel_flop", L),
        ("Standover", "standover", L), ("Stack to headset top", "stack_headset", L),
        ("Steerer length (crown to top)", "steerer_length", L),
    ]),
    ("Fit", [
        ("Saddle height", "saddle_height", L), ("Saddle setback", "saddle_setback", L),
        ("Saddle nose behind BB", "saddle_nose_setback", L), ("Effective seat angle", "seat_angle_eff", A),
        ("Handlebar X from BB", "bar_x", L), ("Handlebar Y from BB", "bar_y", L),
        ("Hands X from BB", "hand_x", L), ("Hands Y from BB", "hand_y", L),
        ("Saddle to bar drop", "saddle_bar_drop", L), ("Saddle nose to bar", "nose_to_bar", L),
        ("Saddle nose to hands", "nose_to_hand", L), ("Seatpost setback needed", "seatpost_setback", L),
        ("Seatpost exposed", "seatpost_exposed", L), ("Seatpost insertion", "seatpost_insertion", L),
        ("Virtual top tube", "top_tube_virtual", L),
    ]),
    ("Clearances", [
        ("Toe clearance", "toe_clearance", L), ("Rear tire to seat tube", "rear_tire_clearance", L),
        ("Front tire to down tube", "front_tire_clearance", L), ("Pedal to ground", "pedal_clearance", L),
        ("Lean angle at pedal strike", "lean_angle", A),
    ]),
    ("Joint angles", [
        ("Head tube / top tube", "angle_ht_tt", A), ("Head tube / down tube", "angle_ht_dt", A),
        ("Seat tube / top tube", "angle_st_tt", A), ("Seat tube / down tube", "angle_st_dt", A),
        ("Seat tube / seat stay", "angle_st_ss", A),
    ]),
]
_STATUS_COLORS = {"ok": "#1d8a3a", "warn": "#c77700", "fail": "#c62828", "info": None}


class ResultsPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Document | None = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.warn = QtWidgets.QLabel()
        self.warn.setWordWrap(True)
        self.warn.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.warn)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Measurement", "Value"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)
        self.with_report = QtWidgets.QCheckBox("Include full analysis (gearing, weight, UCI, structure)")
        self.with_report.setChecked(True)
        self.with_report.toggled.connect(lambda _v: self.refresh())
        lay.addWidget(self.with_report)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.refresh)
        self._expanded: dict[str, bool] = {}

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            try:
                self.doc.changed.disconnect(self._schedule)
            except (TypeError, RuntimeError):
                pass
        self.doc = doc
        if doc is not None:
            doc.changed.connect(self._schedule)
        self.refresh()

    def _schedule(self, *_):
        self._timer.start()

    def refresh(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            self._expanded[it.text(0)] = it.isExpanded()
        self.tree.clear()
        if self.doc is None:
            self.warn.clear()
            return
        g = self.doc.geometry
        units = self.doc.design["units"]
        issues = list(g.warnings)
        try:
            from ..geometry.clearance import problems
            issues += [f"3-D: {p}" for p in problems(g)]
        except Exception:
            pass
        if issues:
            self.warn.setText("".join(f"<div style='color:#c62828'>⚠ {w}</div>" for w in issues))
            self.warn.show()
        else:
            self.warn.setText("<span style='color:#1d8a3a'>✓ No geometry or clearance warnings</span>")
        for title, rows in SECTIONS:
            top = QtWidgets.QTreeWidgetItem([title, ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for label, key, kind in rows:
                if key == "_ratio":
                    val = f"{g.v['stack'] / g.v['reach']:.3f}" if g.v.get("reach") else "–"
                elif key not in g.v:
                    continue
                else:
                    v = g.v[key]
                    val = fmt_angle(v) if kind == A else fmt_len(v, units, suffix=True)
                it = QtWidgets.QTreeWidgetItem([label, val])
                it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if key == "toe_clearance" and g.v[key] < 0:
                    it.setForeground(1, QtGui.QBrush(QtGui.QColor("#c62828")))
                top.addChild(it)
            top.setExpanded(self._expanded.get(title, title in ("Geometry", "Fit", "Clearances")))
        if self.with_report.isChecked():
            self._add_report(g)

    def _add_report(self, g) -> None:
        try:
            from ..analysis.report import full_report
        except ImportError:
            return
        try:
            sections = full_report(g)
        except Exception as exc:              # keep the panel alive if analysis fails
            top = QtWidgets.QTreeWidgetItem(["Analysis", f"error: {exc}"])
            self.tree.addTopLevelItem(top)
            return
        for sec in sections:
            if sec.title in ("Key geometry", "Geometry"):
                continue
            top = QtWidgets.QTreeWidgetItem([sec.title, ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for row in sec.rows:
                label, value, status = (list(row) + ["info"])[:3]
                it = QtWidgets.QTreeWidgetItem([str(label), str(value)])
                it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                col = _STATUS_COLORS.get(status)
                if col:
                    it.setForeground(1, QtGui.QBrush(QtGui.QColor(col)))
                it.setToolTip(0, str(label))
                it.setToolTip(1, str(value))
                top.addChild(it)
            top.setExpanded(self._expanded.get(sec.title, False))
