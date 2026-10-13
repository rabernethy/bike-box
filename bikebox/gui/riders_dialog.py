"""Rider database: save the current rider's measurements, apply a saved rider
to the design, or delete one."""
from __future__ import annotations

from ..model import params as P
from ..model import riders as R
from ..model.units import fmt_len
from ..qt import QtWidgets
from .document import Document

# a few headline measurements to show per rider
SHOW = ["rider_height", "inseam", "torso_length", "arm_length", "shoulder_width", "rider_mass"]


class RidersDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Rider database")
        self.resize(640, 420)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Saved riders (body measurements). Apply one to drive the fit advisor and "
                                       "sizing; everything else in the design is unchanged."))
        self.table = QtWidgets.QTableWidget(0, 1 + len(SHOW))
        heads = ["Rider"] + [P.get(k).label if P.has(k) else k for k in SHOW]
        self.table.setHorizontalHeaderLabels(heads)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(lambda _i: self.apply())
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Save current rider…")
        b.clicked.connect(self.save_current)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Apply to design")
        b.clicked.connect(self.apply)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Delete")
        b.clicked.connect(self.delete)
        row.addWidget(b)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._reload()

    def _reload(self):
        riders = R.load_all()
        self._names = sorted(riders)
        units = self.doc.design["units"]
        self.table.setRowCount(len(self._names))
        for r, name in enumerate(self._names):
            vals = riders[name]
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            for c, key in enumerate(SHOW, start=1):
                v = vals.get(key)
                if v in (None, 0, 0.0):
                    txt = ""
                elif key == "rider_mass":
                    txt = f"{v:g} kg"
                else:
                    txt = fmt_len(float(v), units, suffix=True)
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(txt))

    def _selected(self) -> str | None:
        rows = {i.row() for i in self.table.selectedItems()}
        return self._names[min(rows)] if rows else None

    def save_current(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save rider", "Rider name:")
        if ok and name.strip():
            R.save(name.strip(), R.rider_from_design(self.doc.design))
            self._reload()

    def apply(self):
        name = self._selected()
        if not name:
            return
        changes = {k: R.load_all().get(name, {}).get(k) for k in R.RIDER_KEYS
                   if k in R.load_all().get(name, {})}
        changes = {k: v for k, v in changes.items() if P.has(k) and self.doc.design.get(k) != v}
        if changes:
            self.doc.set_params(changes, f"Apply rider '{name}'")
        self.accept()

    def delete(self):
        name = self._selected()
        if name and QtWidgets.QMessageBox.question(self, "Delete rider", f"Delete '{name}'?") == \
                QtWidgets.QMessageBox.StandardButton.Yes:
            R.delete(name)
            self._reload()
