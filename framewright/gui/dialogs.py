"""General dialogs: dimensions, photo underlay, comparison, snapshots, title
block, extra tubes, preferences."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from ..geometry import dimensions as DIM
from ..geometry.solver import solve
from ..geometry.vec import cosd, sind
from ..model.design import Design
from ..model.units import MM_PER_IN
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt
GHOST_COLORS = ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00", "#7f7f7f"]


def _buttons(dlg, ok=True, cancel=True):
    flags = QtWidgets.QDialogButtonBox.StandardButton(0)
    if ok:
        flags |= QtWidgets.QDialogButtonBox.StandardButton.Ok
    if cancel:
        flags |= QtWidgets.QDialogButtonBox.StandardButton.Cancel
    bb = QtWidgets.QDialogButtonBox(flags)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


# --------------------------------------------------------------------------
# dimension value editing (double-click a dimension)
# --------------------------------------------------------------------------
DRIVING = {
    "stack": lambda v, g: {"front_v_mode": "stack", "stack": v},
    "reach": lambda v, g: {"front_h_mode": "reach", "reach": v},
    "ett": lambda v, g: {"front_h_mode": "ett", "top_tube_effective": v},
    "ht_length": lambda v, g: {"front_v_mode": "ht_length", "head_tube_length": v},
    "hta": lambda v, g: {"head_tube_angle": v},
    "sta": lambda v, g: {"seat_tube_angle": v},
    "st_ct": lambda v, g: {"st_length_mode": "ct", "seat_tube_length": v},
    "st_cc": lambda v, g: {"st_length_mode": "cc", "seat_tube_length": v},
    "st_ext": lambda v, g: ({"st_extension": v} if g.design["st_length_mode"] == "cc"
                            else {"tt_mode": "st_extension", "st_extension": v}),
    "chainstay": lambda v, g: {"cs_mode": "length", "chainstay_length": v},
    "front_center": lambda v, g: {"front_h_mode": "front_center", "front_center": v},
    "wheelbase": lambda v, g: {"front_h_mode": "wheelbase", "wheelbase": v},
    "bb_drop": lambda v, g: {"bb_mode": "drop", "bb_drop": v},
    "bb_height": lambda v, g: {"bb_mode": "height", "bb_height": v},
    "fork_offset": lambda v, g: {"fork_offset": v},
    "fork_ac": lambda v, g: {"fork_length": v},
    "trail": lambda v, g: {"fork_offset": g.wheels["front"].outer_r * cosd(g.v["head_tube_angle"])
                           - v * sind(g.v["head_tube_angle"])},
    "saddle_height": lambda v, g: {"saddle_mode": "height_angle", "saddle_height": v},
    "seat_angle_eff": lambda v, g: {"saddle_mode": "height_angle", "seat_angle_source": "custom",
                                    "seat_angle_eff": v},
    "stem": lambda v, g: {"stem_length": v},
    "crank": lambda v, g: {"crank_length": v},
    "bar_x": lambda v, g: {"front_h_mode": "bar_x", "bar_x": v},
    "bar_y": lambda v, g: {"front_v_mode": "bar_y", "bar_y": v},
}


def edit_dimension_value(doc: Document, dim_id: str, parent=None) -> None:
    dd = DIM.BY_ID.get(dim_id)
    if dd is None:
        return
    g = doc.geometry
    value = DIM.measure(g, dim_id)
    units = doc.design["units"]
    if dim_id not in DRIVING:
        QtWidgets.QMessageBox.information(parent, dd.label,
                                          f"{dd.label} = {DIM.format_value(value, dd.kind, units)}\n\n"
                                          "This dimension is driven by other inputs and can't be edited directly.")
        return
    is_len = dd.kind == "linear"
    shown = value / MM_PER_IN if (is_len and units == "in") else value
    suffix = "°" if not is_len else (" in" if units == "in" else " mm")
    v, ok = QtWidgets.QInputDialog.getDouble(parent, f"Edit {dd.label}", f"{dd.label} ({suffix.strip()}):",
                                             shown, -100000, 100000, 3 if units == "in" else 2)
    if not ok:
        return
    if is_len and units == "in":
        v *= MM_PER_IN
    doc.set_params(DRIVING[dim_id](v, g), f"Set {dd.label}")


# --------------------------------------------------------------------------
class DimensionsDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Dimensions")
        self.resize(560, 620)
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs, 1)
        # catalogue
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Dimension", "Value"])
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        for text, fn in (("All", self._all), ("None", self._none), ("Defaults", self._defaults)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        st = QtWidgets.QGroupBox("Dimension states")
        sl = QtWidgets.QHBoxLayout(st)
        self.states = QtWidgets.QComboBox()
        self.states.setEditable(False)
        sl.addWidget(self.states, 1)
        for text, fn in (("Apply", self._apply_state), ("Save as…", self._save_state), ("Delete", self._del_state)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            sl.addWidget(b)
        v.addWidget(st)
        tabs.addTab(w, "Catalogue")
        # user dimensions
        w2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(w2)
        self.utable = QtWidgets.QTableWidget(0, 5)
        self.utable.setHorizontalHeaderLabels(["Id", "Type", "Points", "Label", "Offset"])
        self.utable.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        v2.addWidget(self.utable, 1)
        r2 = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Delete selected")
        b.clicked.connect(self._del_udim)
        r2.addWidget(b)
        r2.addStretch(1)
        hint = QtWidgets.QLabel("Add user dimensions from the toolbar (point-to-point / angle).")
        hint.setStyleSheet("color: gray")
        r2.addWidget(hint)
        v2.addLayout(r2)
        tabs.addTab(w2, "User dimensions")
        lay.addWidget(_buttons(self))
        self._fill()

    def _fill(self):
        g = self.doc.geometry
        units = self.doc.design["units"]
        visible = set(DIM.visible_ids(g))
        self.tree.clear()
        cats: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for dd in DIM.CATALOG:
            top = cats.get(dd.category)
            if top is None:
                top = QtWidgets.QTreeWidgetItem([dd.category, ""])
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
                cats[dd.category] = top
            try:
                val = DIM.format_value(DIM.measure(g, dd.id), dd.kind, units)
            except Exception:
                val = "–"
            it = QtWidgets.QTreeWidgetItem([dd.label, val])
            it.setData(0, Qt.ItemDataRole.UserRole, dd.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if dd.id in visible else Qt.CheckState.Unchecked)
            top.addChild(it)
        self.states.clear()
        self.states.addItems(sorted((self.doc.design.extras.get("dimension_states") or {}).keys()))
        uds = self.doc.design.extras.get("user_dimensions") or []
        self.utable.setRowCount(len(uds))
        for r, u in enumerate(uds):
            pts = ", ".join(p if isinstance(p, str) else f"({p.get('x')}, {p.get('y')})" for p in u.get("points", []))
            for c, val in enumerate([u.get("id"), u.get("kind"), pts, u.get("label", ""), u.get("offset", 30)]):
                item = QtWidgets.QTableWidgetItem(str(val))
                if c not in (3, 4):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.utable.setItem(r, c, item)

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _checked(self) -> list[str]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self._items()
                if it.checkState(0) == Qt.CheckState.Checked]

    def _set(self, ids):
        ids = set(ids)
        for it in self._items():
            it.setCheckState(0, Qt.CheckState.Checked if it.data(0, Qt.ItemDataRole.UserRole) in ids
                             else Qt.CheckState.Unchecked)

    def _all(self):
        self._set(d.id for d in DIM.CATALOG)

    def _none(self):
        self._set([])

    def _defaults(self):
        self._set(DIM.DEFAULT_VISIBLE)

    def _apply_state(self):
        name = self.states.currentText()
        st = (self.doc.design.extras.get("dimension_states") or {}).get(name)
        if st is not None:
            self._set(st)

    def _save_state(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save dimension state", "Name:")
        if ok and name.strip():
            states = dict(self.doc.design.extras.get("dimension_states") or {})
            states[name.strip()] = self._checked()
            self.doc.set_extra("dimension_states", states, "Save dimension state")
            self._fill()

    def _del_state(self):
        name = self.states.currentText()
        states = dict(self.doc.design.extras.get("dimension_states") or {})
        if name in states:
            del states[name]
            self.doc.set_extra("dimension_states", states, "Delete dimension state")
            self._fill()

    def _del_udim(self):
        rows = sorted({i.row() for i in self.utable.selectedIndexes()}, reverse=True)
        uds = list(self.doc.design.extras.get("user_dimensions") or [])
        for r in rows:
            if r < len(uds):
                del uds[r]
        self.doc.set_extra("user_dimensions", uds, "Delete user dimensions")
        self._fill()

    def accept(self):
        self.doc.set_extra("visible_dimensions", self._checked(), "Choose dimensions")
        uds = [dict(u) for u in self.doc.design.extras.get("user_dimensions") or []]
        changed = False
        for r, u in enumerate(uds):
            if r >= self.utable.rowCount():
                break
            label = self.utable.item(r, 3).text()
            try:
                off = float(self.utable.item(r, 4).text())
            except ValueError:
                off = u.get("offset", 30)
            if label != u.get("label", "") or off != u.get("offset"):
                u["label"], u["offset"] = label, off
                changed = True
        if changed:
            self.doc.set_extra("user_dimensions", uds, "Edit user dimensions")
        super().accept()


# --------------------------------------------------------------------------
class PhotoDialog(QtWidgets.QDialog):
    """Import a photo as a reference underlay and position/scale it."""

    def __init__(self, doc: Document, canvas=None, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.canvas = canvas
        self.setWindowTitle("Photo underlay")
        ph = dict(doc.design.extras.get("photo") or {})
        form = QtWidgets.QFormLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(str(ph.get("path", "")))
        b = QtWidgets.QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(b)
        form.addRow("Image", row)

        def spin(val, lo, hi, dec=1, step=1.0, suffix=""):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setSuffix(suffix)
            s.setValue(val)
            return s
        self.x = spin(float(ph.get("x", -950)), -10000, 10000, 1, 5, " mm")
        self.y = spin(float(ph.get("y", 1100)), -10000, 10000, 1, 5, " mm")
        self.scale = spin(float(ph.get("mm_per_px", 1.0)), 0.0001, 1000, 5, 0.01, " mm/px")
        self.rot = spin(float(ph.get("rotation", 0.0)), -180, 180, 2, 0.25, "°")
        self.opacity = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(int(float(ph.get("opacity", 0.5)) * 100))
        self.flip = QtWidgets.QCheckBox("Mirror horizontally")
        self.flip.setChecked(bool(ph.get("flip", False)))
        form.addRow("Top-left X", self.x)
        form.addRow("Top-left Y", self.y)
        form.addRow("Scale", self.scale)
        form.addRow("Rotation", self.rot)
        form.addRow("Opacity", self.opacity)
        form.addRow("", self.flip)
        hint = QtWidgets.QLabel("Tip: after applying, use Tools ▸ Calibrate photo and click two points a known "
                                "distance apart (e.g. the axles) to set the scale.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        form.addRow(hint)
        bb = _buttons(self)
        rm = bb.addButton("Remove photo", QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole)
        rm.clicked.connect(self._remove)
        form.addRow(bb)

    def _browse(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose photo", str(Path.home()),
                                                      "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if fn:
            self.path.setText(fn)
            img = QtGui.QImage(fn)
            if not img.isNull() and self.scale.value() == 1.0:
                # guess: fit 1800 mm across the image width
                self.scale.setValue(1800.0 / max(img.width(), 1))

    def _remove(self):
        self.doc.set_extra("photo", None, "Remove photo")
        self.reject()

    def accept(self):
        if self.path.text().strip():
            self.doc.set_extra("photo", {"path": self.path.text().strip(), "x": self.x.value(), "y": self.y.value(),
                                         "mm_per_px": self.scale.value(), "rotation": self.rot.value(),
                                         "opacity": self.opacity.value() / 100.0, "flip": self.flip.isChecked()},
                               "Photo underlay")
        super().accept()


# --------------------------------------------------------------------------
class CompareDialog(QtWidgets.QDialog):
    """Choose designs to overlay as coloured 'ghosts'."""

    def __init__(self, doc: Document, other_docs: list[Document], parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Compare designs")
        self.resize(520, 420)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Overlay these designs (aligned at the BB):"))
        self.list = QtWidgets.QListWidget()
        lay.addWidget(self.list, 1)
        self.sources: list[tuple[str, Design]] = []
        for od in other_docs:
            if od is not doc:
                self.sources.append((f"Open: {od.display_name}", od.design))
        for snap in doc.design.extras.get("snapshots") or []:
            d = doc.design.snapshot_design(snap["name"])
            if d is not None:
                self.sources.append((f"Snapshot: {snap['name']} ({snap.get('time', '')})", d))
        for gh in doc.ghosts:
            if not any(gh["design"] is s[1] for s in self.sources):
                self.sources.append((gh["label"], gh["design"]))
        active = {id(gh["design"]) for gh in doc.ghosts}
        for label, d in self.sources:
            it = QtWidgets.QListWidgetItem(label)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if id(d) in active else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        b = QtWidgets.QPushButton("Add design file…")
        b.clicked.connect(self._add_file)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_buttons(self))

    def _add_file(self):
        fns, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add designs", str(Path.home()),
                                                        "FrameWright designs (*.fwd)")
        for fn in fns:
            try:
                d = Design.load(fn)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Open failed", f"{fn}\n{exc}")
                continue
            self.sources.append((f"File: {Path(fn).name}", d))
            it = QtWidgets.QListWidgetItem(f"File: {Path(fn).name}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)

    def accept(self):
        ghosts = []
        for i in range(self.list.count()):
            if self.list.item(i).checkState() == Qt.CheckState.Checked:
                label, d = self.sources[i]
                ghosts.append({"label": label, "design": d, "color": GHOST_COLORS[len(ghosts) % len(GHOST_COLORS)]})
        self.doc.ghosts = ghosts
        super().accept()


# --------------------------------------------------------------------------
class SnapshotsDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Snapshots")
        self.resize(560, 380)
        lay = QtWidgets.QHBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        lay.addWidget(self.list, 1)
        col = QtWidgets.QVBoxLayout()
        for text, fn in (("Take snapshot…", self._take), ("Show differences", self._diff),
                         ("Overlay as ghost", self._ghost), ("Restore", self._restore), ("Delete", self._delete)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        col.addWidget(close)
        lay.addLayout(col)
        self._fill()

    def _fill(self):
        self.list.clear()
        for s in self.doc.design.extras.get("snapshots") or []:
            self.list.addItem(f"{s['name']}   —   {s.get('time', '')}")

    def _cur(self):
        i = self.list.currentRow()
        snaps = self.doc.design.extras.get("snapshots") or []
        return snaps[i] if 0 <= i < len(snaps) else None

    def _take(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Snapshot", "Name:",
                                                  text=f"Snapshot {len(self.doc.design.extras.get('snapshots') or []) + 1}")
        if ok:
            d = self.doc.design.copy()
            d.snapshot(name or "Snapshot")
            self.doc.set_extra("snapshots", d.extras["snapshots"], "Take snapshot")
            self._fill()

    def _diff(self):
        s = self._cur()
        if not s:
            return
        from ..model import params as P
        rows = []
        for k, old in s["values"].items():
            new = self.doc.design.get(k)
            if new != old and P.has(k):
                rows.append(f"{P.get(k).label}: {old}  →  {new}")
        g0 = solve(self.doc.design.snapshot_design(s["name"]))
        g1 = self.doc.geometry
        for k in ("stack", "reach", "wheelbase", "front_center", "trail", "standover", "top_tube_effective"):
            if abs(g0.v[k] - g1.v[k]) > 0.05:
                rows.append(f"[{k}] {g0.v[k]:.1f}  →  {g1.v[k]:.1f}")
        QtWidgets.QMessageBox.information(self, f"Changes since '{s['name']}'",
                                          "\n".join(rows) if rows else "No changes.")

    def _ghost(self):
        s = self._cur()
        if s:
            d = self.doc.design.snapshot_design(s["name"])
            self.doc.ghosts = [gh for gh in self.doc.ghosts if gh["label"] != f"Snapshot: {s['name']}"] + [
                {"label": f"Snapshot: {s['name']}", "design": d, "color": GHOST_COLORS[len(self.doc.ghosts) % 7]}]
            self.doc.refresh()

    def _restore(self):
        s = self._cur()
        if s:
            self.doc.set_params(dict(s["values"]), f"Restore snapshot '{s['name']}'")

    def _delete(self):
        i = self.list.currentRow()
        snaps = list(self.doc.design.extras.get("snapshots") or [])
        if 0 <= i < len(snaps):
            del snaps[i]
            self.doc.set_extra("snapshots", snaps, "Delete snapshot")
            self._fill()


# --------------------------------------------------------------------------
class TitleBlockDialog(QtWidgets.QDialog):
    FIELDS = [("company", "Company / builder"), ("address", "Address / contact"), ("revision", "Revision"),
              ("checked_by", "Checked by"), ("material_note", "Material / finish note"),
              ("tolerance", "General tolerance note")]

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Title block")
        tb = dict(doc.design.extras.get("title_block") or {})
        form = QtWidgets.QFormLayout(self)
        self.params = {}
        for key, label in (("title", "Title"), ("designer", "Designer"), ("customer", "Customer / rider"),
                           ("frame_size_label", "Size"), ("drawing_number", "Drawing number")):
            le = QtWidgets.QLineEdit(str(doc.design.get(key, "")))
            form.addRow(label, le)
            self.params[key] = le
        self.extras = {}
        for key, label in self.FIELDS:
            le = QtWidgets.QLineEdit(str(tb.get(key, "")))
            form.addRow(label, le)
            self.extras[key] = le
        row = QtWidgets.QHBoxLayout()
        self.logo = QtWidgets.QLineEdit(str(tb.get("logo", "")))
        b = QtWidgets.QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(self.logo, 1)
        row.addWidget(b)
        form.addRow("Logo image", row)
        form.addRow(_buttons(self))

    def _browse(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Logo", str(Path.home()), "Images (*.png *.jpg *.jpeg *.svg)")
        if fn:
            self.logo.setText(fn)

    def accept(self):
        self.doc.set_params({k: le.text() for k, le in self.params.items()}, "Title block")
        tb = dict(self.doc.design.extras.get("title_block") or {})
        tb.update({k: le.text() for k, le in self.extras.items()})
        tb["logo"] = self.logo.text()
        self.doc.set_extra("title_block", tb, "Title block")
        super().accept()


# --------------------------------------------------------------------------
def parse_point_spec(text: str):
    """'ht_bottom' | 'ht_bottom+10,-5' | 'st@0.3' | 'st@120mm' | 'x,y'."""
    t = text.strip()
    if "@" in t:
        tube, pos = t.split("@", 1)
        pos = pos.strip().lower()
        if pos.endswith("mm"):
            return {"tube": tube.strip(), "s": float(pos[:-2])}
        return {"tube": tube.strip(), "pos": float(pos)}
    if "+" in t:
        name, off = t.split("+", 1)
        dx, dy = (float(x) for x in off.split(","))
        return {"point": name.strip(), "dx": dx, "dy": dy}
    if "," in t:
        x, y = (float(v) for v in t.split(",", 1))
        return {"x": x, "y": y}
    return t


def format_point_spec(spec) -> str:
    if isinstance(spec, str):
        return spec
    if "tube" in spec:
        return f"{spec['tube']}@{spec['s']:g}mm" if "s" in spec else f"{spec['tube']}@{spec.get('pos', 0.5):g}"
    if "point" in spec:
        return f"{spec['point']}+{spec.get('dx', 0):g},{spec.get('dy', 0):g}"
    return f"{spec.get('x', 0):g},{spec.get('y', 0):g}"


class ExtraTubesDialog(QtWidgets.QDialog):
    """Extra tubes (mixte laterals, step-through, cargo, braces...)."""
    COLS = ["Name", "Start", "End", "OD", "Wall", "Bend", "Mirrored", "Z start", "Z end"]

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Extra tubes")
        self.resize(860, 380)
        lay = QtWidgets.QVBoxLayout(self)
        help_ = QtWidgets.QLabel("End points: a named point (e.g. <b>ht_bottom</b>, <b>rear_axle</b>), a point with "
                                 "offset (<b>ht_bottom+0,-40</b>), a position along a tube (<b>st@0.25</b> fraction or "
                                 "<b>st@120mm</b>), or coordinates from the BB (<b>-200,150</b>). Remove standard tubes "
                                 "with Frame ▸ Advanced ▸ Remove tubes.")
        help_.setWordWrap(True)
        lay.addWidget(help_)
        self.table = QtWidgets.QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        for text, fn in (("Add", self._add), ("Delete", self._delete)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_buttons(self))
        for et in doc.design.extras.get("extra_tubes") or []:
            self._add(et)

    def _add(self, et=None):
        et = et if isinstance(et, dict) else {"name": f"tube{self.table.rowCount() + 1}", "a": "ht_bottom",
                                              "b": "st@0.25", "od": 28.6, "wall": 0.9}
        r = self.table.rowCount()
        self.table.insertRow(r)
        vals = [et.get("name", ""), format_point_spec(et.get("a", "bb")), format_point_spec(et.get("b", "bb")),
                et.get("od", 28.6), et.get("wall", 0.9), et.get("bend", 0.0), "yes" if et.get("mirrored") else "no",
                et.get("za", 0.0), et.get("zb", 0.0)]
        for c, v in enumerate(vals):
            self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))

    def _delete(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def accept(self):
        out = []
        try:
            for r in range(self.table.rowCount()):
                cell = lambda c: self.table.item(r, c).text() if self.table.item(r, c) else ""
                out.append({"name": cell(0) or f"tube{r + 1}", "a": parse_point_spec(cell(1)),
                            "b": parse_point_spec(cell(2)), "od": float(cell(3) or 28.6),
                            "wall": float(cell(4) or 0.9), "bend": float(cell(5) or 0),
                            "mirrored": cell(6).strip().lower() in ("yes", "y", "true", "1"),
                            "za": float(cell(7) or 0), "zb": float(cell(8) or 0)})
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Extra tubes", f"Invalid value: {exc}")
            return
        self.doc.set_extra("extra_tubes", out, "Edit extra tubes")
        super().accept()


# --------------------------------------------------------------------------
class PreferencesDialog(QtWidgets.QDialog):
    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("Preferences")
        form = QtWidgets.QFormLayout(self)
        self.ui_scale = QtWidgets.QDoubleSpinBox()
        self.ui_scale.setRange(0.5, 3.0)
        self.ui_scale.setSingleStep(0.1)
        self.ui_scale.setValue(float(settings.value("ui/line_scale", 1.0)))
        form.addRow("Drawing line/text scale", self.ui_scale)
        self.font = QtWidgets.QSpinBox()
        self.font.setRange(7, 24)
        self.font.setValue(int(settings.value("ui/font_size", 0) or QtWidgets.QApplication.font().pointSize()))
        form.addRow("Interface font size", self.font)
        self.icons = QtWidgets.QSpinBox()
        self.icons.setRange(12, 64)
        self.icons.setValue(int(settings.value("ui/icon_size", 22)))
        form.addRow("Toolbar icon size", self.icons)
        self.theme = QtWidgets.QComboBox()
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.setCurrentText(str(settings.value("ui/theme", "System")))
        form.addRow("Theme", self.theme)
        self.units = QtWidgets.QComboBox()
        self.units.addItems(["mm", "in"])
        self.units.setCurrentText(str(settings.value("defaults/units", "mm")))
        form.addRow("Default units (new designs)", self.units)
        self.reverse = QtWidgets.QCheckBox("Reverse mouse-wheel zoom")
        self.reverse.setChecked(settings.value("ui/reverse_wheel", "false") in (True, "true"))
        form.addRow("", self.reverse)
        self.handles = QtWidgets.QCheckBox("Show drag handles")
        self.handles.setChecked(settings.value("ui/handles", "true") in (True, "true"))
        form.addRow("", self.handles)
        self.recent = QtWidgets.QSpinBox()
        self.recent.setRange(0, 40)
        self.recent.setValue(int(settings.value("ui/recent_count", 12)))
        form.addRow("Recent files list length", self.recent)
        self.autosave = QtWidgets.QSpinBox()
        self.autosave.setRange(0, 60)
        self.autosave.setSuffix(" min (0 = off)")
        self.autosave.setValue(int(settings.value("files/autosave_min", 0)))
        form.addRow("Autosave backups", self.autosave)
        form.addRow(_buttons(self))

    def accept(self):
        s = self.s
        s.setValue("ui/line_scale", self.ui_scale.value())
        s.setValue("ui/font_size", self.font.value())
        s.setValue("ui/icon_size", self.icons.value())
        s.setValue("ui/theme", self.theme.currentText())
        s.setValue("defaults/units", self.units.currentText())
        s.setValue("ui/reverse_wheel", self.reverse.isChecked())
        s.setValue("ui/handles", self.handles.isChecked())
        s.setValue("ui/recent_count", self.recent.value())
        s.setValue("files/autosave_min", self.autosave.value())
        super().accept()
