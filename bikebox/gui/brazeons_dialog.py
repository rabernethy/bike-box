"""Braze-on / mount placement: add, edit, remove and position bosses, cable
stops/guides, rack & fender eyelets and disc mounts on the frame tubes."""
from __future__ import annotations

from ..geometry.solver import solve
from ..qt import QtCore, QtWidgets
from .document import Document

Qt = QtCore.Qt

TYPES = [("bottle", "Bottle bosses (pair)"), ("boss", "Single boss (M5)"), ("cable_stop", "Cable stop"),
         ("cable_guide", "Cable guide"), ("rack_eyelet", "Rack eyelet"), ("fender_eyelet", "Fender eyelet"),
         ("disc_mount", "Disc mount tab")]
TUBES = [("dt", "Down tube"), ("tt", "Top tube"), ("st", "Seat tube"), ("ht", "Head tube"),
         ("cs", "Chainstay"), ("ss", "Seat stay")]
FROM = [("a", "from the far / lower end"), ("b", "from the near / upper end")]

PRESETS = {
    "Down-tube bottle": {"type": "bottle", "tube": "dt", "s": 180, "spacing": 64, "label": "DT bottle"},
    "Seat-tube bottle": {"type": "bottle", "tube": "st", "s": 140, "spacing": 64, "label": "ST bottle"},
    "Top-tube bag bosses": {"type": "boss", "tube": "tt", "s": 60, "spacing": 35, "label": "TT bag"},
    "Rack eyelet (seat stay)": {"type": "rack_eyelet", "tube": "ss", "s": 15, "label": "rack"},
    "Fender eyelet (chainstay)": {"type": "fender_eyelet", "tube": "cs", "s": 20, "label": "fender"},
    "Down-tube cable stop": {"type": "cable_stop", "tube": "dt", "s": 90, "from": "b", "label": "cable stop"},
}


class BrazeOnsDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Braze-ons & mounts")
        self.resize(720, 460)
        lay = QtWidgets.QVBoxLayout(self)

        pr = QtWidgets.QHBoxLayout()
        pr.addWidget(QtWidgets.QLabel("Add preset:"))
        self.preset = QtWidgets.QComboBox()
        self.preset.addItem("—", None)
        for name in PRESETS:
            self.preset.addItem(name, name)
        self.preset.activated.connect(self._add_preset)
        pr.addWidget(self.preset)
        pr.addStretch(1)
        lay.addLayout(pr)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Type", "Tube", "Pos (mm)", "Measured", "Side", "Spacing", "Label"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        # add row editor
        form = QtWidgets.QHBoxLayout()
        self.e_type = QtWidgets.QComboBox()
        for v, l in TYPES:
            self.e_type.addItem(l, v)
        self.e_tube = QtWidgets.QComboBox()
        for v, l in TUBES:
            self.e_tube.addItem(l, v)
        self.e_pos = QtWidgets.QDoubleSpinBox(); self.e_pos.setRange(0, 2000); self.e_pos.setSuffix(" mm"); self.e_pos.setValue(120)
        self.e_from = QtWidgets.QComboBox()
        for v, l in FROM:
            self.e_from.addItem(l, v)
        self.e_side = QtWidgets.QDoubleSpinBox(); self.e_side.setRange(-60, 60); self.e_side.setSuffix(" mm")
        self.e_spacing = QtWidgets.QDoubleSpinBox(); self.e_spacing.setRange(0, 200); self.e_spacing.setSuffix(" mm"); self.e_spacing.setValue(64)
        self.e_label = QtWidgets.QLineEdit()
        for w in (self.e_type, self.e_tube, self.e_pos, self.e_from, self.e_side, self.e_spacing, self.e_label):
            form.addWidget(w)
        add = QtWidgets.QPushButton("Add")
        add.clicked.connect(self._add_current)
        form.addWidget(add)
        lay.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        dele = QtWidgets.QPushButton("Delete selected")
        dele.clicked.connect(self._delete)
        row.addWidget(dele)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._reload()

    def _items(self) -> list[dict]:
        return [dict(b) for b in self.doc.design.extras.get("brazeons") or []]

    def _reload(self):
        items = self._items()
        g = self.doc.geometry
        labels_t = dict(TYPES)
        labels_tube = dict(TUBES)
        self.table.setRowCount(len(items))
        resolved = {id(b): None for b in items}
        for i, b in enumerate(items):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(labels_t.get(b.get("type"), b.get("type", ""))))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(labels_tube.get(b.get("tube"), b.get("tube", ""))))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{float(b.get('s', 0)):g}"))
            frm = "near/upper" if b.get("from") == "b" else "far/lower"
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(frm))
            self.table.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{float(b.get('side', 0) or 0):g}"))
            self.table.setItem(i, 5, QtWidgets.QTableWidgetItem(f"{float(b.get('spacing', 0) or 0):g}"))
            self.table.setItem(i, 6, QtWidgets.QTableWidgetItem(str(b.get("label", ""))))

    def _save(self, items: list[dict], text: str):
        self.doc.set_extra("brazeons", items, text)
        self._reload()

    def _add_current(self):
        items = self._items()
        items.append({"type": self.e_type.currentData(), "tube": self.e_tube.currentData(),
                      "s": self.e_pos.value(), "from": self.e_from.currentData(),
                      "side": self.e_side.value(), "spacing": self.e_spacing.value() if self.e_type.currentData()
                      in ("bottle", "boss") else 0.0, "label": self.e_label.text().strip()})
        self._save(items, "Add braze-on")

    def _add_preset(self, _i):
        name = self.preset.currentData()
        if not name:
            return
        items = self._items()
        items.append(dict(PRESETS[name]))
        self.preset.setCurrentIndex(0)
        self._save(items, f"Add {name}")

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not rows:
            return
        items = self._items()
        for r in rows:
            if 0 <= r < len(items):
                del items[r]
        self._save(items, "Delete braze-on")
