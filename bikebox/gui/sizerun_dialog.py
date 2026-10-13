"""Size-run dialog: generate a family of sizes from the current design,
preview the geometry chart, overlay them, or export the chart as CSV."""
from __future__ import annotations

from ..geometry.solver import solve
from ..model import sizerun as SR
from ..model.units import fmt_angle, fmt_len
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document
from .dialogs import GHOST_COLORS

Qt = QtCore.Qt

# the drivers the user edits per size (key, column label)
DRIVERS = [("seat_tube_length", "Seat tube"), ("stack", "Stack"), ("reach", "Reach")]
# the geometry chart shown for each generated size (label, geometry key, angle?)
CHART = [("Stack", "stack", False), ("Reach", "reach", False), ("Seat tube", "seat_tube_cc", False),
         ("Head tube", "head_tube_length", False), ("Head angle", "head_tube_angle", True),
         ("Seat angle", "seat_tube_angle", True), ("Eff. top tube", "top_tube_effective", False),
         ("Wheelbase", "wheelbase", False), ("Front centre", "front_center", False),
         ("Trail", "trail", False), ("Standover", "standover", False)]


class SizeRunDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Size run")
        self.resize(820, 620)
        self._sizes: list[tuple[str, object]] = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Generate a range of sizes from the current design. Edit the driving "
                                       "dimensions per size; everything else is shared."))

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Sizes:"))
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(1, 12)
        self.count.setValue(5)
        self.count.valueChanged.connect(self._reset_rows)
        top.addWidget(self.count)
        reset = QtWidgets.QPushButton("Reset to suggested spread")
        reset.clicked.connect(self._reset_rows)
        top.addWidget(reset)
        top.addStretch(1)
        lay.addLayout(top)

        # editable drivers table (rows = sizes)
        self.drv = QtWidgets.QTableWidget(0, 1 + len(DRIVERS))
        self.drv.setHorizontalHeaderLabels(["Name"] + [lbl for _k, lbl in DRIVERS])
        self.drv.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.drv.verticalHeader().setVisible(False)
        self.drv.itemChanged.connect(lambda _i: self._regenerate())
        lay.addWidget(self.drv)

        lay.addWidget(QtWidgets.QLabel("Resulting geometry:"))
        self.chart = QtWidgets.QTableWidget(len(CHART), 1)
        self.chart.verticalHeader().setVisible(False)
        self.chart.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.chart.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.chart, 1)

        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Overlay all as ghosts")
        b.clicked.connect(self.overlay)
        row.addWidget(b)
        b = QtWidgets.QPushButton("Export size chart CSV…")
        b.clicked.connect(self.export_csv)
        row.addWidget(b)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        self._reset_rows()

    # -- rows -------------------------------------------------------------------
    def _reset_rows(self, *_):
        specs = SR.linear_run(self.doc.design, self.count.value(), SR.suggest_ranges(self.doc.design))
        self.drv.blockSignals(True)
        self.drv.setRowCount(len(specs))
        for r, spec in enumerate(specs):
            self.drv.setItem(r, 0, QtWidgets.QTableWidgetItem(spec.name))
            for c, (key, _lbl) in enumerate(DRIVERS, start=1):
                self.drv.setItem(r, c, QtWidgets.QTableWidgetItem(f"{spec.overrides.get(key, ''):g}"
                                                                  if spec.overrides.get(key) is not None else ""))
        self.drv.blockSignals(False)
        self._regenerate()

    def _specs(self) -> list[SR.SizeSpec]:
        specs = []
        for r in range(self.drv.rowCount()):
            name_it = self.drv.item(r, 0)
            name = name_it.text() if name_it else f"Size {r + 1}"
            ov = {}
            for c, (key, _lbl) in enumerate(DRIVERS, start=1):
                it = self.drv.item(r, c)
                if it and it.text().strip():
                    try:
                        ov[key] = float(it.text())
                    except ValueError:
                        pass
            specs.append(SR.SizeSpec(name, ov))
        return specs

    def _regenerate(self):
        self._sizes = SR.generate(self.doc.design, self._specs())
        units = self.doc.design["units"]
        self.chart.setColumnCount(len(self._sizes))
        self.chart.setHorizontalHeaderLabels([n for n, _d in self._sizes])
        self.chart.setVerticalHeaderLabels([lbl for lbl, _k, _a in CHART])
        self.chart.verticalHeader().setVisible(True)
        for c, (_name, d) in enumerate(self._sizes):
            try:
                g = solve(d)
            except Exception:
                continue
            for r, (_lbl, key, is_ang) in enumerate(CHART):
                v = g.v.get(key)
                txt = "" if v is None else (fmt_angle(v) if is_ang else fmt_len(v, units, suffix=True))
                self.chart.setItem(r, c, QtWidgets.QTableWidgetItem(txt))

    # -- actions ----------------------------------------------------------------
    def overlay(self):
        self.doc.ghosts = [{"label": n, "design": d, "color": GHOST_COLORS[i % len(GHOST_COLORS)]}
                           for i, (n, d) in enumerate(self._sizes)]
        parent = self.parent()
        if parent is not None and hasattr(parent, "view") and parent.view() is not None:
            parent.view().update_ghosts()
        self.accept()

    def export_csv(self):
        from ..export import csv_export
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export size chart",
                                                      str(self.doc.design.title.replace("/", "-") + "-sizes.csv"),
                                                      "CSV (*.csv)")
        if fn:
            if not fn.lower().endswith(".csv"):
                fn += ".csv"
            csv_export.export_csv(self._sizes, fn)
            QtWidgets.QMessageBox.information(self, "Size run", f"Wrote {len(self._sizes)} sizes to {fn}")
