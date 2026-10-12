"""Parts libraries and the sourced parts catalog: browse, inspect specs and
sources, apply to the design, save your own items."""
from __future__ import annotations

import html

from ..model import params as P
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt


class LibraryDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        from ..model import library as L
        self.L = L
        self.doc = doc
        self.setWindowTitle("Parts libraries & catalog")
        self.resize(1250, 720)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search all libraries (brand, model, size…)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_items)
        top.addWidget(self.search, 1)
        self.sourced = QtWidgets.QCheckBox("Sourced catalog only")
        self.sourced.toggled.connect(self._fill_items)
        top.addWidget(self.sourced)
        self.current_only = QtWidgets.QCheckBox("Hide discontinued")
        self.current_only.toggled.connect(self._fill_items)
        top.addWidget(self.current_only)
        lay.addLayout(top)

        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.cats = QtWidgets.QListWidget()
        self.items = QtWidgets.QTreeWidget()
        self.items.setHeaderLabels(["Item", "Brand", "Status"])
        self.items.setRootIsDecorated(False)
        self.items.setUniformRowHeights(True)
        self.items.setSortingEnabled(True)
        self.items.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        right = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        self.detail = QtWidgets.QTableWidget(0, 3)
        self.detail.setHorizontalHeaderLabels(["Parameter", "Library value", "Current"])
        self.detail.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.detail.verticalHeader().setVisible(False)
        self.detail.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.info = QtWidgets.QTextBrowser()
        self.info.setOpenExternalLinks(True)
        right.addWidget(self.detail)
        right.addWidget(self.info)
        right.setSizes([260, 380])
        split.addWidget(self.cats)
        split.addWidget(self.items)
        split.addWidget(right)
        split.setSizes([170, 520, 560])
        lay.addWidget(split, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Apply to design")
        b.clicked.connect(self.apply)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Save current values as library item…")
        b.clicked.connect(self.save_item)
        row.addWidget(b)
        self.count = QtWidgets.QLabel()
        self.count.setStyleSheet("color: gray")
        row.addWidget(self.count)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        for c in L.categories():
            it = QtWidgets.QListWidgetItem(L.category_label(c))
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.cats.addItem(it)
        self.cats.currentRowChanged.connect(lambda _r: self._fill_items())
        self.items.currentItemChanged.connect(lambda cur, _prev: self._show(cur))
        self.items.itemDoubleClicked.connect(lambda _i, _c: self.apply())
        self._items = []
        if self.cats.count():
            self.cats.setCurrentRow(0)

    # -- listing -------------------------------------------------------------------
    def _category(self) -> str | None:
        c = self.cats.currentItem()
        return c.data(Qt.ItemDataRole.UserRole) if c else None

    def _fill_items(self, *_):
        text = self.search.text().strip()
        if text:
            items = self.L.search(text)
        else:
            cat = self._category()
            items = self.L.items(cat) if cat else []
        if self.sourced.isChecked():
            items = [i for i in items if i.meta.get("catalog")]
        if self.current_only.isChecked():
            items = [i for i in items if i.meta.get("status") != "discontinued"]
        self._items = items
        self.items.setSortingEnabled(False)
        self.items.clear()
        for idx, it in enumerate(items):
            name = it.name + (f"   [{self.L.category_label(it.category)}]" if text else "")
            row = QtWidgets.QTreeWidgetItem([name, str(it.meta.get("brand", "") or ("generic" if not it.meta.get(
                "catalog") else "")), str(it.meta.get("status", "") or "")])
            row.setData(0, Qt.ItemDataRole.UserRole, idx)
            if it.meta.get("catalog"):
                row.setToolTip(0, "Sourced catalog item")
            if it.meta.get("status") == "discontinued":
                for c in range(3):
                    row.setForeground(c, QtGui.QBrush(QtGui.QColor("gray")))
            self.items.addTopLevelItem(row)
        self.items.setSortingEnabled(True)
        n_src = sum(1 for i in items if i.meta.get("catalog"))
        self.count.setText(f"{len(items)} items ({n_src} sourced)")
        if items:
            self.items.setCurrentItem(self.items.topLevelItem(0))
        else:
            self.detail.setRowCount(0)
            self.info.clear()

    def _selected(self):
        cur = self.items.currentItem()
        if cur is None:
            return None
        idx = cur.data(0, Qt.ItemDataRole.UserRole)
        return self._items[idx] if idx is not None and 0 <= idx < len(self._items) else None

    # -- details ----------------------------------------------------------------------
    def _show(self, cur):
        it = self._selected()
        if it is None:
            return
        rows = []
        names = {"tt": "Top tube", "dt": "Down tube", "st": "Seat tube", "ht": "Head tube", "cs": "Chainstay",
                 "ss": "Seat stay", "fork_blade": "Fork blade", "steerer": "Steerer"}
        for k, v in it.values.items():
            if k == "tubes" and isinstance(v, dict):
                for t, spec in v.items():
                    if isinstance(spec, dict):
                        txt = f"Ø{spec.get('od', '?')} × {spec.get('wall', '?')}"
                        if spec.get("length_mm"):
                            txt += f", {spec['length_mm']} long"
                        rows.append((names.get(t, t), txt, ""))
                continue
            label = P.get(k).label if P.has(k) else k
            rows.append((label, str(v), str(self.doc.design.get(k, ""))))
        self.detail.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, txt in enumerate(row):
                self.detail.setItem(r, c, QtWidgets.QTableWidgetItem(txt))
        self.info.setHtml(self._info_html(it))

    def _info_html(self, it) -> str:
        m = it.meta
        e = html.escape
        parts = [f"<h3>{e(it.name)}</h3>"]
        line = " · ".join(e(str(m[k])) for k in ("brand", "model", "variant", "years") if m.get(k))
        if line:
            parts.append(f"<p>{line}</p>")
        if m.get("status"):
            parts.append(f"<p><b>Status:</b> {e(str(m['status']))}</p>")
        specs = m.get("specs")
        if isinstance(specs, dict) and specs:
            rows = "".join(f"<tr><td>{e(str(k).replace('_', ' '))}</td><td><b>{e(str(v))}</b></td></tr>"
                           for k, v in specs.items())
            parts.append(f"<h4>Specifications</h4><table cellspacing='4'>{rows}</table>")
        derived = m.get("derived")
        if isinstance(derived, dict) and derived:
            rows = "".join(f"<li><b>{e(k)}</b>: {e(str(v))}</li>" for k, v in derived.items())
            parts.append(f"<h4>Derived values</h4><ul>{rows}</ul>")
        notes = m.get("notes") or m.get("note") or m.get("description")
        if notes:
            if isinstance(notes, (list, tuple)):
                notes = " ".join(str(n) for n in notes)
            parts.append(f"<h4>Notes</h4><p>{e(str(notes))}</p>")
        srcs = m.get("sources")
        if isinstance(srcs, list) and srcs:
            rows = []
            for s in srcs:
                if not isinstance(s, dict):
                    continue
                url = str(s.get("url", ""))
                pub = e(str(s.get("publisher") or url))
                kind = e(str(s.get("kind", "")))
                acc = e(str(s.get("accessed", "")))
                link = f"<a href='{e(url)}'>{pub}</a>" if url.startswith(("http://", "https://")) else pub
                rows.append(f"<li>{link} <span style='color:gray'>({kind}{', ' + acc if acc else ''})</span></li>")
            parts.append(f"<h4>Sources</h4><ul>{''.join(rows)}</ul>")
        elif not m.get("catalog"):
            src = m.get("source") or m.get("source_file")
            parts.append("<p style='color:gray'>Generic library item"
                         + (f" ({e(str(src))})" if src else "") + " — not tied to a specific product.</p>")
        return "".join(parts)

    # -- actions -----------------------------------------------------------------------
    def apply(self):
        it = self._selected()
        if it is None:
            return
        tmp = self.doc.design.copy()
        self.L.apply(tmp, it)
        changes = {k: v for k, v in tmp.values.items() if self.doc.design.values.get(k) != v}
        if changes:
            self.doc.set_params(changes, f"Apply {it.name}")
        elif not it.values:
            QtWidgets.QMessageBox.information(self, "Library", "This is a reference part: it has specs but sets "
                                                               "no design parameters.")
        self._show(self.items.currentItem())

    def save_item(self):
        cat = self._category() or "custom"
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
