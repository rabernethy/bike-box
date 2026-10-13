"""Cable / hose routing: add common routes (internal or external) and remove
them. Routes draw on the frame; internal routes mark entry/exit ports."""
from __future__ import annotations

from ..qt import QtCore, QtWidgets
from .document import Document

Qt = QtCore.Qt

TYPES = {"shift": "Rear shift cable", "shift_front": "Front shift cable", "brake": "Rear brake",
         "dropper": "Dropper post", "di2": "Di2 / electronic", "dynamo": "Dynamo wire", "cable": "Other"}

# presets: route points as specs along the frame tubes (resolved by the solver)
PRESETS = {
    "Rear shift (internal, DT→CS)": {
        "type": "shift", "internal": True, "label": "RD",
        "points": [{"tube": "dt", "s": 60, "from": "b"}, {"tube": "dt", "s": 40}, {"tube": "cs", "s": 90}, "rear_axle"]},
    "Front shift (internal, DT)": {
        "type": "shift_front", "internal": True, "label": "FD",
        "points": [{"tube": "dt", "s": 60, "from": "b"}, {"tube": "dt", "s": 30}, {"tube": "st", "s": 120, "from": "b"}]},
    "Rear brake hose (internal, DT→CS)": {
        "type": "brake", "internal": True, "label": "rear brake",
        "points": [{"tube": "dt", "s": 90, "from": "b"}, {"tube": "dt", "s": 40}, {"tube": "cs", "s": 60}, "rear_axle"]},
    "Rear brake hose (internal, TT→SS)": {
        "type": "brake", "internal": True, "label": "rear brake",
        "points": [{"tube": "tt", "s": 60}, {"tube": "tt", "s": 40, "from": "b"}, {"tube": "ss", "s": 80}, "rear_axle"]},
    "Dropper (internal, DT→ST)": {
        "type": "dropper", "internal": True, "label": "dropper",
        "points": [{"tube": "dt", "s": 60, "from": "b"}, {"tube": "dt", "s": 120}, {"tube": "st", "s": 150, "from": "b"}, "st_top"]},
    "Dynamo wire (internal, DT→HT)": {
        "type": "dynamo", "internal": True, "label": "dynamo",
        "points": [{"tube": "dt", "s": 30, "from": "b"}, {"tube": "dt", "s": 120}, "crown_bottom"]},
}


class RoutingDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Cable & hose routing")
        self.resize(560, 420)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Add common cable/hose routes. They draw on the frame; internal routes "
                                       "mark entry/exit ports (also listed on the build sheet)."))
        pr = QtWidgets.QHBoxLayout()
        pr.addWidget(QtWidgets.QLabel("Add preset:"))
        self.preset = QtWidgets.QComboBox()
        self.preset.addItem("—", None)
        for name in PRESETS:
            self.preset.addItem(name, name)
        self.preset.activated.connect(self._add_preset)
        pr.addWidget(self.preset, 1)
        lay.addLayout(pr)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Type", "Routing", "Points", "Label"])
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        d = QtWidgets.QPushButton("Delete selected")
        d.clicked.connect(self._delete)
        row.addWidget(d)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._reload()

    def _routes(self):
        return [dict(r) for r in self.doc.design.extras.get("routing") or []]

    def _reload(self):
        routes = self._routes()
        self.table.setRowCount(len(routes))
        for i, r in enumerate(routes):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(TYPES.get(r.get("type"), r.get("type", ""))))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem("internal" if r.get("internal") else "external"))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(len(r.get("points") or []))))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(str(r.get("label", ""))))

    def _add_preset(self, _i):
        name = self.preset.currentData()
        if not name:
            return
        routes = self._routes()
        routes.append(dict(PRESETS[name]))
        self.preset.setCurrentIndex(0)
        self.doc.set_extra("routing", routes, f"Add route {name}")
        self._reload()

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        routes = self._routes()
        for r in rows:
            if 0 <= r < len(routes):
                del routes[r]
        self.doc.set_extra("routing", routes, "Delete route")
        self._reload()
