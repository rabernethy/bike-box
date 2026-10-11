"""Miter (tube coping) templates: preview, full-scale PDF, SVG, DXF, G-code,
cut list."""
from __future__ import annotations

from pathlib import Path

from ..qt import QtCore, QtGui, QtWidgets
from .document import Document
from .scene_view import SceneView

Qt = QtCore.Qt


class MitreDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        from ..export import mitre_output as MO
        from ..geometry import mitre as M
        self.M, self.MO = M, MO
        self.doc = doc
        self.setWindowTitle("Miter templates")
        self.resize(1100, 720)
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        left.addWidget(QtWidgets.QLabel("Cuts (select one or more):"))
        left.addWidget(self.list, 1)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left.addWidget(self.info)
        opts = QtWidgets.QFormLayout()
        self.page = QtWidgets.QComboBox()
        self.page.addItems(["A4", "Letter", "A3", "Tabloid"])
        self.landscape = QtWidgets.QCheckBox("Landscape")
        self.landscape.setChecked(True)
        opts.addRow("Paper", self.page)
        opts.addRow("", self.landscape)
        left.addLayout(opts)
        for text, fn in (("Export PDF (print at 100%)…", self.export_pdf), ("Export SVG…", self.export_svg),
                         ("Export DXF…", self.export_dxf), ("Export G-code…", self.export_gcode),
                         ("Cut list…", self.cut_list)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            left.addWidget(b)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        left.addWidget(close)
        w = QtWidgets.QWidget()
        w.setLayout(left)
        w.setMaximumWidth(360)
        lay.addWidget(w)
        self.view = SceneView(paper_px_per_mm=3.0)
        lay.addWidget(self.view, 1)
        g = doc.geometry
        try:
            self.cuts = M.compute_mitres(g)
        except Exception as exc:
            self.cuts = []
            QtWidgets.QMessageBox.warning(self, "Miters", f"Could not compute miters: {exc}")
        for c in self.cuts:
            self.list.addItem(c.label)
        self.list.currentRowChanged.connect(self._show)
        if self.cuts:
            self.list.setCurrentRow(0)
            self.list.selectAll()

    def _selected(self):
        rows = sorted({i.row() for i in self.list.selectedIndexes()})
        return [self.cuts[r] for r in rows] or list(self.cuts)

    def _show(self, row: int) -> None:
        if not (0 <= row < len(self.cuts)):
            return
        c = self.cuts[row]
        self.view.set_scene(self.MO.mitre_template_scene(c, self.doc.design.title, self.doc.design["units"]))
        self.info.setText(
            f"<b>{c.label}</b><br>OD {c.od:.1f} × {c.width:.1f} mm, wall {c.wall:.2f} mm<br>"
            f"Angle {c.angle:.2f}°, offset {c.offset:.1f} mm<br>"
            f"Hole saw Ø{c.holesaw_diameter:.1f} at {c.holesaw_angle:.2f}°, offset {c.holesaw_offset:.1f} mm<br>"
            f"Long point {c.long_point:.1f} mm, short point {c.short_point:.1f} mm, phase {c.phase:.1f}°")

    def _name(self, title, suffix, filt):
        base = self.doc.design.title.replace("/", "-") + "-miters" + suffix
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, str(Path.home() / base), filt)
        if fn and not fn.lower().endswith(suffix):
            fn += suffix
        return fn

    def export_pdf(self):
        fn = self._name("Miter templates PDF", ".pdf", "PDF (*.pdf)")
        if fn:
            self.MO.save_mitre_pdf(self._selected(), fn, page_size=self.page.currentText(),
                                   landscape=self.landscape.isChecked(), title=self.doc.design.title)
            QtWidgets.QMessageBox.information(self, "Miter templates",
                                              f"Wrote {fn}.\nPrint at 100% / 'actual size' and check the 50 mm "
                                              "calibration square before cutting.")

    def export_svg(self):
        fn = self._name("Miter templates SVG", ".svg", "SVG (*.svg)")
        if fn:
            self.MO.save_mitre_svg(self._selected(), fn)

    def export_dxf(self):
        fn = self._name("Miter templates DXF", ".dxf", "DXF (*.dxf)")
        if fn:
            self.MO.save_mitre_dxf(self._selected(), fn)

    def export_gcode(self):
        from ..export import gcode
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "G-code output folder", str(Path.home()))
        if d:
            files = gcode.save_gcode(self._selected(), d)
            QtWidgets.QMessageBox.information(self, "G-code", f"Wrote {len(files)} files to {d}.\n"
                                                              "Verify every program in a simulator before cutting.")

    def cut_list(self):
        rows = self.MO.cut_list_rows(self.doc.geometry, self.cuts)
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Cut list")
        dlg.resize(820, 360)
        v = QtWidgets.QVBoxLayout(dlg)
        t = QtWidgets.QTableWidget(max(len(rows) - 1, 0), len(rows[0]) if rows else 0)
        if rows:
            t.setHorizontalHeaderLabels([str(h) for h in rows[0]])
            for r, row in enumerate(rows[1:]):
                for c, val in enumerate(row):
                    t.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(t)
        b = QtWidgets.QPushButton("Copy")
        b.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(
            "\n".join("\t".join(str(x) for x in r) for r in rows)))
        v.addWidget(b)
        dlg.exec()
