"""Frame, fork and complete-bike weight *estimates*.

Tube masses come from :meth:`Tube.mass` (double-butted, OD and wall from the
design, trimmed roughly for mitres).  Everything else (BB shell, dropouts,
lugs / fillets / welds, braze-ons, paint, components) uses typical values that
the user can override through the "Analysis → Weight" parameters.  Results are
in grams and are estimates only: weigh real parts where it matters.
"""
from __future__ import annotations

import math
from typing import Any

from ..geometry.solver import MATERIAL_DENSITY, Geometry, Tube
from ..model import params as P
from ..model.design import Design

G = "Analysis"
S = "Weight"


def _g(key, label, default, help="", vis=None, section=S):
    return P.ParamDef(key, label, G, section, P.FLOAT, float(default), "g", 0, 20000, 5, help=help,
                      visible_if=vis)


P.register([
    P.ParamDef("bb_shell_wall", "BB shell wall (estimate)", G, S, P.FLOAT, 2.5, "mm", 0.5, 10, 0.1,
               help="Average wall of the bottom-bracket shell, used for weight and stiffness estimates"),
    _g("dropout_mass_rear", "Rear dropouts (pair)", 0, "0 = typical value for the frame material"),
    _g("dropout_mass_front", "Fork dropouts (pair)", 0, "0 = typical value for the frame material"),
    P.ParamDef("paint_areal_mass", "Paint / finish", G, S, P.FLOAT, 150.0, "g/m²", 0, 1000, 10,
               help="Primer + paint + clear per square metre of tube surface"),
    _g("wt_wheelset", "Wheelset (no tyres, cassette or rotors)", 1700),
    _g("wt_tires", "Tyres (pair)", 650),
    _g("wt_tubes", "Inner tubes / sealant (pair)", 200),
    _g("wt_crankset", "Crankset incl. chainrings", 700),
    _g("wt_bottom_bracket", "Bottom bracket bearings", 90),
    _g("wt_cassette", "Cassette", 260),
    _g("wt_sprocket", "Single cog / belt sprocket (rear)", 60),
    _g("wt_chain", "Chain", 250),
    _g("wt_belt", "Belt", 80),
    _g("wt_front_derailleur", "Front derailleur", 95),
    _g("wt_rear_derailleur", "Rear derailleur", 240),
    _g("wt_levers", "Brake / shift levers (pair)", 450),
    _g("wt_brake_disc", "Disc brake caliper + rotor (each)", 280),
    _g("wt_brake_rim", "Rim brake (each)", 160),
    _g("wt_handlebar", "Handlebar", 280),
    _g("wt_stem", "Stem", 130),
    _g("wt_headset", "Headset", 90),
    _g("wt_seatpost", "Seatpost", 240),
    _g("wt_dropper", "Dropper seatpost", 550),
    _g("wt_saddle", "Saddle", 230),
    _g("wt_bar_tape", "Bar tape / grips", 60),
    _g("wt_pedals", "Pedals (pair)", 300),
    _g("wt_cables", "Cables, housing, hoses", 150),
    _g("wt_bottle_cage", "Bottle cage (each)", 35),
    _g("wt_fenders", "Fenders (pair)", 550),
    _g("wt_rack_rear", "Rear rack", 700),
    _g("wt_rack_front", "Front rack", 500),
    _g("wt_internal_hub", "Internal hub (extra over a plain hub)", 1300),
    _g("wt_gearbox", "Gearbox unit", 2200),
    _g("wt_suspension_fork", "Suspension fork (complete)", 1700),
    _g("wt_other", "Other parts / accessories", 0),
])

# Typical dropout pair masses (g) by material, rear / front.
_DROPOUT_REAR = {"steel": 100, "stainless": 100, "titanium": 60, "aluminium": 60, "aluminium7005": 60,
                 "scandium": 60, "carbon": 70, "bamboo": 100, "wood": 100}
_DROPOUT_FRONT = {"steel": 50, "stainless": 50, "titanium": 30, "aluminium": 35, "aluminium7005": 35,
                  "scandium": 35, "carbon": 30, "bamboo": 50, "wood": 50}
# Walls of non-steel parts are usually thicker; scale factor for crowns / small parts.
_THICKNESS = {"steel": 1.0, "stainless": 1.0, "titanium": 1.3, "aluminium": 1.8, "aluminium7005": 1.8,
              "scandium": 1.8, "carbon": 1.8, "bamboo": 3.0, "wood": 3.0}
_STEERER_WALL = {"steel": 1.6, "stainless": 1.6, "titanium": 1.6, "aluminium": 2.2, "aluminium7005": 2.2,
                 "scandium": 2.2, "carbon": 2.6, "bamboo": 1.6, "wood": 1.6}
BRASS_DENSITY = 8.5e-3        # g/mm^3, fillet-brazing rod
STEEL = MATERIAL_DENSITY["steel"]

NOTE = "Estimate from tube dimensions and typical part masses; weigh real parts where it matters"


def _rho(material: str) -> float:
    return MATERIAL_DENSITY.get(material, STEEL)


def _frame_material(d: Design) -> str:
    return str(d["frame_material"])


def _od(t: Tube) -> float:
    return (t.od_a + t.od_b + t.w_a + t.w_b) / 4.0


def _receiving_od(g: Geometry, join: str | None) -> float:
    """OD of whatever a tube end is mitred into (for trimming c-c lengths)."""
    d = g.design
    if join == "bb":
        return d.f("bb_shell_od")
    if join in g.tubes:
        t = g.tubes[join]
        return _od(t)
    return 0.0


def _trimmed_length(g: Geometry, t: Tube) -> float:
    """Approximate cut length: c-c length less half the receiving tube at each end,
    and less the dropout for stays."""
    d = g.design
    L = t.length
    trim = 0.0
    for end, join in (("a", t.join_a), ("b", t.join_b)):
        if join == "dropout":
            trim += d.f("cs_dropout_length") if t.name == "cs" else d.f("ss_dropout_length")
        elif join:
            trim += _receiving_od(g, join) / 2.0
    if t.name == "ht" or t.kind == "fork":
        trim = 0.0
    return max(L - trim, 0.25 * L)


def _surface(t: Tube, length: float) -> float:
    n = 2 if t.mirrored else 1
    return math.pi * _od(t) * length * n


def _joints(g: Geometry) -> list[tuple[str, float]]:
    """(joint label, OD of the tube that is joined) for every frame joint."""
    out = []
    for name, t in g.tubes.items():
        if t.kind == "fork":
            continue
        n = 2 if t.mirrored else 1
        for join, od in ((t.join_a, t.od_a), (t.join_b, t.od_b)):
            if join and join != "dropout":
                out += [(f"{t.label} / {join}", od)] * n
    return out


def frame_weight(g: Geometry) -> dict[str, Any]:
    """Estimated frame and fork masses (grams).

    Returns ``{"frame_items": {label: g}, "fork_items": {label: g}, "frame": g,
    "fork": g, "frame_and_fork": g, "tubes": {tube name: g}, "estimate": True,
    "notes": [...]}``.  Mirrored tubes (stays, fork blades) count both sides.
    """
    d = g.design
    mat = _frame_material(d)
    rho = _rho(mat)
    thick = _THICKNESS.get(mat, 1.0)
    frame: dict[str, float] = {}
    fork: dict[str, float] = {}
    tubes: dict[str, float] = {}
    paint_area = 0.0
    fork_area = 0.0
    notes = [NOTE]

    # -- tubes ----------------------------------------------------------------
    for name, t in g.tubes.items():
        L = _trimmed_length(g, t)
        m = t.mass(L)
        tubes[name] = m
        label = t.label + (" (pair)" if t.mirrored else "")
        if t.kind == "fork":
            if d["fork_type"] != "suspension":
                fork[label] = m
                fork_area += _surface(t, L)
        else:
            frame[label] = frame.get(label, 0.0) + m
            paint_area += _surface(t, L)

    # -- bottom-bracket shell ---------------------------------------------------
    od, w = d.f("bb_shell_od"), d.f("bb_shell_width")
    wall = min(d.f("bb_shell_wall"), od / 2)
    shell = math.pi * (od * wall - wall * wall) * w * rho * 0.85      # ~15 % for tube openings
    frame["BB shell"] = shell
    paint_area += math.pi * od * w

    # -- dropouts -------------------------------------------------------------
    rear_do = d.f("dropout_mass_rear") or _DROPOUT_REAR.get(mat, 100)
    frame["Rear dropouts (pair)"] = rear_do

    # -- joints -----------------------------------------------------------------
    js = d["joint_style"]
    joints = _joints(g)
    if js == "lugged":
        sock = d.f("lug_socket_length") + 0.5 * d.f("lug_point_length")
        lw = d.f("lug_wall")
        lug_rho = rho if mat in ("steel", "stainless", "titanium", "aluminium", "aluminium7005",
                                 "scandium") else _rho("aluminium")
        total = 0.0
        for _label, jod in joints:
            total += math.pi * (jod + lw) * lw * sock * lug_rho
        # head lugs and seat lug also sleeve the receiving tube
        ht = g.tubes.get("ht")
        if ht is not None:
            total += 2 * math.pi * (_od(ht) + lw) * lw * d.f("lug_socket_length") * lug_rho
        st = g.tubes.get("st")
        if st is not None and "tt" in g.tubes:
            total += math.pi * (_od(st) + lw) * lw * d.f("lug_socket_length") * lug_rho
        frame["Lugs"] = total
        if mat not in ("steel", "stainless", "titanium", "aluminium", "aluminium7005", "scandium"):
            notes.append("Lugs estimated as aluminium")
    elif js == "fillet":
        r = d.f("fillet_radius")
        area = (1 - math.pi / 4) * r * r            # concave fillet cross-section
        frame["Brass fillets"] = sum(area * math.pi * jod * 1.1 * BRASS_DENSITY for _l, jod in joints)
    elif js == "bonded":
        frame["Adhesive / joint wraps"] = 6.0 * len(joints)
    else:
        frame["Weld filler"] = 2.5 * len(joints)

    # -- braze-ons and fittings (typical, steel-ish values) ---------------------------
    b = 0.0
    nb = (2 if d["bottle_dt"] else 0) + (2 if d["bottle_st"] else 0)
    b += 3.0 * nb
    if d["dt_cable_stops"]:
        b += 10.0
    if d["drive_type"] == "derailleur":
        b += 20.0                                    # hanger / derailleur mount
        if d["front_derailleur"]:
            b += 10.0                                # braze-on / band mount
    if d["cs_bridge"]:
        b += 15.0 * thick * rho / STEEL
    if d["ss_bridge"] and "ss" in g.tubes:
        b += 20.0 * thick * rho / STEEL
    if d["pump_pegs"]:
        b += 4.0
    if d["kickstand_plate"]:
        b += 25.0
    b += {"binder": 15.0, "clamp": 0.0, "wedge": 25.0}.get(d["seat_clamp"], 15.0)
    rb = d["brake_rear"]
    b += {"disc": 35.0, "cantilever": 16.0, "v": 16.0}.get(rb, 0.0)
    if d["fenders"] or d["rack_rear"]:
        b += 12.0
    frame["Braze-ons & fittings"] = b

    # -- paint --------------------------------------------------------------------
    areal = d.f("paint_areal_mass") * 1e-6         # g/mm^2
    frame["Paint"] = paint_area * areal

    # -- fork ---------------------------------------------------------------------
    if d["fork_type"] == "suspension":
        fork["Suspension fork"] = d.f("wt_suspension_fork")
    else:
        bod = d.f("fork_blade_od")
        crown = (d.f("fork_crown_width") + bod) * bod * d.f("fork_crown_height") * 0.15 * rho * thick
        fork["Crown"] = crown
        sw = min(_STEERER_WALL.get(mat, 1.6), d.f("steerer_od") / 2)
        sod = d.f("steerer_od")
        steer_len = g.v.get("steerer_length", 0.0)
        fork["Steerer"] = math.pi * (sod * sw - sw * sw) * steer_len * rho
        fork["Fork dropouts (pair)"] = d.f("dropout_mass_front") or _DROPOUT_FRONT.get(mat, 50)
        fork["Brake mount"] = {"disc": 25.0, "cantilever": 16.0, "v": 16.0}.get(d["brake_front"], 0.0)
        fork_area += math.pi * sod * d.f("fork_crown_height") * 2
        fork["Paint"] = fork_area * areal
    f_total = sum(frame.values())
    k_total = sum(fork.values())
    return {"frame_items": frame, "fork_items": fork, "frame": f_total, "fork": k_total,
            "frame_and_fork": f_total + k_total, "tubes": tubes, "estimate": True, "notes": notes}


def bike_weight(g: Geometry) -> dict[str, Any]:
    """Estimated complete-bike mass (grams): frame + fork + components.

    Component masses come from the ``wt_*`` parameters and are included only
    when the design uses them (derailleurs, brakes by type, fenders...).
    Returns ``{"frame", "fork", "components": {label: g}, "total", "estimate",
    "notes"}``.
    """
    d = g.design
    fw = frame_weight(g)
    c: dict[str, float] = {}

    def add(label: str, key: str, n: float = 1.0):
        v = d.f(key) * n
        if v:
            c[label] = c.get(label, 0.0) + v

    add("Wheelset", "wt_wheelset")
    add("Tyres", "wt_tires")
    add("Tubes / sealant", "wt_tubes")
    add("Crankset", "wt_crankset")
    add("Bottom bracket", "wt_bottom_bracket")
    drive = d["drive_type"]
    belt = drive == "belt" or (drive in ("hub_gear", "gearbox") and d.get("hub_belt", False))
    if drive == "derailleur":
        add("Cassette", "wt_cassette")
        add("Rear derailleur", "wt_rear_derailleur")
        if d["front_derailleur"] and len(d.lst("chainrings")) > 1:
            add("Front derailleur", "wt_front_derailleur")
    else:
        add("Rear sprocket", "wt_sprocket")
    add("Belt" if belt else "Chain", "wt_belt" if belt else "wt_chain")
    if drive == "hub_gear":
        add("Internal hub (extra)", "wt_internal_hub")
    elif drive == "gearbox":
        add("Gearbox", "wt_gearbox")
    if d["lever_type"] != "none":
        add("Levers / shifters", "wt_levers")
    for end in ("brake_front", "brake_rear"):
        bt = d[end]
        if bt == "disc":
            add("Brakes", "wt_brake_disc")
        elif bt != "none":
            add("Brakes", "wt_brake_rim")
    add("Handlebar", "wt_handlebar")
    add("Stem", "wt_stem")
    add("Headset", "wt_headset")
    if d["seatpost_type"] == "dropper":
        add("Seatpost (dropper)", "wt_dropper")
    elif d["seatpost_type"] != "seatmast":
        add("Seatpost", "wt_seatpost")
    add("Saddle", "wt_saddle")
    add("Bar tape / grips", "wt_bar_tape")
    if d["pedal_type"] != "none":
        add("Pedals", "wt_pedals")
    add("Cables / hoses", "wt_cables")
    nc = (1 if d["bottle_dt"] else 0) + (1 if d["bottle_st"] else 0)
    if nc:
        add("Bottle cages", "wt_bottle_cage", nc)
    if d["fenders"]:
        add("Fenders", "wt_fenders")
    if d["rack_rear"]:
        add("Rear rack", "wt_rack_rear")
    if d["rack_front"]:
        add("Front rack", "wt_rack_front")
    add("Other", "wt_other")
    comp = sum(c.values())
    total = fw["frame"] + fw["fork"] + comp
    return {"frame": fw["frame"], "fork": fw["fork"], "frame_detail": fw, "components": c,
            "components_total": comp, "total": total, "estimate": True,
            "notes": [NOTE, "Component masses are typical defaults (Analysis → Weight)"]}
