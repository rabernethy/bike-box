"""Customer / order: edit the customer and pricing on a design, see the quote
total, save the order, and export a quote PDF."""
from __future__ import annotations

from ..analysis import bom as BOM
from ..model import orders as O
from ..qt import QtCore, QtWidgets
from .document import Document

Qt = QtCore.Qt
_SYM = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "$", "AUD": "$"}


class OrdersDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Customer & order")
        self.resize(640, 640)
        self.o = O.get_order(doc.design)
        lay = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        c = self.o["customer"]
        self.name = QtWidgets.QLineEdit(c.get("name", ""))
        self.email = QtWidgets.QLineEdit(c.get("email", ""))
        self.phone = QtWidgets.QLineEdit(c.get("phone", ""))
        self.address = QtWidgets.QLineEdit(c.get("address", ""))
        self.notes = QtWidgets.QLineEdit(c.get("notes", ""))
        self.order_no = QtWidgets.QLineEdit(self.o.get("order_no", ""))
        self.status = QtWidgets.QComboBox()
        self.status.addItems(O.STATUSES)
        self.status.setCurrentText(self.o.get("status", "quote"))
        self.due = QtWidgets.QLineEdit(self.o.get("due", ""))
        self.due.setPlaceholderText("YYYY-MM-DD")
        self.currency = QtWidgets.QComboBox()
        self.currency.addItems(list(_SYM))
        self.currency.setCurrentText(self.o.get("currency", "USD"))
        for lbl, w in (("Customer", self.name), ("Email", self.email), ("Phone", self.phone),
                       ("Address", self.address), ("Notes", self.notes), ("Order #", self.order_no),
                       ("Status", self.status), ("Due", self.due), ("Currency", self.currency)):
            form.addRow(lbl, w)
        lay.addLayout(form)

        # per-part prices
        lay.addWidget(QtWidgets.QLabel("Part prices (your pricing — catalog has none):"))
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Component", "Part", "Price"])
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self._fill_parts()
        self.table.itemChanged.connect(lambda _i: self._update_total())

        pr = QtWidgets.QHBoxLayout()
        self.labor_hours = QtWidgets.QDoubleSpinBox(); self.labor_hours.setRange(0, 999); self.labor_hours.setValue(float(self.o.get("labor_hours", 0) or 0)); self.labor_hours.setSuffix(" h")
        self.labor_rate = QtWidgets.QDoubleSpinBox(); self.labor_rate.setRange(0, 9999); self.labor_rate.setValue(float(self.o.get("labor_rate", 0) or 0)); self.labor_rate.setPrefix("rate ")
        self.frame_price = QtWidgets.QDoubleSpinBox(); self.frame_price.setRange(0, 99999); self.frame_price.setValue(float(self.o.get("frame_price", 0) or 0)); self.frame_price.setPrefix("frame ")
        for w in (self.labor_hours, self.labor_rate, self.frame_price):
            w.valueChanged.connect(self._update_total)
            pr.addWidget(w)
        lay.addLayout(pr)
        self.total_label = QtWidgets.QLabel()
        self.total_label.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.total_label)

        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Save order")
        b.clicked.connect(self.save)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Export quote (PDF)…")
        b.clicked.connect(self.export_quote)
        row.addWidget(b)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)
        self._update_total()

    def _fill_parts(self):
        rows = [r for r in BOM.build(self.doc.design, self.doc.geometry) if r.component != "Frame"]
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        prices = self.o.get("prices", {})
        for i, r in enumerate(rows):
            comp = QtWidgets.QTableWidgetItem(r.component)
            comp.setFlags(Qt.ItemFlag.ItemIsEnabled)
            part = QtWidgets.QTableWidgetItem(r.part or r.spec or "—")
            part.setFlags(Qt.ItemFlag.ItemIsEnabled)
            price = QtWidgets.QTableWidgetItem(f"{float(prices.get(r.component, 0) or 0):g}")
            self.table.setItem(i, 0, comp)
            self.table.setItem(i, 1, part)
            self.table.setItem(i, 2, price)
        self.table.blockSignals(False)

    def _collect(self) -> dict:
        prices = {}
        for i in range(self.table.rowCount()):
            comp = self.table.item(i, 0).text()
            try:
                prices[comp] = float(self.table.item(i, 2).text())
            except (TypeError, ValueError):
                pass
        return {
            "customer": {"name": self.name.text(), "email": self.email.text(), "phone": self.phone.text(),
                         "address": self.address.text(), "notes": self.notes.text()},
            "order_no": self.order_no.text(), "status": self.status.currentText(), "due": self.due.text(),
            "currency": self.currency.currentText(), "labor_hours": self.labor_hours.value(),
            "labor_rate": self.labor_rate.value(), "frame_price": self.frame_price.value(), "prices": prices,
        }

    def _update_total(self):
        tmp = self.doc.design.copy()
        O.set_order(tmp, self._collect())
        q = O.quote(tmp, self.doc.geometry)
        sym = _SYM.get(q["currency"], "")
        self.total_label.setText(
            f"Parts {sym}{q['parts_total']:,.2f}  +  labour {sym}{q['labor']:,.2f}  +  frame "
            f"{sym}{q['frame_price']:,.2f}   =   Total {sym}{q['total']:,.2f}")

    def save(self):
        order = self._collect()
        self.doc.set_extra("order", order, "Edit order")
        O.log_order(self.doc.design, self.doc.geometry)
        QtWidgets.QMessageBox.information(self, "Order", "Order saved to the design and the order log.")

    def export_quote(self):
        from ..export import quote
        self.doc.set_extra("order", self._collect(), "Edit order")
        title = (self.doc.design.get("title") or "quote").replace("/", "-")
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export quote", f"{title}-quote.pdf", "PDF (*.pdf)")
        if fn:
            if not fn.lower().endswith(".pdf"):
                fn += ".pdf"
            quote.save_pdf(self.doc.design, fn, self.doc.geometry)
            QtWidgets.QMessageBox.information(self, "Quote", f"Wrote {fn}")
