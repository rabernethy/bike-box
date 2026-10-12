"""Frame geometry solver.

``solve(design)`` turns parameter values into named points, tube centrelines
and derived measurements.  It is pure Python, has no Qt dependency and runs in
well under a millisecond, so the GUI re-solves on every edit.

Coordinate system: origin at the BB centre, +X forward, +Y up, +Z drive side.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..model import params as P
from ..model.design import Design
from .vec import (V, V3, arc_through, cosd, line_intersect, point_line_distance,
                  polyline_length, polyline_point_at, project_on_line, sind, tand)

# analysis settings that the solver itself needs
P.register([
    P.ParamDef("standover_at", "Standover measured at", "Analysis", "Standover", P.CHOICE, "tt_mid",
               choices=(("tt_mid", "Top tube midpoint"), ("custom", "Distance from BB"), ("bb", "Over the BB")),
               morph=False),
    P.ParamDef("standover_x", "Standover point forward of BB", "Analysis", "Standover", P.FLOAT, 150.0, "mm",
               -300, 600, 1, visible_if=("standover_at", ("custom",))),
    P.ParamDef("toe_overhang", "Toe ahead of pedal spindle", "Analysis", "Toe overlap", P.FLOAT, 95.0, "mm",
               0, 250, 1, help="Distance from the pedal axle forward to the shoe toe (≈ 85-115 mm)"),
    P.ParamDef("toe_clearance_min", "Minimum toe clearance", "Analysis", "Toe overlap", P.FLOAT, 0.0, "mm",
               -100, 200, 1, help="Warning threshold; set to the value your target standard requires"),
    P.ParamDef("pedal_width", "Pedal body half-width outboard of spindle end", "Analysis", "Lean angle",
               P.FLOAT, 45.0, "mm", 0, 120, 1),
    P.ParamDef("pedal_thickness", "Pedal body thickness", "Analysis", "Lean angle", P.FLOAT, 18.0, "mm", 0, 60, 1),
    P.ParamDef("remove_tubes", "Remove tubes", "Frame", "Advanced", P.STR, "",
               help="Comma-separated tube names to omit: tt, dt, st, ss, cs (e.g. 'tt' for a step-through)",
               morph=False),
])

MATERIAL_DENSITY = {          # g / mm^3
    "steel": 7.85e-3, "stainless": 7.95e-3, "titanium": 4.48e-3, "aluminium": 2.70e-3,
    "aluminium7005": 2.78e-3, "carbon": 1.55e-3, "scandium": 2.75e-3, "bamboo": 0.70e-3, "wood": 0.60e-3,
}
MATERIAL_YOUNG = {            # MPa
    "steel": 205e3, "stainless": 193e3, "titanium": 100e3, "aluminium": 69e3, "aluminium7005": 72e3,
    "carbon": 70e3, "scandium": 70e3, "bamboo": 18e3, "wood": 12e3,
}


@dataclass
class Wheel:
    center: V
    bsd: float
    tire_w: float
    tire_h: float
    rim_depth: float
    hub_spacing: float

    @property
    def outer_r(self) -> float:
        return self.bsd / 2 + self.tire_h

    @property
    def rim_r(self) -> float:
        """Radius of the rim's outer edge (slightly above the bead seat)."""
        return self.bsd / 2 + 3.0

    @property
    def rim_inner_r(self) -> float:
        return self.bsd / 2 - self.rim_depth + 3.0

    @property
    def diameter(self) -> float:
        return 2 * self.outer_r


@dataclass
class Tube:
    """A tube centreline with section data.

    ``a``/``b`` are the centre-line end points in side view (centre-to-centre at
    joints).  ``za``/``zb`` are the lateral offsets of the centreline at each
    end (stays come in mirrored pairs, ``mirrored=True`` means a copy exists at
    ``-z``).  ``od_*`` is the side-view depth, ``w_*`` the top-view width.
    """
    name: str
    label: str
    a: V
    b: V
    od_a: float
    od_b: float
    w_a: float = 0.0
    w_b: float = 0.0
    wall_end: float = 1.0
    wall_mid: float = 1.0
    butt_length: float = 0.0
    bend: float = 0.0
    profile: str = "round"
    material: str = "steel"
    za: float = 0.0
    zb: float = 0.0
    mirrored: bool = False
    join_a: str | None = None
    join_b: str | None = None
    kind: str = "main"          # main | stay | fork | extra
    draw_a: V | None = None     # visible end points (dropout ends etc.)
    draw_b: V | None = None
    _pts: list[V] | None = field(default=None, repr=False)

    def __post_init__(self):
        if not self.w_a:
            self.w_a = self.od_a
        if not self.w_b:
            self.w_b = self.od_b

    def points(self, segments: int = 24) -> list[V]:
        """Centre-line polyline from a to b (an arc when the tube is bent)."""
        if self._pts is None or len(self._pts) != (segments + 1 if self.bend else 2):
            self._pts = arc_through(self.a, self.b, self.bend, segments) if abs(self.bend) > 1e-6 else [self.a, self.b]
        return self._pts

    def draw_points(self, segments: int = 24) -> list[V]:
        """Visible portion (trimmed at dropouts etc.)."""
        pts = self.points(segments)
        L = polyline_length(pts)
        s0 = 0.0 if self.draw_a is None else max(0.0, project_on_line(self.draw_a, self.a, self.b - self.a))
        s1 = L if self.draw_b is None else min(L, project_on_line(self.draw_b, self.a, self.b - self.a))
        if s0 <= 1e-9 and s1 >= L - 1e-9:
            return pts
        out = [polyline_point_at(pts, s0)[0]]
        acc = 0.0
        for i in range(len(pts) - 1):
            acc += pts[i].dist(pts[i + 1])
            if s0 < acc < s1:
                out.append(pts[i + 1])
        out.append(polyline_point_at(pts, s1)[0])
        return out

    @property
    def length(self) -> float:
        return polyline_length(self.points())

    @property
    def chord(self) -> float:
        return self.a.dist(self.b)

    def od_at(self, t: float) -> float:
        return self.od_a + (self.od_b - self.od_a) * t

    def w_at(self, t: float) -> float:
        return self.w_a + (self.w_b - self.w_a) * t

    def dir_a(self) -> V:
        p = self.points()
        return (p[1] - p[0]).norm()

    def dir_b(self) -> V:
        p = self.points()
        return (p[-1] - p[-2]).norm()

    def point_at(self, s: float) -> tuple[V, V]:
        """Point and tangent at distance ``s`` from ``a`` along the centreline."""
        return polyline_point_at(self.points(), s)

    def a3(self) -> V3:
        return V3(self.a.x, self.a.y, self.za)

    def b3(self) -> V3:
        return V3(self.b.x, self.b.y, self.zb)

    def mass(self, length: float | None = None) -> float:
        """Approximate mass in grams for a double-butted tube."""
        L = self.length if length is None else length
        rho = MATERIAL_DENSITY.get(self.material, MATERIAL_DENSITY["steel"])
        depth = (self.od_a + self.od_b) / 2.0
        width = (self.w_a + self.w_b) / 2.0
        butt = min(self.butt_length, L / 2)
        mid = max(L - 2 * butt, 0.0)

        def area(wall):
            # wall cross-section = mid-wall perimeter of the (elliptical) section x wall
            wall = min(wall, min(depth, width) / 2)
            a, b = (depth - wall) / 2, (width - wall) / 2
            h = ((a - b) / (a + b)) ** 2 if a + b > 0 else 0.0
            perim = math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))     # Ramanujan
            return perim * wall

        vol = area(self.wall_end) * 2 * butt + area(self.wall_mid) * mid
        n = 2 if self.mirrored else 1
        return vol * rho * n


@dataclass
class Geometry:
    design: Design
    p: dict[str, V] = field(default_factory=dict)        # named points
    tubes: dict[str, Tube] = field(default_factory=dict)
    v: dict[str, float] = field(default_factory=dict)    # derived values
    wheels: dict[str, Wheel] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    ground_y: float = 0.0
    u: V = field(default_factory=lambda: V(0, 1))        # steering axis (up)
    n: V = field(default_factory=lambda: V(1, 0))        # steering axis forward normal
    s: V = field(default_factory=lambda: V(0, 1))        # seat tube axis (up)
    n_st: V = field(default_factory=lambda: V(1, 0))
    bar_path: list[V] = field(default_factory=list)      # handlebar centreline (side view)
    ok: bool = True

    def point(self, name: str) -> V:
        return self.p[name]

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


def _material(d: Design, key: str) -> str:
    m = d.get(key, "frame")
    return d["frame_material"] if m in (None, "frame") else m


def cockpit_offset(d: Design, u: V, n: V) -> tuple[V, V]:
    """Vector from head-tube top to (stem steerer clamp centre, bar clamp centre)."""
    if d["stem_type"] == "quill":
        rise = d.f("upper_stack") + d.f("quill_height")
    else:
        rise = d.f("upper_stack") + d.f("spacers") + d.f("stem_clamp_height") / 2
    a = d.f("stem_angle")
    stem_dir = n * cosd(a) + u * sind(a)
    clamp = u * rise
    return clamp, clamp + stem_dir * d.f("stem_length")


def bar_profile(d: Design) -> tuple[list[V], dict[str, V]]:
    """Handlebar centre-line in the bar's local frame (clamp at origin, +x
    forward) plus local hand positions."""
    t = d["bar_type"]
    r = d.f("bar_reach")
    hands: dict[str, V] = {}
    pts: list[V] = []
    if t == "drop":
        drop = d.f("bar_drop")
        rb = max(drop / 2.0, 10.0)
        x0 = max(r - rb, 0.0)
        pts = [V(0, 0), V(x0, 0)]
        for i in range(1, 19):
            a = 90 - 180 * i / 18
            pts.append(V(x0 + rb * cosd(a), -rb + rb * sind(a)))
        pts.append(V(x0 - 110, -drop))
        lever = V(x0 + rb * cosd(40), -rb + rb * sind(40))      # lever clamp on the bend
        hands["lever"] = lever
        hands["hoods"] = lever + V(d.f("hood_reach"), 30)
        hands["drops"] = V(x0 - 35, -drop)
        hands["tops"] = V(25, 0)
        hands["grips"] = hands["hoods"]
    elif t == "bullhorn":
        rise = d.f("bar_rise")
        pts = [V(0, 0), V(r * 0.6, 0), V(r, rise * 0.5), V(r + 60, rise)]
        hands["grips"] = hands["hoods"] = hands["drops"] = V(r + 40, rise)
        hands["tops"] = V(25, 0)
    else:
        rise = d.f("bar_rise")
        sweep = d.f("bar_backsweep")
        back = (d.f("bar_width") / 2) * sind(sweep) * (1.0 if t != "swept" else 1.0)
        mid = V(-back * 0.3, rise * 0.7)
        pts = [V(0, 0), mid, V(-back, rise)]
        g = V(-back + 20 * cosd(sweep), rise)
        hands["grips"] = hands["hoods"] = hands["drops"] = g
        hands["tops"] = V(0, rise * 0.5)
    rot = d.f("bar_rotation")
    if rot:
        pts = [p.rot(rot) for p in pts]
        hands = {k: v.rot(rot) for k, v in hands.items()}
    return pts, hands


def solve(d: Design) -> Geometry:
    g = Geometry(design=d)
    p = g.p
    v = g.v
    removed = {s.strip().lower() for s in str(d.get("remove_tubes", "")).split(",") if s.strip()}

    # -- wheels and ground ------------------------------------------------------
    rear = Wheel(V(), d.f("rear_bsd"), d.f("rear_tire_width"), d.f("rear_tire_height"),
                 d.f("rim_depth_rear"), d.f("rear_hub_spacing"))
    front = Wheel(V(), d.f("front_bsd"), d.f("front_tire_width"), d.f("front_tire_height"),
                  d.f("rim_depth_front"), d.f("front_hub_spacing"))
    Rr, Rf = rear.outer_r, front.outer_r
    if d["bb_mode"] == "height":
        bb_height = d.f("bb_height")
        bb_drop = Rr - bb_height
    else:
        bb_drop = d.f("bb_drop")
        bb_height = Rr - bb_drop
    tandem = d["frame_type"] == "tandem"
    # drive (rear) BB: the origin, or the stoker BB of a tandem
    SB = V(-d.f("tandem_bb_distance"), d.f("tandem_bb_dy")) if tandem else V(0.0, 0.0)
    g.ground_y = SB.y - bb_height
    ry = SB.y + bb_drop
    fy = Rf + g.ground_y

    sta = d.f("seat_tube_angle")
    hta = d.f("head_tube_angle")
    s = V(-cosd(sta), sind(sta))
    n_st = V(sind(sta), cosd(sta))
    u = V(-cosd(hta), sind(hta))
    n = V(sind(hta), cosd(hta))
    g.u, g.n, g.s, g.n_st = u, n, s, n_st
    P0 = n_st * d.f("st_bb_offset")

    def x_on_st(y: float) -> float:
        return P0.x - (y - P0.y) * cosd(sta) / sind(sta)

    # rear seat tube: the seat tube itself, or the stoker seat tube of a tandem
    if tandem:
        ssta = d.f("stoker_st_angle")
        s2, n_s2, P2 = V(-cosd(ssta), sind(ssta)), V(sind(ssta), cosd(ssta)), SB
    else:
        ssta, s2, n_s2, P2 = sta, s, n_st, P0

    # -- rear axle --------------------------------------------------------------
    st_od = d.f("st_od")
    if d["cs_mode"] == "tire_gap":
        dd = Rr + d.f("rear_tire_gap") + st_od / 2
        rx = P2.x - (dd + (ry - P2.y) * cosd(ssta)) / sind(ssta)
    else:
        cs = d.f("chainstay_length")
        if cs <= abs(bb_drop):
            g.warn("Chainstay shorter than the BB drop; using minimum length")
            cs = abs(bb_drop) + 1
        rx = SB.x - math.sqrt(cs * cs - bb_drop * bb_drop)
    rear_axle = V(rx, ry)
    stay_node = rear_axle - V(d.f("dropout_offset_x"), d.f("dropout_offset_y"))
    dtype = d["dropout_type"]
    if dtype in ("horizontal", "track", "sliding"):
        # slot direction (pointing forward along the chainstay, rotated by the slot angle)
        f = (SB - rear_axle).norm().rot(-d.f("dropout_slot_angle"))
        L, pos = d.f("dropout_slot_length"), min(d.f("axle_in_slot"), d.f("dropout_slot_length"))
        if dtype == "horizontal":            # opening faces forward, closed end at the rear
            closed = rear_axle - f * pos
            slot = (closed, closed + f * L)
        else:                                # track ends / sliding: opening faces rearward
            closed = rear_axle + f * pos
            slot = (closed, closed - f * L)
        g.p["slot_closed"], g.p["slot_open"] = slot
        stay_node = slot[0].lerp(slot[1], 0.5) - V(d.f("dropout_offset_x"), d.f("dropout_offset_y"))

    # -- front end ----------------------------------------------------------------
    AC = d.f("fork_length")
    if d["fork_type"] == "suspension":
        AC -= d.f("fork_travel") * d.f("fork_sag") / 100.0
    LS = d.f("lower_stack")
    off = d.f("fork_offset")
    _, bar_off = cockpit_offset(d, u, n)

    vmode = d["front_v_mode"]
    if vmode == "stack":
        Ty = d.f("stack")
    elif vmode == "bar_y":
        Ty = d.f("bar_y") - bar_off.y
    else:
        Ty = None
    if Ty is None:
        HTL = d.f("head_tube_length")
        Ty = fy + (AC + LS + HTL) * u.y - off * n.y
    else:
        HTL = (Ty - fy + off * n.y) / u.y - AC - LS
    K = AC + LS + HTL

    hmode = d["front_h_mode"]
    if hmode == "front_center":
        fc = d.f("front_center")
        if fc <= abs(fy):
            g.warn("Front centre shorter than the axle height difference")
            fc = abs(fy) + 1
        Ax = math.sqrt(fc * fc - fy * fy)
        Tx = Ax + K * u.x - off * n.x
    elif hmode == "wheelbase":
        Ax = rx + d.f("wheelbase")
        Tx = Ax + K * u.x - off * n.x
    else:
        if hmode == "ett":
            Tx = d.f("top_tube_effective") + x_on_st(Ty)
        elif hmode == "bar_x":
            Tx = d.f("bar_x") - bar_off.x
        else:
            Tx = d.f("reach")
        Ax = Tx - K * u.x + off * n.x
    front_axle = V(Ax, fy)
    T = V(Tx, Ty)
    ht_bottom = T - u * HTL
    crown = ht_bottom - u * LS
    rear.center, front.center = rear_axle, front_axle
    g.wheels = {"rear": rear, "front": front}
    if HTL < 40:
        g.warn(f"Head tube length is {HTL:.0f} mm; check the front end inputs")

    # -- main triangle --------------------------------------------------------------
    st_len = d.f("seat_tube_length")
    ext = d.f("st_extension")

    def junctions(tt_off: float, dt_off: float):
        J_ht = T - u * tt_off
        J_dt = ht_bottom + u * dt_off
        # down tube: line through J_dt passing at distance dt_bb_offset from BB
        Ld = max(J_dt.length(), 1e-6)
        phi = math.atan2(J_dt.y, J_dt.x)
        alpha = math.asin(max(-0.99, min(0.99, d.f("dt_bb_offset") / Ld)))
        psi = phi - alpha
        w_dt = V(math.cos(psi), math.sin(psi))
        dt_a = w_dt.perp() * d.f("dt_bb_offset")
        if d["st_length_mode"] == "cc":
            J_st = P0 + s * st_len
            st_top = J_st + s * ext
        else:
            st_top = P0 + s * st_len
            if d["tt_mode"] == "st_extension":
                J_st = st_top - s * ext
            else:
                ta = d.f("top_tube_angle")
                J = line_intersect(J_ht, V(cosd(ta), sind(ta)), P0, s)
                J_st = J if J is not None else st_top - s * ext
        return J_ht, J_dt, w_dt, dt_a, J_st, st_top

    def ht_r(from_bottom: float) -> float:
        """Head tube outer radius at a distance from its bottom face (tapered HTs)."""
        f = max(0.0, min(1.0, from_bottom / max(HTL, 1e-6)))
        return (d.f("ht_od_bottom") + (d.f("ht_od_top") - d.f("ht_od_bottom")) * f) / 2

    def edge_k(tube_r: float, host_r: float, axis: V, tube_dir: V) -> float:
        """Distance along the head tube from a tube's centre-line junction to the
        point where the tube's outer edge meets the head tube's rear surface."""
        c = max(-0.999, min(0.999, axis.norm().dot(tube_dir.norm())))
        sn = math.sqrt(1 - c * c)
        return (tube_r + host_r * c) / max(sn, 0.05)

    tt_off, dt_off = d.f("tt_ht_offset"), d.f("dt_ht_offset")
    r_tt, r_dt = d.f("tt_od") / 2, d.f("dt_od") / 2
    if d["ht_junction_mode"] == "stickout":
        # head tube stick-out above the top tube edge / below the down tube edge;
        # the centre-line offsets depend on the joint angles, so iterate
        for _ in range(8):
            J_ht, J_dt, w_dt, dt_a, J_st, st_top = junctions(tt_off, dt_off)
            n_tt = d.f("ht_top_stickout") + edge_k(r_tt, ht_r(HTL - tt_off), u, (J_st - J_ht))
            n_dt = d.f("ht_bottom_stickout") + edge_k(r_dt, ht_r(dt_off), u * -1, w_dt * -1)
            done = abs(n_tt - tt_off) < 1e-9 and abs(n_dt - dt_off) < 1e-9
            tt_off, dt_off = n_tt, n_dt
            if done:
                break
    J_ht, J_dt, w_dt, dt_a, J_st, st_top = junctions(tt_off, dt_off)
    tt_vec = J_ht - J_st
    tt_dir = tt_vec.norm()
    v["tt_ht_offset"], v["dt_ht_offset"] = tt_off, dt_off
    v["ht_top_stickout"] = tt_off - edge_k(r_tt, ht_r(HTL - tt_off), u, tt_dir * -1)
    v["ht_bottom_stickout"] = dt_off - edge_k(r_dt, ht_r(dt_off), u * -1, w_dt * -1)

    # seat stay junction
    ss_attach = d["ss_attach"]
    if tandem:
        # stoker top tube from the captain seat tube back to the stoker seat tube
        st_a = J_st - s * d.f("stoker_tt_drop")
        sta2 = d.f("stoker_tt_angle")
        J2 = line_intersect(st_a, V(cosd(sta2), sind(sta2)), P2, s2) or (P2 + s2 * d.f("stoker_st_length") * 0.9)
        g.p["stoker_tt_front"], g.p["stoker_tt_st"] = st_a, J2
        rear_J, rear_dir = J2, (st_a - J2).norm()
    else:
        rear_J, rear_dir = J_st, tt_dir
    if ss_attach == "top_tube":
        SSJ = rear_J + rear_dir * d.f("ss_offset")
    else:
        SSJ = rear_J - s2 * d.f("ss_offset")

    # -- saddle -----------------------------------------------------------------
    if d["saddle_mode"] == "xy":
        S = V(d.f("saddle_x"), d.f("saddle_y"))
    else:
        sa = sta if d["seat_angle_source"] == "seat_tube" else d.f("seat_angle_eff")
        S = V(-cosd(sa), sind(sa)) * d.f("saddle_height")
    tilt = d.f("saddle_tilt")
    sx = V(cosd(tilt), sind(tilt))
    sy = sx.perp()
    nose = S + sx * d.f("saddle_ref_to_nose")
    tail = nose - sx * d.f("saddle_length")
    # rail clamp: where a line through S parallel to the post axis meets the rail plane
    rails = S - s * (d.f("saddle_stack") / max(s.dot(sy), 0.2))
    t_rails = project_on_line(rails, P0, s)
    post_top = P0 + s * t_rails
    setback = -point_line_distance(rails, P0, s)          # + = clamp behind post axis
    t_st_top = project_on_line(st_top, P0, s)
    post_len = d.f("seatpost_length")
    post_bottom = post_top - s * post_len
    insertion = t_st_top - (t_rails - post_len)
    exposed = t_rails - t_st_top

    # -- cockpit ----------------------------------------------------------------
    clamp_off, bar_off = cockpit_offset(d, u, n)
    stem_clamp = T + clamp_off
    bar = T + bar_off
    if d["stem_type"] == "quill":
        steerer_top = T + u * (d.f("upper_stack") + d.f("quill_height") + 25)
    else:
        steerer_top = T + u * (d.f("upper_stack") + d.f("spacers") + d.f("stem_clamp_height")
                               + d.f("steerer_above_stem"))
    bar_local, hands_local = bar_profile(d)
    g.bar_path = [bar + q for q in bar_local]
    hands = {k: bar + q for k, q in hands_local.items()}
    hand = hands.get(d["hand_position"], hands.get("hoods", bar))

    # -- crank ------------------------------------------------------------------
    cl = d.f("crank_length")
    pedal = V.polar(cl, d.f("crank_angle"))

    # -- points -------------------------------------------------------------------
    p.update({
        "bb": V(0, 0), "rear_axle": rear_axle, "front_axle": front_axle, "stay_node": stay_node,
        "ht_top": T, "ht_bottom": ht_bottom, "crown": crown,
        "headset_top": T + u * d.f("upper_stack"),
        "st_bottom": P0, "st_top": st_top, "tt_st": J_st, "tt_ht": J_ht, "dt_ht": J_dt, "dt_bb": dt_a,
        "ss_top": SSJ, "saddle": S, "saddle_nose": nose, "saddle_tail": tail, "saddle_rails": rails,
        "seatpost_top": post_top, "seatpost_bottom": post_bottom,
        "stem_clamp": stem_clamp, "bar": bar, "steerer_top": steerer_top, "hand": hand,
        "hoods": hands.get("hoods", bar), "drops": hands.get("drops", bar), "tops": hands.get("tops", bar),
        "pedal": pedal, "pedal_l": -pedal, "pedal_fwd": V(cl, 0),
        "ground_rear": V(rx, g.ground_y), "ground_front": V(Ax, g.ground_y),
        "ground_bb": V(0, g.ground_y), "drive_bb": SB,
    })
    if "lever" in hands:
        p["lever"] = hands["lever"]

    # -- tubes --------------------------------------------------------------------
    d_ = d
    def tube(name, label, a, b, od_key, prefix, kind="main", join_a=None, join_b=None):
        od = d_.f(od_key)
        od_end = d_.f(f"{prefix}_od_end") if P.has(f"{prefix}_od_end") else 0.0
        prof = d_.get(f"{prefix}_profile", "round")
        w = d_.f(f"{prefix}_od2") if prof != "round" and P.has(f"{prefix}_od2") else od
        od_a = od_end if od_end > 0 else od
        w_a = w * (od_a / od) if od_end > 0 else w
        return Tube(name, label, a, b, od_a, od, w_a, w,
                    wall_end=d_.f(f"{prefix}_wall_end"), wall_mid=d_.f(f"{prefix}_wall_mid"),
                    butt_length=d_.f(f"{prefix}_butt_length"), bend=d_.f(f"{prefix}_bend"),
                    profile=prof, material=_material(d_, f"{prefix}_material"), kind=kind,
                    join_a=join_a, join_b=join_b)

    tubes = g.tubes
    tubes["ht"] = Tube("ht", "Head tube", ht_bottom, T, d.f("ht_od_bottom"), d.f("ht_od_top"),
                       wall_end=d.f("ht_wall"), wall_mid=d.f("ht_wall"),
                       material=_material(d, "ht_material"))
    if "st" not in removed:
        tubes["st"] = tube("st", "Seat tube", P0, st_top, "st_od", "st", join_a="bb")
    if "tt" not in removed:
        tubes["tt"] = tube("tt", "Top tube", J_st, J_ht, "tt_od", "tt", join_a="st", join_b="ht")
    if "dt" not in removed:
        tubes["dt"] = tube("dt", "Down tube", dt_a, J_dt, "dt_od", "dt", join_a="bb", join_b="ht")

    hub_r = rear.hub_spacing / 2 + 3.0
    # stay spreads (0 = automatic)
    cs_z = d.f("cs_spread_bb") / 2 or max(d.f("bb_shell_width") / 2 - d.f("cs_od_bb") / 2, 5.0)
    rear_st = d.f("st_od")
    ss_z = d.f("ss_spread_top") / 2 or (rear_st / 2 + d.f("ss_od_top") * 0.25)
    v["cs_spread_bb"], v["ss_spread_top"] = 2 * cs_z, 2 * ss_z
    if "cs" not in removed:
        cs_dir = (SB - stay_node).norm()
        cs_w = d.f("cs_width_bb")
        cs_profile = d["cs_profile"] if not cs_w or d["cs_profile"] != "round" else "oval"
        tubes["cs"] = Tube("cs", "Chainstay", stay_node, SB, d.f("cs_od_drop"), d.f("cs_od_bb"),
                           d.f("cs_od_drop"), cs_w or d.f("cs_od_bb"),
                           wall_end=d.f("cs_wall"), wall_mid=d.f("cs_wall"), bend=d.f("cs_bend"),
                           profile=cs_profile, material=_material(d, "cs_material"),
                           za=hub_r, zb=cs_z, mirrored=True, kind="stay",
                           join_a="dropout", join_b="bb2" if tandem else "bb",
                           draw_a=stay_node + cs_dir * d.f("cs_dropout_length"))
    if ss_attach != "none" and "ss" not in removed:
        ss_target = SSJ
        style = d["ss_style"]
        if style in ("wishbone", "mono"):
            W = SSJ + (stay_node - SSJ).norm() * d.f("wishbone_length")
            p["wishbone"] = W
            tubes["ss_mono"] = Tube("ss_mono", "Seat stay (wishbone)", W, SSJ, d.f("ss_od_top") * 1.4,
                                    d.f("ss_od_top") * 1.4, wall_end=d.f("ss_wall") * 1.2,
                                    wall_mid=d.f("ss_wall") * 1.2, material=_material(d, "ss_material"),
                                    kind="stay", join_a="ss",
                                    join_b=("tt" if ss_attach == "top_tube" else "st") + ("2" if tandem else ""))
            ss_target = W
        ss_dir = (ss_target - stay_node).norm()
        ztop = ss_z if style == "conventional" else max(d.f("ss_od_top"), 8)
        if style == "mono":
            ztop = 0.0
        tubes["ss"] = Tube("ss", "Seat stay", stay_node, ss_target, d.f("ss_od_drop"), d.f("ss_od_top"),
                           wall_end=d.f("ss_wall"), wall_mid=d.f("ss_wall"), bend=d.f("ss_bend"),
                           profile=d["ss_profile"], material=_material(d, "ss_material"),
                           za=hub_r, zb=ztop, mirrored=True, kind="stay", join_a="dropout",
                           join_b=("ss_mono" if style in ("wishbone", "mono")
                                   else ("tt" if ss_attach == "top_tube" else "st") + ("2" if tandem else "")),
                           draw_a=stay_node + ss_dir * d.f("ss_dropout_length"))

    if tandem:
        _tandem_tubes(g, d, SB, s2, P2, stay_node, hub_r)
    if d["frame_type"] == "tall":
        _tall_frame(g, d, u, stay_node, hub_r)

    # fork blades (side view centre-line from crown to axle)
    crown_bottom = crown - u * d.f("fork_crown_height")
    p["crown_bottom"] = crown_bottom
    fr = front.hub_spacing / 2 + 3.0
    tubes["fork"] = Tube("fork", "Fork blade", front_axle, crown_bottom, d.f("fork_blade_od_tip"),
                         d.f("fork_blade_od"), wall_end=d.f("fork_wall_end"), wall_mid=d.f("fork_wall_mid"),
                         butt_length=d.f("fork_butt_length"),
                         bend=(off * 0.45 if d["fork_blade_shape"] == "curved" and d["fork_type"] == "rigid" else 0.0),
                         material=_material(d, "fork_material"), za=fr, zb=d.f("fork_crown_width") / 2,
                         mirrored=True, kind="fork", join_b="crown")

    # extra user tubes
    for i, et in enumerate(d.extras.get("extra_tubes") or []):
        try:
            od_b_ = float(et.get("od", 25.4))
            a = _resolve_point(g, et.get("a"), float(et.get("od_end", 0.0) or od_b_) / 2)
            b = _resolve_point(g, et.get("b"), od_b_ / 2)
        except (KeyError, TypeError, ValueError):
            g.warn(f"Extra tube {et.get('name', i)}: unresolved end point")
            continue
        # "in phase": keep this tube parallel to another tube (its side-view
        # direction), holding the chosen end fixed and preserving its length
        par = et.get("parallel_to")
        if par:
            ref = tubes.get(par)
            rdir = (ref.b - ref.a) if ref is not None else None
            if rdir is not None and rdir.length() > 1e-6:
                rdir = rdir.norm()
                length_ab = (b - a).length()
                anchor = str(et.get("phase_anchor", "a"))
                if anchor == "b":
                    a = b - rdir * length_ab
                elif anchor == "mid":
                    mid = (a + b) * 0.5
                    a, b = mid - rdir * (length_ab * 0.5), mid + rdir * (length_ab * 0.5)
                else:
                    b = a + rdir * length_ab
            else:
                g.warn(f"Extra tube {et.get('name', i)}: tube '{par}' to stay parallel to is not available")
        name = f"x{i}_" + str(et.get("name", f"tube{i}"))
        od = float(et.get("od", 25.4))
        od_end = float(et.get("od_end", 0.0) or od)              # optional taper toward the start
        prof = str(et.get("profile", "round"))
        w = float(et.get("od2", 0.0) or od) if prof != "round" else od
        mat = str(et.get("material", "frame"))
        tubes[name] = Tube(name, str(et.get("label", et.get("name", "Extra tube"))), a, b, od_end, od,
                           w * od_end / od, w,
                           wall_end=float(et.get("wall", 0.9)), wall_mid=float(et.get("wall_mid", et.get("wall", 0.9))),
                           butt_length=float(et.get("butt_length", 0.0)), profile=prof,
                           bend=float(et.get("bend", 0.0)), material=d["frame_material"] if mat == "frame" else mat,
                           za=float(et.get("za", 0.0)), zb=float(et.get("zb", 0.0)),
                           mirrored=bool(et.get("mirrored", False)), kind="extra",
                           join_a=et.get("join_a") or _spec_join(et.get("a")),
                           join_b=et.get("join_b") or _spec_join(et.get("b")))

    # -- derived values -----------------------------------------------------------
    sa_eff = math.degrees(math.atan2(S.y, -S.x)) if S.length() > 1 else sta
    # trail: steering axis meets the ground
    t_g = (g.ground_y - T.y) / u.y
    axis_ground = T + u * t_g
    trail = axis_ground.x - Ax
    p["axis_ground"] = axis_ground
    # standover: top surface of the highest straddled tube at xs
    so_mode = d["standover_at"]
    if so_mode == "custom":
        xs = d.f("standover_x")
    elif so_mode == "bb":
        xs = 0.0
    else:
        xs = (J_st.x + J_ht.x) / 2
    ys = None
    for name, tb in tubes.items():
        if name in ("ht", "st", "st2", "cs", "ss", "ss_mono", "fork") or tb.kind == "stay":
            continue
        top = _tube_top_at(tb, xs)
        if top is not None and (ys is None or top > ys):
            ys = top
    if ys is None and "tt" in tubes:          # outside the top tube: use its higher end
        ys = max(J_st.y, J_ht.y) + tubes["tt"].od_b / 2
    if ys is not None:
        standover = ys - g.ground_y
        p["standover"] = V(xs, ys)
    else:
        standover = float("nan")
    cl_toe = cl + d.f("toe_overhang")
    fender_extra = (d.f("fender_clearance") + 2.0) if d["fenders"] else 0.0
    fc_dist = front_axle.length()
    toe_clear = fc_dist - cl_toe - Rf - fender_extra

    st_tube = tubes.get("st")
    if tandem:
        st_tube = tubes.get("st2")
    rear_tire_clear = (abs(point_line_distance(rear_axle, P2, s2)) - Rr
                       - (st_tube.od_at(0.15) if st_tube else st_od) / 2)
    dt_tube = tubes.get("dt")
    front_tire_clear = (abs(point_line_distance(front_axle, dt_a, w_dt)) - Rf - (dt_tube.od_b if dt_tube else 0) / 2)
    pedal_clear = bb_height - cl - d.f("pedal_thickness") / 2
    lean = math.degrees(math.atan2(max(pedal_clear, 0.0), d.f("q_factor") / 2 + d.f("pedal_width")))

    bridge_w = float(d.get("cs_bridge_width", 16.0) or 16.0)
    cs_bridge = d.f("cs_bridge_pos") or max(rear_axle.dist(SB) - Rr - bridge_w / 2 - 6.0, 40.0)
    v["cs_bridge_pos"] = cs_bridge
    v.update({
        "stack": T.y, "reach": T.x, "head_tube_length": HTL, "head_tube_angle": hta,
        "seat_tube_angle": sta, "seat_angle_eff": sa_eff,
        "seat_tube_ct": (st_top - P0).length(), "seat_tube_cc": (J_st - P0).length(),
        "st_extension": (st_top - J_st).dot(s),
        "top_tube_cc": tt_vec.length(), "top_tube_angle": tt_vec.angle(),
        "top_tube_effective": T.x - x_on_st(T.y),
        "top_tube_virtual": T.x + T.y * cosd(sa_eff) / max(sind(sa_eff), 1e-6),
        "down_tube_cc": (J_dt - dt_a).length(),
        "chainstay_length": rear_axle.dist(SB), "rear_center_h": SB.x - rx,
        "front_center": fc_dist, "front_center_h": Ax, "wheelbase": Ax - rx,
        "bb_drop": bb_drop, "bb_height": bb_height, "bb_drop_front": fy,
        "fork_length": AC, "fork_offset": off, "lower_stack": LS,
        "trail": trail, "mech_trail": trail * sind(hta), "wheel_flop": trail * sind(hta) * cosd(hta),
        "standover": standover,
        "saddle_height": S.length(), "saddle_setback": -S.x, "saddle_nose_setback": -nose.x,
        "saddle_x": S.x, "saddle_y": S.y,
        "bar_x": bar.x, "bar_y": bar.y, "hand_x": hand.x, "hand_y": hand.y,
        "hoods_x": p["hoods"].x, "hoods_y": p["hoods"].y,
        "saddle_bar_drop": S.y - bar.y, "saddle_hand_drop": S.y - hand.y,
        "saddle_to_bar": S.dist(bar), "nose_to_bar": nose.dist(bar), "nose_to_hand": nose.dist(hand),
        "saddle_bar_reach_h": bar.x - S.x,
        "stack_headset": T.y + u.y * d.f("upper_stack"), "reach_headset": T.x + u.x * d.f("upper_stack"),
        "seatpost_setback": setback, "seatpost_exposed": exposed, "seatpost_insertion": insertion,
        "toe_clearance": toe_clear, "toe_radius": cl_toe,
        "rear_tire_clearance": rear_tire_clear, "front_tire_clearance": front_tire_clear,
        # exactly the quantity the "tire gap" rear-end mode drives (nominal seat tube OD)
        "rear_tire_gap": abs(point_line_distance(rear_axle, P2, s2)) - Rr - st_od / 2,
        "pedal_clearance": pedal_clear, "lean_angle": lean,
        "crank_length": cl, "rear_wheel_dia": rear.diameter, "front_wheel_dia": front.diameter,
        "ss_length": tubes["ss"].chord if "ss" in tubes else 0.0,
        "steerer_length": (steerer_top - crown).length(),
    })

    # -- warnings -----------------------------------------------------------------
    if v["st_extension"] < -1 and "st" in tubes and "tt" in tubes:
        g.warn("Top tube meets the seat tube above its top; lengthen the seat tube or lower the top tube")
    if d["frame_type"] == "tall":
        R = p["crank_bb"]
        v["toe_clearance"] = toe_clear = front_axle.dist(R) - cl_toe - Rf - fender_extra
        v["pedal_clearance"] = pedal_clear = (R.y - g.ground_y) - cl - d.f("pedal_thickness") / 2
        v["lean_angle"] = math.degrees(math.atan2(max(pedal_clear, 0.0), d.f("q_factor") / 2 + d.f("pedal_width")))
    if insertion < d.f("seatpost_min_insertion"):
        g.warn(f"Seatpost insertion {insertion:.0f} mm is below the minimum {d.f('seatpost_min_insertion'):.0f} mm")
    if toe_clear < d.f("toe_clearance_min"):
        g.warn(f"Toe overlap: clearance {toe_clear:.0f} mm")
    if rear_tire_clear < 3:
        g.warn(f"Rear tire to seat tube clearance only {rear_tire_clear:.1f} mm")
    rail_adjust = setback - d.f("seatpost_offset")
    v["saddle_rail_adjust"] = rail_adjust
    if abs(rail_adjust) > d.f("rail_range"):
        g.warn(f"Saddle needs {rail_adjust:+.0f} mm of rail adjustment with a {d.f('seatpost_offset'):.0f} mm "
               f"setback post (range ±{d.f('rail_range'):.0f} mm)")
    # problem curves: bends larger than a semicircle or tighter than the tubing tolerates
    for name, tb in tubes.items():
        if abs(tb.bend) < 1e-6:
            continue
        L = tb.chord
        if abs(tb.bend) >= L / 2:
            g.warn(f"{tb.label}: bend of {tb.bend:.0f} mm exceeds a semicircle; reduce the sagitta")
            continue
        R = (L * L / 4 + tb.bend * tb.bend) / (2 * abs(tb.bend))
        od = max(tb.od_a, tb.od_b)
        v[f"bend_radius_{name}"] = R
        if R < 3 * od:
            g.warn(f"{tb.label}: bend radius {R:.0f} mm is under 3×OD ({3 * od:.0f} mm); likely to kink")
    # minimum tube lengths: top and down tube must not overlap on the head tube
    if "tt" in tubes and "dt" in tubes:
        def foot(tube_od, ang):
            return tube_od / 2 / max(sind(ang), 0.2)
        gap = (HTL - d.f("tt_ht_offset") - d.f("dt_ht_offset")
               - foot(tubes["tt"].od_b, v.get("angle_ht_tt", _interior(u, tt_dir * -1)))
               - foot(tubes["dt"].od_b, _interior(u * -1, w_dt * -1)))
        v["ht_exposed"] = gap
        if gap < 0:
            g.warn(f"Top tube and down tube overlap by {-gap:.0f} mm on the head tube; lengthen the head tube "
                   "or reduce the junction offsets")
    for name in ("tt", "dt", "st"):
        tb = tubes.get(name)
        if tb is not None and tb.length < 2 * tb.od_b:
            g.warn(f"{tb.label} is only {tb.length:.0f} mm long")

    if d["couplers"] and "tt" in tubes and "dt" in tubes:
        _couplers(g, d)

    # joint ("lug") angles, quoted the way lugsets are: HT/TT ≈ HTA, ST/TT ≈ STA
    v["angle_ht_tt"] = _interior(u, tt_dir * -1)
    v["angle_ht_dt"] = _interior(u * -1, w_dt * -1)
    v["angle_st_tt"] = _interior(s * -1, tt_dir)
    v["angle_st_dt"] = _interior(s, w_dt)
    if d["joint_style"] == "lugged":
        tol = d.f("lug_tolerance")
        if abs(v["angle_ht_tt"] - d.f("lug_ht_angle")) > tol:
            g.warn(f"Head lug angle {v['angle_ht_tt']:.1f}° vs lugset {d.f('lug_ht_angle'):.1f}°: lugs need bending")
        if abs(v["angle_st_tt"] - d.f("lug_st_angle")) > tol:
            g.warn(f"Seat lug angle {v['angle_st_tt']:.1f}° vs lugset {d.f('lug_st_angle'):.1f}°: lugs need bending")
    if "ss" in tubes:
        v["angle_st_ss"] = _interior(s * -1, tubes["ss"].dir_b() * -1)
    return g


RIDER_POINTS = ("saddle", "saddle_nose", "saddle_tail", "saddle_rails", "seatpost_top", "seatpost_bottom",
                "stem_clamp", "bar", "steerer_top", "hand", "hoods", "drops", "tops", "lever", "pedal", "pedal_l",
                "pedal_fwd", "headset_top")


def _tall_frame(g: Geometry, d: Design, u: V, stay_node: V, hub_r: float) -> None:
    """Tall bike: a copy of the main triangle stacked with its head tube coaxial
    above the lower one.  The rider (cranks, saddle, cockpit) moves up with it;
    struts tie the upper BB to the lower frame."""
    p, tubes, v = g.p, g.tubes, g.v
    lift = u * d.f("tall_offset")
    R = lift                                   # upper (rider) BB
    for name in RIDER_POINTS:
        if name in p:
            p[name] = p[name] + lift
    g.bar_path = [q + lift for q in g.bar_path]
    p["crank_bb"] = p["chain_bb"] = p["upper_bb"] = R
    p["cockpit_ht_top"] = p["ht_top"] + lift
    p["cockpit_ht_bottom"] = p["ht_bottom"] + lift
    p["post_st_top"] = p["st_top"] + lift
    for name in ("ht", "tt", "dt", "st"):
        t = tubes.get(name)
        if t is None:
            continue
        tubes["u" + name] = Tube("u" + name, "Upper " + t.label.lower(), t.a + lift, t.b + lift, t.od_a, t.od_b,
                                 t.w_a, t.w_b, t.wall_end, t.wall_mid, t.butt_length, t.bend, t.profile, t.material,
                                 kind="extra", join_a={"bb": "ubb", "st": "ust"}.get(t.join_a or "", t.join_a),
                                 join_b={"ht": "uht", "st": "ust"}.get(t.join_b or "", t.join_b))
    struts = d["tall_struts"]
    od = d.f("tall_strut_od")
    if struts in ("both", "seat_cluster") and R.dist(p["tt_st"]) > od:
        tubes["strut_sc"] = Tube("strut_sc", "Strut (upper BB to seat cluster)", p["tt_st"], R, od, od,
                                 wall_end=0.9, wall_mid=0.9, material=d["frame_material"], kind="extra",
                                 join_a="st", join_b="ubb")
    if struts in ("both", "dropouts"):
        tubes["strut_rear"] = Tube("strut_rear", "Struts (upper BB to dropouts)", stay_node, R, od * 0.85, od,
                                   wall_end=0.9, wall_mid=0.9, material=d["frame_material"], kind="extra",
                                   za=hub_r, zb=d.f("bb_shell_width") / 2 - od / 2, mirrored=True,
                                   join_a="dropout", join_b="ubb")
    v["tall_offset"] = d.f("tall_offset")
    v["rider_bb_height"] = R.y - g.ground_y


def _tandem_tubes(g: Geometry, d: Design, SB: V, s2: V, P2: V, stay_node: V, hub_r: float) -> None:
    """Stoker seat tube, stoker top tube, boom and mid/lateral tubes, stoker
    saddle and bars."""
    p, tubes = g.p, g.tubes
    od = d.f("tandem_tube_od")
    mat = d["frame_material"]
    st2_top = P2 + s2 * d.f("stoker_st_length")
    p["stoker_st_top"] = st2_top
    p["stoker_bb"] = SB

    def t(name, label, a, b, od_, join_a, join_b, **kw):
        tubes[name] = Tube(name, label, a, b, od_, od_, wall_end=d.f("st_wall_end"), wall_mid=d.f("st_wall_mid"),
                           butt_length=d.f("st_butt_length"), material=mat, kind="extra",
                           join_a=join_a, join_b=join_b, **kw)
    t("st2", "Stoker seat tube", P2, st2_top, d.f("st_od"), "bb2", None)
    t("tt2", "Stoker top tube", p["stoker_tt_st"], p["stoker_tt_front"], d.f("tt_od"), "st2", "st")
    t("boom", "Boom tube", SB, V(0, 0), od, "bb2", "bb")
    mid = d["tandem_mid_tube"]
    if mid == "marathon":
        t("mid", "Marathon tube", SB, p["tt_st"], od * 0.9, "bb2", "st")
    elif mid == "direct":
        t("mid", "Direct lateral", SB, p["dt_ht"] + g.u * 25, od * 0.9, "bb2", "ht")
    elif mid == "twin_laterals":
        t("lat", "Lateral tubes", stay_node, p["dt_ht"] + g.u * 25, 19.0, "dropout", "ht", za=hub_r, zb=12.0,
          mirrored=True)
    # stoker saddle on its seat tube angle, stoker bars on the captain seatpost
    a2 = d.f("stoker_st_angle")
    S2 = SB + V(-cosd(a2), sind(a2)) * d.f("stoker_saddle_height")
    p["stoker_saddle"] = S2
    p["stoker_saddle_nose"] = S2 + V(d.f("saddle_ref_to_nose"), 0)
    p["stoker_saddle_tail"] = p["stoker_saddle_nose"] - V(d.f("saddle_length"), 0)
    p["stoker_saddle_rails"] = S2 - s2 * (d.f("saddle_stack") / max(s2.y, 0.2))
    clamp = p["saddle_rails"] - g.s * d.f("stoker_bar_drop")
    p["stoker_stem_clamp"] = clamp
    p["stoker_bar"] = clamp - V(d.f("stoker_stem_length"), 0)
    p["stoker_pedal"] = SB + (p["pedal"] - V(0, 0))
    g.v["tandem_bb_distance"] = SB.dist(V(0, 0))
    g.v["stoker_saddle_height"] = d.f("stoker_saddle_height")
    g.v["stoker_saddle_to_bar"] = S2.dist(p["stoker_bar"])
    g.v["stoker_knee_room"] = p["stoker_bar"].x - p["stoker_saddle_nose"].x


def _couplers(g: Geometry, d: Design) -> None:
    """Coupler positions and a travel-case check: the frame splits into a front
    half (head tube, fork stub) and a rear half; each must fit the case
    diagonal in side view (wheels and fork removed)."""
    tt, dt = g.tubes["tt"], g.tubes["dt"]
    ptt, _ = tt.point_at(min(d.f("coupler_tt_pos"), tt.length - 20))
    pdt, _ = dt.point_at(min(d.f("coupler_dt_pos"), dt.length - 20))
    g.p["coupler_tt"], g.p["coupler_dt"] = ptt, pdt
    front = [ptt, pdt, g.p["ht_top"], g.p["ht_bottom"], g.p["tt_ht"], g.p["dt_ht"]]
    rear = [ptt, pdt, g.p["bb"], g.p["st_top"], g.p["tt_st"], g.p["stay_node"], g.p["drive_bb"]]
    case_diag = math.hypot(d.f("case_length"), d.f("case_width"))

    def span(pts):
        return max(a.dist(b) for a in pts for b in pts)
    fs, rs = span(front) + 40, span(rear) + 40          # allowance for tube ODs / dropouts
    g.v["coupler_front_span"], g.v["coupler_rear_span"] = fs, rs
    if rs > case_diag or fs > case_diag:
        g.warn(f"Frame halves ({rs:.0f} / {fs:.0f} mm) don't fit the travel case diagonal ({case_diag:.0f} mm)")


def _tube_top_at(tb: Tube, xs: float) -> float | None:
    """Height of a tube's top surface at x = xs (None if the tube doesn't span xs)."""
    pts = tb.points()
    for i in range(len(pts) - 1):
        a_, b_ = pts[i], pts[i + 1]
        if min(a_.x, b_.x) - 1e-9 <= xs <= max(a_.x, b_.x) + 1e-9 and abs(b_.x - a_.x) > 1e-9:
            t = (xs - a_.x) / (b_.x - a_.x)
            slope = math.atan2(b_.y - a_.y, b_.x - a_.x)
            if abs(math.cos(slope)) < 0.35:          # near-vertical tubes aren't straddled
                return None
            frac = project_on_line(a_.lerp(b_, t), tb.a, tb.b - tb.a) / max(tb.chord, 1e-9)
            return a_.y + (b_.y - a_.y) * t + tb.od_at(max(0.0, min(1.0, frac))) / 2 / abs(math.cos(slope))
    return None


_POINT_JOINS = {"bb": "bb", "dt_bb": "bb", "st_bottom": "bb", "rear_axle": "dropout", "stay_node": "dropout",
                "ht_top": "ht", "ht_bottom": "ht", "tt_ht": "ht", "dt_ht": "ht", "tt_st": "st", "st_top": "st",
                "ss_top": "st", "crown": "crown", "front_axle": "fork_end"}


def _spec_join(spec: Any) -> str | None:
    """What an extra tube end attaches to, inferred from its point spec."""
    if isinstance(spec, str):
        return _POINT_JOINS.get(spec)
    if isinstance(spec, dict):
        if "tube" in spec:
            return str(spec["tube"])
        if "point" in spec:
            return _POINT_JOINS.get(str(spec["point"]))
    return None


def _interior(a: V, b: V) -> float:
    """Angle between two direction vectors, degrees."""
    c = max(-1.0, min(1.0, a.norm().dot(b.norm())))
    return math.degrees(math.acos(c))


def _resolve_point(g: Geometry, spec: Any, own_r: float = 0.0) -> V:
    """Resolve an extra-tube end point spec.

    * ``"name"`` or ``{"point": name, "dx", "dy"}`` - a named point (+ offset)
    * ``{"tube": name, "pos": fraction | "s": mm, "from": "a"|"b", "side": mm,
      "surface": "above"|"below"}`` - on another tube: at a fraction of its length
      or a distance from its start (``from: "b"`` measures from its end), moved
      ``side`` mm perpendicular to it; ``surface`` sits the new tube on the host
      tube's outer surface (host radius + ``own_r``).  "above" is the left of the
      host's direction: above top/down tubes and stays, behind seat/head tubes.
    * ``{"x", "y"}`` - coordinates from the BB."""
    if isinstance(spec, str):
        return g.p[spec]
    if "point" in spec:
        base = g.p[spec["point"]]
        return base + V(float(spec.get("dx", 0)), float(spec.get("dy", 0)))
    if "tube" in spec:
        t = g.tubes[spec["tube"]]
        L = t.length
        dist = float(spec["s"]) if "s" in spec else float(spec.get("pos", 0.5)) * L
        if spec.get("from") == "b":
            dist = L - dist
        dist = max(0.0, min(L, dist))
        p, tan = t.point_at(dist)
        side = float(spec.get("side", 0.0) or 0.0)
        surf = spec.get("surface")
        if surf in ("above", "below"):
            off = t.od_at(dist / max(L, 1e-9)) / 2 + own_r
            side += off if surf == "above" else -off
        return p + tan.perp() * side if side else p
    return V(float(spec["x"]), float(spec["y"]))
