"""Centre of mass and static weight distribution (bike, optionally with rider).

Frame tubes use :meth:`Tube.mass` placed at each tube's midpoint; other parts
use typical catalogue masses scaled by their size (wheel diameter, tyre width,
cog sizes, crank length ...).  Any estimate can be replaced by a measured value
through ``design.extras["component_masses"]`` (``{name: grams}``, names as
returned by :func:`component_masses`).

The rider is split into Winter / Dempster body segments (mass fractions of
body mass, centre of mass as a fraction of segment length from the proximal
joint) positioned by :func:`framewright.fit.rider.solve_pose`.

Weight distribution is the static balance about the tyre contact points
(directly below the axles): front share = (x_com - x_rear) / (x_front - x_rear).
"""
from __future__ import annotations

import math

from ..geometry.solver import MATERIAL_DENSITY, Geometry, Wheel
from ..geometry.vec import V
from ..model import params as P
from ..render.scene import Z_OVER, Scene, Style
from ..render.theme import Theme
from .rider import GROUP, anatomy, solve_pose

P.register([
    P.ParamDef("com_include_rider", "Include rider in centre of mass", GROUP, "Centre of mass", P.BOOL, True,
               morph=False),
    P.ParamDef("com_bottles_full", "Bottles full", GROUP, "Centre of mass", P.BOOL, True, morph=False,
               help="Count water bottles as full (≈ 650 g each) in the centre-of-mass calculation"),
])

# (name, mass fraction, proximal joint, distal joint, COM fraction from proximal, count)
# Winter, Biomechanics and Motor Control of Human Movement, table 4.1 (after Dempster).
# Both arms coincide in side view, so they are listed once with count 2.
RIDER_SEGMENTS: tuple[tuple[str, float, str, str, float, int], ...] = (
    ("trunk", 0.497, "hip", "shoulder", 0.50, 1),
    ("head_neck", 0.081, "shoulder", "head", 1.00, 1),
    ("upper_arm", 0.028, "shoulder", "elbow", 0.436, 2),
    ("forearm", 0.016, "elbow", "wrist", 0.430, 2),
    ("hand", 0.006, "wrist", "hand", 0.90, 2),
    ("thigh", 0.100, "hip", "knee", 0.433, 1),
    ("shank", 0.0465, "knee", "ankle", 0.433, 1),
    ("foot", 0.0145, "ankle", "ball", 0.50, 1),
    ("thigh_far", 0.100, "hip", "knee_far", 0.433, 1),
    ("shank_far", 0.0465, "knee_far", "ankle_far", 0.433, 1),
    ("foot_far", 0.0145, "ankle_far", "ball_far", 0.50, 1),
)


def _density(material: str) -> float:
    return MATERIAL_DENSITY.get(material, MATERIAL_DENSITY["steel"])


def _wheel_parts(d, key: str, w: Wheel) -> float:
    k = w.bsd / 622.0
    rim = (330.0 + 5.0 * w.rim_depth) * k
    tire = (8.0 * w.tire_w + 0.05 * w.tire_w ** 2) * k
    tube = 110.0 * k
    spokes = int(d[f"spokes_{key}"]) * 6.5
    disc = d[f"brake_{key}"] == "disc"
    hub = (140.0 if key == "front" else 300.0) + (40.0 if disc else 0.0)
    if key == "rear" and d["drive_type"] == "hub_gear":
        hub = 1500.0
    return rim + tire + tube + spokes + hub


def _arc_centroid(c: V, r: float, a0: float, a1: float) -> V:
    half = math.radians(a1 - a0) / 2.0
    if abs(half) < 1e-9:
        return c + V.polar(r, a0)
    return c + V.polar(r * math.sin(half) / half, (a0 + a1) / 2.0)


def _bike_parts(g: Geometry) -> list[tuple[str, float, V]]:
    d = g.design
    p = g.p
    out: list[tuple[str, float, V]] = []
    add = lambda name, m, pt: out.append((name, float(m), pt))

    # frame tubes, fork blades, extra tubes
    for name, tb in g.tubes.items():
        if name == "fork" and d["fork_type"] == "suspension":
            continue
        L = tb.length
        mid, _ = tb.point_at(L / 2.0)
        add(f"tube:{name}", tb.mass(), mid)
    mat = d["frame_material"]
    rho = _density(mat)
    wall = 2.5 if mat in ("steel", "stainless", "titanium") else 3.5
    od, width = d.f("bb_shell_od"), d.f("bb_shell_width")
    add("bb_shell", math.pi * (od * wall - wall * wall) * width * rho, V(0, 0))
    add("dropouts", 140.0 if mat in ("steel", "stainless") else 90.0, p["rear_axle"])
    joints = {"lugged": 380.0, "fillet": 160.0, "bonded": 150.0}.get(d["joint_style"], 40.0)
    centroid = (p["bb"] + p["tt_st"] + p["tt_ht"] + p["dt_ht"]) / 4.0
    add("joints", joints + 40.0, centroid)          # + braze-ons

    # fork
    crown, cb = p["crown"], p["crown_bottom"]
    if d["fork_type"] == "suspension":
        add("fork", 1750.0, p["front_axle"].lerp(crown, 0.55))
    else:
        add("fork_crown", 110.0 if mat == "carbon" else 160.0, crown.lerp(cb, 0.5))
    steerer_len = crown.dist(p["steerer_top"])
    s_od = d.f("steerer_od")
    s_wall, s_rho = (1.2, _density("steel")) if mat in ("steel", "stainless") else (1.8, _density("aluminium"))
    add("steerer", math.pi * (s_od * s_wall - s_wall ** 2) * steerer_len * s_rho, crown.lerp(p["steerer_top"], 0.5))

    # wheels, rotors
    for key in ("front", "rear"):
        w = g.wheels[key]
        add(f"wheel_{key}", _wheel_parts(d, key, w), w.center)
        if d[f"brake_{key}"] == "disc":
            add(f"rotor_{key}", 120.0 * (d.f(f"rotor_{key}") / 160.0) ** 2, w.center)

    # drivetrain
    drive = d["drive_type"]
    ax = p["rear_axle"]
    cogs = d.lst("cogs") or [16.0]
    rings = d.lst("chainrings") or [42.0]
    if drive == "derailleur":
        add("cassette", sum(cogs) * 1.25, ax)
    elif drive != "hub_gear":
        add("cassette", min(cogs) * 2.0 + 15.0, ax)
    add("chain", {"belt": 80.0, "derailleur": 250.0}.get(drive, 290.0), p["bb"].lerp(ax, 0.5) + V(0, -10))
    cl = d.f("crank_length")
    add("crankset", 2 * (0.9 * cl + 45.0) + sum(rings) * 1.6 + 90.0, p.get("chain_bb", V(0, 0)))
    if d["pedal_type"] != "none":
        add("pedal", 150.0, p["pedal"])
        add("pedal_far", 150.0, p["pedal_l"])
    if drive == "derailleur":
        add("rear_derailleur", 230.0, ax + V(10, -50))
        if d["front_derailleur"] and len(rings) > 1:
            add("front_derailleur", 95.0, g.s * 200.0)
    if drive == "gearbox":
        add("gearbox", 2700.0, V(0, -20))

    # brakes & controls
    for key, axle in (("front", p["front_axle"]), ("rear", ax)):
        kind = d[f"brake_{key}"]
        if kind == "disc":
            add(f"caliper_{key}", 130.0, axle + V(-60 if key == "rear" else -40, 50 if key == "rear" else 60))
        elif kind == "caliper":
            mount = p["crown_bottom"] if key == "front" else p.get("ss_bridge", p["ss_top"])
            add(f"caliper_{key}", 165.0, mount)
        elif kind in ("cantilever", "v"):
            add(f"caliper_{key}", 200.0, axle.lerp(p["crown_bottom"] if key == "front" else p["ss_top"], 0.6))
    lever = d["lever_type"]
    if lever != "none":
        add("levers", 440.0 if lever == "road_sti" else 260.0, p["hoods"])
    add("cables", 150.0, p["dt_ht"].lerp(p["bb"], 0.5))

    # cockpit
    ht = g.tubes["ht"]
    add("headset", 100.0, ht.a.lerp(ht.b, 0.5))
    if d.f("spacers") > 0 and d["stem_type"] != "quill":
        add("spacers", 1.5 * d.f("spacers"), p["ht_top"] + g.u * (d.f("upper_stack") + d.f("spacers") / 2))
    add("stem", 60.0 + 0.9 * d.f("stem_length") + (120.0 if d["stem_type"] == "quill" else 0.0),
        p["stem_clamp"].lerp(p["bar"], 0.5))
    bar_pts = g.bar_path or [p["bar"]]
    bar_c = V(sum(q.x for q in bar_pts) / len(bar_pts), sum(q.y for q in bar_pts) / len(bar_pts))
    add("handlebar", {"drop": 280.0, "flat": 200.0, "riser": 290.0, "bullhorn": 250.0}.get(d["bar_type"], 300.0)
        + 60.0, bar_c)

    # saddle & seatpost
    add("saddle", 250.0, p["saddle"] + V(0, -25))
    post = {"dropper": 560.0, "seatmast": 120.0}.get(d["seatpost_type"], 230.0)
    add("seatpost", post, p["seatpost_top"].lerp(p["seatpost_bottom"], 0.5))

    # accessories
    bd, bl = d.f("bottle_diameter"), d.f("bottle_length")
    full = bool(d.get("com_bottles_full", True))
    for key, tname, side in (("bottle_dt", "dt", 1), ("bottle_st", "st", -1)):
        tb = g.tubes.get(tname)
        if not d[key] or tb is None:
            continue
        s0 = d.f("bottle_dt_pos" if tname == "dt" else "bottle_st_pos")
        pt, tan = tb.point_at(s0 - 35 + bl / 2)
        c = pt + tan.perp() * (side * (tb.od_b / 2 + 5 + bd / 2))
        add(f"bottle_{tname}", 35.0 + (650.0 if full else 80.0), c)
    if d["fenders"]:
        for key, a0, a1 in (("rear", -10, 200), ("front", -20, 220)):
            w = g.wheels[key]
            add(f"fender_{key}", 180.0, _arc_centroid(w.center, w.outer_r + d.f("fender_clearance"), a0, a1))
    if d["rack_rear"]:
        add("rack_rear", 650.0, V(ax.x - 50, ax.y + d.f("rack_height") * 0.75))
    if d["rack_front"]:
        fa = p["front_axle"]
        add("rack_front", 500.0, V(fa.x + 40, (fa.y + p["crown"].y) / 2))

    overrides = d.extras.get("component_masses") or {}
    if overrides:
        res = []
        for name, m, pt in out:
            try:
                m = float(overrides.get(name, m))
            except (TypeError, ValueError):
                pass
            res.append((name, m, pt))
        out = res
    return out


def rider_segments(g: Geometry, pose=None) -> list[tuple[str, float, V]]:
    """Rider body segments as (name, grams, centre of mass)."""
    d = g.design
    pose = pose or solve_pose(g)
    J = pose.joints
    mass_g = anatomy(d)["mass"] * 1000.0
    out = []
    for name, frac, a, b, k, count in RIDER_SEGMENTS:
        out.append((f"rider:{name}", mass_g * frac * count, J[a].lerp(J[b], k)))
    return out


def component_masses(g: Geometry, include_rider: bool = True) -> list[tuple[str, float, V]]:
    """Every mass in the system as (name, grams, position of its centre of mass)."""
    parts = _bike_parts(g)
    if include_rider:
        parts += rider_segments(g)
    return parts


def centre_of_mass(g: Geometry, include_rider: bool = True) -> tuple[V, float, float]:
    """(centre of mass, total mass in grams, fraction of weight on the front wheel)."""
    parts = component_masses(g, include_rider)
    total = sum(m for _, m, _ in parts)
    if total <= 0:
        return V(0, 0), 0.0, float("nan")
    cx = sum(m * q.x for _, m, q in parts) / total
    cy = sum(m * q.y for _, m, q in parts) / total
    xr, xf = g.p["ground_rear"].x, g.p["ground_front"].x
    front = (cx - xr) / (xf - xr) if abs(xf - xr) > 1e-9 else float("nan")
    return V(cx, cy), total, front


def _com_symbol(scene: Scene, c: V, r: float, color: str, width: float, tag: str) -> None:
    layer, z = "analysis", Z_OVER + 6
    scene.circle(c, r, Style(color, width, "#ffffff"), layer, z, tag)
    for a0 in (0.0, 180.0):
        pts = [c] + [c + V.polar(r, a0 + 90.0 * i / 12) for i in range(13)]
        scene.poly(pts, Style(None, 0.0, color), layer, z, True, tag)
    scene.circle(c, r, Style(color, width, None), layer, z, tag)


def draw_com(scene: Scene, g: Geometry, theme: Theme) -> None:
    """Centre-of-mass symbol(s) with total mass and front/rear split (if ``show_com``)."""
    d = g.design
    if not d.get("show_com", False):
        return
    with_rider = bool(d.get("com_include_rider", True))
    col = theme.outline or "#000000"
    c, total, front = centre_of_mass(g, with_rider)
    scene.line(c, V(c.x, g.ground_y), Style(col, 0.25, None, dash=(3.0, 2.0)), "analysis", Z_OVER + 5, "com")
    r = 18.0
    _com_symbol(scene, c, r, col, 0.35, "com")
    label = "Bike + rider" if with_rider else "Bike"
    pos = c + V(r * 1.4, r * 0.4)
    scene.text(pos, f"{label} {total / 1000.0:.1f} kg", Style(col, 0.0, None), 2.6, 0.0, "lb", "analysis",
               Z_OVER + 6, tag="com")
    if front == front:
        scene.text(c + V(r * 1.4, -r * 0.4), f"Front {front * 100:.0f} % / rear {(1 - front) * 100:.0f} %",
                   Style(col, 0.0, None), 2.6, 0.0, "lt", "analysis", Z_OVER + 6, tag="com")
    if with_rider:
        cb, tb, fb = centre_of_mass(g, False)
        grey = "#707070"
        _com_symbol(scene, cb, r * 0.65, grey, 0.25, "com:bike")
        scene.text(cb + V(r, 0), f"Bike {tb / 1000.0:.1f} kg ({fb * 100:.0f} % front)", Style(grey, 0.0, None),
                   2.2, 0.0, "lm", "analysis", Z_OVER + 6, tag="com:bike")


def _register() -> None:
    from ..render import bike_scene
    hooks = bike_scene.EXTRA_BUILDERS
    hooks[:] = [f for f in hooks if (getattr(f, "__module__", None), getattr(f, "__name__", None))
                != (__name__, "draw_com")]
    hooks.append(draw_com)


_register()
