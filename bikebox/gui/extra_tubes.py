"""Extra tubes: presets, a single-tube editor and add/edit/delete helpers.

End points are stored as specs that follow the geometry (see
``geometry.solver._resolve_point``): a named point (``"ht_bottom"``), a point
with offset, a position along a tube (``{"tube": "st", "pos": 0.25}``) or
coordinates from the BB.
"""
from __future__ import annotations

import copy

from ..model import params as P
from ..qt import QtCore, QtGui, QtWidgets

from .document import Document

Qt = QtCore.Qt

PRESETS: list[tuple[str, str, list[dict]]] = [
    ("Mixte twin laterals", "Two thin tubes from the head tube past the seat tube to the rear dropouts",
     [{"name": "mixte", "a": {"tube": "ht", "pos": 0.55}, "b": "stay_node", "od": 19.0, "wall": 0.9,
       "mirrored": True, "za": 12.0, "zb": 70.0}]),
    ("Step-through low tube", "Low top tube from the bottom of the head tube to low on the seat tube",
     [{"name": "step", "a": {"tube": "ht", "pos": 0.2}, "b": {"tube": "st", "pos": 0.3}, "od": 31.8, "wall": 0.9,
       "bend": -40.0}]),
    ("Seat cluster brace", "Short gusset from the top tube to the seat tube",
     [{"name": "st_brace", "a": {"tube": "tt", "pos": 0.22}, "b": {"tube": "st", "pos": 0.72}, "od": 19.0,
       "wall": 0.9}]),
    ("Head tube gusset", "Brace from the top tube to the down tube behind the head tube",
     [{"name": "ht_gusset", "a": {"tube": "tt", "pos": 0.85}, "b": {"tube": "dt", "pos": 0.85}, "od": 19.0,
       "wall": 0.9}]),
    ("Twin top tubes (camelback style)", "A second, higher top tube from the head tube top to the seat tube top",
     [{"name": "tt_upper", "a": "st_top", "b": "ht_top", "od": 22.2, "wall": 0.8, "bend": 25.0}]),
    ("Cargo front boom", "Long tube from the down tube forward (bakfiets-style platform support)",
     [{"name": "boom", "a": {"tube": "dt", "pos": 0.25}, "b": {"point": "front_axle", "dx": -40, "dy": -120},
       "od": 38.1, "wall": 1.2}]),
    ("Rear rack struts (integrated)", "Mirrored struts from the seat stays to a rack platform",
     [{"name": "rack_strut", "a": {"tube": "ss", "pos": 0.6}, "b": {"point": "rear_axle", "dx": -150, "dy": 320},
       "od": 10.0, "wall": 1.0, "mirrored": True, "za": 70.0, "zb": 70.0}]),
]


def _next_name(doc: Document, base: str) -> str:
    names = {str(t.get("name")) for t in doc.design.extras.get("extra_tubes") or []}
    if base not in names:
        return base
    i = 2
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


def add_tubes(doc: Document, tubes: list[dict], text: str = "Add extra tube") -> None:
    cur = [dict(t) for t in doc.design.extras.get("extra_tubes") or []]
    for t in tubes:
        t = copy.deepcopy(t)
        t["name"] = _next_name(doc, str(t.get("name", "tube")))
        cur.append(t)
    doc.set_extra("extra_tubes", cur, text)


def delete_tube(doc: Document, index: int) -> None:
    cur = [dict(t) for t in doc.design.extras.get("extra_tubes") or []]
    if 0 <= index < len(cur):
        name = cur[index].get("name", "tube")
        del cur[index]
        doc.set_extra("extra_tubes", cur, f"Delete extra tube {name}")


def tube_index(geom_tube_name: str) -> int | None:
    """Index into extras['extra_tubes'] for a geometry tube named ``x<i>_<name>``."""
    if geom_tube_name.startswith("x") and "_" in geom_tube_name:
        try:
            return int(geom_tube_name[1:geom_tube_name.index("_")])
        except ValueError:
            return None
    return None


_SURFACES = (("", "Centre-line"), ("above", "On its surface: above / behind"),
             ("below", "On its surface: below / in front"))
_FROM = (("a", "mm from its start"), ("b", "mm from its end"), ("pos", "% of its length"))


class EndpointEditor(QtWidgets.QGroupBox):
    """Edit one end of an extra tube: a frame point, a place on another tube
    (distance, side offset, sit on its surface) or X/Y from the BB."""

    def __init__(self, title: str, spec, geometry, own_name: str | None = None, parent=None):
        super().__init__(title, parent)
        self.g = geometry
        lay = QtWidgets.QFormLayout(self)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("On another tube", "tube")
        self.mode.addItem("At a frame point", "point")
        self.mode.addItem("X / Y from the BB", "xy")
        lay.addRow("Attach", self.mode)
        self.stack = QtWidgets.QStackedWidget()
        lay.addRow(self.stack)

        def spin(lo, hi, dec=1, suffix=" mm"):
            sp = QtWidgets.QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(dec)
            sp.setSuffix(suffix)
            return sp
        # tube page
        tw = QtWidgets.QWidget()
        tf = QtWidgets.QFormLayout(tw)
        tf.setContentsMargins(0, 0, 0, 0)
        self.tube = QtWidgets.QComboBox()
        for name, tb in geometry.tubes.items():
            if name != own_name:
                self.tube.addItem(f"{tb.label} [{name}]", name)
        self.dist = spin(0, 5000)
        self.dist_mode = QtWidgets.QComboBox()
        for val, label in _FROM:
            self.dist_mode.addItem(label, val)
        drow = QtWidgets.QHBoxLayout()
        drow.addWidget(self.dist)
        drow.addWidget(self.dist_mode)
        self.surface = QtWidgets.QComboBox()
        for val, label in _SURFACES:
            self.surface.addItem(label, val)
        self.side = spin(-500, 500)
        self.side.setToolTip("Extra offset perpendicular to that tube (+ = above / behind)")
        tf.addRow("Tube", self.tube)
        tf.addRow("Position", drow)
        tf.addRow("Placement", self.surface)
        tf.addRow("Side offset", self.side)
        self.stack.addWidget(tw)
        # point page
        pw = QtWidgets.QWidget()
        pf = QtWidgets.QFormLayout(pw)
        pf.setContentsMargins(0, 0, 0, 0)
        self.point = QtWidgets.QComboBox()
        self.point.addItems(sorted(geometry.p))
        self.dx, self.dy = spin(-3000, 3000), spin(-3000, 3000)
        pf.addRow("Point", self.point)
        pf.addRow("Offset X", self.dx)
        pf.addRow("Offset Y", self.dy)
        self.stack.addWidget(pw)
        # xy page
        xw = QtWidgets.QWidget()
        xf = QtWidgets.QFormLayout(xw)
        xf.setContentsMargins(0, 0, 0, 0)
        self.x, self.y = spin(-5000, 5000), spin(-5000, 5000)
        xf.addRow("X", self.x)
        xf.addRow("Y", self.y)
        self.stack.addWidget(xw)
        self.mode.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.dist_mode.currentIndexChanged.connect(self._dist_units)
        self.set_spec(spec)

    def _dist_units(self, *_):
        pct = self.dist_mode.currentData() == "pos"
        self.dist.setSuffix(" %" if pct else " mm")
        self.dist.setMaximum(100 if pct else 5000)

    def set_spec(self, spec) -> None:
        if isinstance(spec, str):
            self.mode.setCurrentIndex(1)
            self.point.setCurrentText(spec)
        elif isinstance(spec, dict) and "tube" in spec:
            self.mode.setCurrentIndex(0)
            i = self.tube.findData(spec["tube"])
            if i >= 0:
                self.tube.setCurrentIndex(i)
            if "s" in spec:
                self.dist_mode.setCurrentIndex(1 if spec.get("from") == "b" else 0)
                self._dist_units()
                self.dist.setValue(float(spec["s"]))
            else:
                self.dist_mode.setCurrentIndex(2)
                self._dist_units()
                self.dist.setValue(float(spec.get("pos", 0.5)) * 100)
            self.surface.setCurrentIndex(max(0, self.surface.findData(spec.get("surface") or "")))
            self.side.setValue(float(spec.get("side", 0.0) or 0.0))
        elif isinstance(spec, dict) and "point" in spec:
            self.mode.setCurrentIndex(1)
            self.point.setCurrentText(str(spec["point"]))
            self.dx.setValue(float(spec.get("dx", 0)))
            self.dy.setValue(float(spec.get("dy", 0)))
        elif isinstance(spec, dict):
            self.mode.setCurrentIndex(2)
            self.x.setValue(float(spec.get("x", 0)))
            self.y.setValue(float(spec.get("y", 0)))
        self.stack.setCurrentIndex(self.mode.currentIndex())

    def spec(self):
        m = self.mode.currentData()
        if m == "point":
            if abs(self.dx.value()) < 1e-9 and abs(self.dy.value()) < 1e-9:
                return self.point.currentText()
            return {"point": self.point.currentText(), "dx": self.dx.value(), "dy": self.dy.value()}
        if m == "xy":
            return {"x": self.x.value(), "y": self.y.value()}
        out: dict = {"tube": self.tube.currentData()}
        dm = self.dist_mode.currentData()
        if dm == "pos":
            out["pos"] = round(self.dist.value() / 100.0, 4)
        else:
            out["s"] = self.dist.value()
            if dm == "b":
                out["from"] = "b"
        if self.surface.currentData():
            out["surface"] = self.surface.currentData()
        if abs(self.side.value()) > 1e-9:
            out["side"] = self.side.value()
        return out


class ExtraTubeEditor(QtWidgets.QDialog):
    """Edit one extra tube."""

    def __init__(self, doc: Document, tube: dict, parent=None, title: str = "Extra tube"):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle(title)
        self.tube = dict(tube)
        form = QtWidgets.QFormLayout(self)
        t = self.tube
        self.name = QtWidgets.QLineEdit(str(t.get("name", "tube")))
        g = doc.geometry
        own = next((n for n in g.tubes if n.startswith("x") and n.endswith("_" + str(t.get("name", "")))), None)
        self.a = EndpointEditor("Start", t.get("a", "bb"), g, own)
        self.b = EndpointEditor("End", t.get("b", "bb"), g, own)

        def spin(v, lo, hi, dec=1, suffix=" mm"):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSuffix(suffix)
            s.setValue(float(v))
            return s
        self.od = spin(t.get("od", 25.4), 3, 120)
        self.od_end = spin(t.get("od_end", 0.0), 0, 120)
        self.od_end.setToolTip("0 = straight gauge; otherwise the OD at the start end (taper)")
        self.profile = QtWidgets.QComboBox()
        for val, label in (("round", "Round"), ("oval", "Oval"), ("aero", "Aero")):
            self.profile.addItem(label, val)
        self.profile.setCurrentIndex(max(0, self.profile.findData(t.get("profile", "round"))))
        self.od2 = spin(t.get("od2", 0.0), 0, 120)
        self.od2.setToolTip("Top-view width for oval/aero tubes (0 = same as OD)")
        self.wall = spin(t.get("wall", 0.9), 0.2, 10, 2)
        self.wall_mid = spin(t.get("wall_mid", t.get("wall", 0.9)), 0.2, 10, 2)
        self.butt = spin(t.get("butt_length", 0.0), 0, 400)
        self.bend = spin(t.get("bend", 0.0), -300, 300)
        self.bend.setToolTip("Curved tube: sagitta (+ = to the left of start→end)")
        self.material = QtWidgets.QComboBox()
        self.material.addItem("Same as frame", "frame")
        for val, label in P.MATERIALS:
            self.material.addItem(label, val)
        self.material.setCurrentIndex(max(0, self.material.findData(t.get("material", "frame"))))
        # paint: a custom colour for just this tube
        from .param_panel import ColorButton
        self.paint_on = QtWidgets.QCheckBox("Paint this tube")
        self.paint_on.setChecked(bool(t.get("paint")))
        self.paint = ColorButton()
        self.paint.set_color(str(t.get("paint") or doc.design.get("paint_frame", "#c8102e")))
        # the swatch is always clickable; picking a colour ticks "Paint this tube"
        self.paint.color_changed.connect(lambda _c: self.paint_on.setChecked(True))
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(self.paint_on)
        prow.addWidget(self.paint)
        prow.addStretch(1)
        # in phase: keep this tube parallel to another tube
        self.parallel = QtWidgets.QComboBox()
        self.parallel.addItem("Not aligned (free)", "")
        for name, tb in g.tubes.items():
            if name != own:
                self.parallel.addItem(f"{tb.label} [{name}]", name)
        self.parallel.setCurrentIndex(max(0, self.parallel.findData(t.get("parallel_to", "") or "")))
        self.parallel.setToolTip("Keep this tube in phase (parallel) with the chosen tube as the geometry changes")
        self.phase_anchor = QtWidgets.QComboBox()
        for val, label in (("a", "holding the start"), ("b", "holding the end"), ("mid", "about the middle")):
            self.phase_anchor.addItem(label, val)
        self.phase_anchor.setCurrentIndex(max(0, self.phase_anchor.findData(t.get("phase_anchor", "a"))))
        parow = QtWidgets.QHBoxLayout()
        parow.addWidget(self.parallel, 1)
        parow.addWidget(self.phase_anchor)
        self.mirrored = QtWidgets.QCheckBox("Pair (mirrored to both sides)")
        self.mirrored.setChecked(bool(t.get("mirrored", False)))
        self.za = spin(t.get("za", 0.0), -200, 200)
        self.zb = spin(t.get("zb", 0.0), -200, 200)
        ends = QtWidgets.QHBoxLayout()
        ends.addWidget(self.a)
        ends.addWidget(self.b)
        form.addRow(ends)
        for label, w in (("Name", self.name), ("OD (side view)", self.od),
                         ("OD at start (taper)", self.od_end), ("Profile", self.profile), ("Width (top view)", self.od2),
                         ("Wall (ends)", self.wall), ("Wall (centre)", self.wall_mid), ("Butt length", self.butt),
                         ("Bend", self.bend), ("Material", self.material)):
            form.addRow(label, w)
        form.addRow("Paint", prow)
        form.addRow("In phase with", parow)
        for label, w in (("", self.mirrored), ("Lateral offset at start", self.za),
                         ("Lateral offset at end", self.zb)):
            form.addRow(label, w)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def accept(self):
        a, b = self.a.spec(), self.b.spec()
        self.tube.update({"name": self.name.text().strip() or "tube", "a": a, "b": b, "od": self.od.value(),
                          "od_end": self.od_end.value(), "profile": self.profile.currentData(),
                          "od2": self.od2.value(), "wall": self.wall.value(), "wall_mid": self.wall_mid.value(),
                          "butt_length": self.butt.value(), "bend": self.bend.value(),
                          "material": self.material.currentData(), "mirrored": self.mirrored.isChecked(),
                          "za": self.za.value(), "zb": self.zb.value(),
                          "paint": self.paint._color if self.paint_on.isChecked() else "",
                          "parallel_to": self.parallel.currentData() or "",
                          "phase_anchor": self.phase_anchor.currentData()})
        super().accept()


def edit_tube(doc: Document, index: int, parent=None) -> None:
    cur = [dict(t) for t in doc.design.extras.get("extra_tubes") or []]
    if not 0 <= index < len(cur):
        return
    dlg = ExtraTubeEditor(doc, cur[index], parent, f"Edit extra tube '{cur[index].get('name', '')}'")
    if dlg.exec():
        cur[index] = dlg.tube
        doc.set_extra("extra_tubes", cur, f"Edit extra tube {dlg.tube['name']}")


def new_tube_dialog(doc: Document, a, b, parent=None) -> None:
    """Open the editor for a tube drawn on the canvas and add it."""
    tube = {"name": _next_name(doc, "tube"), "a": a, "b": b, "od": 25.4, "wall": 0.9}
    dlg = ExtraTubeEditor(doc, tube, parent, "New extra tube")
    if dlg.exec():
        add_tubes(doc, [dlg.tube])
