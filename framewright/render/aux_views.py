"""Auxiliary views (BikeCAD Pro style): plan view of the rear and front ends,
rear view of the stays, fork crown clearance, pedal-strike lean angle, toe
overlap and true-length views of the stays.

Each builder takes a solved :class:`Geometry` and returns a self-contained
:class:`Scene` (model mm, +Y up on the page) with dimensions of the key
clearances; values come from :mod:`framewright.geometry.clearance` (true 3-D
gaps, even where the 2-D projection shows a different distance).  Anything
below its threshold is drawn in red.

Projections (page x, page y) from model (x, y, z):

* plan / top view, looking down:      (x, -z)   front to the right, drive side at the bottom
* rear view, looking forward:         (z, y)    drive side on the right
* fork front view, looking back along the head-tube normal ``g.n``:
                                      (-z, (p - front_axle) . g.u)   drive side on the left,
                                      steering axis vertical
* lean view: rear view at the BB, leaning toward the drive side
* toe view: side view (x, y) above a plan view (x, -z) sharing the X axis
* stay views: auxiliary views in the plane of each stay's chord and the axis
  of the tube it meets, so true length and the true mitre angle show.

``AUX_VIEWS`` lists ``(title, builder)`` for the GUI.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

from ..geometry import clearance as CL
from ..geometry.solver import Geometry
from ..geometry.vec import V, V3, bbox, circle_points, offset_polyline
from ..model.units import fmt_angle, fmt_len
from .scene import (Z_BACK, Z_CENTERLINE, Z_COMPONENT, Z_DIM, Z_FRAME, Z_FRONT, Z_GROUND, Z_NOTE, Z_OVER,
                    Z_STAY, Z_WHEEL, AngleDim, Arc, Circle, LinearDim, Polyline, Prim, Scene, Style, Text)
from .theme import Theme

PROBLEM = "#d02020"
GOOD = "#1f9d55"
Proj = Callable[[V3], V]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _stroke(pts: Sequence[V], halves: Sequence[float], caps: bool = False) -> list[V]:
    """Outline polygon of a thick 2-D polyline with per-vertex half widths."""
    cl, hw = [], []
    for p, h in zip(pts, halves):
        if cl and p.dist(cl[-1]) < 1e-6:
            continue
        cl.append(p)
        hw.append(h)
    if len(cl) < 2:
        c = pts[0]
        r = max(halves[0], 0.5)
        return circle_points(c, r, 24)[:-1]
    left = offset_polyline(cl, hw)
    right = offset_polyline(cl, [-h for h in hw])
    out = list(left)
    if caps:
        d = (cl[-1] - cl[-2]).norm()
        out += [cl[-1] + d.rot(a) * hw[-1] for a in range(90, -91, -30)][1:-1]
    out += list(reversed(right))
    if caps:
        d = (cl[0] - cl[1]).norm()
        out += [cl[0] + d.rot(a) * hw[0] for a in range(90, -91, -30)][1:-1]
    return out


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[V]:
    return [V(x0, y0), V(x1, y0), V(x1, y1), V(x0, y1)]


def _band(a: V, b: V, half: float) -> list[V]:
    d = (b - a).norm().perp() * half
    return [a + d, b + d, b - d, a - d]


def _hull(points: Sequence[V]) -> list[V]:
    pts = sorted(set((round(p.x, 6), round(p.y, 6)) for p in points))
    if len(pts) <= 2:
        return [V(*p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [V(*p) for p in lower[:-1] + upper[:-1]]


def _shift(prims: Sequence[Prim], dv: V) -> None:
    """Translate primitives in place."""
    for p in prims:
        if isinstance(p, Polyline):
            p.pts = [q + dv for q in p.pts]
            p.holes = [[q + dv for q in h] for h in p.holes]
        elif isinstance(p, (Circle, Arc)):
            p.c = p.c + dv
        elif isinstance(p, Text):
            p.pos = p.pos + dv
        elif isinstance(p, LinearDim):
            p.p1, p.p2 = p.p1 + dv, p.p2 + dv
        elif isinstance(p, AngleDim):
            p.vertex = p.vertex + dv


def _prim_bounds(prims: Sequence[Prim]) -> tuple[float, float, float, float]:
    sc = Scene()
    sc.prims = list(prims)
    return sc.bounds()


def _fmt(value: float, unit: str, units: str) -> str:
    if value != value:
        return "–"
    if math.isinf(value):
        return "none" if value > 0 else "-∞"
    if unit == "deg":
        return fmt_angle(value)
    return fmt_len(value, units)


class _View:
    """Shared state and drawing helpers for one auxiliary view."""

    def __init__(self, g: Geometry, theme: Theme | None):
        self.g = g
        self.d = g.design
        self.t = theme or Theme.from_design(g.design)
        self.sc = Scene()
        self.sc.background = self.t.bg
        self.units = self.d["units"]
        self.det = CL.clearance_details(g)
        self.size = 10.0                      # model-mm text size (set_size)
        self.extents: list[tuple[float, float, float, float]] = []

    # styles -------------------------------------------------------------------
    @property
    def filled(self) -> bool:
        return self.t.mode == "filled"

    def frame_st(self) -> Style:
        return self.t.frame(self.t.frame_fill if self.filled else self.t.component_fill)

    def fork_st(self) -> Style:
        return self.t.frame(self.t.fork_fill if self.filled else self.t.component_fill)

    def tire_st(self, opacity: float = 1.0) -> Style:
        return Style(self.t.outline, self.t.width, self.t.tire if self.filled else None, opacity=opacity)

    def comp_st(self, color: str = "#9a9a9a") -> Style:
        return self.t.comp(color if self.filled else "default")

    def hidden_st(self) -> Style:
        return Style(self.t.outline, self.t.width * 0.45, None, dash=(2.0, 1.2))

    def ghost_st(self) -> Style:
        return Style(self.t.outline, self.t.width * 0.45, None, dash=(3.0, 1.5), opacity=0.6)

    def dim_st(self, problem: bool = False) -> Style:
        return self.t.dimension().with_(stroke=PROBLEM) if problem else self.t.dimension()

    # primitives ---------------------------------------------------------------
    def poly(self, pts, style, layer="frame", z=Z_FRAME, closed=True, tag=""):
        if len(pts) >= 2:
            self.sc.poly(pts, style, layer, z, closed, tag)

    def outline(self, path: CL.Path3, proj: Proj, vdir: V3, t0: float | None = None, t1: float | None = None,
                n: int = 28, caps: bool = False) -> list[V]:
        """Projected silhouette of a 3-D tube (orthographic, viewing along ``vdir``)."""
        cl, hw = [], []
        for t in path.ts(n, t0, t1):
            P3, T, e1, e2, hd, hwid = path.frame(t)
            w = T.cross(vdir)
            w = w.norm() if w.length() > 1e-6 else e1
            cl.append(proj(P3))
            hw.append(CL._support(hd, hwid, e1, e2, w))
        return _stroke(cl, hw, caps)

    def tube(self, path, proj, vdir, style, layer="frame", z=Z_STAY, tag="", caps=False, both=True,
             dropout_end=True):
        for p in ((path, path.mirror()) if both else (path,)):
            self.poly(self.outline(p, proj, vdir, caps=caps), style, layer, z, True, tag)
            if dropout_end and p.vis[0] > 1e-6:
                self.poly(self.outline(p, proj, vdir, 0.0, p.vis[0], 6), self.hidden_st(), layer, z - 1, True, tag)

    def centre(self, pts, layer="centerlines"):
        self.poly(pts, self.t.centre(), layer, Z_CENTERLINE, False)

    def mark(self, p: V, r: float = 6.0, color: str | None = None):
        st = Style(color or self.t.centerline, 0.25)
        self.sc.line(p - V(r, 0), p + V(r, 0), st, "centerlines", Z_CENTERLINE)
        self.sc.line(p - V(0, r), p + V(0, r), st, "centerlines", Z_CENTERLINE)

    def lin(self, p1: V, p2: V, offset: float, text: str, mode: str = "aligned", problem: bool = False,
            tag: str = ""):
        self.sc.add(LinearDim("dimensions", Z_DIM, self.dim_st(problem), tag, p1, p2, offset, mode, text))

    def ang(self, vertex: V, start: float, span: float, radius: float, text: str, problem: bool = False,
            tag: str = ""):
        self.sc.add(AngleDim("dimensions", Z_DIM, self.dim_st(problem), tag, vertex, start, span, radius, text))

    def value(self, key: str) -> float:
        c = self.det.get(key)
        return c.value if c is not None else math.nan

    def problem(self, key: str) -> bool:
        return CL.is_problem(self.g, key, self.value(key))

    def contact(self, key: str, proj: Proj) -> tuple[V, V, float, bool] | None:
        """Projected contact points of a clearance: (p, q, value, problem)."""
        c = self.det.get(key)
        if c is None or c.p is None or c.q is None or not math.isfinite(c.value):
            return None
        return proj(c.p), proj(c.q), c.value, self.problem(key)

    def gap_mark(self, p1: V, p2: V, bad: bool, tag: str = "") -> None:
        col = PROBLEM if bad else self.t.dim
        st = Style(col, 0.25, col)
        r = 0.18 * self.size
        self.sc.circle(p1, r, st, "dimensions", Z_DIM, tag)
        self.sc.circle(p2, r, st, "dimensions", Z_DIM, tag)
        if p1.dist(p2) > 0.3:
            self.sc.line(p1, p2, Style(col, 0.45), "dimensions", Z_DIM, tag)

    def label(self, pos: V, s: str, anchor: str = "lm", color: str | None = None, k: float = 0.62,
              bold: bool = False, layer: str = "dimensions") -> None:
        """Model-sized label whose estimated extent is included in the panel border."""
        size = self.size * k
        self.sc.text(pos, s, Style(color or self.t.outline, 0.25), size, 0.0, anchor, layer, Z_NOTE,
                     annotative=False, bold=bold)
        w, h = len(s) * 0.76 * size, 1.5 * size
        x0 = {"l": pos.x, "c": pos.x - w / 2, "r": pos.x - w}[anchor[0]]
        y0 = {"b": pos.y, "m": pos.y - h / 2, "t": pos.y - h}[anchor[1] if len(anchor) > 1 else "m"]
        self.extents.append((x0, y0, x0 + w, y0 + h))

    def callout(self, key: str, proj: Proj, at: V, label: str, side: str = "right") -> None:
        """Mark a clearance (true 3-D value) and lead it to a label at ``at``."""
        c = self.contact(key, proj)
        if c is None:
            return
        p1, p2, val, bad = c
        self.gap_mark(p1, p2, bad, f"clear:{key}")
        col = PROBLEM if bad else self.t.dim
        mid = p1.lerp(p2, 0.5)
        sgn = 1.0 if side == "right" else -1.0
        shelf = V(at.x - sgn * 0.8 * self.size, at.y)
        self.poly([mid, shelf, at], Style(col, 0.25), "dimensions", Z_DIM, False, f"clear:{key}")
        self.label(at + V(sgn * 0.3 * self.size, 0), f"{label} {_fmt(val, 'mm', self.units)}",
                   "lm" if side == "right" else "rm", col, bold=bad)

    def callouts_column(self, items: Sequence[tuple[str, str]], proj: Proj, x: float, side: str = "right",
                        spacing: float | None = None) -> None:
        """Stack callouts in a column at page x, ordered by contact height so leaders do not cross."""
        sp = spacing or 1.5 * self.size
        rows = []
        for key, lab in items:
            c = self.contact(key, proj)
            if c is not None:
                rows.append((c[0].lerp(c[1], 0.5).y, key, lab))
        rows.sort(key=lambda r: -r[0])
        ys: list[float] = []
        for y, _, _ in rows:
            ys.append(min(y, ys[-1] - sp) if ys else y)
        for (y, key, lab), yy in zip(rows, ys):
            self.callout(key, proj, V(x, yy), lab, side)

    def callouts_stair(self, items: Sequence[tuple[str, str]], proj: Proj, y: float,
                       spacing: float | None = None) -> None:
        """Callouts below the drawing: ordered by contact x, each one row lower."""
        sp = spacing or 1.5 * self.size
        rows = []
        for key, lab in items:
            c = self.contact(key, proj)
            if c is not None:
                rows.append((c[0].lerp(c[1], 0.5).x, key, lab))
        rows.sort()
        last_x = -math.inf
        for i, (x, key, lab) in enumerate(rows):
            xx = max(x + 1.5 * self.size, last_x + 2.0 * self.size)
            last_x = xx
            self.callout(key, proj, V(xx, y - i * sp), lab, "right")

    def set_size(self, start: int = 0) -> None:
        """Choose the model-mm text size from the drawing extent so far."""
        x0, y0, x1, y1 = _prim_bounds(self.sc.prims[start:])
        self.size = max(5.0, min(16.0, 0.026 * max(x1 - x0, y1 - y0, 50.0)))

    def text(self, pos: V, s: str, size: float = 2.8, anchor: str = "lb", color: str | None = None,
             bold: bool = False, layer: str = "notes"):
        self.sc.text(pos, s, Style(color or self.t.outline, 0.25), size, 0.0, anchor, layer, Z_NOTE, bold=bold)

    # panels -------------------------------------------------------------------
    def panel(self, title: str, start: int, lines: Sequence[tuple[str, bool]] = (), place: str = "auto",
              margin: float | None = None) -> tuple[float, float, float, float]:
        """Frame the primitives added since ``start`` with a border, a title and
        a notes table (model-sized text, so the border encloses it)."""
        prims = self.sc.prims[start:]
        x0, y0, x1, y1 = _prim_bounds(prims)
        for ex in self.extents:
            x0, y0, x1, y1 = min(x0, ex[0]), min(y0, ex[1]), max(x1, ex[2]), max(y1, ex[3])
        self.extents = []
        w, h = max(x1 - x0, 50.0), max(y1 - y0, 50.0)
        size = self.size
        m = margin if margin is not None else 1.6 * size
        lines = list(lines)
        tsz = size * 0.72
        line_h = 1.7 * tsz
        tw = max((len(s) for s, _ in lines), default=0) * 0.76 * tsz
        th = len(lines) * line_h
        if place == "auto":
            place = "below" if w > 1.3 * h else "right"
        if lines:
            if place == "below":
                tx, ty = x0, y0 - m
                y0 = ty - th
                x1 = max(x1, x0 + tw)
            else:
                tx, ty = x1 + m, y1
                x1 = tx + tw
                y0 = min(y0, ty - th)
            for i, (s, bad) in enumerate(lines):
                self.sc.text(V(tx, ty - i * line_h), s, Style(PROBLEM if bad else self.t.outline, 0.25),
                             tsz, 0.0, "lt", "notes", Z_NOTE, annotative=False, bold=bad)
        title_h = 1.9 * size
        bx0, by0, bx1, by1 = x0 - m, y0 - m, x1 + m, y1 + title_h + m
        self.sc.text(V(bx0 + 0.6 * size, by1 - 0.5 * size), title, Style(self.t.outline, 0.25), size, 0.0, "lt",
                     "notes", Z_NOTE, annotative=False, bold=True)
        self.poly(_rect(bx0, by0, bx1, by1), Style("#9aa3ad", 0.25, None), "aux_frame", Z_NOTE - 1)
        return bx0, by0, bx1, by1

    def line_for(self, key: str, label: str | None = None) -> tuple[str, bool] | None:
        c = self.det.get(key)
        if c is None:
            return None
        lab, unit = CL.LABELS.get(key, (key, "mm"))
        return f"{label or lab}: {_fmt(c.value, unit, self.units)}", self.problem(key)

    def lines_for(self, keys: Sequence[str | tuple[str, str]]) -> list[tuple[str, bool]]:
        out = []
        for k in keys:
            key, lab = (k, None) if isinstance(k, str) else k
            ln = self.line_for(key, lab)
            if ln is not None:
                out.append(ln)
        return out


def _tire_sil(tm: CL.TireModel, place: Callable[[V], V]) -> list[V]:
    return [place(q) for q in tm.silhouette()]


def _rim_width(tire_w: float) -> float:
    return max(13.0, min(0.62 * tire_w, 45.0))


def _hub(v: _View, key: str, place: Callable[[float, float], V], axial: float = 1.0):
    """Hub, flanges and a few spokes of a wheel seen edge-on. ``place(lateral, radial)``."""
    w = v.g.wheels[key]
    d = v.d
    half = w.hub_spacing / 2
    fl = d.f("hub_flange_front" if key == "front" else "hub_flange_rear") / 2
    st = v.comp_st("#b0b0b0")
    v.poly([place(-half, -9), place(half, -9), place(half, 9), place(-half, 9)], st, "wheels", Z_BACK - 4,
           True, f"hub:{key}")
    zf = half - (18.0 if key == "rear" else 12.0)
    spoke = Style("#777777" if v.filled else v.t.outline, 0.13)
    for s in (-1, 1):
        v.poly([place(s * zf - 1.5, -fl), place(s * zf + 1.5, -fl), place(s * zf + 1.5, fl),
                place(s * zf - 1.5, fl)], st, "wheels", Z_BACK - 4, True, f"hub:{key}")
        for r in (-1, 1):
            v.sc.line(place(s * zf, r * fl), place(s * 2.0, r * w.rim_inner_r), spoke, "wheels", Z_BACK - 5)
    v.sc.line(place(-half - 9, 0), place(half + 9, 0), Style(v.t.outline, v.t.width * 0.8), "wheels",
              Z_FRAME + 2, f"axle:{key}")


# --------------------------------------------------------------------------
# plan view
# --------------------------------------------------------------------------
def top_view_scene(g: Geometry, theme: Theme | None = None) -> Scene:
    """Plan view (x, -z): rear triangle, BB, chainrings, cranks, heel path,
    rear and front tires, fork and handlebar."""
    v = _View(g, theme)
    sc, t, d = v.sc, v.t, v.d
    start = len(sc.prims)
    TP: Proj = lambda p: V(p.x, -p.z)
    vd = V3(0, -1, 0)
    rear, front = CL.tire_model(g, "rear"), CL.tire_model(g, "front")
    x_lo = rear.cx - rear.outer_r - 30
    x_hi = front.cx + front.outer_r + 30
    v.centre([V(x_lo, 0), V(x_hi, 0)])

    # tires & fenders
    for tm in (rear, front):
        v.poly(_tire_sil(tm, lambda q, tm=tm: V(tm.cx + q.x, -q.y)), v.tire_st(), "wheels", Z_WHEEL, True,
               f"tire:{tm.key}")
        fm = CL.fender_model(g, tm.key)
        if fm is not None:
            xs = [tm.cx + fm.R * math.cos(math.radians(fm.a0 + (fm.a1 - fm.a0) * i / 40)) for i in range(41)]
            v.poly(_rect(min(xs), -fm.half_w, max(xs), fm.half_w), v.hidden_st(), "accessories", Z_WHEEL + 1,
                   True, f"fender:{tm.key}")
    for key, tm in (("rear", rear), ("front", front)):
        _hub(v, key, lambda lat, rad, tm=tm: V(tm.cx + rad * 0.6, -lat))

    # chainstays (+ yoke, bridge), seat stays
    cs, ss = CL.stay_path(g, "cs"), CL.stay_path(g, "ss")
    fst = v.frame_st()
    if cs is not None:
        v.tube(cs, TP, vd, fst, "frame", Z_STAY, "tube:cs", caps=False)
        if d.get("cs_yoke"):
            ty = max(cs.vis[0], 1.0 - d.f("cs_yoke_length") / cs.L)
            ts = cs.ts(12, ty, cs.vis[1])
            hw = [cs.frame(tt)[5] for tt in ts]
            outer = [V(cs.point(tt).x, -(cs.z(tt) + h)) for tt, h in zip(ts, hw)]
            v.poly(outer + [V(q.x, -q.y) for q in reversed(outer)], fst, "frame", Z_STAY + 1, True, "yoke")
        if d.get("cs_bridge"):
            tb = max(cs.vis[0], min(cs.vis[1], 1.0 - d.f("cs_bridge_pos") / cs.L))
            P3, _, _, _, _, hw = cs.frame(tb)
            zin = abs(P3.z) - hw
            bw = d.f("cs_bridge_width") / 2
            v.poly(_rect(P3.x - bw, -zin, P3.x + bw, zin), fst, "frame", Z_STAY - 1, True, "brazeon:cs_bridge")
        v.centre([TP(cs.point(tt)) for tt in cs.ts(16, 0.0, 1.0)])
        v.centre([TP(cs.mirror().point(tt)) for tt in cs.ts(16, 0.0, 1.0)])
    if ss is not None:
        v.tube(ss, TP, vd, fst.with_(opacity=0.9), "frame", Z_FRAME - 2, "tube:ss")
        if d.get("ss_bridge"):
            tb = max(ss.vis[0], min(ss.vis[1], CL.ss_bridge_s(g) / ss.L))
            P3, _, _, _, _, hw = ss.frame(tb)
            zin = abs(P3.z) - hw
            bw = d.f("ss_bridge_width") / 2
            v.poly(_rect(P3.x - bw, -zin, P3.x + bw, zin), fst, "frame", Z_FRAME - 3, True, "brazeon:ss_bridge")
    mono = CL.stay_path(g, "ss_mono")
    if mono is not None:
        v.tube(mono, TP, vd, fst, "frame", Z_FRAME - 1, "tube:ss_mono", both=False, dropout_end=False)

    # dropouts
    ax = g.p["rear_axle"]
    half = g.wheels["rear"].hub_spacing / 2
    for s in (1, -1):
        v.poly(_rect(ax.x - 16, s * half, ax.x + 24, s * (half + 6)), v.comp_st("#8a8a8a"), "frame", Z_STAY + 2,
               True, "dropout")

    # main tubes (plan bands)
    for name in ("st", "tt", "dt"):
        tb = g.tubes.get(name)
        if tb is None:
            continue
        path = CL.tube_path(g, name)
        v.poly(v.outline(path, TP, vd, n=4), fst, "frame", Z_FRAME, True, f"tube:{name}")
    ht = g.tubes["ht"]
    v.poly(_band(V(ht.a.x, 0), V(ht.b.x, 0), max(ht.od_a, ht.od_b) / 2), v.t.frame(v.t.ht_fill or fst.fill),
           "frame", Z_FRAME + 2, True, "tube:ht")
    W = d.f("bb_shell_width")
    R = d.f("bb_shell_od") / 2
    bbx = CL.drive_bb(g).x
    for x_ in sorted({0.0, bbx}):
        v.poly(_rect(x_ - R, -W / 2, x_ + R, W / 2), fst, "frame", Z_FRAME + 2, True, "tube:bb")

    # drivetrain: chainrings, cassette, cranks, pedals
    rings = CL.chainrings(g)
    rst = v.comp_st("#9c9c9c")
    for ring in rings:
        v.poly(_rect(bbx - ring.r_out, -(ring.z + ring.half_t), bbx + ring.r_out, -(ring.z - ring.half_t)), rst,
               "drivetrain", Z_COMPONENT, True, "chainring")
    cogs = sorted(d.lst("cogs") or [16])
    pitch = d.f("belt_pitch") if d["drive_type"] == "belt" else d.f("chain_pitch")
    rc_max = CL.pitch_radius(cogs[-1], pitch) + 3
    cw = max(len(cogs) * 3.9, 8.0) if d["drive_type"] == "derailleur" else 8.0
    clz = d.f("chainline")
    v.poly(_rect(ax.x - rc_max, -(clz + cw / 2), ax.x + rc_max, -(clz - cw / 2)), rst, "drivetrain",
           Z_STAY - 2, True, "cassette")
    cl = d.f("crank_length")
    z0, z1 = CL.crank_faces(g)
    th = d.f("crank_arm_thickness")
    q2 = d.f("q_factor") / 2
    crank_st = v.comp_st("#2b2b2b")
    hc = v.det.get("heel")
    heel_deg = hc.extra.get("crank_deg", 180.0) if hc is not None and hc.extra else 180.0
    xd = cl * math.cos(math.radians(heel_deg))
    for s, xp in ((1, bbx + xd), (-1, bbx - xd)):
        arm = [V(bbx, -s * z0), V(xp, -s * z1), V(xp, -s * q2), V(bbx, -s * (z0 + th))]
        v.poly(arm, crank_st, "drivetrain", Z_COMPONENT + 2, True, "crank")
        if d["pedal_type"] != "none":
            v.poly(_rect(xp - 35, -s * q2, xp + 35, -s * (q2 + d.f("pedal_width"))), v.comp_st("#3a3a3a"),
                   "drivetrain", Z_COMPONENT + 2, True, "pedal")

    # shoe at the heel-critical crank angle, heel path
    bad_heel = v.problem("heel")
    shoe = CL.shoe_outline(g, heel_deg, bbx)
    v.poly([TP(V3(p.x, 0, p.y)) for p in shoe], Style(PROBLEM if bad_heel else v.t.outline, 0.3, None,
                                                       dash=(2.5, 1.5)), "analysis", Z_OVER, True, "shoe")
    rh = CL.HEEL_WIDTH_K * d.f("shoe_width")
    back = d.f("heel_behind_pedal") - rh
    al = math.radians(d.f("heel_in_angle"))
    zh = CL.shoe_z(g) - back * math.sin(al) - rh * math.cos(al)
    hx = bbx - back * math.cos(al)
    v.poly([V(-cl + hx - rh, -zh), V(cl + hx + rh, -zh)], Style(PROBLEM if bad_heel else GOOD, 0.3, None,
                                                                dash=(4.0, 1.5)), "analysis", Z_OVER, False,
           "heel_path")
    v.text(V(-cl + hx - rh, -zh - 8), "heel path", 2.4, "lt", PROBLEM if bad_heel else GOOD, layer="analysis")

    # fork, crown, handlebar
    leg = CL.fork_leg_path(g)
    if leg is not None:
        v.tube(leg, TP, vd, v.fork_st(), "fork", Z_FRONT, "fork", dropout_end=False)
        fax = g.p["front_axle"]
        fh = g.wheels["front"].hub_spacing / 2
        for s in (1, -1):
            v.poly(_rect(fax.x - 14, s * fh, fax.x + 14, s * (fh + 5)), v.comp_st("#8a8a8a"), "fork", Z_FRONT + 1,
                   True, "fork:end")
    cb = g.p["crown_bottom"]
    cwh = d.f("fork_crown_width") / 2 + d.f("fork_blade_od") / 2 + 5
    v.poly(_rect(cb.x - d.f("fork_blade_od") / 2 - 6, -cwh, cb.x + d.f("fork_blade_od") / 2 + 6, cwh), v.fork_st(),
           "fork", Z_FRONT + 2, True, "fork:crown")
    bar = g.p["bar"]
    bw = d.f("bar_width") / 2
    bod = d.f("bar_od") / 2
    clamp = g.p["stem_clamp"]
    v.poly(_band(V(clamp.x, 0), V(bar.x, 0), 16), v.comp_st("#2e2e2e"), "cockpit", Z_COMPONENT + 4, True, "stem")
    v.poly(_rect(bar.x - bod, -bw, bar.x + bod, bw), v.comp_st("#1f1f1f"), "cockpit", Z_COMPONENT + 5, True, "bar")

    # dimensions
    v.set_size(start)
    rw = g.wheels["rear"]
    v.lin(V(ax.x, -half), V(ax.x, half), -(rear.outer_r + 20), f"OLD {fmt_len(rw.hub_spacing, v.units)}",
          "vertical")
    if cs is not None:
        pb = cs.point(cs.vis[1])
        v.lin(V(pb.x, -abs(pb.z)), V(pb.x, abs(pb.z)), -45, f"CS c-c {fmt_len(2 * abs(pb.z), v.units)}",
              "vertical")
    v.lin(V(bbx + R, -W / 2), V(bbx + R, W / 2), 12, f"shell {fmt_len(W, v.units)}", "vertical")
    big = rings[0] if rings else None
    if big is not None:
        mid = sum(r.z for r in rings) / len(rings)
        v.lin(V(bbx, 0), V(bbx, -mid), big.r_out + 18, f"chainline {fmt_len(mid, v.units)}", "vertical")
    xp = bbx + abs(xd)
    v.lin(V(xp, -q2), V(xp, q2), 70, f"Q {fmt_len(2 * q2, v.units)}", "vertical")
    fax = g.p["front_axle"]
    fw = g.wheels["front"]
    v.lin(V(fax.x, -fw.hub_spacing / 2), V(fax.x, fw.hub_spacing / 2), front.outer_r + 30,
          f"hub {fmt_len(fw.hub_spacing, v.units)}", "vertical")
    v.lin(V(bar.x, -bw), V(bar.x, bw), 40, f"bar {fmt_len(2 * bw, v.units)}", "vertical")
    y_low = _prim_bounds(sc.prims[start:])[1]
    v.callouts_stair([("heel", "heel"), ("cs_tire", "CS-tire"), ("cs_bridge_tire", "bridge-tire"),
                      ("cs_chainring", "CS-ring"), ("cs_crank", "crank-CS"), ("fork_blade_tire", "blade-tire")],
                     TP, y_low - 1.5 * v.size)

    lines = v.lines_for(["cs_tire", "cs_chainring", "cs_crank", "cs_bridge_tire", "ss_tire", "heel",
                         "fork_blade_tire", "cs_top_angle", "cs_bridge_length"])
    v.panel("Top view (plan) — 3-D clearances", start, lines, "below")
    return sc


# --------------------------------------------------------------------------
# rear view
# --------------------------------------------------------------------------
def rear_view_scene(g: Geometry, theme: Theme | None = None) -> Scene:
    """Rear view (z, y), looking forward from behind: stays converging to the
    dropouts, tire section, bridges, BB shell, chainrings."""
    v = _View(g, theme)
    sc, t, d = v.sc, v.t, v.d
    start = len(sc.prims)
    RP: Proj = lambda p: V(p.z, p.y)
    vd = V3(1, 0, 0)
    tm = CL.tire_model(g, "rear")
    rw = g.wheels["rear"]
    cy = tm.cy
    gx = max(rw.hub_spacing / 2 + 70, d.f("q_factor") / 2 + 40)
    sc.line(V(-gx, g.ground_y), V(gx, g.ground_y), Style(t.outline, t.width * 0.8), "ground", Z_GROUND)

    # far parts: BB shell, seat tube, chainrings
    fst = v.frame_st()
    W, R = d.f("bb_shell_width"), d.f("bb_shell_od") / 2
    by = CL.drive_bb(g).y
    v.poly(_rect(-W / 2, by - R, W / 2, by + R), fst, "frame", Z_BACK, True, "tube:bb")
    st = g.tubes.get("st2") or g.tubes.get("st")
    if st is not None:
        v.poly(_rect(-st.w_b / 2, by + R, st.w_b / 2, st.b.y), fst, "frame", Z_BACK, True, "tube:st")
    for ring in CL.chainrings(g):
        v.poly(_rect(ring.z - ring.half_t, by - ring.r_out, ring.z + ring.half_t, by + ring.r_out),
               v.comp_st("#9c9c9c"),
               "drivetrain", Z_BACK + 1, True, "chainring")
    _hub(v, "rear", lambda lat, rad: V(lat, cy + rad))

    # tire (semi-transparent so the seat tube and bridges behind it show)
    v.poly(_tire_sil(tm, lambda q: V(q.y, cy + q.x)), v.tire_st(0.82), "wheels", Z_STAY - 5, True, "tire:rear")
    fm = CL.fender_model(g, "rear")
    if fm is not None:
        v.poly(_rect(-fm.half_w, cy, fm.half_w, cy + fm.R + fm.half_t), v.hidden_st(), "accessories", Z_STAY - 4,
               True, "fender:rear")

    # stays and bridges
    cs, ss, mono = CL.stay_path(g, "cs"), CL.stay_path(g, "ss"), CL.stay_path(g, "ss_mono")
    if cs is not None:
        v.tube(cs, RP, vd, fst, "frame", Z_STAY, "tube:cs", caps=True)
        if d.get("cs_bridge"):
            tb = max(cs.vis[0], min(cs.vis[1], 1.0 - d.f("cs_bridge_pos") / cs.L))
            P3, _, _, _, _, hw = cs.frame(tb)
            zin = abs(P3.z) - hw
            v.poly(_band(V(-zin, P3.y), V(zin, P3.y), d.f("cs_bridge_width") / 2), fst, "frame", Z_BACK + 2, True,
                   "brazeon:cs_bridge")
    if ss is not None:
        v.tube(ss, RP, vd, fst, "frame", Z_STAY + 1, "tube:ss", caps=False)
        if d.get("ss_bridge"):
            tb = max(ss.vis[0], min(ss.vis[1], CL.ss_bridge_s(g) / ss.L))
            P3, _, _, _, _, hw = ss.frame(tb)
            zin = abs(P3.z) - hw
            v.poly(_band(V(-zin, P3.y), V(zin, P3.y), d.f("ss_bridge_width") / 2), fst, "frame", Z_BACK + 2, True,
                   "brazeon:ss_bridge")
            if math.isfinite(v.value("ss_bridge_length")):
                v.lin(V(-zin, P3.y), V(zin, P3.y), 22, f"bridge {fmt_len(2 * zin, v.units)}", "horizontal")
    if mono is not None:
        v.tube(mono, RP, vd, fst, "frame", Z_STAY + 2, "tube:ss_mono", both=False, dropout_end=False)
    half = rw.hub_spacing / 2
    for s in (1, -1):
        v.poly(_rect(s * half, cy - 22, s * (half + 6), cy + 26), v.comp_st("#8a8a8a"), "frame", Z_FRAME + 1, True,
               "dropout")
    v.centre([V(0, g.ground_y - 10), V(0, (st.b.y if st is not None else cy + tm.outer_r) + 20)])
    v.mark(V(0, cy))

    # dimensions
    v.set_size(start)
    gy = g.ground_y
    v.lin(V(-tm.a, cy - tm.rc), V(tm.a, cy - tm.rc), -(cy - tm.rc - gy) - 1.6 * v.size,
          f"tire {fmt_len(2 * tm.a, v.units)}", "horizontal")
    v.lin(V(-half, cy), V(half, cy), -(cy - gy) - 4.0 * v.size, f"OLD {fmt_len(rw.hub_spacing, v.units)}",
          "horizontal")
    if ss is not None:
        top = ss.point(1.0)
        v.lin(V(-top.z, top.y), V(top.z, top.y), 30, f"SS c-c {fmt_len(2 * top.z, v.units)}", "horizontal")
    if cs is not None:
        pb = cs.point(cs.vis[1])
        v.lin(V(-pb.z, pb.y), V(pb.z, pb.y), -(R + 30), f"CS c-c {fmt_len(2 * pb.z, v.units)}", "horizontal")
    rings = CL.chainrings(g)
    if rings:
        mid = sum(r.z for r in rings) / len(rings)
        v.lin(V(0, by - rings[0].r_out), V(mid, by - rings[0].r_out), -16, f"chainline {fmt_len(mid, v.units)}",
              "horizontal")
    x_right = _prim_bounds(sc.prims[start:])[2] + 2.0 * v.size
    v.callouts_column([("ss_tire", "SS-tire"), ("ss_bridge_tire", "bridge-tire"), ("cs_tire", "CS-tire"),
                       ("cs_bridge_tire", "CS bridge-tire")], RP, x_right)
    lines = v.lines_for(["ss_tire", "cs_tire", "ss_bridge_tire", "cs_bridge_tire", "st_tire", "ss_bridge_length",
                         "ss_rear_angle", "ss_plane_angle", "cs_plane_angle"])
    v.panel("Rear view — seat & chain stays", start, lines, "right")
    return sc


# --------------------------------------------------------------------------
# fork front view
# --------------------------------------------------------------------------
def front_view_scene(g: Geometry, theme: Theme | None = None) -> Scene:
    """Fork front view along the head-tube normal: crown clearance, blades,
    tire section, hub spacing."""
    v = _View(g, theme)
    sc, t, d = v.sc, v.t, v.d
    start = len(sc.prims)
    ax = g.p["front_axle"]
    u = g.u
    FP: Proj = lambda p: V(-p.z, (p.x - ax.x) * u.x + (p.y - ax.y) * u.y)
    w_of = lambda q: (q - ax).dot(u)
    vd = V3(g.n.x, g.n.y, 0.0)
    tm = CL.tire_model(g, "front")
    fw = g.wheels["front"]
    _hub(v, "front", lambda lat, rad: V(-lat, rad))
    v.poly(_tire_sil(tm, lambda q: V(-q.y, q.x)), v.tire_st(0.85), "wheels", Z_STAY - 5, True, "tire:front")
    fm = CL.fender_model(g, "front")
    if fm is not None:
        lows = [fm.R * (math.cos(math.radians(a)) * u.x + math.sin(math.radians(a)) * u.y)
                for a in range(int(fm.a0), int(fm.a1) + 1, 5)]
        v.poly([V(-fm.half_w, min(lows)), V(-fm.half_w, fm.R + fm.half_t), V(fm.half_w, fm.R + fm.half_t),
                V(fm.half_w, min(lows))], Style(t.outline, t.width * 0.6, None), "accessories", Z_STAY - 4, False,
               "fender:front")
        v.poly([V(-fm.half_w, fm.R - fm.half_t), V(fm.half_w, fm.R - fm.half_t)], v.hidden_st(), "accessories",
               Z_STAY - 4, False)
    leg = CL.fork_leg_path(g)
    fst = v.fork_st()
    if leg is not None:
        v.tube(leg, FP, vd, fst, "fork", Z_FRONT, "fork", dropout_end=False)
        if d["fork_type"] == "suspension":
            AC = g.v["fork_length"]
            for s in (1, -1):
                zz = leg.z(0.55 * AC / leg.L)
                y = AC * 0.55
                v.sc.line(V(-s * (zz - 22), y), V(-s * (zz + 22), y), Style(t.outline, t.width * 0.6), "fork",
                          Z_FRONT + 1)
            zl = leg.z(0.4)
            v.poly(_stroke([V(-zl, AC * 0.55 - 30), V(0, AC * 0.55 - 8), V(zl, AC * 0.55 - 30)], [6, 6, 6]), fst,
                   "fork", Z_FRONT - 1, True, "fork:arch")
    half = fw.hub_spacing / 2
    for s in (1, -1):
        v.poly(_rect(-s * half, -14, -s * (half + 5), 22), v.comp_st("#8a8a8a"), "fork", Z_FRONT + 1, True,
               "fork:end")
    cb, cr = g.p["crown_bottom"], g.p["crown"]
    w_cb, w_cr = w_of(cb), w_of(cr)
    cwh = d.f("fork_crown_width") / 2
    blade = d.f("fork_stanchion_od") if d["fork_type"] == "suspension" else d.f("fork_blade_od")
    v.poly(_rect(-cwh - blade / 2 - 5, w_cb, cwh + blade / 2 + 5, w_cr), fst, "fork", Z_FRONT + 2, True,
           "fork:crown")
    so = d.f("steerer_od") / 2
    hb = g.p["ht_bottom"]
    w_hb, w_ht = w_of(hb), w_of(g.p["ht_top"])
    v.poly(_rect(-so, w_cr, so, w_hb), v.comp_st("#9a9a9a"), "fork", Z_FRONT + 1, True, "fork:steerer")
    if d.f("lower_stack") > 0:
        hr = d.f("ht_od_bottom") / 2 + 1.5
        v.poly(_rect(-hr, w_cr, hr, w_hb), v.comp_st("#4d4d4d"), "cockpit", Z_FRONT + 3, True, "headset")
    v.poly([V(-d.f("ht_od_bottom") / 2, w_hb), V(d.f("ht_od_bottom") / 2, w_hb), V(d.f("ht_od_top") / 2, w_ht),
            V(-d.f("ht_od_top") / 2, w_ht)], v.t.frame(v.t.ht_fill or v.frame_st().fill), "frame", Z_FRONT + 2,
           True, "tube:ht")
    v.centre([V(0, -tm.outer_r - 15), V(0, w_ht + 15)])
    v.mark(V(0, 0))

    # dimensions
    v.set_size(start)
    v.lin(V(-tm.a, -tm.rc), V(tm.a, -tm.rc), -(tm.outer_r - tm.rc) - 1.6 * v.size,
          f"tire {fmt_len(2 * tm.a, v.units)}", "horizontal")
    v.lin(V(-half, 0), V(half, 0), -tm.outer_r - 4.0 * v.size, f"hub {fmt_len(fw.hub_spacing, v.units)}",
          "horizontal")
    v.lin(V(-cwh, w_cr), V(cwh, w_cr), 26, f"crown c-c {fmt_len(2 * cwh, v.units)}", "horizontal")
    x_right = _prim_bounds(sc.prims[start:])[2] + 2.0 * v.size
    c = v.contact("fork_crown_tire", FP)
    if c is not None:
        p1, p2, val, bad = c
        v.gap_mark(p1, p2, bad, "clear:fork_crown_tire")
        v.lin(V(0, p2.y), V(0, w_cb), tm.a + 30, f"crown-tire {_fmt(val, 'mm', v.units)}", "vertical", bad)
    v.callouts_column([("fork_blade_tire", "blade-tire")], FP, x_right)
    lines = v.lines_for(["fork_crown_tire", "fork_crown_tire_bottomed", "fork_crown_fender", "fork_blade_tire"])
    lines.append((f"Fork axle-to-crown: {fmt_len(g.v['fork_length'], v.units)}", False))
    v.panel("Front view — fork crown clearance", start, lines, "right")
    return sc


# --------------------------------------------------------------------------
# lean angle
# --------------------------------------------------------------------------
def lean_view_scene(g: Geometry, theme: Theme | None = None) -> Scene:
    """Rear elevation at the BB: upright bike (ghost) and the bike leaned until
    the inside pedal touches the ground, rolling on the tire sections."""
    v = _View(g, theme)
    sc, t, d = v.sc, v.t, v.d
    start = len(sc.prims)
    L = CL.lean_solution(g)
    phi = math.radians(L.angle)
    tm = CL.tire_model(g, "rear")
    bb = L.bb                              # coordinates below are relative to this BB
    cy = tm.cy - bb.y
    gy = g.ground_y - bb.y
    cl = d.f("crank_length")
    q2 = d.f("q_factor") / 2
    pw, pt = d.f("pedal_width"), d.f("pedal_thickness")
    z0, z1 = CL.crank_faces(g)
    th = d.f("crank_arm_thickness")
    W, R = d.f("bb_shell_width"), d.f("bb_shell_od") / 2
    st_name = "st2" if "st2" in g.tubes else "st"
    st_tb = g.tubes.get(st_name)
    top_y = min((st_tb.b.y - bb.y) if st_tb is not None else 400.0, cy + tm.outer_r + 40)

    def parts() -> list[tuple[list[V], str, str]]:
        """(polygon in upright rear-view coords, kind, tag)."""
        out = [(_tire_sil(tm, lambda q: V(q.y, cy + q.x)), "tire", "tire:rear"),
               (_rect(-W / 2, -R, W / 2, R), "frame", "tube:bb")]
        if st_tb is not None:
            out.append((_rect(-st_tb.w_b / 2, R, st_tb.w_b / 2, top_y), "frame", "tube:st"))
        for ring in CL.chainrings(g):
            out.append((_rect(ring.z - ring.half_t, -ring.r_out, ring.z + ring.half_t, ring.r_out), "comp",
                        "chainring"))
        for s in (1, -1):
            out.append(([V(s * z0, 0), V(s * z1, -s * cl), V(s * q2, -s * cl), V(s * (z0 + th), 0)], "crank",
                        "crank"))
            if d["pedal_type"] != "none":
                out.append((_rect(s * q2, -s * cl - pt / 2, s * (q2 + pw), -s * cl + pt / 2), "pedal", "pedal"))
        return out

    s_, c_ = math.sin(phi), math.cos(phi)
    rot = lambda p: V(p.x * c_ + p.y * s_, -p.x * s_ + p.y * c_)      # clockwise: top leans to +Z
    # translation: the roll line (interpolated contact height) lands on the ground, rear contact at zeta 0
    rlow = min((rot(V(z, e)) for z, e in L.tire_pts), key=lambda p: p.y)
    ft = CL.tire_model(g, "front")
    flow = min(rot(V(u, ft.cy - bb.y - (ft.rc + vv))).y for u, vv in ft.outer_half(96))
    roll = (1 - L.wf) * rlow.y + L.wf * flow
    shift = V(-rlow.x, gy - roll)
    lean = lambda p: rot(p) + shift
    gx = max(cl + 120, tm.outer_r * 0.6)
    sc.line(V(-gx, gy), V(gx + q2, gy), Style(t.outline, t.width * 0.8), "ground", Z_GROUND)
    x = -gx
    while x < gx + q2:
        sc.line(V(x, gy), V(x - 10, gy - 10), Style(t.outline, t.width * 0.4), "ground", Z_GROUND)
        x += 20
    # the rear of the tire is nearest the viewer: draw it over the seat tube, semi-transparent
    styles = {"tire": v.tire_st(0.82), "frame": v.frame_st(), "comp": v.comp_st("#9c9c9c"),
              "crank": v.comp_st("#2b2b2b"), "pedal": v.comp_st("#3a3a3a")}
    zs = {"tire": Z_STAY - 5, "frame": Z_BACK, "comp": Z_COMPONENT, "crank": Z_COMPONENT + 2,
          "pedal": Z_COMPONENT + 3}
    for pts, kind, tag in parts():
        v.poly(pts, v.ghost_st(), "ghost", Z_GROUND + 2, True, tag)
        v.poly([lean(p) for p in pts], styles[kind], "frame" if kind in ("frame", "tire") else "drivetrain",
               zs[kind], True, tag)
    # centre planes
    v.centre([V(0, gy), V(0, top_y)])
    contact = V(0.0, gy)          # rear tire contact after the lean
    plane_top = lean(V(0, top_y))
    plane_bot = lean(V(0, cy - tm.outer_r))
    v.centre([plane_bot, plane_top])
    bad = v.problem("lean_angle_3d")
    rad = 0.55 * (top_y - gy)
    v.ang(contact, 90.0 - L.angle, L.angle, rad, f"lean {fmt_angle(L.angle)}", bad, "dim:lean")
    # pedal strike point and upright pedal clearance
    strike = lean(V(q2 + pw, -cl - pt / 2))
    col = PROBLEM if bad else GOOD
    sc.circle(strike, 4, Style(col, 0.35, None), "analysis", Z_OVER, "strike")
    pc = g.v["pedal_clearance"]
    v.set_size(start)
    lines = [(f"Pedal-strike lean angle (3-D): {fmt_angle(L.angle)}", bad),
             (f"Planar estimate (solver): {fmt_angle(g.v['lean_angle'])}", False),
             (f"Pedal clearance upright: {fmt_len(pc, v.units)}", False),
             (f"Tire section: {d.get('tire_profile', 'round')}, {fmt_len(2 * tm.a, v.units)} wide", False)]
    v.panel("Lean angle — pedal strike", start, lines, "right")
    return sc


# --------------------------------------------------------------------------
# toe overlap
# --------------------------------------------------------------------------
def _steered_tire_points(g: Geometry, tm: CL.TireModel, deg: float, n_ang: int = 60) -> list[V3]:
    pts = []
    sec = tm.section(10)
    for i in range(n_ang):
        a = 2 * math.pi * i / n_ang
        ca, sa = math.cos(a), math.sin(a)
        for uu, vv in sec:
            r = tm.rc + vv
            if r < tm.bead_r - 1:
                continue
            pts.append(CL.steer_point(g, V3(tm.cx + r * ca, tm.cy + r * sa, uu), deg))
    return pts


def _steered_fender_points(g: Geometry, fm: CL.FenderModel, deg: float) -> list[list[V3]]:
    edges = []
    for zz in (-fm.half_w, fm.half_w):
        edge = []
        for i in range(41):
            a = math.radians(fm.a0 + (fm.a1 - fm.a0) * i / 40)
            edge.append(CL.steer_point(g, V3(fm.cx + fm.R * math.cos(a), fm.cy + fm.R * math.sin(a), zz), deg))
        edges.append(edge)
    return edges


def toe_view_scene(g: Geometry, theme: Theme | None = None) -> Scene:
    """Toe overlap: side view (top) and plan view (bottom) with the front wheel
    steered to the angle where the tire first touches the toe (crank forward)."""
    v = _View(g, theme)
    sc, t, d = v.sc, v.t, v.d
    start = len(sc.prims)
    tm = CL.tire_model(g, "front")
    fm = CL.fender_model(g, "front")
    c_ang = v.det.get("toe_steer_angle")
    contact = c_ang is not None and math.isfinite(c_ang.value)
    deg = c_ang.value if contact else 25.0
    tpts = _steered_tire_points(g, tm, deg)
    fax = g.p["front_axle"]
    cl = d.f("crank_length")
    stack = d.f("pedal_stack")
    col = PROBLEM if contact else GOOD

    # ---- side view ----------------------------------------------------------
    gy = g.ground_y
    sc.line(V(-cl - d.f("heel_behind_pedal") - 30, gy), V(fax.x + tm.outer_r + 30, gy),
            Style(t.outline, t.width * 0.8), "ground", Z_GROUND)
    v.poly(circle_points(fax, tm.outer_r, 96), v.ghost_st(), "ghost", Z_WHEEL - 2, True, "tire:front")
    v.poly(_hull([V(p.x, p.y) for p in tpts]), v.tire_st(0.55), "wheels", Z_WHEEL, True, "tire:steered")
    if fm is not None:
        for edge in _steered_fender_points(g, fm, deg):
            v.poly([V(p.x, p.y) for p in edge], Style(t.outline, t.width * 0.6, None), "accessories", Z_WHEEL + 1,
                   False, "fender:front")
    v.centre([g.p["axis_ground"], g.p["ht_top"]])
    v.mark(fax)
    R = d.f("bb_shell_od") / 2
    v.poly(circle_points(V(0, 0), R, 32), v.frame_st(), "frame", Z_FRAME, True, "tube:bb")
    for name in ("dt", "st"):
        tb = g.tubes.get(name)
        if tb is not None:
            v.poly(_band(tb.a, tb.b, tb.od_b / 2), Style(t.outline, t.width * 0.5, None), "frame", Z_FRAME - 1, True,
                   f"tube:{name}")
    v.poly(_band(V(0, 0), V(cl, 0), 9), v.comp_st("#2b2b2b"), "drivetrain", Z_COMPONENT, True, "crank")
    rings = CL.chainrings(g)
    if rings:
        v.poly(circle_points(V(0, 0), rings[0].r_out, 72), Style(t.outline, t.width * 0.4, None), "drivetrain",
               Z_COMPONENT - 1, True, "chainring")
    xh, xt = cl - d.f("heel_behind_pedal"), cl + d.f("toe_overhang")
    shoe = [V(xh, stack), V(xt - 20, stack), V(xt, stack + 10), V(xt - 4, stack + CL.TOE_BOX_H - 6),
            V(xt - 30, stack + CL.TOE_BOX_H), V(xt - 75, stack + CL.TOE_BOX_H + 18),
            V(xh + 45, stack + CL.HEEL_COUNTER_H + 8), V(xh + 8, stack + CL.HEEL_COUNTER_H), V(xh - 3, stack + 20)]
    v.poly(shoe, Style(col, 0.35, None), "analysis", Z_OVER, True, "shoe")
    toe_r = g.v["toe_radius"]
    a_c = fax.angle()
    sc.arc(V(0, 0), toe_r, a_c - 35, 70, Style(PROBLEM if g.v["toe_clearance"] < 0 else GOOD, 0.3, None,
                                                 dash=(3, 2)), "analysis", Z_OVER, "toe")
    if contact and c_ang.p is not None:
        sc.circle(V(c_ang.p.x, c_ang.p.y), 5, Style(PROBLEM, 0.4, None), "analysis", Z_OVER + 1, "toe:contact")
    if g.v["toe_clearance"] < 1e6:
        v.lin(fax.norm() * toe_r, fax - fax.norm() * tm.outer_r, 22,
              f"toe circle {fmt_len(g.v['toe_clearance'], v.units)}", "aligned", g.v["toe_clearance"] < 0)
    side_n = len(sc.prims)

    # ---- plan view (built at the origin, then moved below the side view) -----
    TP: Proj = lambda p: V(p.x, -p.z)
    pstart = len(sc.prims)
    v.centre([V(-cl - d.f("heel_behind_pedal") - 30, 0), V(fax.x + tm.outer_r + 30, 0)])
    sil = _tire_sil(tm, lambda q: V(tm.cx + q.x, -q.y))
    v.poly(sil, v.ghost_st(), "ghost", Z_WHEEL - 2, True, "tire:front")
    v.poly(_hull([TP(p) for p in tpts]), v.tire_st(0.55), "wheels", Z_WHEEL, True, "tire:steered")
    if fm is not None:
        for edge in _steered_fender_points(g, fm, deg):
            v.poly([TP(p) for p in edge], Style(t.outline, t.width * 0.6, None), "accessories", Z_WHEEL + 1, False,
                   "fender:front")
    W = d.f("bb_shell_width")
    v.poly(_rect(-R, -W / 2, R, W / 2), v.frame_st(), "frame", Z_FRAME, True, "tube:bb")
    for name in ("dt", "tt"):
        path = CL.tube_path(g, name)
        if path is not None:
            v.poly(v.outline(path, TP, V3(0, -1, 0), n=4), Style(t.outline, t.width * 0.5, None), "frame",
                   Z_FRAME - 1, True, f"tube:{name}")
    z0, z1 = CL.crank_faces(g)
    q2 = d.f("q_factor") / 2
    th = d.f("crank_arm_thickness")
    for s, xp in ((1, cl), (-1, -cl)):
        v.poly([V(0, -s * z0), V(xp, -s * z1), V(xp, -s * q2), V(0, -s * (z0 + th))], v.comp_st("#2b2b2b"),
               "drivetrain", Z_COMPONENT, True, "crank")
    v.poly([TP(V3(p.x, 0, p.y)) for p in CL.shoe_outline(g, 0.0)], Style(col, 0.35, None), "analysis", Z_OVER, True,
           "shoe")
    if contact and c_ang.p is not None:
        sc.circle(TP(c_ang.p), 5, Style(PROBLEM, 0.4, None), "analysis", Z_OVER + 1, "toe:contact")
    # steer angle: wheel heading (projected) vs the centre line
    fwd = CL.steer_point(g, V3(fax.x + 1.0, fax.y, 0.0), deg) - CL.steer_point(g, V3(fax.x, fax.y, 0.0), deg)
    head = V(fwd.x, -fwd.z).norm()
    sax = CL.steer_point(g, V3(fax.x, fax.y, 0.0), deg)
    a_proj = head.angle()
    # heading line through the steered axle; meets the centre line (page y = 0) at the pivot
    if abs(head.y) > 1e-6:
        piv = TP(sax) - head * (TP(sax).y / head.y)
    else:
        piv = TP(sax)
    sc.line(piv - head * 60, TP(sax) + head * (tm.outer_r + 20), t.centre(), "centerlines", Z_CENTERLINE)
    v.ang(piv, 0.0, a_proj, tm.outer_r * 0.9, f"steer {fmt_angle(deg)}" + ("" if contact else " (illustr.)"),
          contact, "dim:steer")
    plan_prims = sc.prims[pstart:]
    v.set_size(start)
    sx0, sy0, sx1, sy1 = _prim_bounds(sc.prims[start:side_n])
    px0, py0, px1, py1 = _prim_bounds(plan_prims)
    _shift(plan_prims, V(0.0, (sy0 - 60) - py1))

    lines = []
    if contact:
        lines.append((f"Toe touches the tire at {fmt_angle(deg)} of steering (either way)", True))
    else:
        lines.append(("No toe contact at any steer angle (wheel shown at 25°)", False))
    lines.append((f"Side-view toe circle clearance: {fmt_len(g.v['toe_clearance'], v.units)}",
                  g.v["toe_clearance"] < 0))
    ln = v.line_for("toe_clearance_3d")
    if ln:
        lines.append(ln)
    lines.append((f"Crank forward, shoe {fmt_len(d.f('shoe_width'), v.units)} wide, toe "
                  f"{fmt_len(d.f('toe_overhang'), v.units)} ahead of the spindle", False))
    if fm is not None:
        lines.append(("Front fender included", False))
    v.panel("Toe overlap — side and plan views", start, lines, "right")
    return sc


# --------------------------------------------------------------------------
# stay true-length views
# --------------------------------------------------------------------------
def _stay_panel(v: _View, name: str, title: str) -> int | None:
    g, d, sc, t = v.g, v.d, v.sc, v.t
    path = CL.stay_path(g, name)
    tb = g.tubes.get(name)
    if path is None or tb is None:
        return None
    start = len(sc.prims)
    fab = CL.stay_fabrication(g, name)
    a3, b3 = path.point(0.0), path.point(1.0)
    D = (b3 - a3).norm()
    recv = CL.receiver_axis(g, tb.join_b)
    A = recv[1] if recv is not None else V3(0, 0, 1)
    E = A - D * A.dot(D)
    if E.length() < 1e-6:
        E = path.frame(0.5)[2]
    E = E.norm()
    if E.y < 0 or (abs(E.y) < 1e-9 and E.z < 0):
        E = E * -1
    N = D.cross(E)
    PJ: Proj = lambda p: V((p - a3).dot(D), (p - a3).dot(E))
    fst = v.frame_st()
    v.poly(v.outline(path, PJ, N, n=36), fst, "frame", Z_STAY, True, f"tube:{name}")
    if path.vis[0] > 1e-6:
        v.poly(v.outline(path, PJ, N, 0.0, path.vis[0], 6), v.hidden_st(), "frame", Z_STAY - 1, True)
    v.centre([PJ(path.point(tt)) for tt in path.ts(24, 0.0, 1.0)])
    # receiving tube (its axis lies in the view plane: true angle)
    L3 = (b3 - a3).length()
    if recv is not None:
        A0, Ad, Rr = recv
        k = (b3 - A0).dot(Ad)
        foot = A0 + Ad * k
        if tb.join_b == "bb":
            c0, c1 = A0 - Ad * (d.f("bb_shell_width") / 2), A0 + Ad * (d.f("bb_shell_width") / 2)
        else:
            c0, c1 = foot - Ad * 70, foot + Ad * 70
        p0, p1 = PJ(c0), PJ(c1)
        v.poly(_band(p0, p1, Rr), fst.with_(opacity=0.85), "frame", Z_FRAME, True, f"tube:{tb.join_b}")
        ext = (p1 - p0).norm()
        v.centre([p0 - ext * 15, p1 + ext * 15])
        ang_A = math.degrees(math.atan2(Ad.dot(E), Ad.dot(D)))
        cands = [ang_A, ang_A + 180.0, ang_A - 180.0]
        tgt = min(cands, key=lambda a: abs(((a - 180.0) + 180.0) % 360.0 - 180.0))
        span = ((tgt - 180.0) + 180.0) % 360.0 - 180.0
        if "mitre_angle" in fab:
            v.ang(PJ(b3), 180.0, span, min(0.22 * L3, 90.0), fmt_angle(fab["mitre_angle"]), tag=f"dim:{name}_mitre")
    # dropout plate (projected) and its angle
    Dxy = V3(D.x, D.y, 0.0).norm()
    Z = V3(0, 0, 1)
    plate = [a3 - Dxy * 22 - Z * 3, a3 + Dxy * 40 - Z * 3, a3 + Dxy * 40 + Z * 3, a3 - Dxy * 22 + Z * 3]
    v.poly([PJ(p) for p in plate], v.comp_st("#8a8a8a"), "frame", Z_STAY + 1, True, "dropout")
    v.mark(PJ(a3))
    if name == "cs":
        trace = PJ(a3 + Dxy * 100)
        a_tr = trace.angle()
        v.ang(V(0, 0), 0.0, a_tr, min(0.3 * L3, 110.0), fmt_angle(fab.get("dropout_angle", 0.0)), tag="dim:cs_drop")
    # lengths
    od = max(tb.od_a, tb.od_b)
    v.lin(PJ(a3), PJ(b3), -(od + 28), f"c-c {fmt_len(fab['chord'], v.units)}", "aligned")
    pa, pb = PJ(path.point(path.vis[0])), PJ(path.point(path.vis[1]))
    v.lin(pa, pb, -(od + 62), f"cut {fmt_len(fab['visible_length'], v.units)}", "aligned")
    keys = ["true_length", "chord", "visible_length", "side_angle", "top_angle", "rear_angle", "plane_angle",
            "mitre_angle", "phase", "dropout_angle"]
    lines = []
    for k in keys:
        if k in fab:
            lab, unit = CL.LABELS.get(f"{name}_{k}", (k, "mm"))
            lines.append((f"{lab}: {_fmt(fab[k], unit, v.units)}", False))
    recv_name = {"bb": "BB shell", "st": "seat tube", "tt": "top tube", "ss_mono": "wishbone"}.get(tb.join_b or "",
                                                                                                   "tube")
    lines.append((f"View plane: stay axis + {recv_name} axis (true mitre angle)", False))
    v.panel(title, start, lines, "below")
    return start


def stay_views_scene(g: Geometry, theme: Theme | None = None) -> Scene:
    """True-length auxiliary views of a chainstay and a seat stay with their end angles."""
    v = _View(g, theme)
    chords = [g.tubes[n].chord for n in ("cs", "ss") if n in g.tubes]
    v.size = max(5.0, min(16.0, 0.026 * max(chords + [200.0])))
    s1 = _stay_panel(v, "cs", "Chainstay — true length view")
    n1 = len(v.sc.prims)
    s2 = _stay_panel(v, "ss", "Seat stay — true length view")
    if s1 is not None and s2 is not None:
        b1 = _prim_bounds(v.sc.prims[s1:n1])
        b2 = _prim_bounds(v.sc.prims[n1:])
        _shift(v.sc.prims[n1:], V(b1[0] - b2[0], (b1[1] - 40) - b2[3]))
    if not v.sc.prims:
        v.text(V(0, 0), "No stays in this design", 4.0, "cm")
    return v.sc


AUX_VIEWS: list[tuple[str, Callable[..., Scene]]] = [
    ("Top view", top_view_scene),
    ("Rear view", rear_view_scene),
    ("Fork crown (front view)", front_view_scene),
    ("Lean angle", lean_view_scene),
    ("Toe overlap", toe_view_scene),
    ("Stay true lengths", stay_views_scene),
]
