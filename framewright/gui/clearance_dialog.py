"""'Fix clearance' dialog: proposes the smallest changes that make the tires fit."""
from __future__ import annotations

from ..geometry import clearance as C
from ..geometry.clearance_fix import Plan, merged_changes, plan_fixes
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt


class FixClearanceDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Fix tire clearance")
        self.resize(980, 460)
        lay = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Problem", "Proposed change", "Clearance", "Side effects"])
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray")
        lay.addWidget(self.note)
        bb = QtWidgets.QDialogButtonBox()
        self.apply_btn = bb.addButton("Apply checked fixes", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QtWidgets.QDialogButtonBox.StandardButton.Close)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.plan: Plan | None = None
        QtCore.QTimer.singleShot(0, self.compute)

    def compute(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.plan = plan_fixes(self.doc.design)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        fixes = self.plan.fixes
        before = C.problems(self.doc.geometry)
        tire_before = [p for p in before if "Toe" not in p]
        self.table.setRowCount(len(fixes))
        units = self.doc.design["units"]
        from ..model.units import fmt_len
        for r, f in enumerate(fixes):
            chk = QtWidgets.QTableWidgetItem(f.problem)
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(f.label))
            cl = QtWidgets.QTableWidgetItem(f"{fmt_len(f.before, units)} → {fmt_len(f.after, units, suffix=True)}")
            cl.setForeground(QtGui.QBrush(QtGui.QColor("#1d8a3a")))
            self.table.setItem(r, 2, cl)
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem("\n".join(f.side_effects) or "geometry unchanged"))
        self.table.resizeRowsToContents()
        if not tire_before:
            self.summary.setText("<b>All tires fit.</b> No tire clearance problems.")
        elif fixes:
            self.summary.setText(f"<b>{len(tire_before)} clearance problem(s).</b> These changes make the tires fit, "
                                 "cheapest remedies first (crimped stays, chainline, stay bends, yoke, bridges, "
                                 "crown) before changing geometry. Uncheck any you don't want.")
        else:
            self.summary.setText("<b>No automatic fix found</b> for: " + "; ".join(tire_before))
        rem = [p for p in self.plan.remaining]
        self.note.setText(("Still to resolve by hand: " + "; ".join(rem)) if rem else "")
        self.apply_btn.setEnabled(bool(fixes))

    def apply(self) -> None:
        if not self.plan:
            return
        chosen = [f for r, f in enumerate(self.plan.fixes)
                  if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]
        if chosen:
            self.doc.set_params(merged_changes(chosen), "Fix tire clearance")
        self.accept()
