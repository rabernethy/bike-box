"""Standard parts libraries (tubing, forks, stems, bars, wheels ...)."""
from __future__ import annotations

from ..model import params as P
from ..qt import QtCore, QtWidgets
from .document import Document

Qt = QtCore.Qt


class LibraryDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        from ..model import library as L
        self.L = L
        self.doc = doc
        self.setWindowTitle("Parts libraries")
        self.resize(980, 600)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search all libraries…")
        self.search.textChanged.connect(self._fill_items)
        top.addWidget(self.search)
        lay.addLayout(top)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.cats = QtWidgets.QListWidget()
        self.items = QtWidgets.QListWidget()
        self.detail = QtWidgets.QTableWidget(0, 3)
        self.detail.setHorizontalHeaderLabels(["Parameter", "Library value", "Current"])
        self.detail.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.detail.verticalHeader().setVisible(False)
        split.addWidget(self.cats)
        split.addWidget(self.items)
        split.addWidget(self.detail)
        split.setSizes([170, 330, 460])
        lay.addWidget(split, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Apply to design")
        b.clicked.connect(self.apply)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Save current values as library item…")
        b.clicked.connect(self.save_item)
        row.addWidget(b)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        for c in L.categories():
            self.cats.addItem(c)
        self.cats.currentRowChanged.connect(lambda _r: self._fill_items())
        self.items.currentRowChanged.connect(self._show)
        self.items.itemDoubleClicked.connect(lambda _i: self.apply())
        self._items = []
        if self.cats.count():
            self.cats.setCurrentRow(0)

    def _fill_items(self, *_):
        text = self.search.text().strip()
        if text:
            self._items = self.L.search(text)
        else:
            c = self.cats.currentItem()
            self._items = self.L.items(c.text()) if c else []
        self.items.clear()
        for it in self._items:
            self.items.addItem(f"{it.name}" + (f"   [{it.category}]" if text else ""))
        if self._items:
            self.items.setCurrentRow(0)
        else:
            self.detail.setRowCount(0)

    def _show(self, row):
        if not (0 <= row < len(self._items)):
            return
        it = self._items[row]
        vals = [(k, v) for k, v in it.values.items()]
        self.detail.setRowCount(len(vals))
        for r, (k, v) in enumerate(vals):
            label = P.get(k).label if P.has(k) else k
            self.detail.setItem(r, 0, QtWidgets.QTableWidgetItem(label))
            self.detail.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))
            self.detail.setItem(r, 2, QtWidgets.QTableWidgetItem(str(self.doc.design.get(k, ""))))
        notes = it.meta.get("notes") or it.meta.get("description") or ""
        self.detail.setToolTip(str(notes))

    def apply(self):
        row = self.items.currentRow()
        if not (0 <= row < len(self._items)):
            return
        tmp = self.doc.design.copy()
        self.L.apply(tmp, self._items[row])
        changes = {k: v for k, v in tmp.values.items() if self.doc.design.values.get(k) != v}
        if changes:
            self.doc.set_params(changes, f"Apply {self._items[row].name}")
        self._show(row)

    def save_item(self):
        c = self.cats.currentItem()
        cat = c.text() if c else "custom"
        keys = sorted({k for it in (self.L.items(cat) or []) for k in it.values if P.has(k)})
        if not keys:
            QtWidgets.QMessageBox.information(self, "Library", "Choose a category with existing items first.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save library item", f"Name for new '{cat}' item:")
        if ok and name.strip():
            vals = {k: self.doc.design[k] for k in keys}
            p = self.L.save_user_item(cat, name.strip(), vals)
            QtWidgets.QMessageBox.information(self, "Library", f"Saved to {p}")
            self._fill_items()
