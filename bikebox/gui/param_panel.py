"""Parameter editors generated from the schema."""
from __future__ import annotations

from ..model import params as P
from ..model.units import MM_PER_IN
from ..qt import QtCore, QtGui, QtWidgets, Signal
from .document import Document

Qt = QtCore.Qt

GROUP_ORDER = ["Frame", "Tubes", "Fork & headset", "Cockpit", "Saddle & seatpost", "Drivetrain",
               "Wheels & brakes", "Accessories", "Joints", "Paint", "Rider & fit", "Analysis", "Manufacturing",
               "Drawing", "Display", "Project"]


def ordered_groups() -> list[str]:
    gs = P.groups()
    return [g for g in GROUP_ORDER if g in gs] + [g for g in gs if g not in GROUP_ORDER]


# "Choose from catalog" buttons per (group, section): (button label, category, tube position|None)
SECTION_CATALOG: dict[tuple[str, str], list[tuple[str, str, str | None]]] = {
    ("Tubes", "Material"): [("Tube set from catalog…", "tubing", None)],
    ("Tubes", "Top tube"): [("Top tube from catalog…", "tubing", "tt")],
    ("Tubes", "Down tube"): [("Down tube from catalog…", "tubing", "dt")],
    ("Tubes", "Seat tube"): [("Seat tube from catalog…", "tubing", "st")],
    ("Tubes", "Head tube"): [("Head tube from catalog…", "tubing", "ht")],
    ("Tubes", "Chainstays"): [("Chainstay from catalog…", "tubing", "cs")],
    ("Tubes", "Seat stays"): [("Seat stay from catalog…", "tubing", "ss")],
    ("Fork & headset", "Fork"): [("Fork from catalog…", "forks", None)],
    ("Fork & headset", "Headset"): [("Headset from catalog…", "headsets", None)],
    ("Cockpit", "Stem"): [("Stem from catalog…", "stems", None)],
    ("Cockpit", "Handlebar"): [("Handlebar from catalog…", "handlebars", None)],
    ("Saddle & seatpost", "Saddle"): [("Saddle from catalog…", "saddles", None)],
    ("Saddle & seatpost", "Seatpost"): [("Seatpost from catalog…", "seatposts", None)],
    ("Drivetrain", "Drive"): [("Crankset…", "cranks", None), ("Cassette…", "cassettes", None),
                              ("Derailleur / groupset…", "drivetrain", None)],
    ("Wheels & brakes", "Rims"): [("Rim from catalog…", "rims", None), ("Hub from catalog…", "hubs", None)],
    ("Wheels & brakes", "Brakes"): [("Brakes from catalog…", "brakes", None)],
    ("Frame", "Wheels"): [("Tire from catalog…", "tires", None)],
    ("Frame", "Bottom bracket & rear"): [("BB shell from catalog…", "bb_shells", None)],
    ("Frame", "Dropouts"): [("Dropouts from catalog…", "dropouts", None)],
    ("Joints", "Lugs"): [("Lug / hardware from catalog…", "frame_hardware", None)],
}


class ColorButton(QtWidgets.QToolButton):
    color_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = "#000000"
        self.setFixedSize(56, 22)
        self.clicked.connect(self._pick)

    def set_color(self, c: str) -> None:
        self._color = c
        self.setStyleSheet(f"QToolButton {{ background: {c}; border: 1px solid #777; border-radius: 3px; }}")
        self.setToolTip(c)

    def _pick(self) -> None:
        settings = QtCore.QSettings("Bike Box", "Bike Box")
        palette = settings.value("paint/palette") or []
        for i, col in enumerate(list(palette)[:16]):
            QtWidgets.QColorDialog.setCustomColor(i, QtGui.QColor(str(col)))
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self, "Choose colour")
        settings.setValue("paint/palette", [QtWidgets.QColorDialog.customColor(i).name() for i in range(16)])
        if c.isValid():
            self.set_color(c.name())
            self.color_changed.emit(c.name())


class ParamPage(QtWidgets.QScrollArea):
    """All parameters of one group, in sections."""

    def __init__(self, doc: Document, group: str, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.group = group
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QtWidgets.QWidget()
        self.vbox = QtWidgets.QVBoxLayout(host)
        self.vbox.setContentsMargins(6, 6, 6, 6)
        self.vbox.setSpacing(8)
        self.editors: dict[str, QtWidgets.QWidget] = {}
        self.rows: dict[str, tuple[QtWidgets.QWidget, QtWidgets.QWidget, QtWidgets.QGroupBox]] = {}
        self.sections: dict[str, QtWidgets.QGroupBox] = {}
        self._units = doc.design["units"]
        self._build()
        self.vbox.addStretch(1)
        self.setWidget(host)

    def _build(self) -> None:
        for pd in P.by_group(self.group):
            box = self.sections.get(pd.section)
            if box is None:
                box = QtWidgets.QGroupBox(pd.section.replace("&", "&&"))
                form = QtWidgets.QFormLayout(box)
                form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                form.setHorizontalSpacing(8)
                form.setVerticalSpacing(3)
                self.sections[pd.section] = box
                self.vbox.addWidget(box)
                self._add_catalog_buttons(box.layout(), pd.section)
            ed = self._editor(pd)
            label = QtWidgets.QLabel(pd.label)
            label.setWordWrap(True)
            label.setToolTip((pd.help + "\n" if pd.help else "") + f"[{pd.key}]")
            ed.setToolTip(label.toolTip())
            box.layout().addRow(label, ed)
            self.editors[pd.key] = ed
            self.rows[pd.key] = (label, ed, box)
        self.refresh()

    def _add_catalog_buttons(self, form: QtWidgets.QFormLayout, section: str) -> None:
        specs = SECTION_CATALOG.get((self.group, section))
        if not specs:
            return
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 2)
        for label, category, pos in specs:
            b = QtWidgets.QPushButton(label)
            b.setToolTip(f"Pick a real, sourced part from the {category} catalog and apply it here")
            b.clicked.connect(lambda _c=False, cat=category, p=pos: self._open_catalog(cat, p))
            row.addWidget(b)
        row.addStretch(1)
        host = QtWidgets.QWidget()
        host.setLayout(row)
        form.addRow(host)

    def _open_catalog(self, category: str, pos: str | None) -> None:
        from .catalog_picker import CatalogPicker
        CatalogPicker(self.doc, category, pos, self).exec()

    def _editor(self, pd: P.ParamDef) -> QtWidgets.QWidget:
        key = pd.key
        if pd.kind in (P.FLOAT,):
            sb = QtWidgets.QDoubleSpinBox()
            sb.setKeyboardTracking(False)
            sb.setAccelerated(True)
            sb.setRange(-1e6, 1e6)
            sb.setMinimumWidth(90)
            sb.valueChanged.connect(lambda v, k=key, s=sb: self._commit_float(k, v))
            self._configure_spin(sb, pd)
            return sb
        if pd.kind == P.INT:
            sb = QtWidgets.QSpinBox()
            sb.setKeyboardTracking(False)
            sb.setRange(int(pd.min if pd.min is not None else -10 ** 6), int(pd.max if pd.max is not None else 10 ** 6))
            sb.valueChanged.connect(lambda v, k=key: self.doc.set_param(k, v))
            return sb
        if pd.kind == P.BOOL:
            cb = QtWidgets.QCheckBox()
            cb.toggled.connect(lambda v, k=key: self.doc.set_param(k, v))
            return cb
        if pd.kind == P.CHOICE:
            combo = QtWidgets.QComboBox()
            for val, lab in pd.choices:
                combo.addItem(lab, val)
            combo.currentIndexChanged.connect(lambda i, k=key, c=combo: self.doc.set_param(k, c.itemData(i)))
            return combo
        if pd.kind == P.COLOR:
            btn = ColorButton()
            btn.color_changed.connect(lambda c, k=key: self.doc.set_param(k, c))
            return btn
        le = QtWidgets.QLineEdit()
        le.editingFinished.connect(lambda k=key, e=le: self.doc.set_param(k, e.text()))
        return le

    def _configure_spin(self, sb: QtWidgets.QDoubleSpinBox, pd: P.ParamDef) -> None:
        sb.blockSignals(True)
        if pd.unit == "mm":
            k = 1.0 / MM_PER_IN if self._units == "in" else 1.0
            sb.setDecimals(3 if self._units == "in" else (2 if (pd.step or 1) < 0.5 else 1))
            sb.setSingleStep((pd.step or 1.0) * k if self._units != "in" else max((pd.step or 1) / 25.4, 0.01))
            lo = pd.min * k if pd.min is not None else -1e6
            hi = pd.max * k if pd.max is not None else 1e6
            sb.setRange(lo, hi)
            sb.setSuffix(" in" if self._units == "in" else " mm")
        else:
            sb.setDecimals(2 if pd.unit in ("deg", "mm") else (2 if (pd.step or 1) < 1 else 1))
            sb.setSingleStep(pd.step or 1.0)
            sb.setRange(pd.min if pd.min is not None else -1e6, pd.max if pd.max is not None else 1e6)
            sb.setSuffix({"deg": "°", "%": " %", "g": " g", "rpm": " rpm", "kg": " kg", "N": " N",
                          "MPa": " MPa"}.get(pd.unit, (" " + pd.unit) if pd.unit else ""))
        sb.blockSignals(False)

    def _commit_float(self, key: str, value: float) -> None:
        pd = P.get(key)
        if pd.unit == "mm" and self._units == "in":
            value *= MM_PER_IN
        cur = self.doc.design.f(key)
        if abs(cur - value) < (1e-3 if self._units == "in" else 1e-6):
            return
        self.doc.set_param(key, value, f"Set {pd.label}")

    def refresh(self) -> None:
        d = self.doc.design
        units = d["units"]
        if units != self._units:
            self._units = units
            for key, ed in self.editors.items():
                if isinstance(ed, QtWidgets.QDoubleSpinBox):
                    self._configure_spin(ed, P.get(key))
        for key, ed in self.editors.items():
            pd = P.get(key)
            v = d.get(key)
            ed.blockSignals(True)
            try:
                if isinstance(ed, QtWidgets.QDoubleSpinBox):
                    val = float(v)
                    if pd.unit == "mm" and units == "in":
                        val /= MM_PER_IN
                    if abs(ed.value() - val) > 1e-9:
                        ed.setValue(val)
                elif isinstance(ed, QtWidgets.QSpinBox):
                    ed.setValue(int(v))
                elif isinstance(ed, QtWidgets.QCheckBox):
                    ed.setChecked(bool(v))
                elif isinstance(ed, QtWidgets.QComboBox):
                    i = ed.findData(v)
                    if i >= 0:
                        ed.setCurrentIndex(i)
                elif isinstance(ed, ColorButton):
                    ed.set_color(str(v))
                elif isinstance(ed, QtWidgets.QLineEdit):
                    if not ed.hasFocus():
                        ed.setText(str(v))
            finally:
                ed.blockSignals(False)
        self.apply_visibility()

    def apply_visibility(self, filter_text: str = "") -> None:
        d = self.doc.design
        ft = filter_text.strip().lower()
        visible_sections: dict[str, bool] = {s: False for s in self.sections}
        for key, (label, ed, box) in self.rows.items():
            pd = P.get(key)
            vis = True
            if pd.visible_if:
                k, allowed = pd.visible_if
                vis = d.get(k) in allowed
            if ft and ft not in pd.label.lower() and ft not in key and ft not in pd.section.lower():
                vis = False
            label.setVisible(vis)
            ed.setVisible(vis)
            if vis:
                visible_sections[pd.section] = True
        for s, box in self.sections.items():
            box.setVisible(visible_sections[s])


class ParamPanel(QtWidgets.QWidget):
    """Group list + lazily built parameter pages, with a search box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Document | None = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search parameters…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumWidth(150)
        self.list.setMinimumWidth(110)
        self.stack = QtWidgets.QStackedWidget()
        split.addWidget(self.list)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([120, 400])
        split.setChildrenCollapsible(False)
        lay.addWidget(split, 1)
        self.list.currentRowChanged.connect(self._show)
        self.pages: dict[str, ParamPage] = {}
        self.groups: list[str] = []

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            try:
                self.doc.changed.disconnect(self._on_changed)
            except (TypeError, RuntimeError):
                pass
        self.doc = doc
        for page in self.pages.values():
            self.stack.removeWidget(page)
            page.deleteLater()
        self.pages = {}
        current = self.list.currentItem().text() if self.list.currentItem() else None
        self.list.blockSignals(True)
        self.list.clear()
        self.groups = ordered_groups()
        for g in self.groups:
            self.list.addItem(g)
        self.list.blockSignals(False)
        if doc is None:
            return
        doc.changed.connect(self._on_changed)
        row = self.groups.index(current) if current in self.groups else 0
        self.list.setCurrentRow(row)
        self._show(row)

    def show_group(self, group: str) -> None:
        if group in self.groups:
            self.list.setCurrentRow(self.groups.index(group))

    def _page(self, group: str) -> ParamPage:
        page = self.pages.get(group)
        if page is None:
            page = ParamPage(self.doc, group)
            self.pages[group] = page
            self.stack.addWidget(page)
            if self.search.text():
                page.apply_visibility(self.search.text())
        return page

    def _show(self, row: int) -> None:
        if self.doc is None or row < 0 or row >= len(self.groups):
            return
        page = self._page(self.groups[row])
        if getattr(page, "_stale", False):
            page._stale = False
            page.refresh()
            page.apply_visibility(self.search.text())
        self.stack.setCurrentWidget(page)

    def _on_changed(self, keys) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, ParamPage):
            page.refresh()
            if self.search.text():
                page.apply_visibility(self.search.text())
        for p in self.pages.values():
            if p is not page:
                p._stale = True

    def _filter(self, text: str) -> None:
        if self.doc is None:
            return
        ft = text.strip().lower()
        # show only groups with matches
        first = None
        for i, g in enumerate(self.groups):
            match = not ft or any(ft in pd.label.lower() or ft in pd.key or ft in pd.section.lower()
                                  for pd in P.by_group(g))
            self.list.item(i).setHidden(not match)
            if match and first is None:
                first = i
        cur = self.list.currentRow()
        if cur < 0 or self.list.item(cur).isHidden():
            if first is not None:
                self.list.setCurrentRow(first)
        page = self.stack.currentWidget()
        if isinstance(page, ParamPage):
            page.apply_visibility(text)
