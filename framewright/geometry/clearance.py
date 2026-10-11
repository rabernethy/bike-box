"""3-D clearance analysis and stay fabrication data.

Everything here works on a solved :class:`~framewright.geometry.solver.Geometry`
in model space (mm / degrees, origin at the BB centre, +X forward, +Y up,
+Z drive side) and has no Qt dependency.  ``clearances(g)`` returns a flat
``{key: value}`` table; ``clearance_details(g)`` returns the same keys as
:class:`Contact` records (value plus the two closest points) so drawings can
place a dimension exactly where the gap is.

Models
------
* **Tires** are tori: the cross-section chosen by ``tire_profile`` revolved
  about the axle (which runs along Z).  ``round`` = circle of the tire width
  tangent to the outer radius; ``elliptical`` = width x height ellipse sitting
  on the bead seat; ``square`` = rounded rectangle (knobby shoulders).  The
  3-D distance from a point to a torus equals the 2-D distance in the
  meridional half-plane, so every tire query is a 2-D signed distance.
* **Tubes** are swept elliptical sections along a 3-D centre-line: the
  side-view centre-line from ``Tube.a/b`` (including the side-view bend) plus
  a lateral offset ``z(t)`` (linear ``za -> zb``; chainstays add the top-view
  bend / S-bend and the optional yoke registered here).  The gap between a
  tube and an obstacle is ``SDF(centre) - support(section, direction)``,
  exact for round tubes of constant diameter.
* **Chainrings** are flat discs of radius ``pitch radius + outer clearance``
  and thickness ``chain_width`` at the chainline (rings spaced
  ``chainring_spacing`` apart, biggest outboard).
* **Crank arm** sweeps a shallow cone: its inner face runs from
  ``shell/2 + crank_arm_offset`` at the spindle to ``Q/2 - thickness`` at the
  pedal eye.
* **Feet** stay horizontal: the toe box is a vertical prism (height
  ``TOE_BOX_H``) whose longest point (the big toe, ``TOE_TIP_K`` of the shoe
  width in from the inner edge) reaches ``toe_overhang`` ahead of the
  spindle, rounded back to the full ``shoe_width``; the heel is a vertical cylinder of
  radius ``0.36 * shoe_width`` (height ``HEEL_COUNTER_H``) whose back is
  ``heel_behind_pedal`` behind it.  The shoe centre-line sits
  ``pedal_axle_length`` outboard of the crank face (``q_factor/2``);
  ``heel_in_angle`` rotates the foot in plan view.
* **Steering** rotates the front wheel (and fender) about the steering axis
  (``g.u`` through ``g.p['ht_top']``).  Positive angles steer left, which
  swings the back of the wheel toward the drive-side toe; by symmetry the
  same angle to the right reaches the left toe.
* **Lean**: the bike rolls on the tire sections (the roll line joins the two
  contact points; at the BB its height is interpolated between the wheels)
  until the lowest pedal corner touches the ground.

Fabrication numbers (``stay_fabrication``) give true 3-D lengths, side/top/
rear-view angles, the out-of-plane ("dihedral") angle, the mitre angle at the
receiving tube and the *end phase*: the rotation about the stay axis between
the dropout slot and the mitre at the other end (what a tube notcher needs).
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Callable

from ..model import params as P
from .solver import Geometry, Tube
from .vec import V, V3, arc_through, polyline_length, project_on_line

INF = math.inf
NAN = math.nan
TOE_BOX_H = 35.0          # toe box height above the sole
HEEL_COUNTER_H = 60.0     # heel counter height above the sole
HEEL_WIDTH_K = 0.36       # heel radius as a fraction of shoe width
TOE_TIP_K = 0.30          # longest point of the toe (big toe), fraction of shoe width from the inner edge

# --------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------
_G, _S = "Frame", "3-D & clearances"


def _mm(key, label, default, lo, hi, step=1.0, help="", vis=None):
    return P.ParamDef(key, label, _G, _S, P.FLOAT, float(default), "mm", lo, hi, step, (), help, vis)


P.register([
    P.ParamDef("tire_profile", "Tire cross-section", _G, _S, P.CHOICE, "round",
               choices=(("round", "Round (circle of tire width)"), ("elliptical", "Elliptical (width x height)"),
                        ("square", "Square shoulders (knobby)")),
               help="Shape revolved about the axle for 3-D clearance checks", morph=False),
    P.ParamDef("cs_top_bend_style", "Chainstay shape (top view)", _G, _S, P.CHOICE, "straight",
               choices=(("straight", "Straight"), ("bent", "Single bend"), ("s_bend", "S-bend")), morph=False),
    _mm("cs_top_bend", "Chainstay top-view bend (sagitta)", 0, -40, 40, 0.5,
        "Lateral offset of the bend from the straight stay (+ = outward, away from the tire)",
        ("cs_top_bend_style", ("bent", "s_bend"))),
    P.ParamDef("cs_top_bend_pos", "Chainstay bend position from BB", _G, _S, P.FLOAT, 35.0, "%", 5, 95, 1,
               help="Single bend: apex; S-bend: inflection point (percent of the stay length from the BB)",
               visible_if=("cs_top_bend_style", ("bent", "s_bend"))),
    P.ParamDef("cs_yoke", "Chainstay yoke", _G, _S, P.BOOL, False,
               help="Single-piece yoke behind the BB: narrow at the shell, splitting into the two stays",
               morph=False),
    _mm("cs_yoke_length", "Yoke length from BB centre", 115, 20, 300, 1, vis=("cs_yoke", (True,))),
    _mm("cs_yoke_spread", "Stay spacing at yoke end (c-c)", 76, 20, 250, 0.5, vis=("cs_yoke", (True,))),
    _mm("cs_bridge_width", "Chainstay bridge tube width", 16, 4, 40, 0.1),
    _mm("ss_bridge_width", "Seat stay bridge tube width", 12.7, 4, 40, 0.1),
    _mm("chainring_outer_clearance", "Chainring envelope beyond pitch circle", 6, 0, 30, 0.5,
        "Radial allowance for teeth and chain outside the pitch circle"),
    _mm("chainring_spacing", "Chainring spacing (c-c)", 4.5, 0, 20, 0.1),
    _mm("chain_width", "Chain / chainring envelope width", 6.0, 1, 20, 0.1),
    _mm("crank_arm_offset", "Crank arm inner face outboard of shell face", 8, -20, 40, 0.5,
        "Lateral gap from the BB shell face to the crank arm's inner face at the spindle"),
    _mm("crank_arm_thickness", "Crank arm thickness at pedal eye", 15, 4, 40, 0.5,
        "Q factor is measured over the outer faces; the inner face is this much further in"),
    _mm("pedal_axle_length", "Crank face to shoe centre-line", 53, 10, 120, 0.5),
    _mm("shoe_width", "Shoe width", 100, 50, 160, 1),
    _mm("heel_behind_pedal", "Heel behind pedal spindle", 190, 60, 320, 1),
    P.ParamDef("heel_in_angle", "Foot angle (+ = heel in)", _G, _S, P.FLOAT, 0.0, "deg", -25, 25, 0.5),
    _mm("min_tire_clearance", "Minimum tire clearance", 4, -20, 60, 0.5,
        "Tire clearances below this are flagged in red"),
    _mm("min_part_clearance", "Minimum part clearance", 2, -20, 60, 0.5,
        "Chainring, crank, heel and toe clearances below this are flagged in red"),
    P.ParamDef("min_lean_angle", "Minimum pedal-strike lean angle", _G, _S, P.FLOAT, 25.0, "deg", 0, 60, 0.5),
])


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _support(hd: float, hw: float, e1: V3, e2: V3, d: V3) -> float:
    """Half-extent of an elliptical section (half-depth ``hd`` along ``e1``,
    half-width ``hw`` along ``e2``) in direction ``d`` (support function)."""
    a = d.dot(e1) * hd
    b = d.dot(e2) * hw
    return math.sqrt(a * a + b * b)


def _ellipse_sdf(u: float, v: float, a: float, b: float) -> tuple[float, float, float]:
    """Signed distance from (u, v) to the ellipse (u/a)^2 + (v/b)^2 = 1 and the
    outward unit normal at the closest point (trig-free iteration, accurate
    inside and outside)."""
    x0, y0 = abs(u), abs(v)
    tx = ty = 0.7071067811865476
    a2b2 = a * a - b * b
    for _ in range(5):
        x, y = a * tx, b * ty
        ex = a2b2 * tx ** 3 / a
        ey = -a2b2 * ty ** 3 / b
        rx, ry = x - ex, y - ey
        qx, qy = x0 - ex, y0 - ey
        r = math.hypot(rx, ry)
        q = math.hypot(qx, qy)
        if q < 1e-12:
            break
        tx = _clamp((qx * r / q + ex) / a, 0.0, 1.0)
        ty = _clamp((qy * r / q + ey) / b, 0.0, 1.0)
        t = math.hypot(tx, ty)
        tx, ty = tx / t, ty / t
    cx, cy = a * tx, b * ty
    nx, ny = cx / (a * a), cy / (b * b)
    nn = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nn, ny / nn
    dist = math.hypot(x0 - cx, y0 - cy)
    inside = (x0 / a) ** 2 + (y0 / b) ** 2 < 1.0
    return (-dist if inside else dist), math.copysign(nx, u), math.copysign(ny, v)


def _rbox_sdf(u: float, v: float, a: float, b: float, k: float) -> tuple[float, float, float]:
    """Signed distance to a rounded rectangle (half extents a, b; corner radius k)."""
    qx = abs(u) - (a - k)
    qy = abs(v) - (b - k)
    if qx > 0 and qy > 0:
        L = math.hypot(qx, qy)
        return L - k, math.copysign(qx / L, u), math.copysign(qy / L, v)
    if qx > qy:
        return qx - k, math.copysign(1.0, u), 0.0
    return qy - k, 0.0, math.copysign(1.0, v)


# --------------------------------------------------------------------------
# tires and fenders
# --------------------------------------------------------------------------
@dataclass
class TireModel:
    """Torus tire model: wheel centre (cx, cy), axle along Z; section centre at
    radius ``rc`` with lateral half-width ``a`` and radial half-height ``b``."""
    key: str
    cx: float
    cy: float
    rc: float
    a: float
    b: float
    shape: str
    outer_r: float
    bead_r: float

    @property
    def corner(self) -> float:
        return 0.45 * min(self.a, self.b)

    @property
    def center(self) -> V:
        return V(self.cx, self.cy)

    def section_sdf(self, u: float, v: float) -> tuple[float, float, float]:
        """(signed distance, n_u, n_v) for lateral ``u`` / radial ``v`` measured
        from the section centre."""
        if self.shape == "square":
            return _rbox_sdf(u, v, self.a, self.b, self.corner)
        if self.shape == "round" or abs(self.a - self.b) < 1e-9:
            rr = math.hypot(u, v)
            if rr < 1e-12:
                return -self.a, 0.0, 1.0
            return rr - self.a, u / rr, v / rr
        return _ellipse_sdf(u, v, self.a, self.b)

    def sdf(self, p: V3) -> tuple[float, V3]:
        """Signed distance from ``p`` to the tire surface and the outward unit
        normal at the closest surface point."""
        dx, dy = p.x - self.cx, p.y - self.cy
        r = math.hypot(dx, dy)
        if r < 1e-9:
            dx, dy, r = 1.0, 0.0, 1.0
        d, nu, nv = self.section_sdf(p.z, r - self.rc)
        return d, V3(nv * dx / r, nv * dy / r, nu)

    def outer_half(self, n: int = 24) -> list[tuple[float, float]]:
        """Tread half of the section as (u, v), from (a, 0) over the crown to (-a, 0)."""
        if self.shape == "square":
            a, b, k = self.a, self.b, self.corner
            pts = [(a, 0.0), (a, b - k)]
            m = max(n // 4, 3)
            pts += [(a - k + k * math.cos(math.pi / 2 * i / m), b - k + k * math.sin(math.pi / 2 * i / m))
                    for i in range(1, m + 1)]
            pts += [(-(a - k) + k * math.cos(math.pi / 2 + math.pi / 2 * i / m),
                     b - k + k * math.sin(math.pi / 2 + math.pi / 2 * i / m)) for i in range(0, m + 1)]
            pts += [(-a, 0.0)]
            return pts
        return [(self.a * math.cos(math.pi * i / n), self.b * math.sin(math.pi * i / n)) for i in range(n + 1)]

    def section(self, n: int = 24) -> list[tuple[float, float]]:
        """Closed section outline (u, v)."""
        top = self.outer_half(n)
        return top + [(u, -v) for u, v in reversed(top[1:-1])]

    def half_width_at(self, r: float) -> float:
        """Lateral half-width of the tire at radius ``r`` from the axle."""
        v = r - self.rc
        if v <= 0:
            return self.a if v >= -self.b else 0.0
        if v >= self.b:
            return 0.0
        if self.shape == "square":
            k = self.corner
            if v <= self.b - k:
                return self.a
            dv = v - (self.b - k)
            return self.a - k + math.sqrt(max(k * k - dv * dv, 0.0))
        return self.a * math.sqrt(max(1.0 - (v / self.b) ** 2, 0.0))

    def silhouette(self, n: int = 24) -> list[V]:
        """Outline of the tire seen edge-on (looking along a direction in the
        wheel plane) as (xi, zeta): xi = in-plane offset from the axle,
        zeta = lateral (Z)."""
        top = self.outer_half(n)
        right = [V(self.rc + v, u) for u, v in top]
        left = [V(-(self.rc + v), u) for u, v in reversed(top)]
        return right + left


def tire_model(g: Geometry, key: str) -> TireModel:
    w = g.wheels[key]
    shape = str(g.design.get("tire_profile", "round"))
    if shape == "round":
        a = b = w.tire_w / 2
        rc = w.outer_r - a
    else:
        a, b = w.tire_w / 2, w.tire_h / 2
        rc = w.bsd / 2 + b
    return TireModel(key, w.center.x, w.center.y, rc, a, b, shape, w.outer_r, w.bsd / 2)


@dataclass
class FenderModel:
    """Fender band: radius ``R`` (mid-thickness), lateral half-width
    ``half_w``, covering wheel angles ``a0..a1`` (degrees CCW from +X)."""
    key: str
    cx: float
    cy: float
    R: float
    half_w: float
    half_t: float
    a0: float
    a1: float

    def sdf(self, p: V3) -> float:
        dx, dy = p.x - self.cx, p.y - self.cy
        ang = math.degrees(math.atan2(dy, dx))
        ang = (ang - self.a0) % 360.0 + self.a0
        if ang > self.a1:
            return INF
        r = math.hypot(dx, dy)
        du = max(abs(p.z) - self.half_w, 0.0)
        return math.hypot(du, r - self.R) - self.half_t


FENDER_COVER = {"rear": (-10.0, 200.0), "front": (-20.0, 220.0)}    # matches bike_scene


def fender_model(g: Geometry, key: str) -> FenderModel | None:
    d = g.design
    if not d.get("fenders"):
        return None
    w = g.wheels[key]
    a0, a1 = FENDER_COVER[key]
    return FenderModel(key, w.center.x, w.center.y, w.outer_r + d.f("fender_clearance") + 1.0,
                       d.f("fender_width") / 2, 1.0, a0, a1)


# --------------------------------------------------------------------------
# 3-D tube centre-lines
# --------------------------------------------------------------------------
class Path3:
    """A tube centre-line in 3-D: side-view polyline ``pts`` parametrised by
    arc-length fraction ``t`` (0 at ``pts[0]``), lateral offset ``z_fn(t)``,
    side-view depth ``od_fn(t)`` and top-view width ``w_fn(t)``.  ``vis`` is
    the visible t-range (dropout end to where the tube meets its receiver)."""

    def __init__(self, name: str, pts: list[V], z_fn: Callable[[float], float],
                 od_fn: Callable[[float], float], w_fn: Callable[[float], float] | None = None,
                 vis: tuple[float, float] = (0.0, 1.0), sign: float = 1.0, label: str = ""):
        self.name = name
        self.label = label or name
        self.pts = list(pts)
        cum = [0.0]
        for i in range(1, len(self.pts)):
            cum.append(cum[-1] + self.pts[i - 1].dist(self.pts[i]))
        self.cum = cum
        self.L = cum[-1] if cum[-1] > 1e-9 else 1e-9
        self.z_fn = z_fn
        self.od_fn = od_fn
        self.w_fn = w_fn or od_fn
        self.vis = vis
        self.sign = sign

    def mirror(self) -> "Path3":
        return Path3(self.name, self.pts, self.z_fn, self.od_fn, self.w_fn, self.vis, -self.sign, self.label)

    def xy(self, t: float) -> tuple[V, V]:
        s = _clamp(t, 0.0, 1.0) * self.L
        i = min(max(bisect_right(self.cum, s) - 1, 0), len(self.pts) - 2)
        seg = self.cum[i + 1] - self.cum[i]
        f = (s - self.cum[i]) / seg if seg > 1e-12 else 0.0
        a, b = self.pts[i], self.pts[i + 1]
        return a.lerp(b, f), (b - a).norm()

    def z(self, t: float) -> float:
        return self.sign * self.z_fn(_clamp(t, 0.0, 1.0))

    def point(self, t: float) -> V3:
        p, _ = self.xy(t)
        return V3(p.x, p.y, self.z(t))

    def tangent(self, t: float) -> V3:
        _, tan = self.xy(t)
        h = 1e-4
        t0, t1 = max(0.0, t - h), min(1.0, t + h)
        dz = (self.z(t1) - self.z(t0)) / (t1 - t0)
        return V3(tan.x * self.L, tan.y * self.L, dz).norm()

    def frame(self, t: float) -> tuple[V3, V3, V3, V3, float, float]:
        """(point, tangent, e1 = side-view normal, e2 = lateral, half-depth, half-width)."""
        p, tan = self.xy(t)
        P3 = V3(p.x, p.y, self.z(t))
        T = self.tangent(t)
        n = V3(-tan.y, tan.x, 0.0)
        e1 = (n - T * n.dot(T)).norm()
        e2 = T.cross(e1)
        tt = _clamp(t, 0.0, 1.0)
        return P3, T, e1, e2, self.od_fn(tt) / 2, self.w_fn(tt) / 2

    def ts(self, n: int, t0: float | None = None, t1: float | None = None) -> list[float]:
        a = self.vis[0] if t0 is None else t0
        b = self.vis[1] if t1 is None else t1
        n = max(n, 2)
        return [a + (b - a) * i / (n - 1) for i in range(n)]

    def length(self, t0: float = 0.0, t1: float = 1.0, n: int = 96) -> float:
        pts = [self.point(t) for t in self.ts(n, t0, t1)]
        return sum((pts[i + 1] - pts[i]).length() for i in range(len(pts) - 1))


def _side_pts(tb: Tube, segments: int = 48) -> list[V]:
    return arc_through(tb.a, tb.b, tb.bend, segments) if abs(tb.bend) > 1e-6 else [tb.a, tb.b]


def _bump(t: float, ta: float) -> float:
    """0 at both ends, 1 at ``ta`` (piecewise parabola, C1 at the apex)."""
    if t <= ta:
        return 1.0 - ((ta - t) / ta) ** 2
    return 1.0 - ((t - ta) / (1.0 - ta)) ** 2


def _s_curve(t: float, ta: float) -> float:
    """S-bend: outward hump between the inflection ``ta`` and the BB end
    (t = 1), inward hump toward the dropout."""
    if t >= ta:
        return math.sin(math.pi * (t - ta) / (1.0 - ta))
    return -math.sin(math.pi * t / ta)


def cs_lateral_fn(g: Geometry, tb: Tube, L: float) -> Callable[[float], float]:
    """Chainstay lateral offset z(t), t = 0 at the dropout node, 1 at the BB:
    linear spread, optional yoke and top-view bend / S-bend."""
    d = g.design
    za, zb = tb.za, tb.zb
    if d.get("cs_yoke"):
        ty = _clamp(1.0 - d.f("cs_yoke_length") / max(L, 1e-9), 0.02, 0.98)
        zy = d.f("cs_yoke_spread") / 2

        def base(t: float) -> float:
            if t <= ty:
                return za + (zy - za) * t / ty
            return zy + (zb - zy) * (t - ty) / (1.0 - ty)
    else:
        def base(t: float) -> float:
            return za + (zb - za) * t
    style = d.get("cs_top_bend_style", "straight")
    sag = d.f("cs_top_bend")
    ta = _clamp(1.0 - d.f("cs_top_bend_pos") / 100.0, 0.05, 0.95)
    if style == "bent" and abs(sag) > 1e-9:
        return lambda t: base(t) + sag * _bump(t, ta)
    if style == "s_bend" and abs(sag) > 1e-9:
        return lambda t: base(t) + sag * _s_curve(t, ta)
    return base


def _line_dist(p: V3, a: V3, d: V3) -> float:
    w = p - a
    return (w - d * w.dot(d)).length()


def drive_bb(g: Geometry) -> V:
    """Centre of the BB the chainstays and chainrings belong to (the stoker BB of a tandem)."""
    return g.p.get("stoker_bb", V(0.0, 0.0))


def receiver_axis(g: Geometry, join: str | None) -> tuple[V3, V3, float] | None:
    """(point, unit axis, radius) of the tube a stay end meets."""
    d = g.design
    if join in ("bb", "bb2"):
        c = drive_bb(g) if join == "bb2" else V(0.0, 0.0)
        return V3(c.x, c.y, 0), V3(0, 0, 1), d.f("bb_shell_od") / 2
    tb = g.tubes.get(join or "")
    if tb is None:
        return None
    a, b = V3(tb.a.x, tb.a.y, 0.0), V3(tb.b.x, tb.b.y, 0.0)
    return a, (b - a).norm(), max(tb.od_a, tb.od_b) / 2


def _exit_t(path: Path3, recv: tuple[V3, V3, float] | None, t_lo: float) -> float:
    """Largest t at which the centre-line is still outside the receiving cylinder."""
    if recv is None:
        return 1.0
    a, dirn, R = recv
    if _line_dist(path.point(1.0), a, dirn) >= R:
        return 1.0
    lo, hi = t_lo, 1.0
    if _line_dist(path.point(lo), a, dirn) < R:
        return lo
    for _ in range(40):
        mid = (lo + hi) / 2
        if _line_dist(path.point(mid), a, dirn) >= R:
            lo = mid
        else:
            hi = mid
    return lo


def stay_path(g: Geometry, name: str) -> Path3 | None:
    """Drive-side 3-D centre-line of a stay (``cs``, ``ss`` or ``ss_mono``)."""
    tb = g.tubes.get(name)
    if tb is None:
        return None
    pts = _side_pts(tb)
    L = polyline_length(pts)
    if name == "cs":
        z_fn = cs_lateral_fn(g, tb, L)
    else:
        za, zb = tb.za, tb.zb
        z_fn = lambda t: za + (zb - za) * t
    t0 = 0.0
    if tb.draw_a is not None and tb.chord > 1e-9:
        t0 = _clamp(project_on_line(tb.draw_a, tb.a, tb.b - tb.a) / tb.chord, 0.0, 0.9)
    path = Path3(name, pts, z_fn, tb.od_at, tb.w_at, (t0, 1.0), label=tb.label)
    join_b = tb.join_b if name != "ss_mono" else tb.join_b
    path.vis = (t0, max(t0, _exit_t(path, receiver_axis(g, join_b), t0)))
    return path


def tube_path(g: Geometry, name: str) -> Path3 | None:
    """In-plane (z = 0) main tube as a Path3, visible from the receiving tube at its ``a`` end."""
    tb = g.tubes.get(name)
    if tb is None:
        return None
    pts = _side_pts(tb)
    path = Path3(name, pts, lambda t: 0.0, tb.od_at, tb.w_at, label=tb.label)
    t0 = 0.0
    if tb.join_a in ("bb", "bb2"):
        R = g.design.f("bb_shell_od") / 2
        c = drive_bb(g) if tb.join_a == "bb2" else V(0.0, 0.0)
        lo, hi = 0.0, 0.5
        for _ in range(40):
            mid = (lo + hi) / 2
            p = path.point(mid)
            if math.hypot(p.x - c.x, p.y - c.y) < R:
                lo = mid
            else:
                hi = mid
        t0 = hi
    path.vis = (t0, 1.0)
    return path


def fork_leg_path(g: Geometry) -> Path3 | None:
    """Drive-side fork blade (rigid) or stanchion + lower leg (suspension)."""
    fk = g.tubes.get("fork")
    if fk is None:
        return None
    d = g.design
    ax = g.p["front_axle"]
    fr, zc = fk.za, fk.zb
    z_fn = lambda t: fr + (zc - fr) * t
    if d["fork_type"] == "suspension":
        AC = g.v["fork_length"]
        ch = d.f("fork_crown_height")
        L = max(AC - ch, 10.0)
        pts = [ax, ax + g.u * L]
        st = d.f("fork_stanchion_od")
        t_low = _clamp(AC * 0.55 / L, 0.0, 1.0)
        od_fn = lambda t: st + 10.0 if t <= t_low else st
        return Path3("fork", pts, z_fn, od_fn, od_fn, (_clamp(12.0 / L, 0, 0.5), 1.0), label="Fork leg")
    pts = _side_pts(fk)
    L = polyline_length(pts)
    return Path3("fork", pts, z_fn, fk.od_at, fk.w_at, (_clamp(26.0 / max(L, 1.0), 0, 0.5), 1.0),
                 label="Fork blade")


# --------------------------------------------------------------------------
# contacts
# --------------------------------------------------------------------------
@dataclass
class Contact:
    """A clearance: ``value`` (mm, negative = interference), ``p`` = closest
    point on the first part's surface, ``q`` = closest point on the second."""
    value: float
    p: V3 | None = None
    q: V3 | None = None
    t: float = NAN
    extra: dict = field(default_factory=dict)

    @staticmethod
    def none() -> "Contact":
        return Contact(NAN)


SdfFn = Callable[[V3], tuple[float, V3]]


def tube_contact(path: Path3, sdf: SdfFn, t0: float | None = None, t1: float | None = None,
                 n: int = 40) -> Contact:
    """Minimum gap between a tube and an obstacle given by its signed distance
    function (coarse sampling + golden-section refinement)."""
    def ev(t: float):
        P3, T, e1, e2, hd, hw = path.frame(t)
        dist, gr = sdf(P3)
        if not math.isfinite(dist):
            return INF, P3, gr, dist, 0.0
        h = _support(hd, hw, e1, e2, gr)
        return dist - h, P3, gr, dist, h

    ts = path.ts(n, t0, t1)
    vals = [ev(t)[0] for t in ts]
    i = min(range(len(ts)), key=lambda k: vals[k])
    if not math.isfinite(vals[i]):
        return Contact(INF)
    lo, hi = ts[max(i - 1, 0)], ts[min(i + 1, len(ts) - 1)]
    gr_ = 0.6180339887498949
    c, d_ = hi - gr_ * (hi - lo), lo + gr_ * (hi - lo)
    fc, fd = ev(c)[0], ev(d_)[0]
    for _ in range(28):
        if fc < fd:
            hi, d_, fd = d_, c, fc
            c = hi - gr_ * (hi - lo)
            fc = ev(c)[0]
        else:
            lo, c, fc = c, d_, fd
            d_ = lo + gr_ * (hi - lo)
            fd = ev(d_)[0]
    tb = (lo + hi) / 2
    best = min(((vals[i], ts[i]), (ev(tb)[0], tb)), key=lambda x: x[0])
    val, P3, gr, dist, h = ev(best[1])
    return Contact(val, P3 - gr * h, P3 - gr * dist, best[1])


def _disc_sdf(p: V3, z0: float, R: float, ht: float, c: V = V(0.0, 0.0)) -> tuple[float, V3]:
    """Signed distance to a disc (radius R, half-thickness ht) in the plane z = z0, centred on the BB axis at ``c``."""
    px, py = p.x - c.x, p.y - c.y
    rho = math.hypot(px, py)
    ex, ey = (px / rho, py / rho) if rho > 1e-9 else (1.0, 0.0)
    dzs = p.z - z0
    sz = 1.0 if dzs >= 0 else -1.0
    dr, dz = rho - R, abs(dzs) - ht
    if dr > 0 and dz > 0:
        L = math.hypot(dr, dz)
        return L, V3(ex * dr / L, ey * dr / L, sz * dz / L)
    if dr > dz:
        return dr, V3(ex, ey, 0.0)
    return dz, V3(0.0, 0.0, sz)


def pitch_radius(teeth: float, pitch: float = 12.7) -> float:
    return pitch / (2 * math.sin(math.pi / max(teeth, 3)))


@dataclass
class Ring:
    teeth: float
    z: float
    r_pitch: float
    r_out: float
    half_t: float


def chainrings(g: Geometry) -> list[Ring]:
    """Chainring envelopes, biggest (outermost) first."""
    d = g.design
    rings = sorted(d.lst("chainrings") or [42.0], reverse=True)
    pitch = d.f("belt_pitch") if d["drive_type"] == "belt" else d.f("chain_pitch")
    n = len(rings)
    sp, cl = d.f("chainring_spacing"), d.f("chainline")
    out = []
    for i, teeth in enumerate(rings):
        rp = pitch_radius(teeth, pitch)
        out.append(Ring(teeth, cl + ((n - 1) / 2 - i) * sp, rp, rp + d.f("chainring_outer_clearance"),
                        d.f("chain_width") / 2))
    return out


def crank_faces(g: Geometry) -> tuple[float, float]:
    """Lateral position of the crank arm's inner face at the spindle and at the pedal eye."""
    d = g.design
    return (d.f("bb_shell_width") / 2 + d.f("crank_arm_offset"),
            d.f("q_factor") / 2 - d.f("crank_arm_thickness"))


def shoe_z(g: Geometry) -> float:
    d = g.design
    return d.f("q_factor") / 2 + d.f("pedal_axle_length")


def crank_contact(g: Geometry, cs: Path3) -> Contact:
    """Crank arm inner face (swept through a full turn) to the drive-side chainstay."""
    cl = g.design.f("crank_length")
    z0, z1 = crank_faces(g)
    bb = drive_bb(g)
    best = Contact(INF)
    ez = V3(0, 0, 1)
    for t in cs.ts(120):
        P3, T, e1, e2, hd, hw = cs.frame(t)
        rho = math.hypot(P3.x - bb.x, P3.y - bb.y)
        if rho > cl + 12.0:
            continue
        zc = z0 + (z1 - z0) * min(rho, cl) / max(cl, 1e-9)
        h = _support(hd, hw, e1, e2, ez)
        c = zc - (P3.z + h)
        if c < best.value:
            best = Contact(c, V3(P3.x, P3.y, P3.z + h), V3(P3.x, P3.y, zc), t)
    return best


def bridge_contact(g: Geometry, path: Path3, t: float, width: float, tire: TireModel) -> Contact:
    """A bridge tube (along Z, between the two stays at parameter ``t``) to the tire."""
    P3, T, e1, e2, hd, hw = path.frame(t)
    zin = max(abs(P3.z) - hw, 0.0)
    r = width / 2
    best = Contact(INF)
    for k in range(11):
        z = -zin + 2 * zin * k / 10
        Q = V3(P3.x, P3.y, z)
        dist, gr = tire.sdf(Q)
        if dist - r < best.value:
            best = Contact(dist - r, Q - gr * r, Q - gr * dist, t, {"z_in": zin})
    return best


def ss_bridge_s(g: Geometry) -> float:
    """Distance along the seat stay from the dropout node to the bridge (same rule as the side view)."""
    d = g.design
    pos = d.f("ss_bridge_pos")
    if pos <= 0:
        w = g.wheels["rear"]
        pos = (w.rim_r - 6 + d.f("brake_reach")) if d["brake_rear"] == "caliper" else w.outer_r + 12
    return pos


def crown_points(g: Geometry) -> list[V3]:
    """Sample points over the fork crown's underside (plane normal to the steering axis)."""
    d = g.design
    cb, u, n = g.p["crown_bottom"], g.u, g.n
    cw = d.f("fork_crown_width") / 2
    if d["fork_type"] == "suspension":
        AC = g.v["fork_length"]
        top = g.p["front_axle"] + u * (AC - d.f("fork_crown_height"))
        nt = (top - cb).dot(n)
        st = d.f("fork_stanchion_od")
        hs = d.f("steerer_od") / 2 + 6
        n0, n1 = min(-hs, nt - st / 2 - 6), max(hs, nt + st / 2 + 6)
    else:
        half = d.f("fork_blade_od") / 2 + 4
        n0, n1 = -half, half
    pts = []
    for i in range(9):
        z = -cw + 2 * cw * i / 8
        for j in range(7):
            nn = n0 + (n1 - n0) * j / 6
            pts.append(V3(cb.x + n.x * nn, cb.y + n.y * nn, z))
    return pts


def crown_contact(g: Geometry, tire: TireModel, fender: FenderModel | None = None) -> Contact:
    best = Contact(INF)
    for Q in crown_points(g):
        if fender is not None:
            dist = fender.sdf(Q)
            if dist < best.value:
                best = Contact(dist, Q, None)
            continue
        dist, gr = tire.sdf(Q)
        if dist < best.value:
            best = Contact(dist, Q, Q - gr * dist)
    return best


# --------------------------------------------------------------------------
# feet
# --------------------------------------------------------------------------
def heel_contact(g: Geometry, paths: list[Path3]) -> Contact:
    """Heel (vertical cylinder, foot horizontal) through a full crank turn vs
    the drive-side stays in ``paths``."""
    d = g.design
    cl = d.f("crank_length")
    stack = d.f("pedal_stack")
    rh = HEEL_WIDTH_K * d.f("shoe_width")
    back = max(d.f("heel_behind_pedal") - rh, 0.0)
    al = math.radians(d.f("heel_in_angle"))
    hdx = -back * math.cos(al)
    hz = shoe_z(g) - back * math.sin(al)
    bb = drive_bb(g)
    samples = []
    for path in paths:
        for t in path.ts(36):
            samples.append((path, t) + path.frame(t))

    def at(theta: float, keep: bool = False):
        px = bb.x + cl * math.cos(math.radians(theta))
        py = bb.y + cl * math.sin(math.radians(theta))
        cx, y0 = px + hdx, py + stack
        y1 = y0 + HEEL_COUNTER_H
        best = (INF, None)
        for (path, t, P3, T, e1, e2, hd, hw) in samples:
            ddx, ddz = P3.x - cx, P3.z - hz
            rxz = math.hypot(ddx, ddz)
            dxz = rxz - rh
            dy = max(y0 - P3.y, P3.y - y1)
            if dy <= 0:
                dist = dxz
                n = V3(ddx / rxz, 0, ddz / rxz) if rxz > 1e-9 else V3(0, 0, -1)
            elif dxz <= 0:
                dist = dy
                n = V3(0, 1 if P3.y > y1 else -1, 0)
            else:
                L = math.hypot(dxz, dy)
                dist = L
                n = V3(ddx / rxz * dxz / L, (1 if P3.y > y1 else -1) * dy / L, ddz / rxz * dxz / L)
            h = _support(hd, hw, e1, e2, n)
            c = dist - h
            if c < best[0]:
                best = (c, (path, t, P3, n, h, dist))
        return best

    coarse = [(th, at(th)[0]) for th in range(0, 360, 5)]
    th0 = min(coarse, key=lambda x: x[1])[0]
    lo, hi = th0 - 5.0, th0 + 5.0
    for _ in range(30):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if at(m1)[0] < at(m2)[0]:
            hi = m2
        else:
            lo = m1
    th = (lo + hi) / 2
    val, info = at(th)
    if info is None:
        return Contact(INF)
    path, t, P3, n, h, dist = info
    return Contact(val, P3 + n * h, P3 + n * dist, t, {"crank_deg": th % 360.0, "tube": path.name})


def _toe_local(g: Geometry, n: int = 6) -> list[tuple[float, float]]:
    """Toe box outline in the foot frame: (forward of the spindle, lateral
    from the shoe centre-line, + = outboard), inner edge first."""
    d = g.design
    w = d.f("shoe_width")
    ri, ro = TOE_TIP_K * w, (1.0 - TOE_TIP_K) * w
    tip = d.f("toe_overhang")
    loc = [(tip - 1.6 * ri, 0.0)]                  # inner edge, behind the toe box
    for i in range(n + 1):                         # inner quarter: inner edge -> tip
        a = math.pi / 2 * i / n
        loc.append((tip - ri + ri * math.sin(a), ri - ri * math.cos(a)))
    for i in range(1, n + 1):                      # outer quarter: tip -> outer edge
        a = math.pi / 2 * i / n
        loc.append((tip - 0.8 * ro + 0.8 * ro * math.cos(a), ri + ro * math.sin(a)))
    return [(fx, lz - w / 2) for fx, lz in loc]


def _foot_to_plan(g: Geometry, crank_deg: float, loc: list[tuple[float, float]], bb_x: float = 0.0) -> list[V]:
    """Foot frame -> plan (x, z) for the drive-side foot (heel_in_angle applied)."""
    d = g.design
    al = math.radians(d.f("heel_in_angle"))
    px = bb_x + d.f("crank_length") * math.cos(math.radians(crank_deg))
    zc = shoe_z(g)
    ca, sa = math.cos(al), math.sin(al)
    return [V(px + fx * ca - lz * sa, zc + fx * sa + lz * ca) for fx, lz in loc]


def toe_outline(g: Geometry, crank_deg: float = 0.0, n: int = 6) -> list[V]:
    """Plan-view (x, z) outline of the drive-side shoe's toe box, inner edge
    first, crank at ``crank_deg`` (0 = horizontal forward).

    The longest point (big toe) sits ``TOE_TIP_K`` of the shoe width in from
    the inner edge, ``toe_overhang`` ahead of the spindle; the inner and outer
    sides are quarter ellipses back to the full shoe width."""
    return _foot_to_plan(g, crank_deg, _toe_local(g, n))


def shoe_outline(g: Geometry, crank_deg: float = 0.0, bb_x: float = 0.0) -> list[V]:
    """Closed plan-view (x, z) outline of the whole drive-side shoe (crank centre at x = ``bb_x``)."""
    d = g.design
    w = d.f("shoe_width")
    rh = HEEL_WIDTH_K * w
    back = max(d.f("heel_behind_pedal") - rh, 0.0)
    loc = _toe_local(g)
    heel = [(-back - rh * math.sin(math.pi * i / 12), rh * math.cos(math.pi * i / 12)) for i in range(13)]
    return _foot_to_plan(g, crank_deg, loc + heel, bb_x)


def toe_points(g: Geometry, crank_deg: float = 0.0) -> list[V3]:
    """Surface samples of the drive-side toe box (crank at ``crank_deg``, 0 = horizontal forward)."""
    d = g.design
    py = d.f("crank_length") * math.sin(math.radians(crank_deg))
    y0 = py + d.f("pedal_stack")
    plan = toe_outline(g, crank_deg)
    return [V3(p.x, y0 + h, p.y) for h in (0.0, TOE_BOX_H / 2, TOE_BOX_H) for p in plan]


def _steer_matrix(g: Geometry, deg: float):
    k = V3(g.u.x, g.u.y, 0.0).norm()
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    C = 1 - c
    kx, ky, kz = k.x, k.y, k.z
    return ((c + kx * kx * C, kx * ky * C - kz * s, kx * kz * C + ky * s),
            (ky * kx * C + kz * s, c + ky * ky * C, ky * kz * C - kx * s),
            (kz * kx * C - ky * s, kz * ky * C + kx * s, c + kz * kz * C))


def steer_point(g: Geometry, p: V3, deg: float) -> V3:
    """Rotate ``p`` by ``deg`` about the steering axis (+ = steer left: the
    front of the wheel goes to -Z, its back toward the drive-side toe)."""
    H = g.p["ht_top"]
    R = _steer_matrix(g, deg)
    vx, vy, vz = p.x - H.x, p.y - H.y, p.z
    return V3(H.x + R[0][0] * vx + R[0][1] * vy + R[0][2] * vz,
              H.y + R[1][0] * vx + R[1][1] * vy + R[1][2] * vz,
              R[2][0] * vx + R[2][1] * vy + R[2][2] * vz)


def _toe_min(g: Geometry, deg: float, tire: TireModel, fender: FenderModel | None,
             pts: list[V3]) -> tuple[float, int]:
    """Fast scan: (smallest gap, index of the toe sample) with the wheel steered ``deg``."""
    H = g.p["ht_top"]
    R = _steer_matrix(g, -deg)
    (a, b, c), (d_, e, f), (gg, h, i) = R
    best, bi = INF, -1
    cx, cy, rc = tire.cx, tire.cy, tire.rc
    for idx, p in enumerate(pts):
        vx, vy, vz = p.x - H.x, p.y - H.y, p.z
        x = H.x + a * vx + b * vy + c * vz
        y = H.y + d_ * vx + e * vy + f * vz
        z = gg * vx + h * vy + i * vz
        dist = tire.section_sdf(z, math.hypot(x - cx, y - cy) - rc)[0]
        if fender is not None:
            dist = min(dist, fender.sdf(V3(x, y, z)))
        if dist < best:
            best, bi = dist, idx
    return best, bi


def toe_gap(g: Geometry, deg: float, tire: TireModel | None = None, fender: FenderModel | None = None,
            pts: list[V3] | None = None) -> Contact:
    """Gap between the toe and the front tire (+ fender) with the wheel steered
    ``deg``; ``p`` = toe point, ``q`` = closest tire point (both in the world frame)."""
    tire = tire or tire_model(g, "front")
    pts = pts if pts is not None else toe_points(g)
    val, idx = _toe_min(g, deg, tire, fender, pts)
    if idx < 0:
        return Contact(INF)
    p = pts[idx]
    w = steer_point(g, p, -deg)
    dist, gr = tire.sdf(w)
    q = steer_point(g, w - gr * dist, deg)
    return Contact(val, p, q, deg)


def toe_steer_angle(g: Geometry, max_deg: float = 90.0, step: float = 1.5) -> float | None:
    """Smallest steer angle (degrees, either direction) at which the toe
    (crank horizontal forward) touches the front tire or fender; None if
    it never does up to ``max_deg``."""
    tire = tire_model(g, "front")
    fender = fender_model(g, "front")
    pts = toe_points(g)
    gap = lambda a: _toe_min(g, a, tire, fender, pts)[0]
    if gap(0.0) <= 0:
        return 0.0
    a_prev = 0.0
    a = step
    while a <= max_deg + 1e-9:
        if gap(a) <= 0:
            lo, hi = a_prev, a
            for _ in range(22):
                mid = (lo + hi) / 2
                if gap(mid) <= 0:
                    hi = mid
                else:
                    lo = mid
            return hi
        a_prev = a
        a += step
    return None


# --------------------------------------------------------------------------
# lean angle
# --------------------------------------------------------------------------
@dataclass
class LeanResult:
    angle: float                    # degrees
    pivot_eta: float                # upright height (rel. to BB) of the roll line at the BB
    tire_pts: list[tuple[float, float]]     # rear tire bottom section (zeta, eta) in the BB plane
    pedal_pts: list[tuple[float, float]]    # pedal corners (zeta, eta)
    wf: float                       # front-wheel weight of the roll-line interpolation
    bb: V = field(default_factory=V)  # BB the result refers to (eta is relative to it)


def lean_solution(g: Geometry, bb: V | None = None) -> LeanResult:
    """Pedal-strike lean angle with the tires rolling on their sections.
    Rear-view coordinates (zeta lateral, eta up) at the BB ``bb`` (default:
    the lowest-angle BB, i.e. the stoker BB of a tandem if that is worse);
    leaning to +Z."""
    if bb is None:
        cands = [lean_solution(g, V(0.0, 0.0))]
        if "stoker_bb" in g.p:
            cands.append(lean_solution(g, g.p["stoker_bb"]))
        return min(cands, key=lambda r: r.angle)
    d = g.design
    rear, front = tire_model(g, "rear"), tire_model(g, "front")
    xr, xf = rear.cx, front.cx
    wf = _clamp((bb.x - xr) / (xf - xr), 0.0, 1.0) if abs(xf - xr) > 1e-9 else 0.5

    def bottom(tm: TireModel):
        return [(u, tm.cy - bb.y - (tm.rc + v)) for u, v in tm.outer_half(96)]

    rp, fp = bottom(rear), bottom(front)
    cl = d.f("crank_length")
    yb = -cl - d.f("pedal_thickness") / 2
    q2 = d.f("q_factor") / 2
    pedal = [(q2 + d.f("pedal_width"), yb), (q2, yb)]

    def low(pts, phi):
        s, c = math.sin(phi), math.cos(phi)
        return min(-z * s + e * c for z, e in pts)

    def h(phi):
        return low(pedal, phi) - ((1 - wf) * low(rp, phi) + wf * low(fp, phi))

    pivot = (1 - wf) * min(e for _, e in rp) + wf * min(e for _, e in fp)
    result_bb = bb
    if h(0.0) <= 0:
        ang = 0.0
    elif h(math.radians(89.9)) > 0:
        ang = 89.9
    else:
        lo, hi = 0.0, math.radians(89.9)
        for _ in range(50):
            mid = (lo + hi) / 2
            if h(mid) > 0:
                lo = mid
            else:
                hi = mid
        ang = math.degrees((lo + hi) / 2)
    return LeanResult(ang, pivot, rp, pedal, wf, result_bb)


# --------------------------------------------------------------------------
# stay fabrication data
# --------------------------------------------------------------------------
def _signed_angle(a: V3, b: V3, axis: V3) -> float:
    return math.degrees(math.atan2(axis.dot(a.cross(b)), a.dot(b)))


def _fold90(a: float) -> float:
    """Fold an angle into (-90, 90] (a notch is symmetric under 180 deg rotation)."""
    a = (a + 90.0) % 180.0 - 90.0
    return 90.0 if abs(a + 90.0) < 1e-9 else a


def stay_fabrication(g: Geometry, name: str) -> dict[str, float]:
    """True lengths and angles of a stay for fabrication.

    Keys: ``true_length`` (3-D centre-line, node to junction), ``chord``,
    ``visible_length`` (centre-line from the dropout end to the receiving tube
    surface), ``side_angle`` / ``top_angle`` / ``rear_angle`` (chord angle in
    each view: from horizontal, from the centre plane, from vertical),
    ``plane_angle`` (out of the frame plane), ``mitre_angle`` (between the
    stay's end tangent and the receiving tube axis), ``phase`` (rotation about
    the chord between the dropout slot plane and the mitre's symmetry plane)
    and ``dropout_angle`` (stay end tangent vs the dropout plate plane)."""
    path = stay_path(g, name)
    tb = g.tubes.get(name)
    if path is None or tb is None:
        return {}
    a3, b3 = path.point(0.0), path.point(1.0)
    ch = b3 - a3
    L3 = ch.length()
    D = ch.norm()
    dx, dy, dz = abs(ch.x), abs(ch.y), abs(ch.z)
    out = {
        "true_length": path.length(0.0, 1.0),
        "chord": L3,
        "visible_length": path.length(path.vis[0], path.vis[1]),
        "side_angle": math.degrees(math.atan2(dy, dx)),
        "top_angle": math.degrees(math.atan2(dz, dx)) if dx > 1e-9 else 90.0,
        "rear_angle": math.degrees(math.atan2(dz, dy)) if dy > 1e-9 else 90.0,
        "plane_angle": math.degrees(math.asin(_clamp(dz / max(L3, 1e-9), 0.0, 1.0))),
    }
    Ta = path.tangent(0.0)
    out["dropout_angle"] = math.degrees(math.asin(_clamp(abs(Ta.z), 0.0, 1.0)))
    recv = receiver_axis(g, tb.join_b)
    if recv is not None:
        A = recv[1]
        Tb = path.tangent(1.0)
        out["mitre_angle"] = math.degrees(math.acos(_clamp(abs(Tb.dot(A)), 0.0, 1.0)))
        Z = V3(0, 0, 1)
        Na = (Z - D * Z.dot(D))
        Nb = D.cross(A)
        if Na.length() > 1e-9 and Nb.length() > 1e-9:
            out["phase"] = abs(_fold90(_signed_angle(Na.norm(), Nb.norm(), D)))
        else:
            out["phase"] = 0.0
    return out


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------
TIRE_KEYS = ("cs_tire", "ss_tire", "st_tire", "cs_bridge_tire", "ss_bridge_tire", "fork_crown_tire",
             "fork_crown_tire_bottomed", "fork_crown_fender", "fork_blade_tire")
PART_KEYS = ("cs_chainring", "cs_crank", "heel", "heel_cs", "heel_ss", "toe_clearance_3d")

LABELS: dict[str, tuple[str, str]] = {
    "cs_tire": ("Chainstay to tire", "mm"),
    "cs_chainring": ("Chainstay to chainring", "mm"),
    "cs_crank": ("Crank arm to chainstay", "mm"),
    "cs_bridge_tire": ("Chainstay bridge to tire", "mm"),
    "ss_tire": ("Seat stay to tire", "mm"),
    "ss_bridge_tire": ("Seat stay bridge to tire", "mm"),
    "st_tire": ("Seat tube to tire", "mm"),
    "fork_crown_tire": ("Fork crown to tire", "mm"),
    "fork_crown_tire_bottomed": ("Fork crown to tire (bottomed out)", "mm"),
    "fork_crown_fender": ("Fork crown to fender", "mm"),
    "fork_blade_tire": ("Fork blade to tire", "mm"),
    "heel": ("Heel clearance", "mm"),
    "heel_cs": ("Heel to chainstay", "mm"),
    "heel_ss": ("Heel to seat stay", "mm"),
    "toe_clearance_3d": ("Toe to front tire (straight)", "mm"),
    "toe_steer_angle": ("Toe overlap steer angle", "deg"),
    "lean_angle_3d": ("Pedal-strike lean angle", "deg"),
    "ss_bridge_length": ("Seat stay bridge length (inside)", "mm"),
    "cs_bridge_length": ("Chainstay bridge length (inside)", "mm"),
}
for _n, _lab in (("cs", "Chainstay"), ("ss", "Seat stay")):
    for _k, _l, _u in (("true_length", "true length", "mm"), ("chord", "chord (c-c)", "mm"),
                       ("visible_length", "cut length (centre-line)", "mm"),
                       ("side_angle", "side-view angle", "deg"), ("top_angle", "top-view angle", "deg"),
                       ("rear_angle", "rear-view angle", "deg"), ("plane_angle", "out-of-plane angle", "deg"),
                       ("mitre_angle", "mitre angle", "deg"), ("phase", "end phase", "deg"),
                       ("dropout_angle", "dropout angle", "deg")):
        LABELS[f"{_n}_{_k}"] = (f"{_lab} {_l}", _u)


def clearance_details(g: Geometry, use_cache: bool = True) -> dict[str, Contact]:
    """All 3-D clearances as :class:`Contact` records (see ``LABELS``).
    Missing parts give ``Contact(nan)``; "never touches" gives ``inf``."""
    if use_cache:
        cached = getattr(g, "_fw_clearance_details", None)
        if cached is not None:
            return cached
    d = g.design
    out: dict[str, Contact] = {}
    rear, front = tire_model(g, "rear"), tire_model(g, "front")
    rear_sdf = rear.sdf
    cs, ss, mono = stay_path(g, "cs"), stay_path(g, "ss"), stay_path(g, "ss_mono")

    if cs is not None:
        out["cs_tire"] = tube_contact(cs, rear_sdf)
        rings = chainrings(g)
        best = Contact(INF)
        bbc = drive_bb(g)
        for ring in rings:
            c = tube_contact(cs, lambda p, r=ring: _disc_sdf(p, r.z, r.r_out, r.half_t, bbc))
            c.extra["teeth"] = ring.teeth
            if c.value < best.value:
                best = c
        out["cs_chainring"] = best
        out["cs_crank"] = crank_contact(g, cs)
        if d.get("cs_bridge"):
            t = _clamp(1.0 - d.f("cs_bridge_pos") / cs.L, cs.vis[0], cs.vis[1])
            out["cs_bridge_tire"] = bridge_contact(g, cs, t, d.f("cs_bridge_width"), rear)
    else:
        for k in ("cs_tire", "cs_chainring", "cs_crank"):
            out[k] = Contact.none()

    if ss is not None:
        c = tube_contact(ss, rear_sdf)
        if mono is not None:
            m = tube_contact(Path3("ss_mono", mono.pts, lambda t: 0.0, mono.od_fn, mono.w_fn, mono.vis), rear_sdf)
            if m.value < c.value:
                c = m
        out["ss_tire"] = c
        if d.get("ss_bridge"):
            t = _clamp(ss_bridge_s(g) / ss.L, ss.vis[0], ss.vis[1])
            out["ss_bridge_tire"] = bridge_contact(g, ss, t, d.f("ss_bridge_width"), rear)
    else:
        out["ss_tire"] = Contact.none()

    st = tube_path(g, "st2" if "st2" in g.tubes else "st")
    out["st_tire"] = tube_contact(st, rear_sdf) if st is not None else Contact.none()

    out["fork_crown_tire"] = crown_contact(g, front)
    if d["fork_type"] == "suspension":
        rem = d.f("fork_travel") * (1.0 - d.f("fork_sag") / 100.0)
        c = out["fork_crown_tire"]
        out["fork_crown_tire_bottomed"] = Contact(c.value - rem, c.p, c.q, extra={"travel_left": rem})
    ffend = fender_model(g, "front")
    if ffend is not None:
        out["fork_crown_fender"] = crown_contact(g, front, ffend)
    leg = fork_leg_path(g)
    out["fork_blade_tire"] = tube_contact(leg, front.sdf) if leg is not None else Contact.none()

    heel_paths = [p for p in (cs, ss) if p is not None]
    if heel_paths:
        hc = heel_contact(g, [cs]) if cs is not None else Contact.none()
        hs = heel_contact(g, [ss]) if ss is not None else Contact.none()
        out["heel_cs"], out["heel_ss"] = hc, hs
        vals = [c for c in (hc, hs) if math.isfinite(c.value)]
        out["heel"] = min(vals, key=lambda c: c.value) if vals else Contact(INF)
    out["toe_clearance_3d"] = toe_gap(g, 0.0, front, ffend)
    ang = toe_steer_angle(g)
    if ang is None:
        out["toe_steer_angle"] = Contact(INF)
    else:
        c = toe_gap(g, ang, front, ffend)
        out["toe_steer_angle"] = Contact(ang, c.p, c.q, ang)
    out["lean_angle_3d"] = Contact(lean_solution(g).angle)

    for name in ("cs", "ss"):
        for k, v in stay_fabrication(g, name).items():
            out[f"{name}_{k}"] = Contact(v)
    if ss is not None and d.get("ss_bridge"):
        out["ss_bridge_length"] = Contact(2 * out["ss_bridge_tire"].extra.get("z_in", NAN))
    if cs is not None and d.get("cs_bridge"):
        out["cs_bridge_length"] = Contact(2 * out["cs_bridge_tire"].extra.get("z_in", NAN))
    if use_cache:
        try:
            g._fw_clearance_details = out
        except AttributeError:
            pass
    return out


def clearances(g: Geometry) -> dict[str, float]:
    """3-D clearances (mm), angles (deg) and stay fabrication numbers.

    Clearances are surface-to-surface gaps (negative = interference):
    ``cs_tire``, ``cs_chainring``, ``cs_crank``, ``cs_bridge_tire``,
    ``ss_tire``, ``ss_bridge_tire``, ``st_tire``, ``fork_crown_tire``
    (+ ``_bottomed`` for suspension forks), ``fork_crown_fender``,
    ``fork_blade_tire``, ``heel`` / ``heel_cs`` / ``heel_ss``,
    ``toe_clearance_3d``.  ``toe_steer_angle`` is ``inf`` when the toe never
    touches.  ``lean_angle_3d`` is the pedal-strike lean.  Fabrication keys
    are ``cs_*`` / ``ss_*`` from :func:`stay_fabrication`."""
    return {k: c.value for k, c in clearance_details(g).items()}


def threshold(g: Geometry, key: str) -> float | None:
    d = g.design
    if key in TIRE_KEYS:
        return d.f("min_tire_clearance")
    if key in PART_KEYS:
        return d.f("min_part_clearance")
    if key == "lean_angle_3d":
        return d.f("min_lean_angle")
    return None


def is_problem(g: Geometry, key: str, value: float | None = None) -> bool:
    """True when a clearance is below its threshold (or the toe can touch the tire)."""
    if value is None:
        value = clearance_details(g).get(key, Contact.none()).value
    if value != value:
        return False
    if key == "toe_steer_angle":
        return math.isfinite(value)
    lim = threshold(g, key)
    return lim is not None and value < lim


def problems(g: Geometry) -> list[str]:
    """Human-readable messages for every clearance below its threshold."""
    out = []
    for k, c in clearance_details(g).items():
        if not is_problem(g, k, c.value):
            continue
        label, unit = LABELS.get(k, (k, "mm"))
        if k == "toe_steer_angle":
            out.append(f"Toe touches the front tire at {c.value:.1f}° of steering")
        elif unit == "deg":
            out.append(f"{label} only {c.value:.1f}°")
        else:
            out.append(f"{label} {c.value:.1f} mm")
    return out
