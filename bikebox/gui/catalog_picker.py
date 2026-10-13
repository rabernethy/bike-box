"""In-context catalog picker.

Opened from a component's section in the parameter panel ("Choose from
catalog…") so a part — or a single tube for one frame position — can be applied
straight to the design without digging through the full library browser.
"""
from __future__ import annotations

import html

from ..model import library as L
from ..model import params as P
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt

def _weight_g(specs) -> float | None:
    """A grams figure from a catalog item's specs, if one is published."""
    if not isinstance(specs, dict):
        return None
    for key in ("weight_g", "weight_g_approx", "weight_from_g", "set_weight_g", "weight_g_pair", "weight"):
        v = specs.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    lo, hi = specs.get("weight_g_min"), specs.get("weight_g_max")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        return (lo + hi) / 2.0
    return None


# human labels for the per-position tube pickers
TUBE_LABELS = {"tt": "top tube", "dt": "down tube", "st": "seat tube", "ht": "head tube",
               "cs": "chainstay", "ss": "seat stay", "fork": "fork blade", "steerer": "steerer"}


class CatalogPicker(QtWidgets.QDialog):
    def __init__(self, doc: Document, category: str, tube_pos: str | None = None, parent=None,
                 title: str | None = None):
        super().__init__(parent)
        self.doc = doc
        self.category = category
        self.tube_pos = tube_pos
        self.setWindowTitle(title or f"Choose {L.category_label(category)} from catalog")
        self.resize(900, 560)
        lay = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search (brand, model, size…)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        top.addWidget(self.search, 1)
        self.current_only = QtWidgets.QCheckBox("Hide discontinued")
        self.current_only.toggled.connect(self._fill)
        top.addWidget(self.current_only)
        lay.addLayout(top)

        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(lambda _r: self._show())
        self.list.itemDoubleClicked.connect(lambda _i: self.use())
        self.info = QtWidgets.QTextBrowser()
        self.info.setOpenExternalLinks(True)
        split.addWidget(self.list)
        split.addWidget(self.info)
        split.setSizes([400, 480])
        lay.addWidget(split, 1)

        row = QtWidgets.QHBoxLayout()
        self.count = QtWidgets.QLabel()
        self.count.setStyleSheet("color: gray")
        row.addWidget(self.count)
        row.addStretch(1)
        use = QtWidgets.QPushButton("Use selected")
        use.setDefault(True)
        use.clicked.connect(self.use)
        row.addWidget(use)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

        self._items: list[L.LibraryItem] = []
        self._fill()

    def _candidates(self) -> list[L.LibraryItem]:
        text = self.search.text().strip()
        items = L.search(text) if text else L.items(self.category)
        items = [i for i in items if i.category == self.category]
        if self.tube_pos:
            items = [i for i in items if self.tube_pos in L.item_tube_positions(i)]
        if self.current_only.isChecked():
            items = [i for i in items if i.meta.get("status") != "discontinued"]
        return items

    def _fill(self, *_):
        self._items = self._candidates()
        self.list.clear()
        for it in self._items:
            label = it.name + ("" if it.meta.get("status") != "discontinued" else "  (discontinued)")
            self.list.addItem(label)
        n_src = sum(1 for i in self._items if i.meta.get("catalog"))
        where = f" for the {TUBE_LABELS.get(self.tube_pos, self.tube_pos)}" if self.tube_pos else ""
        self.count.setText(f"{len(self._items)} items{where} ({n_src} sourced)")
        if self._items:
            self.list.setCurrentRow(0)
        else:
            self.info.clear()

    def _selected(self) -> L.LibraryItem | None:
        r = self.list.currentRow()
        return self._items[r] if 0 <= r < len(self._items) else None

    def _show(self):
        it = self._selected()
        if it is None:
            self.info.clear()
            return
        e = html.escape
        parts = [f"<h3>{e(it.name)}</h3>"]
        m = it.meta
        line = " · ".join(e(str(m[k])) for k in ("brand", "model", "variant", "years") if m.get(k))
        if line:
            parts.append(f"<p>{line}</p>")
        if m.get("status"):
            parts.append(f"<p><b>Status:</b> {e(str(m['status']))}</p>")
        # what this would set on the design
        if self.tube_pos:
            changes = self._preview_changes(it)
        else:
            changes = self._preview_changes(it)
        if changes:
            rows = "".join(f"<tr><td>{e(P.get(k).label if P.has(k) else k)}</td>"
                           f"<td>{e(str(self.doc.design.get(k)))}</td><td><b>{e(str(v))}</b></td></tr>"
                           for k, v in changes.items())
            parts.append("<h4>Would set</h4><table cellspacing='4'>"
                         "<tr><td></td><td>current</td><td>new</td></tr>" + rows + "</table>")
        specs = m.get("specs")
        if isinstance(specs, dict) and specs:
            rows = "".join(f"<tr><td>{e(str(k).replace('_', ' '))}</td><td><b>{e(str(v))}</b></td></tr>"
                           for k, v in specs.items())
            parts.append(f"<h4>Specifications</h4><table cellspacing='4'>{rows}</table>")
        srcs = m.get("sources")
        if isinstance(srcs, list) and srcs:
            rows = []
            for s in srcs:
                if not isinstance(s, dict):
                    continue
                url = str(s.get("url", ""))
                pub = e(str(s.get("publisher") or url))
                link = f"<a href='{e(url)}'>{pub}</a>" if url.startswith(("http://", "https://")) else pub
                rows.append(f"<li>{link}</li>")
            parts.append(f"<h4>Sources</h4><ul>{''.join(rows)}</ul>")
        self.info.setHtml("".join(parts))

    def _preview_changes(self, it: L.LibraryItem) -> dict:
        tmp = self.doc.design.copy()
        if self.tube_pos:
            L.apply_tube(tmp, it, self.tube_pos)
        else:
            L.apply(tmp, it)
        return {k: v for k, v in tmp.values.items() if self.doc.design.values.get(k) != v}

    def _bom_entry(self, it: L.LibraryItem) -> dict:
        m = it.meta
        src = ""
        srcs = m.get("sources")
        if isinstance(srcs, list) and srcs and isinstance(srcs[0], dict):
            src = str(srcs[0].get("url") or srcs[0].get("publisher") or "")
        return {k: v for k, v in {
            "id": it.id, "name": it.name, "category": it.category, "brand": m.get("brand"),
            "model": m.get("model"), "variant": m.get("variant"), "source": src,
            "weight_g": _weight_g(m.get("specs")),
            "price": m.get("price_usd") if isinstance(m.get("price_usd"), (int, float)) else None,
        }.items() if v is not None and v != ""}

    def use(self):
        it = self._selected()
        if it is None:
            return
        changes = self._preview_changes(it)
        what = f"{TUBE_LABELS.get(self.tube_pos, self.tube_pos)}: " if self.tube_pos else ""
        # record the assignment for the bill of materials, in the same undo step
        bom = dict(self.doc.design.extras.get("bom") or {})
        entry = self._bom_entry(it)
        if self.tube_pos:
            bom[self.tube_pos] = entry
        elif self.category == "tubing":
            for pos in L.item_tube_positions(it):      # a whole tube set
                bom[pos] = entry
        else:
            bom[self.category] = entry
        self.doc.undo.beginMacro(f"Use {what}{it.name}")
        if changes:
            self.doc.set_params(changes, f"Use {what}{it.name}")
        self.doc.set_extra("bom", bom, "Assign catalog part")
        self.doc.undo.endMacro()
        self.accept()


def choose(doc: Document, category: str, tube_pos: str | None = None, parent=None) -> None:
    CatalogPicker(doc, category, tube_pos, parent).exec()
