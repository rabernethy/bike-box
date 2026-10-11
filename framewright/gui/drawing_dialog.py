"""Drawing sheet export & printing with live preview."""
from __future__ import annotations

from pathlib import Path

from ..qt import QtCore, QtGui, QtPrintSupport, QtWidgets
from .document import Document

Qt = QtCore.Qt


class DrawingDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None, fmt: str = "pdf", ghosts=()):
        super().__init__(parent)
        from ..export import drawing as DR
        self.DR = DR
        self.doc = doc
        self.fmt = fmt
        self.ghosts = list(ghosts)
        self.setWindowTitle({"print": "Print drawing"}.get(fmt, f"Export drawing ({fmt.upper()})"))
        self.resize(1200, 760)
        lay = QtWidgets.QHBoxLayout(self)
        form_w = QtWidgets.QWidget()
        form_w.setMaximumWidth(330)
        form = QtWidgets.QFormLayout(form_w)
        self.page = QtWidgets.QComboBox()
        self.page.addItems([k for k in DR.PAGE_SIZES if k != "custom"])
        self.page.setCurrentText(str(doc.design.get("drawing_page", "A3")))
        self.landscape = QtWidgets.QCheckBox("Landscape")
        self.landscape.setChecked(True)
        self.scale = QtWidgets.QComboBox()
        self.scale.addItem("Auto (largest that fits)", None)
        for item in DR.STANDARD_SCALES:
            val, label = item if isinstance(item, tuple) else (item, DR.scale_label(item))
            self.scale.addItem(label, val)
        self.checks = {}
        for key, label, default in (("border", "Border", True), ("title_block", "Title block", True),
                                    ("geometry_table", "Geometry table", True), ("tube_table", "Tube table", False),
                                    ("custom_tables", "Custom tables", True), ("monochrome", "Monochrome", False)):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(default)
            cb.toggled.connect(self.refresh)
            self.checks[key] = cb
        self.dims = QtWidgets.QCheckBox("Dimensions")
        self.dims.setChecked(bool(doc.design["show_dimensions"]))
        self.dims.toggled.connect(self.refresh)
        self.dpi = QtWidgets.QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(200)
        form.addRow("Paper", self.page)
        form.addRow("", self.landscape)
        form.addRow("Scale", self.scale)
        for cb in self.checks.values():
            form.addRow("", cb)
        form.addRow("", self.dims)
        if fmt == "png":
            form.addRow("Resolution (dpi)", self.dpi)
        b = QtWidgets.QPushButton("Title block…")
        b.clicked.connect(self._title_block)
        form.addRow("", b)
        b = QtWidgets.QPushButton("Tables from CSV…")
        b.clicked.connect(self._csv_table)
        form.addRow("", b)
        go = QtWidgets.QPushButton({"print": "Print…"}.get(fmt, f"Export {fmt.upper()}…"))
        go.setDefault(True)
        go.clicked.connect(self.export)
        form.addRow(go)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.reject)
        form.addRow(close)
        self.scale_label = QtWidgets.QLabel()
        form.addRow("Using", self.scale_label)
        lay.addWidget(form_w)
        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(600, 420)
        self.preview.setStyleSheet("background: #6b6b6b;")
        lay.addWidget(self.preview, 1)
        for w in (self.page, self.scale):
            w.currentIndexChanged.connect(self.refresh)
        self.landscape.toggled.connect(self.refresh)
        QtCore.QTimer.singleShot(0, self.refresh)

    def options(self):
        o = self.DR.SheetOptions()
        o.page = self.page.currentText()
        o.landscape = self.landscape.isChecked()
        o.scale = self.scale.currentData()
        for k, cb in self.checks.items():
            setattr(o, k, cb.isChecked())
        o.dpi = self.dpi.value()
        o.dimensions = self.dims.isChecked()
        return o

    def _design(self):
        d = self.doc.design.copy()
        d.set("show_dimensions", self.dims.isChecked())
        return d

    def refresh(self, *_):
        try:
            sheet = self.DR.build_sheet(self._design(), None, self.options(), ghosts=self.ghosts)
        except Exception as exc:
            self.preview.setText(f"Preview failed: {exc}")
            return
        w_mm, h_mm = sheet.page_w, sheet.page_h
        avail = self.preview.size()
        k = min(avail.width() / w_mm, avail.height() / h_mm) * 0.96
        dpi = k * 25.4 * self.devicePixelRatioF()
        img = QtGui.QImage(int(w_mm * k * self.devicePixelRatioF()), int(h_mm * k * self.devicePixelRatioF()),
                           QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QtGui.QColor("white"))
        p = QtGui.QPainter(img)
        self.DR.render_sheet(p, sheet, dpi)
        p.end()
        img.setDevicePixelRatio(self.devicePixelRatioF())
        self.preview.setPixmap(QtGui.QPixmap.fromImage(img))
        sc = getattr(sheet, "scale", None)
        if sc:
            self.scale_label.setText(self.DR.scale_label(sc))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QtCore.QTimer.singleShot(0, self.refresh)

    def _title_block(self):
        from .dialogs import TitleBlockDialog
        TitleBlockDialog(self.doc, self).exec()
        self.refresh()

    def _csv_table(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Table from CSV", str(Path.home()), "CSV (*.csv)")
        if not fn:
            return
        try:
            from ..export.csv_export import read_csv_table
            rows = read_csv_table(fn)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "CSV", str(exc))
            return
        tables = list(self.doc.design.extras.get("tables") or [])
        tables.append({"title": Path(fn).stem, "rows": rows})
        self.doc.set_extra("tables", tables, "Add table")
        self.refresh()

    def export(self):
        d = self._design()
        o = self.options()
        if self.fmt == "print":
            printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.PrinterMode.HighResolution)
            dlg = QtPrintSupport.QPrintDialog(printer, self)
            if dlg.exec():
                self.DR.print_sheet(d, printer, o)
            return
        suffix = "." + self.fmt
        start = str(Path.home() / (d.title.replace("/", "-") + suffix))
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export drawing", start, f"{self.fmt.upper()} (*{suffix})")
        if not fn:
            return
        if not fn.lower().endswith(suffix):
            fn += suffix
        if self.fmt == "pdf":
            self.DR.save_pdf(d, fn, o, ghosts=self.ghosts)
        elif self.fmt == "svg":
            self.DR.save_sheet_svg(d, fn, o)
        else:
            self.DR.save_sheet_png(d, fn, o, dpi=self.dpi.value())
        self.accept()
