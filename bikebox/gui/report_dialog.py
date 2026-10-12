"""Analysis report: geometry, gearing, chain/belt, weight, UCI, structure,
fixture numbers.  Sections come from analysis.report.full_report."""
from __future__ import annotations

import csv
from pathlib import Path

from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt
_COLORS = {"ok": "#1d8a3a", "pass": "#1d8a3a", "warn": "#c77700", "fail": "#c62828"}


class ReportDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None, focus: str | None = None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Analysis report")
        self.resize(820, 680)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        lay.addWidget(self.tabs, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Refresh")
        b.clicked.connect(self.build)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Export CSV…")
        b.clicked.connect(self.export)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Copy as text")
        b.clicked.connect(self.copy)
        row.addWidget(b)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.sections = []
        self.build()
        if focus:
            for i in range(self.tabs.count()):
                if focus.lower() in self.tabs.tabText(i).lower():
                    self.tabs.setCurrentIndex(i)
                    break

    def build(self) -> None:
        self.tabs.clear()
        g = self.doc.geometry
        try:
            from ..analysis.report import full_report
            self.sections = full_report(g)
        except Exception as exc:
            self.sections = []
            self.tabs.addTab(QtWidgets.QLabel(f"Analysis unavailable: {exc}"), "Error")
            return
        for sec in self.sections:
            table = QtWidgets.QTableWidget(len(sec.rows), 2)
            table.setHorizontalHeaderLabels(["Item", "Value"])
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            for r, row in enumerate(sec.rows):
                label, value, status = (list(row) + ["info"])[:3]
                a = QtWidgets.QTableWidgetItem(str(label))
                b = QtWidgets.QTableWidgetItem(str(value))
                b.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                col = _COLORS.get(str(status))
                if col:
                    b.setForeground(QtGui.QBrush(QtGui.QColor(col)))
                a.setToolTip(str(label))
                b.setToolTip(str(value))
                table.setItem(r, 0, a)
                table.setItem(r, 1, b)
            self.tabs.addTab(table, sec.title.replace("&", "&&"))

    def _rows(self):
        for sec in self.sections:
            for row in sec.rows:
                label, value, status = (list(row) + ["info"])[:3]
                yield sec.title, label, value, status

    def export(self) -> None:
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export report", str(Path.home() / "report.csv"),
                                                      "CSV (*.csv)")
        if fn:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Section", "Item", "Value", "Status"])
                w.writerows(self._rows())

    def copy(self) -> None:
        lines = []
        cur = None
        for sec, label, value, status in self._rows():
            if sec != cur:
                lines.append(f"\n== {sec} ==")
                cur = sec
            lines.append(f"{label:40s} {value}")
        QtWidgets.QApplication.clipboard().setText("\n".join(lines).strip())
