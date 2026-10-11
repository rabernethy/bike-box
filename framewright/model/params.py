"""Parameter schema.

Every design input is declared here (or registered by a module via
``register``) as a :class:`ParamDef`.  The GUI builds its editors from this
schema, the file format stores values by key, CSV export iterates it, and
morphing interpolates over it.  Adding a feature usually starts with adding
parameters here.

Conventions
-----------
* Lengths are millimetres, angles are degrees, masses are grams.
* The model origin is the bottom-bracket centre, +X points forward (toward the
  front wheel), +Y points up.  +Z points to the drive (right) side.
* ``visible_if`` is ``(key, allowed_values)``; the editor hides the parameter
  unless ``design[key]`` is one of ``allowed_values``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

FLOAT, INT, BOOL, CHOICE, STR, COLOR, LIST = (
    "float", "int", "bool", "choice", "str", "color", "list")


@dataclass(frozen=True)
class ParamDef:
    key: str
    label: str
    group: str
    section: str
    kind: str = FLOAT
    default: Any = 0.0
    unit: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[tuple[str, str], ...] = ()   # (value, label)
    help: str = ""
    visible_if: tuple[str, tuple[Any, ...]] | None = None
    morph: bool = True          # include when interpolating designs

    @property
    def is_length(self) -> bool:
        return self.kind == FLOAT and self.unit == "mm"

    def coerce(self, value: Any) -> Any:
        """Convert ``value`` (possibly from JSON or a text field) to this kind."""
        k = self.kind
        if k == FLOAT:
            v = float(value)
            if self.min is not None and v < self.min:
                v = float(self.min)
            if self.max is not None and v > self.max:
                v = float(self.max)
            return v
        if k == INT:
            v = int(round(float(value)))
            if self.min is not None and v < self.min:
                v = int(self.min)
            if self.max is not None and v > self.max:
                v = int(self.max)
            return v
        if k == BOOL:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if k == CHOICE:
            v = str(value)
            if self.choices and v not in {c[0] for c in self.choices}:
                return self.default
            return v
        if k == LIST:
            return format_list(parse_list(value))
        return str(value)


def parse_list(value: Any) -> list[float]:
    """Parse ``"50, 34"`` / ``[50, 34]`` into a list of numbers."""
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = [s for s in str(value).replace(";", ",").replace(" ", ",").split(",") if s.strip()]
    out = []
    for s in items:
        try:
            out.append(float(s))
        except (TypeError, ValueError):
            continue
    return out


def format_list(values: Iterable[float]) -> str:
    return ", ".join(f"{v:g}" for v in values)


_REGISTRY: dict[str, ParamDef] = {}
_ORDER: list[str] = []


def register(defs: Iterable[ParamDef]) -> None:
    """Add parameter definitions.  Modules call this at import time to add
    their own parameters without editing this file."""
    for d in defs:
        if d.key not in _REGISTRY:
            _ORDER.append(d.key)
        _REGISTRY[d.key] = d


def get(key: str) -> ParamDef:
    return _REGISTRY[key]


def has(key: str) -> bool:
    return key in _REGISTRY


def all_params() -> list[ParamDef]:
    return [_REGISTRY[k] for k in _ORDER]


def defaults() -> dict[str, Any]:
    return {k: _REGISTRY[k].default for k in _ORDER}


def groups() -> list[str]:
    seen: list[str] = []
    for k in _ORDER:
        g = _REGISTRY[k].group
        if g not in seen:
            seen.append(g)
    return seen


def by_group(group: str) -> list[ParamDef]:
    return [d for d in all_params() if d.group == group]


# --------------------------------------------------------------------------
# helpers for compact declarations
# --------------------------------------------------------------------------
def _mm(key, label, group, section, default, lo=None, hi=None, step=1.0, help="", vis=None):
    return ParamDef(key, label, group, section, FLOAT, float(default), "mm", lo, hi, step, (), help, vis)


def _deg(key, label, group, section, default, lo=None, hi=None, step=0.1, help="", vis=None):
    return ParamDef(key, label, group, section, FLOAT, float(default), "deg", lo, hi, step, (), help, vis)


def _num(key, label, group, section, default, unit="", lo=None, hi=None, step=1.0, help="", vis=None):
    return ParamDef(key, label, group, section, FLOAT, float(default), unit, lo, hi, step, (), help, vis)


def _int(key, label, group, section, default, lo=None, hi=None, help="", vis=None):
    return ParamDef(key, label, group, section, INT, int(default), "", lo, hi, 1, (), help, vis)


def _bool(key, label, group, section, default, help="", vis=None):
    return ParamDef(key, label, group, section, BOOL, bool(default), help=help, visible_if=vis, morph=False)


def _choice(key, label, group, section, default, choices, help="", vis=None):
    ch = tuple((c, c.replace("_", " ").capitalize()) if isinstance(c, str) else c for c in choices)
    return ParamDef(key, label, group, section, CHOICE, default, choices=ch, help=help,
                    visible_if=vis, morph=False)


def _color(key, label, group, section, default, help=""):
    return ParamDef(key, label, group, section, COLOR, default, help=help, morph=False)


def _str(key, label, group, section, default="", help="", vis=None):
    return ParamDef(key, label, group, section, STR, default, help=help, visible_if=vis, morph=False)


def _list(key, label, group, section, default, help="", vis=None):
    return ParamDef(key, label, group, section, LIST, default, help=help, visible_if=vis, morph=False)


MATERIALS = (
    ("steel", "Steel (CrMo)"), ("stainless", "Stainless steel"), ("titanium", "Titanium 3Al-2.5V"),
    ("aluminium", "Aluminium 6061"), ("aluminium7005", "Aluminium 7005"), ("carbon", "Carbon fibre"),
    ("scandium", "Scandium-aluminium"), ("bamboo", "Bamboo"), ("wood", "Wood"),
)
PROFILES = (("round", "Round"), ("oval", "Oval / elliptical"), ("aero", "Aero (teardrop)"))

G = "Frame"
_frame = [
    # -- wheels ---------------------------------------------------------------
    _mm("rear_bsd", "Rear rim BSD", G, "Wheels", 622, 100, 900, help="ISO bead seat diameter (700c = 622, 650b = 584, 29er = 622, 26\" = 559)"),
    _mm("rear_tire_width", "Rear tire width", G, "Wheels", 32, 10, 130),
    _mm("rear_tire_height", "Rear tire height", G, "Wheels", 30, 10, 130, help="Radial height of the tire above the bead seat"),
    _mm("front_bsd", "Front rim BSD", G, "Wheels", 622, 100, 900),
    _mm("front_tire_width", "Front tire width", G, "Wheels", 32, 10, 130),
    _mm("front_tire_height", "Front tire height", G, "Wheels", 30, 10, 130),
    # -- bottom bracket & rear --------------------------------------------------
    _choice("bb_mode", "BB position by", G, "Bottom bracket & rear", "drop",
            (("drop", "BB drop"), ("height", "BB height"))),
    _mm("bb_drop", "BB drop", G, "Bottom bracket & rear", 70, -200, 200, vis=("bb_mode", ("drop",)),
        help="Vertical distance the BB centre sits below the rear axle"),
    _mm("bb_height", "BB height", G, "Bottom bracket & rear", 270, 50, 600, vis=("bb_mode", ("height",)),
        help="BB centre height above the ground"),
    _choice("cs_mode", "Rear end by", G, "Bottom bracket & rear", "length",
            (("length", "Chainstay length"), ("tire_gap", "Rear tire to seat tube gap"))),
    _mm("chainstay_length", "Chainstay length", G, "Bottom bracket & rear", 420, 250, 900, vis=("cs_mode", ("length",))),
    _mm("rear_tire_gap", "Rear tire gap", G, "Bottom bracket & rear", 12, -50, 200, vis=("cs_mode", ("tire_gap",)),
        help="Clearance between the rear tire and the seat tube surface"),
    _mm("bb_shell_od", "BB shell OD", G, "Bottom bracket & rear", 40, 20, 120),
    _mm("bb_shell_width", "BB shell width", G, "Bottom bracket & rear", 68, 40, 140),
    _mm("rear_hub_spacing", "Rear hub spacing (OLD)", G, "Bottom bracket & rear", 135, 100, 200),
    _choice("dropout_type", "Rear dropout type", G, "Dropouts", "vertical",
            (("vertical", "Vertical"), ("horizontal", "Horizontal (forward-facing slot)"),
             ("track", "Track (rear-facing slot)"), ("sliding", "Sliding"), ("thru", "Thru-axle"))),
    _mm("dropout_slot_length", "Slot length", G, "Dropouts", 30, 5, 80,
        vis=("dropout_type", ("horizontal", "track", "sliding"))),
    _deg("dropout_slot_angle", "Slot angle", G, "Dropouts", 0, -45, 45, 0.5,
         vis=("dropout_type", ("horizontal", "track", "sliding")),
         help="Slot angle relative to the chainstay (0 = parallel)"),
    _mm("axle_in_slot", "Axle position in slot", G, "Dropouts", 15, 0, 80,
        vis=("dropout_type", ("horizontal", "track", "sliding")),
        help="Distance of the axle from the front (closed) end of the slot"),
    _mm("dropout_offset_x", "Dropout offset X", G, "Bottom bracket & rear", 0, -60, 60,
        help="Offset of the axle from the stay convergence point (positive = axle forward)"),
    _mm("dropout_offset_y", "Dropout offset Y", G, "Bottom bracket & rear", 0, -60, 60),
    # -- seat tube --------------------------------------------------------------
    _deg("seat_tube_angle", "Seat tube angle", G, "Seat tube", 73.5, 55, 90),
    _choice("st_length_mode", "Seat tube length measured", G, "Seat tube", "ct",
            (("ct", "Centre to top"), ("cc", "Centre to centre (top tube)"))),
    _mm("seat_tube_length", "Seat tube length", G, "Seat tube", 540, 100, 1000),
    _mm("st_extension", "Seat tube extension", G, "Seat tube", 25, -100, 400,
        help="Seat tube length above the top tube centreline (used with c-c length or 'by extension' top tube)"),
    _mm("st_bb_offset", "Seat tube BB offset", G, "Seat tube", 0, -60, 60,
        help="Perpendicular offset of the seat tube axis from the BB centre (+ = forward)"),
    # -- front end ---------------------------------------------------------------
    _deg("head_tube_angle", "Head tube angle", G, "Front end", 72.0, 45, 90),
    _choice("front_v_mode", "Front end height by", G, "Front end", "ht_length",
            (("ht_length", "Head tube length"), ("stack", "Stack"), ("bar_y", "Handlebar height"))),
    _choice("front_h_mode", "Front end length by", G, "Front end", "reach",
            (("reach", "Reach"), ("front_center", "Front centre"), ("ett", "Effective top tube"),
             ("wheelbase", "Wheelbase"), ("bar_x", "Handlebar reach"))),
    _mm("head_tube_length", "Head tube length", G, "Front end", 150, 40, 400, vis=("front_v_mode", ("ht_length",))),
    _mm("stack", "Stack", G, "Front end", 580, 300, 900, vis=("front_v_mode", ("stack",))),
    _mm("bar_y", "Handlebar Y (from BB)", G, "Front end", 620, 200, 1100, vis=("front_v_mode", ("bar_y",)),
        help="Height of the handlebar clamp centre above the BB"),
    _mm("reach", "Reach", G, "Front end", 390, 200, 700, vis=("front_h_mode", ("reach",))),
    _mm("front_center", "Front centre", G, "Front end", 600, 400, 1000, vis=("front_h_mode", ("front_center",))),
    _mm("top_tube_effective", "Effective top tube", G, "Front end", 560, 300, 900, vis=("front_h_mode", ("ett",))),
    _mm("wheelbase", "Wheelbase", G, "Front end", 1010, 700, 1600, vis=("front_h_mode", ("wheelbase",))),
    _mm("bar_x", "Handlebar X (from BB)", G, "Front end", 480, 200, 900, vis=("front_h_mode", ("bar_x",)),
        help="Horizontal distance from the BB to the handlebar clamp centre"),
    # -- top & down tube ---------------------------------------------------------
    _choice("tt_mode", "Top tube defined by", G, "Top & down tube", "st_extension",
            (("angle", "Top tube angle"), ("st_extension", "Seat tube extension"))),
    _deg("top_tube_angle", "Top tube angle", G, "Top & down tube", 0.0, -30, 45, vis=("tt_mode", ("angle",)),
         help="Slope of the top tube from horizontal (+ = front end higher)"),
    _mm("tt_ht_offset", "Top tube below head tube top", G, "Top & down tube", 20, -50, 200,
        help="Distance along the head tube from its top face to the top tube centreline"),
    _mm("dt_ht_offset", "Down tube above head tube bottom", G, "Top & down tube", 30, -50, 200,
        help="Distance along the head tube from its bottom face to the down tube centreline"),
    _mm("dt_bb_offset", "Down tube BB offset", G, "Top & down tube", 0, -60, 60,
        help="Perpendicular offset of the down tube axis from the BB centre (+ = above)"),
    # -- seat stays ---------------------------------------------------------------
    _choice("ss_attach", "Seat stays attach to", G, "Seat stays", "seat_tube",
            (("seat_tube", "Seat tube"), ("top_tube", "Top tube"), ("none", "None (no seat stays)"))),
    _mm("ss_offset", "Seat stay offset", G, "Seat stays", 15, -150, 400,
        help="Seat stay junction distance from the top tube/seat tube junction (along the tube attached to)"),
    _choice("ss_style", "Seat stay style", G, "Seat stays", "conventional",
            (("conventional", "Conventional"), ("wishbone", "Wishbone"), ("mono", "Mono stay"))),
    _mm("wishbone_length", "Wishbone stem length", G, "Seat stays", 80, 10, 300, vis=("ss_style", ("wishbone", "mono"))),
    _mm("ss_spread_top", "Seat stay spread at top (c-c)", G, "Seat stays", 0, 0, 200,
        help="0 = automatic: stays wrap the sides of the seat tube"),
    _mm("cs_spread_bb", "Chainstay spread at BB (c-c)", G, "Seat stays", 0, 0, 200,
        help="0 = automatic: stay outer faces flush with the BB shell faces"),
]

_frame += [
    _choice("frame_type", "Frame type", G, "Tandem", "single", (("single", "Single"), ("tandem", "Tandem"))),
    _mm("tandem_bb_distance", "Captain BB to stoker BB", G, "Tandem", 740, 400, 1400, vis=("frame_type", ("tandem",)),
        help="Horizontal distance from the captain (front) BB back to the stoker (rear) BB"),
    _mm("tandem_bb_dy", "Stoker BB height offset", G, "Tandem", 0, -100, 100, vis=("frame_type", ("tandem",)),
        help="Stoker BB height relative to the captain BB (+ = higher)"),
    _deg("stoker_st_angle", "Stoker seat tube angle", G, "Tandem", 73.0, 55, 90, vis=("frame_type", ("tandem",))),
    _mm("stoker_st_length", "Stoker seat tube (c-t)", G, "Tandem", 480, 200, 900, vis=("frame_type", ("tandem",))),
    _mm("stoker_tt_drop", "Stoker top tube below captain top tube", G, "Tandem", 0, -100, 300,
        vis=("frame_type", ("tandem",)),
        help="Where the stoker top tube leaves the captain seat tube, measured down from the top tube junction"),
    _deg("stoker_tt_angle", "Stoker top tube angle", G, "Tandem", 0, -30, 30, 0.5, vis=("frame_type", ("tandem",)),
         help="+ = front end higher"),
    _choice("tandem_mid_tube", "Mid / lateral tubes", G, "Tandem", "marathon",
            (("marathon", "Marathon (captain seat cluster to stoker BB)"),
             ("direct", "Direct lateral (head tube to stoker BB)"),
             ("twin_laterals", "Twin laterals (head tube to rear dropouts)"), ("none", "None")),
            vis=("frame_type", ("tandem",))),
    _mm("tandem_tube_od", "Boom / lateral tube OD", G, "Tandem", 31.8, 10, 60, 0.1, vis=("frame_type", ("tandem",))),
    _mm("stoker_saddle_height", "Stoker saddle height", G, "Tandem", 690, 300, 1100, vis=("frame_type", ("tandem",)),
        help="Stoker BB to saddle top along the stoker seat tube angle"),
    _mm("stoker_bar_drop", "Stoker bars below captain saddle", G, "Tandem", 110, 20, 300,
        vis=("frame_type", ("tandem",)), help="Stoker stem clamp on the captain's seatpost, below the rails"),
    _mm("stoker_stem_length", "Stoker stem length", G, "Tandem", 110, 0, 250, vis=("frame_type", ("tandem",))),
    _int("timing_ring", "Timing ring teeth", G, "Tandem", 32, 20, 60, vis=("frame_type", ("tandem",))),
]

_frame += [
    _choice("bb_housing", "BB drive unit", G, "Drive unit (e-bike / gearbox)", "none",
            (("none", "None (standard BB shell)"), ("gearbox", "Gearbox housing"), ("mid_motor", "Mid-drive motor"))),
    _mm("housing_length", "Housing length", G, "Drive unit (e-bike / gearbox)", 170, 50, 400,
        vis=("bb_housing", ("gearbox", "mid_motor"))),
    _mm("housing_height", "Housing height", G, "Drive unit (e-bike / gearbox)", 150, 50, 400,
        vis=("bb_housing", ("gearbox", "mid_motor"))),
    _mm("housing_dx", "Housing centre X from BB", G, "Drive unit (e-bike / gearbox)", 20, -200, 200,
        vis=("bb_housing", ("gearbox", "mid_motor"))),
    _mm("housing_dy", "Housing centre Y from BB", G, "Drive unit (e-bike / gearbox)", 25, -200, 200,
        vis=("bb_housing", ("gearbox", "mid_motor"))),
    _deg("housing_rotation", "Housing rotation", G, "Drive unit (e-bike / gearbox)", 0, -90, 90, 1,
         vis=("bb_housing", ("gearbox", "mid_motor"))),
    _num("housing_mass", "Drive unit mass", G, "Drive unit (e-bike / gearbox)", 2900, "g", 0, 10000, 10,
         vis=("bb_housing", ("gearbox", "mid_motor"))),
    _choice("battery", "Battery", G, "Drive unit (e-bike / gearbox)", "none",
            (("none", "None"), ("downtube", "On the down tube"), ("integrated", "Integrated in the down tube"),
             ("rack", "Rear rack"))),
    _mm("battery_length", "Battery length", G, "Drive unit (e-bike / gearbox)", 380, 100, 700,
        vis=("battery", ("downtube", "integrated", "rack"))),
    _mm("battery_thickness", "Battery thickness", G, "Drive unit (e-bike / gearbox)", 75, 20, 150,
        vis=("battery", ("downtube", "integrated", "rack"))),
    _mm("battery_pos", "Battery start from BB", G, "Drive unit (e-bike / gearbox)", 120, 0, 600,
        vis=("battery", ("downtube", "integrated"))),
    _num("battery_mass", "Battery mass", G, "Drive unit (e-bike / gearbox)", 2600, "g", 0, 10000, 10,
         vis=("battery", ("downtube", "integrated", "rack"))),
]

_frame += [
    _bool("couplers", "Frame couplers (travel)", G, "Couplers & travel case", False),
    _mm("coupler_tt_pos", "Top tube coupler from seat tube", G, "Couplers & travel case", 120, 30, 600,
        vis=("couplers", (True,))),
    _mm("coupler_dt_pos", "Down tube coupler from BB", G, "Couplers & travel case", 160, 30, 700,
        vis=("couplers", (True,))),
    _mm("coupler_length", "Coupler length", G, "Couplers & travel case", 70, 30, 150, vis=("couplers", (True,))),
    _mm("case_length", "Travel case inside length", G, "Couplers & travel case", 660, 300, 1500,
        vis=("couplers", (True,))),
    _mm("case_width", "Travel case inside width", G, "Couplers & travel case", 660, 300, 1500,
        vis=("couplers", (True,))),
]

G = "Tubes"
_tubes = [
    _choice("frame_material", "Frame material", G, "Material", "steel", MATERIALS),
    _choice("joint_style", "Joint style", G, "Material", "tig",
            (("tig", "TIG / welded"), ("fillet", "Fillet brazed"), ("lugged", "Lugged"), ("bonded", "Bonded / carbon"))),
]
for key, name, od, wall_e, wall_m, butt in (
        ("tt", "Top tube", 28.6, 0.8, 0.5, 80),
        ("dt", "Down tube", 31.8, 0.8, 0.5, 90),
        ("st", "Seat tube", 28.6, 0.8, 0.5, 120)):
    _tubes += [
        _choice(f"{key}_profile", f"{name} profile", G, name, "round", PROFILES),
        _mm(f"{key}_od", f"{name} OD (side view)", G, name, od, 5, 120, 0.1,
            help="Outer diameter, or depth as seen in side view for shaped tubes"),
        _mm(f"{key}_od2", f"{name} width (top view)", G, name, od, 5, 120, 0.1, vis=(f"{key}_profile", ("oval", "aero"))),
        _mm(f"{key}_od_end", f"{name} OD at far end", G, name, 0, 0, 120, 0.1,
            help="0 = straight gauge.  Otherwise the tube tapers linearly to this OD at its rear/lower end"),
        _mm(f"{key}_wall_end", f"{name} wall (butts)", G, name, wall_e, 0.2, 10, 0.05),
        _mm(f"{key}_wall_mid", f"{name} wall (centre)", G, name, wall_m, 0.2, 10, 0.05),
        _mm(f"{key}_butt_length", f"{name} butt length", G, name, butt, 0, 400),
        _mm(f"{key}_bend", f"{name} bend (sagitta)", G, name, 0, -200, 200, 0.5,
            help="Curved tubes: offset of the arc midpoint from the chord, + = to the left of the tube "
                 "direction (top & down tube: upward; seat tube: rearward)"),
        _choice(f"{key}_material", f"{name} material", G, name, "frame", (("frame", "Same as frame"),) + MATERIALS),
    ]
_tubes += [
    _mm("ht_od_top", "Head tube OD (top)", G, "Head tube", 36.0, 20, 80, 0.1),
    _mm("ht_od_bottom", "Head tube OD (bottom)", G, "Head tube", 36.0, 20, 80, 0.1,
        help="Make larger than the top OD for a tapered head tube"),
    _mm("ht_wall", "Head tube wall", G, "Head tube", 1.2, 0.3, 10, 0.05),
    _choice("ht_material", "Head tube material", G, "Head tube", "frame", (("frame", "Same as frame"),) + MATERIALS),
    _mm("ht_ext_top", "Head tube extension above top tube", G, "Head tube", 0, 0, 100, help="Informational; included in head tube length"),
    _choice("cs_profile", "Chainstay profile", G, "Chainstays", "round", PROFILES),
    _mm("cs_od_bb", "Chainstay OD at BB", G, "Chainstays", 22.2, 5, 60, 0.1),
    _mm("cs_od_drop", "Chainstay OD at dropout", G, "Chainstays", 16.0, 5, 60, 0.1),
    _mm("cs_wall", "Chainstay wall", G, "Chainstays", 0.7, 0.2, 5, 0.05),
    _mm("cs_bend", "Chainstay bend (sagitta)", G, "Chainstays", 0, -100, 100, 0.5),
    _mm("cs_dropout_length", "Chainstay end to axle", G, "Chainstays", 35, 0, 150, help="Length taken up by the dropout"),
    _choice("cs_material", "Chainstay material", G, "Chainstays", "frame", (("frame", "Same as frame"),) + MATERIALS),
    _choice("ss_profile", "Seat stay profile", G, "Seat stays", "round", PROFILES),
    _mm("ss_od_top", "Seat stay OD at top", G, "Seat stays", 16.0, 5, 60, 0.1),
    _mm("ss_od_drop", "Seat stay OD at dropout", G, "Seat stays", 12.7, 5, 60, 0.1),
    _mm("ss_wall", "Seat stay wall", G, "Seat stays", 0.7, 0.2, 5, 0.05),
    _mm("ss_bend", "Seat stay bend (sagitta)", G, "Seat stays", 0, -100, 100, 0.5),
    _mm("ss_dropout_length", "Seat stay end to axle", G, "Seat stays", 35, 0, 150),
    _choice("ss_material", "Seat stay material", G, "Seat stays", "frame", (("frame", "Same as frame"),) + MATERIALS),
]

G = "Fork & headset"
_fork = [
    _choice("fork_type", "Fork type", G, "Fork", "rigid",
            (("rigid", "Rigid"), ("suspension", "Suspension"))),
    _mm("fork_length", "Fork axle-to-crown", G, "Fork", 395, 250, 650,
        help="Measured parallel to the steering axis from the axle to the crown race seat"),
    _mm("fork_offset", "Fork offset (rake)", G, "Fork", 50, -20, 120),
    _mm("fork_travel", "Suspension travel", G, "Fork", 100, 0, 220, vis=("fork_type", ("suspension",))),
    _num("fork_sag", "Sag", G, "Fork", 0, "%", 0, 50, 1, help="Geometry is solved with the fork compressed by this fraction of travel",
         vis=("fork_type", ("suspension",))),
    _mm("fork_stanchion_od", "Stanchion diameter", G, "Fork", 34, 20, 45, vis=("fork_type", ("suspension",))),
    _mm("fork_crown_height", "Crown height", G, "Fork", 25, 5, 80),
    _mm("fork_crown_width", "Crown width (blade c-c)", G, "Fork", 110, 50, 200),
    _mm("fork_blade_od", "Blade OD", G, "Fork", 28, 10, 60, 0.1),
    _mm("fork_blade_od_tip", "Blade OD at dropout", G, "Fork", 14, 5, 60, 0.1),
    _mm("fork_wall_end", "Blade wall (crown end)", G, "Fork", 1.2, 0.3, 5, 0.05),
    _mm("fork_wall_mid", "Blade wall (tip / thin section)", G, "Fork", 0.9, 0.3, 5, 0.05),
    _mm("fork_butt_length", "Blade butt length", G, "Fork", 120, 0, 400),
    _choice("fork_material", "Fork material", G, "Fork", "frame", (("frame", "Same as frame"),) + MATERIALS),
    _choice("fork_blade_shape", "Blade shape", G, "Fork", "straight",
            (("straight", "Straight (offset at crown)"), ("curved", "Curved (traditional)"))),
    _mm("front_hub_spacing", "Front hub spacing", G, "Fork", 100, 70, 160),
    _mm("lower_stack", "Headset lower stack", G, "Headset", 12, 0, 60,
        help="Height from the head tube bottom face to the crown race seat"),
    _mm("upper_stack", "Headset upper stack", G, "Headset", 8, 0, 60),
    _mm("spacers", "Spacer stack", G, "Headset", 20, 0, 150),
    _mm("steerer_od", "Steerer OD", G, "Headset", 28.6, 20, 40, 0.1),
    _mm("steerer_above_stem", "Steerer above stem", G, "Headset", 3, 0, 60),
]

G = "Cockpit"
_cockpit = [
    _choice("stem_type", "Stem type", G, "Stem", "threadless",
            (("threadless", "Threadless"), ("quill", "Quill"))),
    _mm("stem_length", "Stem length", G, "Stem", 100, 0, 200),
    _deg("stem_angle", "Stem angle", G, "Stem", -6, -60, 60, 1,
         help="Relative to the perpendicular of the steerer (+ = rise)"),
    _mm("stem_clamp_height", "Stem steerer clamp height", G, "Stem", 40, 10, 80),
    _mm("quill_height", "Quill extension", G, "Stem", 60, 0, 250, vis=("stem_type", ("quill",)),
        help="Height of the quill clamp centre above the headset"),
    _choice("bar_type", "Handlebar type", G, "Handlebar", "drop",
            (("drop", "Drop bar"), ("flat", "Flat bar"), ("riser", "Riser bar"), ("bullhorn", "Bullhorn"),
             ("swept", "Swept-back (north road)"))),
    _mm("bar_reach", "Bar reach", G, "Handlebar", 80, 0, 200),
    _mm("bar_drop", "Bar drop", G, "Handlebar", 125, 0, 250, vis=("bar_type", ("drop",))),
    _mm("bar_rise", "Bar rise", G, "Handlebar", 0, -50, 150, vis=("bar_type", ("riser", "flat", "swept", "bullhorn"))),
    _deg("bar_backsweep", "Bar backsweep", G, "Handlebar", 9, 0, 70, 1, vis=("bar_type", ("riser", "flat", "swept"))),
    _mm("bar_width", "Bar width", G, "Handlebar", 420, 300, 900),
    _deg("bar_rotation", "Bar rotation", G, "Handlebar", 0, -45, 45, 0.5),
    _mm("bar_od", "Bar diameter", G, "Handlebar", 31.8, 22, 36, 0.1),
    _choice("lever_type", "Brake lever / shifter", G, "Handlebar", "road_sti",
            (("road_sti", "Road integrated (hoods)"), ("flat", "Flat bar lever"), ("none", "None"))),
    _mm("hood_reach", "Hood reach", G, "Handlebar", 40, 0, 120, vis=("lever_type", ("road_sti",)),
        help="Horizontal distance from the lever clamp on the bend forward to the hand position on the hood"),
    _choice("hand_position", "Hand position (rider)", G, "Handlebar", "hoods",
            (("hoods", "Hoods"), ("drops", "Drops"), ("tops", "Tops"), ("grips", "Grips (flat bars)"))),
]

G = "Saddle & seatpost"
_saddle = [
    _choice("saddle_mode", "Saddle position by", G, "Saddle position", "height_angle",
            (("height_angle", "Saddle height + seat angle"), ("xy", "X / Y from BB"))),
    _mm("saddle_height", "Saddle height", G, "Saddle position", 730, 300, 1200, vis=("saddle_mode", ("height_angle",)),
        help="BB centre to the saddle top at the saddle reference point, along the seat angle"),
    _choice("seat_angle_source", "Seat angle", G, "Saddle position", "seat_tube",
            (("seat_tube", "Same as seat tube"), ("custom", "Custom (effective)")), vis=("saddle_mode", ("height_angle",))),
    _deg("seat_angle_eff", "Effective seat angle", G, "Saddle position", 73.5, 55, 90, vis=("seat_angle_source", ("custom",))),
    _mm("saddle_x", "Saddle X (from BB)", G, "Saddle position", -200, -500, 300, vis=("saddle_mode", ("xy",))),
    _mm("saddle_y", "Saddle Y (from BB)", G, "Saddle position", 700, 200, 1200, vis=("saddle_mode", ("xy",))),
    _mm("saddle_length", "Saddle length", G, "Saddle", 270, 150, 400),
    _mm("saddle_ref_to_nose", "Reference point to nose", G, "Saddle", 140, 0, 400,
        help="Horizontal distance from the saddle reference point (clamp centre) forward to the nose"),
    _mm("saddle_stack", "Saddle stack (rails to top)", G, "Saddle", 45, 10, 120),
    _deg("saddle_tilt", "Saddle tilt", G, "Saddle", 0, -20, 20, 0.5, help="+ = nose up"),
    _mm("seatpost_od", "Seatpost diameter", G, "Seatpost", 27.2, 20, 40, 0.1),
    _mm("seatpost_offset", "Seatpost setback (head offset)", G, "Seatpost", 0, -30, 50, 0.5,
        help="Offset of the post's clamp behind its axis; the remainder is taken up by sliding the saddle rails"),
    _mm("rail_range", "Saddle rail adjustment range (±)", G, "Seatpost", 20, 0, 60),
    _mm("seatpost_length", "Seatpost length", G, "Seatpost", 350, 100, 600),
    _mm("seatpost_min_insertion", "Minimum insertion", G, "Seatpost", 65, 0, 300),
    _choice("seatpost_type", "Seatpost type", G, "Seatpost", "standard",
            (("standard", "Standard"), ("dropper", "Dropper"), ("seatmast", "Integrated seat mast"))),
    _mm("dropper_travel", "Dropper travel", G, "Seatpost", 150, 0, 250, vis=("seatpost_type", ("dropper",))),
    _mm("dropper_drop", "Dropper current drop", G, "Seatpost", 0, 0, 250, vis=("seatpost_type", ("dropper",))),
]

G = "Drivetrain"
_drive = [
    _choice("drive_type", "Drive type", G, "Drive", "derailleur",
            (("derailleur", "Derailleur"), ("singlespeed", "Single speed / fixed"), ("hub_gear", "Internal hub"),
             ("belt", "Belt drive"), ("gearbox", "Gearbox (Pinion style)"))),
    _mm("crank_length", "Crank length", G, "Drive", 172.5, 80, 220, 0.5),
    _list("chainrings", "Chainrings (teeth)", G, "Drive", "50, 34"),
    _list("cogs", "Cassette / cogs (teeth)", G, "Drive", "11, 12, 13, 14, 15, 17, 19, 21, 24, 28, 32"),
    _deg("crank_angle", "Crank angle (display)", G, "Drive", -30, -360, 360, 1,
         help="Angle of the drive-side crank from horizontal-forward"),
    _num("cadence", "Cadence (gearing table)", G, "Drive", 90, "rpm", 10, 200, 1),
    _mm("chainline", "Chainline", G, "Drive", 43.5, 30, 70, 0.5),
    _mm("chain_pitch", "Chain pitch", G, "Drive", 12.7, 5, 20, 0.01),
    _mm("belt_pitch", "Belt pitch", G, "Drive", 11.0, 5, 20, 0.1, vis=("drive_type", ("belt",))),
    _choice("pedal_type", "Pedal type", G, "Drive", "clipless",
            (("clipless", "Clipless"), ("flat", "Flat / platform"), ("none", "None"))),
    _mm("pedal_stack", "Pedal + cleat stack", G, "Drive", 12, 0, 40, help="Pedal axle to shoe sole"),
    _mm("q_factor", "Q factor", G, "Drive", 147, 100, 250),
    _bool("front_derailleur", "Front derailleur", G, "Drive", True),
]

G = "Wheels & brakes"
_wheels = [
    _mm("rim_depth_front", "Front rim depth", G, "Rims", 22, 5, 100),
    _mm("rim_depth_rear", "Rear rim depth", G, "Rims", 22, 5, 100),
    _int("spokes_front", "Front spokes", G, "Spokes", 28, 0, 72),
    _int("spokes_rear", "Rear spokes", G, "Spokes", 32, 0, 72),
    _int("cross_front", "Front lacing cross", G, "Spokes", 2, 0, 4),
    _int("cross_rear", "Rear lacing cross", G, "Spokes", 3, 0, 4),
    _mm("hub_flange_front", "Front hub flange dia.", G, "Spokes", 40, 20, 120),
    _mm("hub_flange_rear", "Rear hub flange dia.", G, "Spokes", 48, 20, 120),
    _choice("brake_front", "Front brake", G, "Brakes", "disc",
            (("disc", "Disc"), ("caliper", "Rim caliper"), ("cantilever", "Cantilever"), ("v", "V-brake"), ("none", "None"))),
    _choice("brake_rear", "Rear brake", G, "Brakes", "disc",
            (("disc", "Disc"), ("caliper", "Rim caliper"), ("cantilever", "Cantilever"), ("v", "V-brake"), ("none", "None"))),
    _mm("rotor_front", "Front rotor", G, "Brakes", 160, 100, 230),
    _mm("rotor_rear", "Rear rotor", G, "Brakes", 160, 100, 230),
    _mm("brake_reach", "Caliper reach (rim brakes)", G, "Brakes", 49, 30, 80,
        help="Mounting bolt to brake track centre; places the brake bridge"),
]

G = "Accessories"
_acc = [
    _bool("bottle_dt", "Down tube bottle", G, "Bottles", True),
    _bool("bottle_st", "Seat tube bottle", G, "Bottles", True),
    _mm("bottle_dt_pos", "Down tube lower boss from BB", G, "Bottles", 190, 40, 600),
    _mm("bottle_st_pos", "Seat tube lower boss from BB", G, "Bottles", 140, 40, 600),
    _mm("boss_spacing", "Boss spacing", G, "Bottles", 64, 30, 130),
    _mm("bottle_diameter", "Bottle diameter", G, "Bottles", 74, 50, 110),
    _mm("bottle_length", "Bottle length", G, "Bottles", 200, 100, 300),
    _bool("fenders", "Fenders", G, "Fenders & racks", False),
    _mm("fender_clearance", "Fender clearance", G, "Fenders & racks", 12, 0, 60),
    _mm("fender_width", "Fender width", G, "Fenders & racks", 45, 20, 100),
    _bool("rack_rear", "Rear rack", G, "Fenders & racks", False),
    _mm("rack_height", "Rear rack height above axle", G, "Fenders & racks", 380, 150, 550),
    _bool("rack_front", "Front rack", G, "Fenders & racks", False),
    _bool("cs_bridge", "Chainstay bridge", G, "Braze-ons", True),
    _mm("cs_bridge_pos", "Chainstay bridge from BB", G, "Braze-ons", 110, 30, 300),
    _bool("ss_bridge", "Seat stay bridge", G, "Braze-ons", True),
    _mm("ss_bridge_pos", "Seat stay bridge from axle", G, "Braze-ons", 0, 0, 600,
        help="0 = place automatically from the brake reach (rim brakes) or at tire clearance"),
    _bool("dt_cable_stops", "Down tube cable stops/bosses", G, "Braze-ons", True),
    _mm("dt_cable_stop_pos", "Cable stops from head tube", G, "Braze-ons", 100, 20, 600),
    _bool("pump_pegs", "Pump peg", G, "Braze-ons", False),
    _choice("seat_clamp", "Seat clamp", G, "Braze-ons", "binder",
            (("binder", "Seat binder bolt / ears"), ("clamp", "Separate collar"), ("wedge", "Internal wedge"))),
    _bool("kickstand_plate", "Kickstand plate", G, "Braze-ons", False),
]

G = "Joints"
_joints = [
    _mm("lug_socket_length", "Lug socket length", G, "Lugs", 32, 5, 100, vis=("joint_style", ("lugged",))),
    _mm("lug_point_length", "Lug point length", G, "Lugs", 18, 0, 80, vis=("joint_style", ("lugged",))),
    _mm("lug_wall", "Lug thickness", G, "Lugs", 1.2, 0.3, 5, 0.1, vis=("joint_style", ("lugged",))),
    _choice("lug_style", "Lug style", G, "Lugs", "pointed",
            (("pointed", "Pointed"), ("long_point", "Long point"), ("rounded", "Rounded"), ("heart", "Heart cut-out")),
            vis=("joint_style", ("lugged",))),
    _deg("lug_ht_angle", "Lugset HT/TT angle", G, "Lugs", 72.0, 50, 90, vis=("joint_style", ("lugged",)),
         help="Angle the lugs are cast at (used to warn when the design needs bending)"),
    _deg("lug_st_angle", "Lugset ST/TT angle", G, "Lugs", 73.0, 50, 90, vis=("joint_style", ("lugged",))),
    _deg("lug_tolerance", "Lug angle tolerance", G, "Lugs", 1.5, 0, 10, vis=("joint_style", ("lugged",))),
    _mm("fillet_radius", "Fillet radius", G, "Fillets", 10, 1, 50, vis=("joint_style", ("fillet",))),
]

G = "Display"
_display = [
    _choice("units", "Units", G, "Units", "mm", (("mm", "Millimetres"), ("in", "Inches"))),
    _choice("display_mode", "Drawing mode", G, "Style", "filled",
            (("filled", "Painted"), ("outline", "Outline"), ("centerline", "Centrelines (stick)"),
             ("blueprint", "Blueprint"))),
    _int("wheel_detail", "Wheel detail", G, "Style", 3, 0, 3, help="0 = circles, 1 = rims & tires, 2 = + hubs, 3 = + spokes"),
    _num("outline_width", "Outline weight", G, "Style", 0.35, "mm", 0.05, 3, 0.05),
    _bool("show_frame", "Frame", G, "Layers", True),
    _bool("show_fork", "Fork", G, "Layers", True),
    _bool("show_wheels", "Wheels", G, "Layers", True),
    _bool("show_drivetrain", "Drivetrain", G, "Layers", True),
    _bool("show_cockpit", "Cockpit (stem & bars)", G, "Layers", True),
    _bool("show_saddle", "Saddle & seatpost", G, "Layers", True),
    _bool("show_brakes", "Brakes", G, "Layers", True),
    _bool("show_accessories", "Accessories", G, "Layers", True),
    _bool("show_rider", "Rider", G, "Layers", False),
    _bool("show_dimensions", "Dimensions", G, "Layers", True),
    _bool("show_centerlines", "Centrelines", G, "Layers", True),
    _bool("show_ground", "Ground line", G, "Layers", True),
    _bool("show_toe_circle", "Toe overlap circle", G, "Layers", False),
    _bool("show_com", "Centre of mass", G, "Layers", False),
    _bool("show_notes", "On-screen notes", G, "Layers", True),
    _bool("show_photo", "Photo underlay", G, "Layers", True),
    _bool("show_grid", "Grid", G, "Layers", False),
    _bool("show_ghost", "Comparison ghosts", G, "Layers", True),
    _bool("show_title_block", "Title block (drawings)", G, "Layers", True),
    _num("dimension_line_weight", "Dimension line weight", G, "Style", 0.25, "mm", 0.05, 2, 0.05),
    _num("dimension_text_size", "Dimension text height", G, "Style", 2.6, "mm", 1.0, 8, 0.1),
    _bool("dimension_text_horizontal", "Keep dimension text horizontal", G, "Style", False),
    _color("color_background", "Background", G, "Colours", "#ffffff"),
    _color("color_outline", "Outline", G, "Colours", "#1a1a1a"),
    _color("color_dimension", "Dimensions", G, "Colours", "#1f5fbf"),
    _color("color_centerline", "Centrelines", G, "Colours", "#c03030"),
    _color("color_components", "Components", G, "Colours", "#4a4a4a"),
    _color("color_tire", "Tires", G, "Colours", "#2b2b2b"),
    _color("color_rider", "Rider", G, "Colours", "#7f9fbf"),
]

G = "Paint"
_paint = [
    _color("paint_frame", "Frame colour", G, "Main colours", "#c8102e"),
    _color("paint_fork", "Fork colour", G, "Main colours", "#c8102e"),
    _color("paint_head_tube", "Head tube colour", G, "Main colours", "#f4f4f4"),
    _color("paint_lugs", "Lug / accent colour", G, "Main colours", "#d4af37"),
    _color("paint_decal", "Decal colour", G, "Decals", "#ffffff"),
    _str("decal_text", "Down tube decal", G, "Decals", "FRAMEWRIGHT"),
    _str("decal_font", "Decal font", G, "Decals", "Sans Serif"),
    _mm("decal_size", "Decal height", G, "Decals", 0, 0, 60, help="0 = automatic (75% of down tube OD)"),
    _bool("decal_italic", "Italic", G, "Decals", True),
    _bool("decal_bold", "Bold", G, "Decals", True),
    _str("ht_badge_text", "Head tube badge", G, "Decals", "FW"),
    _bool("paint_per_tube", "Individual tube colours", G, "Tube colours", False),
    ParamDef("paint_tt", "Top tube", G, "Tube colours", COLOR, "#c8102e", visible_if=("paint_per_tube", (True,)), morph=False),
    ParamDef("paint_dt", "Down tube", G, "Tube colours", COLOR, "#c8102e", visible_if=("paint_per_tube", (True,)), morph=False),
    ParamDef("paint_st", "Seat tube", G, "Tube colours", COLOR, "#c8102e", visible_if=("paint_per_tube", (True,)), morph=False),
    ParamDef("paint_cs", "Chainstays", G, "Tube colours", COLOR, "#c8102e", visible_if=("paint_per_tube", (True,)), morph=False),
    ParamDef("paint_ss", "Seat stays", G, "Tube colours", COLOR, "#c8102e", visible_if=("paint_per_tube", (True,)), morph=False),
    _color("paint_components", "Component finish", G, "Main colours", "#2b2b2b"),
    _choice("fade_style", "Fade", G, "Fades & panels", "none",
            (("none", "None"), ("dt", "Down tube fade"), ("all", "All main tubes"), ("panel", "Down & seat tube panels"))),
    _color("paint_fade_to", "Fade / panel colour", G, "Fades & panels", "#1a1a1a"),
    _num("fade_position", "Fade position", G, "Fades & panels", 50, "%", 0, 100, 1),
]

_meta = [
    _str("title", "Design title", "Project", "Info", "Untitled design"),
    _str("designer", "Designer", "Project", "Info", ""),
    _str("customer", "Customer / rider", "Project", "Info", ""),
    _str("frame_size_label", "Size label", "Project", "Info", ""),
    _str("drawing_number", "Drawing number", "Project", "Info", ""),
    _str("notes_text", "Build notes", "Project", "Info", ""),
]

register(_frame + _tubes + _fork + _cockpit + _saddle + _drive + _wheels + _acc + _joints + _paint + _display + _meta)
