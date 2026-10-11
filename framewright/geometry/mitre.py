"""Tube mitre (coping) geometry.

For every tube end that meets other tubes, compute the cut line as it appears
on the tube's outer surface unrolled flat: a full-scale wrap-around template.

Method
------
For ``samples`` angles around the cut tube's outer surface (round or
elliptical, optionally tapered) take the surface line through that point
running along the tube, and intersect it with the receiving surfaces.  Every
receiver is a convex solid: a straight "lofted" tube whose elliptical section
(semi-depth ``A(s)``, semi-width ``B(s)``) varies linearly along its axis.
That one implicit form covers round cylinders, elliptic (oval) cylinders,
cones (tapered head tubes) and the BB shell.  A receiver can be capped at
either end (a flat end face).

Along a surface line the implicit function is (quasi-)convex, so a vectorised
golden-section search finds the closest approach and bisection then finds the
entry point exactly.  The tube is cut where, coming from its body, the line
first enters *any* receiver (the root closest to the tube body).  Where a line
misses the main receiver (cut tube wider than, or offset from, the receiver)
the cut is taken at the closest approach (uncapped receiver) or at the end
face (capped receiver) and a note is added.

Conventions (all cuts)
----------------------
* ``d``  : unit axis pointing *out of* the tube at that end (body -> joint).
* ``v``  : axial distance from the tube's centre-to-centre end point toward
  the body.  Material at smaller ``v`` than the cut line is removed, so
  ``long_point = min v`` (where the tube reaches furthest: the saddle horns)
  and ``short_point = max v`` (deepest part of the cope).
* ``u``  : distance around the outer surface, ``0 <= u <= perimeter``.
  ``u = 0`` is the **reference line**, the side of the tube facing ``e1``:
  the in-plane perpendicular of the tube axis on its upper side (the side
  with +Y; for a vertical tube the +X side).  ``u`` increases toward ``e2``,
  the **drive side** (+Z), reaching the opposite side at ``perimeter / 2``
  and the non-drive side at ``3/4``.  The frame is built from the tube's a->b
  direction, so both ends of a straight tube share the same reference line.
* Stays come in mirrored pairs: cuts are computed for the drive-side copy;
  the non-drive copy is the mirror image (template flipped, print side in).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..model import params as P
from .solver import Geometry, Tube
from .vec import polyline_length, project_on_line

P.register([
    P.ParamDef("mitre_stock_allowance", "Stock allowance per tube", "Manufacturing", "Mitres", P.FLOAT, 20.0,
               "mm", 0, 300, 1, help="Added to the long-to-long length to give the minimum stock length"),
    P.ParamDef("mitre_samples", "Points per mitre", "Manufacturing", "Mitres", P.INT, 360, "", 36, 3600, 1,
               help="Points computed around each tube for templates and G-code", morph=False),
])

_X = np.array([1.0, 0.0, 0.0])
_Y = np.array([0.0, 1.0, 0.0])
_Z = np.array([0.0, 0.0, 1.0])
_GOLD = (math.sqrt(5.0) - 1.0) / 2.0


# --------------------------------------------------------------------------
# result type
# --------------------------------------------------------------------------
@dataclass
class MitreCut:
    """One coped tube end.  See the module docstring for ``u``/``v`` conventions."""
    tube: str                   # Tube name in Geometry.tubes, e.g. "tt"
    end: str                    # "a" or "b"
    label: str                  # e.g. "Top tube → head tube"
    receivers: list[str]        # receivers that shape the cut, main receiver first: ["ht"], ["bb", "st"]
    od: float                   # section at the cut end: side-view depth
    width: float                # top-view width (= od for round)
    wall: float
    perimeter: float            # unrolled length (pi*od, or the ellipse perimeter)
    points: list[tuple[float, float]]   # (u, v), samples + 1 points, last == first + perimeter
    angle: float                # acute angle between cut-tube axis and main receiver axis (deg)
    offset: float               # perpendicular distance between the axes (mm, >= 0), see offset_dir
    long_point: float           # min v (tube reaches furthest)
    short_point: float          # max v (deepest point of the cope)
    holesaw_diameter: float     # receiver diameter seen across the joint (local OD for tapered/oval)
    holesaw_angle: float        # notcher setting: 90 - angle (0 = square cut)
    holesaw_offset: float       # notcher offset (= offset)
    phase: float                # rotation of this cut relative to the other end of the tube (deg)
    # -- extra detail --------------------------------------------------------------
    tube_label: str = ""
    end_label: str = ""         # e.g. "head-tube end"
    receiver_labels: list[str] = field(default_factory=list)
    profile: str = "round"
    mirrored: bool = False      # a mirror-image copy is needed (stay pairs)
    contact: float = 1.0        # fraction of the outline that actually meets a receiver
    phase_abs: float = 0.0      # rotation of the cut's symmetry plane from its nominal (frame-aligned) plane
    saw_rotation: float = 0.0   # receiver axis direction around the tube, from the reference line (0..180)
    offset_dir: str = ""        # where the receiver axis lies from the cut axis, e.g. "NON-DRIVE SIDE"
    wrap_reversed: bool = False  # template drawn with u running right-to-left (see export.mitre_output)
    ref_name: str = "TOP"       # names of the u = 0, P/4, P/2, 3P/4 lines
    side_name: str = "DRIVE SIDE"
    opp_name: str = "BOTTOM"
    nside_name: str = "NON-DRIVE SIDE"
    polar: list[float] = field(default_factory=list)    # polar angle (deg) of each point about the axis
    radius: list[float] = field(default_factory=list)   # surface distance from the axis at each point
    end_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis: tuple[float, float, float] = (1.0, 0.0, 0.0)      # d (outward)
    ref_dir: tuple[float, float, float] = (0.0, 1.0, 0.0)   # e1
    side_dir: tuple[float, float, float] = (0.0, 0.0, 1.0)  # e2
    notes: list[str] = field(default_factory=list)

    @property
    def u(self) -> list[float]:
        return [p[0] for p in self.points]

    @property
    def v(self) -> list[float]:
        return [p[1] for p in self.points]

    @property
    def depth(self) -> float:
        """Axial length of the cope (short point - long point)."""
        return self.short_point - self.long_point

    def mirror(self) -> "MitreCut":
        """The mirror-image cut (non-drive-side stay): u -> perimeter - u."""
        import copy
        m = copy.copy(self)
        Pm = self.perimeter
        m.points = [(Pm - u, v) for u, v in reversed(self.points)]
        m.polar = [360.0 - a for a in reversed(self.polar)]
        m.radius = list(reversed(self.radius))
        m.side_name, m.nside_name = self.nside_name, self.side_name
        m.wrap_reversed = not self.wrap_reversed
        m.phase, m.phase_abs = -self.phase, -self.phase_abs
        m.saw_rotation = (180.0 - self.saw_rotation) % 180.0
        m.side_dir = tuple(-c for c in self.side_dir)
        m.end_point = (self.end_point[0], self.end_point[1], -self.end_point[2])
        m.axis = (self.axis[0], self.axis[1], -self.axis[2])
        m.notes = list(self.notes)
        return m


# --------------------------------------------------------------------------
# receiving surfaces
# --------------------------------------------------------------------------
@dataclass
class Receiver:
    """Straight tube solid with a linearly varying elliptical section.

    ``p0`` is the axis point at ``s = 0``; ``t`` the unit axis; the section
    has semi-axis ``A(s) = a0 + (a1 - a0) s / length`` along ``e1`` and
    ``B(s)`` along ``e2``.  The section is extrapolated beyond ``[0, length]``
    unless the end is capped (``cap_lo`` at ``s = 0``, ``cap_hi`` at ``s = length``).
    """
    name: str
    label: str
    p0: np.ndarray
    t: np.ndarray
    length: float
    e1: np.ndarray
    e2: np.ndarray
    a0: float
    a1: float
    b0: float
    b1: float
    cap_lo: bool = False
    cap_hi: bool = False

    @classmethod
    def cylinder(cls, point: Sequence[float], axis: Sequence[float], radius: float, *, length: float = 100.0,
                 name: str = "r", label: str = "", cap_lo: bool = False, cap_hi: bool = False) -> "Receiver":
        return cls.loft(point, axis, None, radius, radius, radius, radius, length=length, name=name, label=label,
                        cap_lo=cap_lo, cap_hi=cap_hi)

    @classmethod
    def cone(cls, point: Sequence[float], axis: Sequence[float], r0: float, r1: float, length: float, *,
             name: str = "r", label: str = "", cap_lo: bool = False, cap_hi: bool = False) -> "Receiver":
        """Round tube tapering from radius ``r0`` at ``point`` to ``r1`` at ``point + axis*length``."""
        return cls.loft(point, axis, None, r0, r1, r0, r1, length=length, name=name, label=label,
                        cap_lo=cap_lo, cap_hi=cap_hi)

    @classmethod
    def loft(cls, point: Sequence[float], axis: Sequence[float], depth_dir: Sequence[float] | None,
             a0: float, a1: float, b0: float, b1: float, *, length: float = 100.0, name: str = "r",
             label: str = "", cap_lo: bool = False, cap_hi: bool = False) -> "Receiver":
        t = _unit(np.asarray(axis, float))
        if depth_dir is None:
            e1, e2 = tube_frame(t)
        else:
            e1 = _unit(np.asarray(depth_dir, float) - np.dot(depth_dir, t) * t)
            e2 = np.cross(t, e1)
        return cls(name, label or name, np.asarray(point, float), t, float(length), e1, e2,
                   float(a0), float(a1), float(b0), float(b1), cap_lo, cap_hi)

    def semi(self, s):
        """(A, B) semi-axes at axial position ``s`` (scalar or array)."""
        f = s / self.length if self.length > 1e-9 else 0.0 * s
        A = np.maximum(self.a0 + (self.a1 - self.a0) * f, 1e-3)
        B = np.maximum(self.b0 + (self.b1 - self.b0) * f, 1e-3)
        return A, B

    @property
    def is_round(self) -> bool:
        return abs(self.a0 - self.b0) < 1e-9 and abs(self.a1 - self.b1) < 1e-9

    def g(self, pts: np.ndarray) -> np.ndarray:
        """Implicit function: < 0 inside the (uncapped) section, 0 on the surface."""
        w = pts - self.p0
        s = w @ self.t
        A, B = self.semi(s)
        return np.sqrt((w @ self.e1 / A) ** 2 + (w @ self.e2 / B) ** 2) - 1.0

    def axial(self, pts: np.ndarray) -> np.ndarray:
        return (pts - self.p0) @ self.t

    def half_extent(self, s: float, direction: np.ndarray) -> float:
        """Half-width of the section at ``s`` measured along ``direction`` (projected into the section)."""
        A, B = self.semi(s)
        c1, c2 = float(np.dot(direction, self.e1)), float(np.dot(direction, self.e2))
        n = math.hypot(c1, c2)
        if n < 1e-12:
            return float(max(A, B))
        c1, c2 = c1 / n, c2 / n
        return float(math.sqrt((A * c1) ** 2 + (B * c2) ** 2))


# --------------------------------------------------------------------------
# frames and helpers
# --------------------------------------------------------------------------
def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v * 0.0


def tube_frame(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Reference (``e1``, "top") and drive-side (``e2``) directions for a tube
    whose axis direction is ``t``.  ``e2`` is +Z made perpendicular to the
    axis; ``e1`` is perpendicular to both, on the +Y side (or +X for a
    vertical tube).  The sign of ``t`` does not matter."""
    t = _unit(np.asarray(t, float))
    e2 = _Z - np.dot(_Z, t) * t
    if np.linalg.norm(e2) < 1e-9:           # tube along Z
        e2 = _X - np.dot(_X, t) * t
    e2 = _unit(e2)
    e1 = _unit(np.cross(e2, t))
    if e1[1] < -1e-9 or (abs(e1[1]) <= 1e-9 and e1[0] < 0):
        e1 = -e1
    return e1, e2


def _direction_name(e: np.ndarray) -> tuple[str, str]:
    """(name, opposite name) for a reference direction."""
    if abs(e[1]) >= 0.5 or abs(e[1]) >= abs(e[0]):
        return ("TOP", "BOTTOM") if e[1] >= 0 else ("BOTTOM", "TOP")
    return ("FRONT", "REAR") if e[0] >= 0 else ("REAR", "FRONT")


def _polyline3(tube: Tube, mirror: bool = False) -> tuple[list[np.ndarray], list[float]]:
    """3-D centre-line polyline (z interpolated by arc length) and cumulative lengths."""
    pts2 = tube.points()
    L2 = max(polyline_length(pts2), 1e-9)
    out, cum, acc = [], [], 0.0
    sgn = -1.0 if mirror else 1.0
    for i, p in enumerate(pts2):
        if i:
            acc += pts2[i - 1].dist(p)
        z = tube.za + (tube.zb - tube.za) * acc / L2
        out.append(np.array([p.x, p.y, sgn * z]))
    acc3 = 0.0
    for i, p in enumerate(out):
        if i:
            acc3 += float(np.linalg.norm(p - out[i - 1]))
        cum.append(acc3)
    return out, cum


def tube_length3(tube: Tube) -> float:
    """Centre-line length including the lateral (Z) run of 3-D stays."""
    return _polyline3(tube)[1][-1]


def end_tangent3(tube: Tube, end: str) -> np.ndarray:
    """Unit a->b direction of the centre line at ``end`` (end tangent for bent tubes)."""
    pts2 = tube.points()
    L2 = max(polyline_length(pts2), 1e-9)
    t2 = tube.dir_a() if end == "a" else tube.dir_b()
    return _unit(np.array([t2.x, t2.y, (tube.zb - tube.za) / L2]))


def receiver_from_tube(tube: Tube, near: np.ndarray, caps: tuple[bool, bool] = (False, False),
                       mirror: bool = False, label: str | None = None) -> Receiver:
    """Receiver for ``tube``.  Bent tubes are straightened about the point of
    their centre line closest to ``near`` (local tangent)."""
    pts, cum = _polyline3(tube, mirror)
    L = cum[-1]
    if len(pts) == 2:
        t = _unit(pts[1] - pts[0])
        base = pts[0]
    else:
        best, bi, bt = 1e18, 0, 0.0
        for i in range(len(pts) - 1):
            seg = pts[i + 1] - pts[i]
            sl2 = float(seg @ seg)
            tt = 0.0 if sl2 < 1e-18 else min(1.0, max(0.0, float((near - pts[i]) @ seg) / sl2))
            dist = float(np.linalg.norm(pts[i] + seg * tt - near))
            if dist < best:
                best, bi, bt = dist, i, tt
        seg = pts[bi + 1] - pts[bi]
        t = _unit(seg)
        c = pts[bi] + seg * bt
        sc = cum[bi] + bt * float(np.linalg.norm(seg))
        base = c - t * sc
    e1, e2 = tube_frame(t)
    return Receiver(tube.name, label if label is not None else tube.label.lower(), base, t, L, e1, e2,
                    tube.od_a / 2, tube.od_b / 2, tube.w_a / 2, tube.w_b / 2, caps[0], caps[1])


def bb_shell_receiver(design, caps: tuple[bool, bool] = (False, False)) -> Receiver:
    """The BB shell: cylinder along Z at the origin."""
    R = design.f("bb_shell_od") / 2
    W = design.f("bb_shell_width")
    return Receiver("bb", "BB shell", np.array([0.0, 0.0, -W / 2]), _Z.copy(), W, _Y.copy(), _X.copy(),
                    R, R, R, R, caps[0], caps[1])


# --------------------------------------------------------------------------
# core intersection
# --------------------------------------------------------------------------
@dataclass
class CopeProfile:
    u: np.ndarray           # (samples+1,) distance around the surface from the reference line
    v: np.ndarray           # axial cut position (toward the body)
    phi: np.ndarray         # parametric angle (rad) of the section ellipse
    polar: np.ndarray       # polar angle (deg) of the surface point about the axis
    radius: np.ndarray      # surface distance from the axis
    winner: np.ndarray      # index of the receiver defining each point
    missed: np.ndarray      # main receiver missed: closest approach / end face used
    perimeter: float
    points3: np.ndarray     # (samples+1, 3) cut points in model space


def ellipse_table(a: float, b: float, n: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """(phi, cumulative arc length) for the ellipse (a cos phi, b sin phi)."""
    phi = np.linspace(0.0, 2 * math.pi, n + 1)
    speed = np.sqrt((a * np.sin(phi)) ** 2 + (b * np.cos(phi)) ** 2)
    arc = np.concatenate([[0.0], np.cumsum((speed[1:] + speed[:-1]) * 0.5 * np.diff(phi))])
    return phi, arc


def ellipse_perimeter(a: float, b: float) -> float:
    if abs(a - b) < 1e-12:
        return 2 * math.pi * a
    return float(ellipse_table(a, b)[1][-1])


def _line_intervals(rec: Receiver, Q: np.ndarray, D: np.ndarray, vlo: float, vhi: float):
    """For lines ``Q - D v`` (one per row) return ``(hit, lo, hi, vstar, slab_lo, slab_hi)``:
    the parameter interval inside the receiver's section, its closest approach and the
    interval inside its end caps."""
    N = len(Q)

    def g_at(v):
        return rec.g(Q - D * v[:, None])

    # golden-section search for the minimum of the (quasi-convex) implicit function
    a = np.full(N, vlo)
    b = np.full(N, vhi)
    c = b - _GOLD * (b - a)
    d = a + _GOLD * (b - a)
    gc, gd = g_at(c), g_at(d)
    for _ in range(64):
        left = gc < gd
        b = np.where(left, d, b)
        a = np.where(left, a, c)
        nc = np.where(left, b - _GOLD * (b - a), d)
        nd = np.where(left, c, a + _GOLD * (b - a))
        fresh = np.where(left, nc, nd)
        gf = g_at(fresh)
        gc, gd = np.where(left, gf, gd), np.where(left, gc, gf)
        c, d = nc, nd
    vstar = (a + b) * 0.5
    gstar = g_at(vstar)
    hit = gstar < 0.0
    tangent = ~hit & (gstar < 1e-7)        # grazing line (e.g. equal diameters): touches at vstar

    def bisect(inside_end, outside_end):
        lo_, hi_ = inside_end.copy(), outside_end.copy()
        for _ in range(56):
            mid = (lo_ + hi_) * 0.5
            ins = g_at(mid) < 0.0
            lo_ = np.where(ins, mid, lo_)
            hi_ = np.where(ins, hi_, mid)
        return (lo_ + hi_) * 0.5

    vh = np.full(N, vhi)
    vl = np.full(N, vlo)
    upper = np.where(tangent, vstar, np.where(g_at(vh) < 0.0, vhi, bisect(vstar, vh)))
    lower = np.where(tangent, vstar, np.where(g_at(vl) < 0.0, vlo, bisect(vstar, vl)))
    hit = hit | tangent

    # end caps: slab constraints on s(v) = sQ - sigma v
    sQ = rec.axial(Q)
    sigma = D @ rec.t
    slab_lo = np.full(N, -np.inf)
    slab_hi = np.full(N, np.inf)
    empty = np.zeros(N, bool)
    for capped, bound, sense in ((rec.cap_lo, 0.0, 1.0), (rec.cap_hi, rec.length, -1.0)):
        if not capped:
            continue
        k = sense * sigma            # constraint: cc - k v >= 0
        cc = sense * (sQ - bound)
        par = np.abs(k) < 1e-12
        empty |= par & (cc < 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            lim = np.where(par, np.nan, cc / np.where(par, 1.0, k))
        slab_hi = np.where(~par & (k > 0), np.minimum(slab_hi, lim), slab_hi)
        slab_lo = np.where(~par & (k < 0), np.maximum(slab_lo, lim), slab_lo)
    slab_lo = np.where(empty, np.inf, slab_lo)
    slab_hi = np.where(empty, -np.inf, slab_hi)
    return hit, lower, upper, vstar, slab_lo, slab_hi


def cope_profile(end: Sequence[float], axis: Sequence[float], e1: Sequence[float], e2: Sequence[float],
                 a: float, b: float, receivers: Sequence[Receiver], samples: int = 360, taper: float = 0.0,
                 v_range: tuple[float, float] | None = None) -> CopeProfile:
    """Unrolled cope of a tube against ``receivers`` (the first is the main receiver).

    ``end`` is the centre-to-centre end point, ``axis`` the outward unit axis
    ``d``, ``e1``/``e2`` the reference and drive-side directions, ``a``/``b``
    the semi-depth (along ``e1``) and semi-width (along ``e2``) at the end.
    ``taper`` is the relative growth of the section per mm toward the body
    (``radius(v) = radius_end * (1 + taper * v)``)."""
    E = np.asarray(end, float)
    dd = _unit(np.asarray(axis, float))
    e1 = _unit(np.asarray(e1, float) - np.dot(e1, dd) * dd)
    e2 = _unit(np.asarray(e2, float) - np.dot(e2, dd) * dd - np.dot(e2, e1) * e1)
    samples = max(int(samples), 8)
    if abs(a - b) < 1e-12:
        perim = 2 * math.pi * a
        phi = np.linspace(0.0, 2 * math.pi, samples + 1)
        u = phi * a
    else:
        tphi, tarc = ellipse_table(a, b)
        perim = float(tarc[-1])
        u = np.linspace(0.0, perim, samples + 1)
        phi = np.interp(u, tarc, tphi)
    cphi, sphi = np.cos(phi), np.sin(phi)
    rho = np.outer(a * cphi, e1) + np.outer(b * sphi, e2)
    Q = E + rho
    D = dd[None, :] - rho * taper
    if v_range is None:
        rmax = max([max(r.a0, r.a1, r.b0, r.b1) for r in receivers] + [0.0])
        vr = min(max(8.0 * (rmax + max(a, b)), 150.0), 1500.0)
        v_range = (-vr, vr)
    vlo, vhi = v_range
    N = len(Q)
    v = np.full(N, -np.inf)
    winner = np.full(N, -1, int)
    missed = np.zeros(N, bool)
    for i, rec in enumerate(receivers):
        hit, lo, hi, vstar, slo, shi = _line_intervals(rec, Q, D, vlo, vhi)
        top = np.minimum(hi, shi)
        valid = hit & (np.maximum(lo, slo) <= top)
        if i == 0:
            capped = rec.cap_lo or rec.cap_hi
            fallback = np.where(np.isfinite(shi), shi, vstar) if capped else vstar
            fallback = np.clip(fallback, vlo, vhi)
            if valid.any() and (~valid).any():
                span = 2.0 * max(a, b)
                fallback = np.clip(fallback, top[valid].min() - span, top[valid].max() + span)
            v = np.where(valid, top, fallback)
            missed = ~valid
            winner[:] = 0
        else:
            better = valid & (top > v + 1e-9)
            v = np.where(better, top, v)
            winner = np.where(better, i, winner)
            missed &= ~better
    polar = np.degrees(np.unwrap(np.arctan2(b * sphi, a * cphi)))
    polar -= polar[0]
    radius = np.hypot(a * cphi, b * sphi)
    pts3 = Q - D * v[:, None]
    return CopeProfile(u, v, phi, polar, radius, winner, missed, perim, pts3)


# --------------------------------------------------------------------------
# frame joints
# --------------------------------------------------------------------------
@dataclass
class _Job:
    tube: str
    end: str
    primary: str
    secondary: tuple[str, ...] = ()
    caps: tuple[bool, bool] = (False, False)


_END_WORDS = {"bb": "BB", "ht": "head-tube", "st": "seat-tube", "tt": "top-tube", "dt": "down-tube",
              "ss_mono": "wishbone", "dropout": "dropout"}


def _jobs(g: Geometry) -> list[_Job]:
    T = g.tubes
    jobs = [_Job("tt", "a", "st"), _Job("tt", "b", "ht"), _Job("dt", "a", "bb", ("st",)),
            _Job("dt", "b", "ht", ("tt",)), _Job("st", "a", "bb"), _Job("cs", "b", "bb")]
    ss = T.get("ss")
    if ss is not None:
        if ss.join_b == "ss_mono":
            jobs.append(_Job("ss", "b", "ss_mono", (), (True, False)))
        elif ss.join_b in ("st", "tt"):
            jobs.append(_Job("ss", "b", ss.join_b, ("tt",) if ss.join_b == "st" else ("st",)))
    mono = T.get("ss_mono")
    if mono is not None and mono.join_b in ("st", "tt"):
        jobs.append(_Job("ss_mono", "b", mono.join_b, ("tt",) if mono.join_b == "st" else ("st",)))
    return [j for j in jobs if j.tube in T]


def _end_point(tube: Tube, end: str) -> np.ndarray:
    p = tube.a3() if end == "a" else tube.b3()
    return np.array([p.x, p.y, p.z])


def _detect(g: Geometry, tube: Tube, end: str) -> list[tuple[str, bool]]:
    """Receivers whose solid contains ``tube``'s end point: [(name, mirrored)], best first."""
    E = _end_point(tube, end)
    found: list[tuple[float, str, bool]] = []
    for name, other in g.tubes.items():
        if name == tube.name or other.kind == "fork":
            continue
        for mirror in ((False, True) if other.mirrored else (False,)):
            rec = receiver_from_tube(other, E, mirror=mirror)
            s = float(rec.axial(E[None, :])[0])
            A, B = rec.semi(min(max(s, 0.0), rec.length))
            if not (-max(A, B) <= s <= rec.length + max(A, B)):
                continue
            w = E - rec.p0
            rho = math.hypot(float(w @ rec.e1) / A, float(w @ rec.e2) / B)
            if rho <= 1.05 + 0.5 / max(A, B):
                found.append((rho, name, mirror))
    d = g.design
    R, W = d.f("bb_shell_od") / 2, d.f("bb_shell_width")
    r = math.hypot(E[0], E[1])
    if r <= R * 1.05 + 0.5 and abs(E[2]) <= W / 2 + R:
        found.append((r / R, "bb", False))
    found.sort(key=lambda f: f[0])
    return [(n, m) for _, n, m in found]


def _receiver(g: Geometry, name: str, near: np.ndarray, caps: tuple[bool, bool], mirror: bool = False) -> Receiver:
    if name == "bb":
        return bb_shell_receiver(g.design, caps)
    tube = g.tubes[name]
    label = tube.label.lower() + (" (non-drive)" if mirror else "")
    return receiver_from_tube(tube, near, caps, mirror, label)


def _wrap90(x: float) -> float:
    """Wrap an angle (deg) to [-90, 90): the cut orientation is defined modulo 180."""
    return (x + 90.0) % 180.0 - 90.0


def _make_cut(g: Geometry, tube: Tube, end: str, recs: list[Receiver], samples: int) -> MitreCut:
    E = _end_point(tube, end)
    t = end_tangent3(tube, end)
    dd = -t if end == "a" else t
    e1, e2 = tube_frame(t)
    od, w = (tube.od_a, tube.w_a) if end == "a" else (tube.od_b, tube.w_b)
    od_other = tube.od_b if end == "a" else tube.od_a
    L3 = tube_length3(tube)
    taper = (od_other - od) / od / L3 if od > 0 and L3 > 1e-6 else 0.0
    a, b = od / 2, w / 2
    rmax = max(max(r.a0, r.a1, r.b0, r.b1) for r in recs)
    vr = min(max(8.0 * (rmax + max(a, b)), 150.0), 1500.0)
    prof = cope_profile(E, dd, e1, e2, a, b, recs, samples, taper, (-vr, min(vr, max(0.95 * L3, 10.0))))

    main = recs[0]
    tr = main.t
    cosang = min(1.0, abs(float(dd @ tr)))
    angle = math.degrees(math.acos(cosang))
    n = np.cross(dd, tr)
    ref_name, opp_name = _direction_name(e1)
    side_name, nside_name = "DRIVE SIDE", "NON-DRIVE SIDE"
    # closest points of the two axes
    w0 = E - main.p0
    bdot = float(dd @ tr)
    den = 1.0 - bdot * bdot
    if np.linalg.norm(n) > 1e-9:
        n = _unit(n)
        offset = float((main.p0 - E) @ n)
        if offset < 0:                      # n points from the cut axis toward the receiver axis
            n, offset = -n, -offset
        c1, c2 = float(n @ e1), float(n @ e2)
        if offset < 1e-6:
            offset, offset_dir = 0.0, ""
        elif abs(c2) >= abs(c1):
            offset_dir = side_name if c2 > 0 else nside_name
        else:
            offset_dir = ref_name if c1 > 0 else opp_name
        s_r = float((w0 @ tr - bdot * (w0 @ dd)) / den)
        hs = 2.0 * main.half_extent(s_r, n)
    else:                                   # parallel axes
        perp = w0 - (w0 @ tr) * tr
        offset = float(np.linalg.norm(perp))
        offset_dir = ""
        s_r = float(w0 @ tr)
        A, B = main.semi(s_r)
        hs = 2.0 * float(max(A, B))
    m = tr - (tr @ dd) * dd
    saw = math.degrees(math.atan2(float(m @ e2), float(m @ e1))) % 180.0 if np.linalg.norm(m) > 1e-9 else 0.0
    nominal = 90.0 if abs(tr[2]) > math.sqrt(0.5) else 0.0
    phase_abs = _wrap90(saw - nominal)
    if abs(phase_abs) < 1e-9:
        phase_abs = 0.0

    used = [0] + sorted({int(i) for i in np.unique(prof.winner) if i > 0})
    receivers = [recs[i].name for i in used]
    rlabels = [recs[i].label for i in used]
    label = f"{tube.label} → {' + '.join(rlabels)}"
    v = prof.v
    notes: list[str] = []
    if prof.missed.any():
        frac = 100.0 * float(prof.missed[:-1].mean())
        how = "trimmed flush with its end face" if (main.cap_lo or main.cap_hi) else "cut at closest approach"
        notes.append(f"{frac:.0f}% of the outline does not meet the {main.label}; those parts are {how}")
    # cope running past the ends of a finite main receiver
    s = main.axial(prof.points3)
    over_lo, over_hi = -float(s.min()), float(s.max()) - main.length
    if main.name == "bb":
        if max(over_lo, over_hi) > 0.5:
            notes.append(f"Cut runs {max(over_lo, over_hi):.1f} mm past the BB shell face")
    else:
        if over_lo > 0.5:
            notes.append(f"Cope runs {over_lo:.1f} mm past the lower end of the {main.label}: trim flush")
        if over_hi > 0.5:
            notes.append(f"Cope runs {over_hi:.1f} mm past the upper end of the {main.label}: trim flush")
    if tube.mirrored:
        notes.append("Make 2: flip the template (print side in) for the non-drive-side tube")
    if tube.profile == "aero":
        notes.append("Aero section approximated by an ellipse")
    if abs(tube.bend) > 1e-6:
        notes.append("Bent tube: cut computed on the end tangent")
    if abs(taper) > 1e-9:
        notes.append("Tapered tube: unrolled at the end section")
    # printed side out, tube end at the top edge: paper +x runs along d x e1
    rvec = np.cross(dd, e1)
    wrap_reversed = bool(rvec @ e2 < 0)
    return MitreCut(
        tube=tube.name, end=end, label=label, receivers=receivers, od=od, width=w, wall=tube.wall_end,
        perimeter=prof.perimeter, points=[(float(x), float(y)) for x, y in zip(prof.u, v)],
        angle=angle, offset=offset, long_point=float(v.min()), short_point=float(v.max()),
        holesaw_diameter=hs, holesaw_angle=90.0 - angle, holesaw_offset=offset, phase=phase_abs,
        tube_label=tube.label, end_label=end_description(tube, end), receiver_labels=rlabels,
        profile=tube.profile if abs(od - w) > 1e-9 else "round", mirrored=tube.mirrored,
        contact=1.0 - float(prof.missed[:-1].mean()),
        phase_abs=phase_abs, saw_rotation=saw, offset_dir=offset_dir, wrap_reversed=wrap_reversed,
        ref_name=ref_name, side_name=side_name, opp_name=opp_name, nside_name=nside_name,
        polar=[float(x) for x in prof.polar], radius=[float(x) for x in prof.radius],
        end_point=tuple(float(x) for x in E), axis=tuple(float(x) for x in dd),
        ref_dir=tuple(float(x) for x in e1), side_dir=tuple(float(x) for x in e2), notes=notes)


def compute_mitres(g: Geometry, samples: int = 360) -> list[MitreCut]:
    """Mitre cuts for every coped tube end of the solved geometry.

    Main tubes: tt.a->st, tt.b->ht, dt.a->BB shell (+st), dt.b->ht (+tt),
    st.a->BB shell; stays: cs.b->BB shell, ss.b->st/tt (or ->wishbone stem),
    wishbone stem->st/tt; extra tubes against whatever their ends meet.
    Secondary receivers appear in ``receivers`` only where they shape the cut.
    """
    cuts: list[MitreCut] = []
    done: set[tuple[str, str]] = set()
    for job in _jobs(g):
        tube = g.tubes[job.tube]
        E = _end_point(tube, job.end)
        if job.primary == "bb" or job.primary in g.tubes:
            recs = [_receiver(g, job.primary, E, job.caps)]
            recs += [_receiver(g, s, E, (True, True)) for s in job.secondary if s in g.tubes and s != job.tube]
        else:
            found = _detect(g, tube, job.end)
            if not found:
                continue
            recs = [_receiver(g, found[0][0], E, (False, False), found[0][1])]
            recs += [_receiver(g, n, E, (True, True), m) for n, m in found[1:]]
        cuts.append(_make_cut(g, tube, job.end, recs, samples))
        done.add((job.tube, job.end))
    for name, tube in g.tubes.items():
        if tube.kind != "extra":
            continue
        for end in ("a", "b"):
            if (name, end) in done:
                continue
            found = _detect(g, tube, end)
            if not found:
                continue
            E = _end_point(tube, end)
            recs = [_receiver(g, found[0][0], E, (False, False), found[0][1])]
            recs += [_receiver(g, n, E, (True, True), m) for n, m in found[1:]]
            cuts.append(_make_cut(g, tube, end, recs, samples))
    _assign_phases(cuts)
    return cuts


def _assign_phases(cuts: list[MitreCut]) -> None:
    by: dict[str, dict[str, MitreCut]] = {}
    for c in cuts:
        by.setdefault(c.tube, {})[c.end] = c
    for ends in by.values():
        if "a" in ends and "b" in ends:
            ph = _wrap90(ends["b"].phase_abs - ends["a"].phase_abs)
            ph = 0.0 if abs(ph) < 1e-9 else ph
            ends["b"].phase = ph
            ends["a"].phase = 0.0 if ph == 0.0 else _wrap90(-ph)
        else:
            for c in ends.values():
                c.phase = c.phase_abs


def end_description(tube: Tube, end: str) -> str:
    """Human description of a tube end, e.g. 'head-tube end'."""
    j = tube.join_a if end == "a" else tube.join_b
    word = _END_WORDS.get(j or "", "")
    return f"{word} end" if word else f"end {end}"


def _free_trim(tube: Tube, end: str) -> float:
    """Length removed at an uncoped end (dropout ends are trimmed to the draw points)."""
    L2 = max(tube.length, 1e-9)
    k = tube_length3(tube) / L2
    if end == "a" and tube.draw_a is not None:
        return max(0.0, project_on_line(tube.draw_a, tube.a, tube.b - tube.a)) * k
    if end == "b" and tube.draw_b is not None:
        return max(0.0, tube.chord - project_on_line(tube.draw_b, tube.a, tube.b - tube.a)) * k
    return 0.0


def cut_lengths(g: Geometry, cuts: list[MitreCut]) -> dict[str, dict]:
    """Per tube: ``cc`` (centre-line length), ``long_to_long`` and
    ``short_to_short`` (finished length between the long / short points of
    the end cuts), ``min_stock`` (long-to-long + allowance), ``phase``
    (rotation of the b-end cut relative to the a-end cut, or of a single cut
    relative to the frame-aligned orientation), plus ``count``, ``label``,
    ``od``, ``width``, ``wall`` and ``angles`` (end -> joint angle)."""
    allowance = float(g.design.get("mitre_stock_allowance", 20.0))
    by: dict[str, dict[str, MitreCut]] = {}
    for c in cuts:
        by.setdefault(c.tube, {})[c.end] = c
    out: dict[str, dict] = {}
    for name, ends in by.items():
        tube = g.tubes.get(name)
        if tube is None:
            continue
        cc = tube_length3(tube)
        lsum = ssum = 0.0
        for end in ("a", "b"):
            c = ends.get(end)
            if c is not None:
                lsum += c.long_point
                ssum += c.short_point
            else:
                trim = _free_trim(tube, end)
                lsum += trim
                ssum += trim
        phase = ends["b"].phase if "b" in ends else ends["a"].phase
        any_cut = next(iter(ends.values()))
        out[name] = {
            "cc": cc, "long_to_long": cc - lsum, "short_to_short": cc - ssum,
            "min_stock": cc - lsum + allowance, "phase": phase,
            "count": 2 if tube.mirrored else 1, "label": tube.label,
            "od": max(tube.od_a, tube.od_b), "width": max(tube.w_a, tube.w_b), "wall": any_cut.wall,
            "angles": {e: c.angle for e, c in ends.items()},
        }
    return out
