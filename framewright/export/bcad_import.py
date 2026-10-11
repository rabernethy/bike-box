"""BikeCAD ``.bcad`` import.

``.bcad`` files are Java ``Properties`` XML (``<properties><entry key=...>``)
with several thousand entries, most of them display settings.  This module maps
the design-defining entries onto FrameWright parameters.

The key meanings were established from public BikeCAD-saved designs and
checked numerically (e.g. stack recomputed from head tube length, head angle,
fork axle-to-crown/offset, lower stack, wheel size and BB drop reproduces the
stored "Stack" exactly; a design saved in stack-and-reach mode stores the reach
that the same design yields in front-centre mode).  Mappings that could not be
verified are applied on a best-effort basis and listed in the import report
stored in ``design.extras["bcad_import"]``.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..geometry.vec import V, cosd, sind
from ..model.design import Design


class BcadImportError(ValueError):
    pass


def read_properties(path: str | Path) -> dict[str, str]:
    """Parse a Java properties XML file into a dict (safe XML parser)."""
    try:
        from defusedxml import ElementTree as ET
    except ImportError as exc:                     # pragma: no cover
        raise BcadImportError("defusedxml is required to read .bcad files") from exc
    try:
        root = ET.parse(str(path)).getroot()
    except Exception as exc:
        raise BcadImportError(f"not a readable BikeCAD file: {exc}") from exc
    if root.tag != "properties":
        raise BcadImportError("not a BikeCAD file (expected a Java properties XML document)")
    return {e.get("key"): (e.text or "") for e in root.iter("entry") if e.get("key")}


def argb_to_hex(value: str | int | float) -> str | None:
    """BikeCAD stores colours as signed 32-bit ARGB integers."""
    try:
        v = int(float(value)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None
    return f"#{(v >> 16) & 0xFF:02x}{(v >> 8) & 0xFF:02x}{v & 0xFF:02x}"


class _Props:
    def __init__(self, props: dict[str, str]):
        self.p = props
        self.used: set[str] = set()

    def f(self, key: str, default: float | None = None) -> float | None:
        raw = self.p.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            v = float(raw)
        except ValueError:
            return default
        if math.isnan(v) or math.isinf(v):
            return default
        self.used.add(key)
        return v

    def i(self, key: str, default: int = 0) -> int:
        v = self.f(key)
        return default if v is None else int(round(v))

    def s(self, key: str, default: str = "") -> str:
        if key in self.p:
            self.used.add(key)
            return str(self.p[key])
        return default

    def b(self, key: str, default: bool = False) -> bool:
        if key not in self.p:
            return default
        self.used.add(key)
        return str(self.p[key]).strip().lower() == "true"

    def colour(self, prefix: str) -> str | None:
        if f"{prefix} color sRGB" in self.p:
            return argb_to_hex(self.s(f"{prefix} color sRGB"))
        r, g, b = (self.f(f"{prefix} color {c}") for c in ("RED", "GREEN", "BLUE"))
        if None not in (r, g, b):
            return f"#{int(r) & 255:02x}{int(g) & 255:02x}{int(b) & 255:02x}"
        return None


def _set(values: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        values[key] = value


def bcad_to_values(props: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Map BikeCAD properties to FrameWright parameter values.
    Returns (values, notes)."""
    P = _Props(props)
    v: dict[str, Any] = {}
    notes: list[str] = []

    # -- wheels -----------------------------------------------------------------
    for end in ("rear", "front"):
        bsd = P.f(f"BSD {end}")
        dia = P.f(f"Wheel diameter {end}")
        width = P.f(f"Wheel width {end}")
        erd = P.f(f"ERD {end}")
        _set(v, f"{end}_bsd", bsd)
        if bsd is not None and dia is not None:
            v[f"{end}_tire_height"] = round((dia - bsd) / 2, 2)
        _set(v, f"{end}_tire_width", width)
        if bsd is not None and erd is not None:
            v[f"rim_depth_{end}"] = round(max((bsd - erd) / 2 + 3.0, 5.0), 1)

    # -- bottom bracket & rear ------------------------------------------------------
    bb_style = P.i("BB measure style", 0)
    bbt = P.f("BB textfield")
    if bbt is not None:
        if bb_style == 1:
            v.update(bb_mode="height", bb_height=bbt)
        else:
            v.update(bb_mode="drop", bb_drop=bbt)
    _set(v, "bb_shell_od", P.f("BB diameter"))
    _set(v, "bb_shell_width", P.f("BB length"))
    cs_style = P.i("CS measure style", 0)
    cst = P.f("CS textfield")
    if cst is not None:
        v.update(cs_mode="length", chainstay_length=cst)
        if cs_style != 0:
            notes.append(f"Rear end was measured with CS style {cs_style}; imported as chainstay length — verify")
    _set(v, "rear_hub_spacing", P.f("Dropout spacing"))

    # -- seat tube --------------------------------------------------------------------
    sta = P.f("Seat angle")
    _set(v, "seat_tube_angle", sta)
    st_len = P.f("Seat tube length")
    ext2 = P.f("Seat tube extension2")            # seat tube top above the top tube centre-line
    st_style = P.i("ST measure style", 0)
    if st_len is not None:
        if st_style == 1:                          # centre to top
            v.update(st_length_mode="ct", seat_tube_length=st_len, tt_mode="st_extension")
        else:                                      # centre to top tube centre-line
            v.update(st_length_mode="cc", seat_tube_length=st_len)
        if ext2 is not None:
            v["st_extension"] = ext2

    # -- head tube, headset, fork ---------------------------------------------------------
    hta = P.f("Head angle")
    _set(v, "head_tube_angle", hta)
    htl = P.f("Head tube length textfield")
    ht_type = P.i("Head tube type", 0)
    if ht_type == 1 and P.f("Head tube d") is not None:
        v["ht_od_top"], v["ht_od_bottom"] = P.f("Head tube d"), P.f("Head tube D", P.f("Head tube d"))
    elif P.f("Head tube diameter") is not None:
        v["ht_od_top"] = v["ht_od_bottom"] = P.f("Head tube diameter")
    # junctions as centre-line offsets (BikeCAD's derived values)
    v["ht_junction_mode"] = "centerline"
    _set(v, "tt_ht_offset", P.f("Head tube upper extension2"))
    _set(v, "dt_ht_offset", P.f("Head tube lower extension2"))
    ft = P.i("Fork type", 0)
    ac, off = P.f(f"FORK{ft}L"), P.f(f"FORK{ft}R")
    _set(v, "fork_length", ac)
    _set(v, "fork_offset", off)
    if ft == 1:
        v["fork_type"] = "suspension"
        travel = P.f("Fork travel")
        _set(v, "fork_travel", travel)
        sag = P.f("Fork sag")
        if travel and sag is not None:
            v["fork_sag"] = round(max(0.0, min(50.0, sag / travel * 100.0)), 1)
            notes.append("Fork sag read as millimetres and converted to % of travel — verify")
    else:
        v["fork_type"] = "rigid"
    _set(v, "lower_stack", P.f("Lower stack height"))
    _set(v, "upper_stack", P.f("Upper stack height"))
    _set(v, "spacers", P.f("Headset spacers"))

    # -- front end ----------------------------------------------------------------------------
    fe = P.i("Top tube front center measure style", 1)
    fcd = P.f("FCD textfield")
    if fe == 1:
        v.update(front_v_mode="ht_length", front_h_mode="front_center")
        _set(v, "head_tube_length", htl)
        _set(v, "front_center", fcd)
    elif fe == 3:
        v.update(front_v_mode="stack", front_h_mode="reach")
        _set(v, "stack", P.f("Stack"))
        _set(v, "reach", fcd)
    elif fe == 0:
        # effective top tube (at the TT/HT junction) + top tube angle: resolved after the
        # seat tube is known (see _ett_front_end); placeholders here
        v.update(front_v_mode="ht_length", front_h_mode="front_center")
        _set(v, "head_tube_length", htl)
        v["__ett"] = (fcd, P.f("Top tube angle textfield"))
        notes.append("Front end was driven by effective top tube + top tube angle; imported as stack and reach "
                     "(head tube length may differ from BikeCAD's by a few mm) — verify")
    elif fe == 2:
        v.update(front_v_mode="bar_y", front_h_mode="bar_x")
        _set(v, "bar_x", fcd)
        _set(v, "bar_y", P.f("Handlebar Y textfield"))
        notes.append("Front end was driven by handlebar X/Y; BikeCAD's handlebar reference point may differ "
                     "from FrameWright's (bar clamp centre) — verify stack and reach")
    else:
        v.update(front_v_mode="ht_length", front_h_mode="front_center")
        _set(v, "head_tube_length", htl)
        notes.append(f"Front-end method {fe} (saddle/hand distance methods) is not supported; imported from head "
                     "tube length and the stored front-end value — verify front centre / reach")
        if fcd is not None and 400 < fcd < 1000:
            v["front_center"] = fcd

    # -- top & down tube, stays ------------------------------------------------------------
    def tube(prefix: str, front: str, rear: str, front2: str | None = None, wall: str | None = None):
        od_f, od_r = P.f(front), P.f(rear)
        if od_f is not None:
            v[f"{prefix}_od"] = od_f
            v[f"{prefix}_od_end"] = od_r if od_r is not None and abs(od_r - od_f) > 0.05 else 0.0
            w = P.f(front2) if front2 else None
            if w is not None and abs(w - od_f) > 0.05:
                v[f"{prefix}_profile"], v[f"{prefix}_od2"] = "oval", w
            else:
                v[f"{prefix}_profile"] = "round"
        t = P.f(wall) if wall else None
        if t:
            v[f"{prefix}_wall_end"] = v[f"{prefix}_wall_mid"] = t
    tube("tt", "Top tube front diameter", "Top tube rear diameter", "Top tube front dia2", "Wall thickness Top tube")
    tube("dt", "Down tube front diameter", "Down tube rear diameter", "Down tube front dia2",
         "Wall thickness Down tube")
    st_od = P.f("Seat tube diameter")
    if st_od is not None:
        v["st_od"] = st_od
        bot = P.f("Seat tube bottom diameter textfield")
        v["st_od_end"] = bot if bot is not None and abs(bot - st_od) > 0.05 else 0.0
    t = P.f("Wall thickness Seat tube")
    if t:
        v["st_wall_end"] = v["st_wall_mid"] = t
    _set(v, "cs_od_bb", P.f("Chain stay vertical diameter"))
    _set(v, "cs_width_bb", P.f("Chain stay horizontal diameter"))
    _set(v, "cs_od_drop", P.f("Chain stay back diameter"))
    _set(v, "cs_wall", P.f("Wall thickness Chain stay") or None)
    _set(v, "ss_od_drop", P.f("Seat stay bottom diameter"))
    _set(v, "ss_od_top", P.f("SEATSTAY_HR"))
    _set(v, "ss_wall", P.f("Wall thickness Seat stay") or None)
    _set(v, "ss_offset", P.f("Seat stay junction0"))
    if P.i("Seat stay mount location", 0) != 0:
        notes.append("Seat stays were mounted somewhere other than the seat tube; imported on the seat tube")
    mat = P.s("MATERIAL").strip().lower()
    mat = {"aluminum": "aluminium", "steel": "steel", "aluminium": "aluminium", "titanium": "titanium",
           "carbon": "carbon", "stainless": "stainless"}.get(mat)
    _set(v, "frame_material", mat)

    # -- saddle & seatpost ---------------------------------------------------------------
    if P.i("SADDLEPOSITIONMEASURESTYLE", 0) != 0:
        notes.append("Saddle position used X/Y measurement in BikeCAD; imported from saddle height and seat angle")
    if P.f("Saddle height") is not None:
        v.update(saddle_mode="height_angle", seat_angle_source="seat_tube", saddle_height=P.f("Saddle height"))
    _set(v, "saddle_length", P.f("Saddle length"))
    _set(v, "saddle_stack", P.f("Saddle thickness"))
    _set(v, "saddle_ref_to_nose", P.f("SADDLETIPtoMIDDLE"))
    _set(v, "saddle_tilt", P.f("Saddle angle"))
    _set(v, "seatpost_od", P.f("Seatpost diameter"))
    _set(v, "seatpost_offset", P.f("Seatpost setback"))
    _set(v, "seatpost_length", P.f("Seatpost LENGTH"))

    # -- cockpit -------------------------------------------------------------------------
    _set(v, "stem_length", P.f("Stem length"))
    _set(v, "stem_angle", P.f("Stem angle"))
    hs = P.i("Handlebar style", 0)
    if hs == 0:
        v["bar_type"] = "drop"
        _set(v, "bar_reach", P.f("Road bar reach"))
        _set(v, "bar_drop", P.f("Road bar drop"))
    elif hs == 2:
        v["bar_type"] = "bullhorn"
        _set(v, "bar_reach", P.f("Bullhorn reach"))
        _set(v, "bar_rise", P.f("Bullhorn rise"))
        v["lever_type"] = "none"
    else:
        v["bar_type"] = "flat"
        v["lever_type"] = "flat"
        v["hand_position"] = "grips"
    _set(v, "bar_width", P.f("Handlebar width"))

    # -- drivetrain ----------------------------------------------------------------------
    _set(v, "crank_length", P.f("Crank length"))
    nr = max(P.i("Number of chainrings", 1), 1)
    rings = [P.f(f"Teeth on chainring {k}") for k in range(nr)]
    rings = [int(r) for r in rings if r]
    nc = P.i("Number of cogs", 0)
    cogs = sorted({int(c) for c in (P.f(f"Teeth on cog {k}") for k in range(max(nc, 1))) if c})
    if rings:
        v["chainrings"] = ", ".join(str(r) for r in rings)
    if cogs:
        v["cogs"] = ", ".join(str(c) for c in cogs)
    if P.i("BELTorCHAIN", 1) == 0:
        v["drive_type"] = "belt"
    elif len(cogs) <= 1 and len(rings) <= 1:
        v["drive_type"] = "singlespeed"
    else:
        v["drive_type"] = "derailleur"
        v["front_derailleur"] = len(rings) > 1

    # -- paint & accessories ----------------------------------------------------------------
    c = P.colour("FIRST")
    if c:
        v["paint_frame"] = v["paint_fork"] = c
    c2 = P.colour("SECOND")
    if c2:
        v["paint_head_tube"] = c2
    front_f, rear_f = P.b("Front Fender include"), P.b("Rear Fender include")
    v["fenders"] = front_f or rear_f
    _set(v, "fender_clearance", P.f("Fender clearance"))
    show_bottles = P.b("Display WATERBOTTLES", False)
    v["bottle_dt"] = show_bottles and P.b("bottle DOWNTUBE0 show", True)
    v["bottle_st"] = show_bottles and P.b("bottle SEATTUBE0 show", True)
    name = P.s("MODEL_NAME").strip()
    if name:
        v["title"] = name
    return v, notes


def _resolve_ett_front_end(d: Design, ett_at_junction: float, tt_angle: float | None) -> None:
    """BikeCAD 'effective top tube + top tube angle': the head tube sits where
    the top tube, leaving the seat tube at ``tt_angle``, reaches a horizontal
    distance ``ett`` from the seat tube axis.  Converted to stack & reach."""
    from ..geometry.solver import solve
    g = solve(d)
    J_st, s = g.p["tt_st"], g.s
    a = tt_angle if tt_angle is not None else g.v["top_tube_angle"]
    dirn = V(cosd(a), sind(a))
    sta = d.f("seat_tube_angle")
    P0 = g.p["st_bottom"]

    def x_st(y):
        return P0.x - (y - P0.y) * cosd(sta) / sind(sta)
    # J = J_st + t*dirn with J.x - x_st(J.y) = ett  (linear in t)
    k = dirn.x + dirn.y * cosd(sta) / sind(sta)
    t = (ett_at_junction - (J_st.x - x_st(J_st.y))) / k
    J_ht = J_st + dirn * t
    T = J_ht + g.u * d.f("tt_ht_offset")
    d.update({"front_v_mode": "stack", "front_h_mode": "reach", "stack": T.y, "reach": T.x})


def load_bcad(path: str | Path) -> Design:
    path = Path(path)
    props = read_properties(path)
    if len(props) < 20 or "Head angle" not in props:
        raise BcadImportError(f"{path.name} does not look like a BikeCAD design ({len(props)} entries)")
    values, notes = bcad_to_values(props)
    ett = values.pop("__ett", None)
    d = Design()
    d.update(values)
    if ett is not None and ett[0] is not None:
        _resolve_ett_front_end(d, ett[0], ett[1])
    if not values.get("title"):
        d.set("title", path.stem)
    from ..geometry.solver import solve
    g = solve(d)
    # self-check: lengths BikeCAD stored that we can recompute
    checks = {}
    htl = props.get("Head tube length textfield")
    if htl and d["front_v_mode"] != "ht_length":
        try:
            checks["head_tube_length"] = (float(htl), g.v["head_tube_length"])
        except ValueError:
            pass
    d.extras["bcad_import"] = {"source": path.name, "entries": len(props), "mapped": len(values),
                               "notes": notes,
                               "checks": {k: {"bikecad": a, "framewright": round(b, 2)} for k, (a, b) in checks.items()}}
    for k, (a, b) in checks.items():
        if abs(a - b) > 1.0:
            notes.append(f"Check: {k} is {b:.1f} here vs {a:.1f} in BikeCAD")
    return d
