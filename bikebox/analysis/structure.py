"""Linear 3-D beam finite-element model of the frame (an *estimate*).

Every solved tube becomes a chain of 2-node Euler-Bernoulli beam elements
with 6 DOF per node (3 translations, 3 rotations): axial, bending in two
planes and St-Venant torsion.  Section properties come from each tube's OD /
width / wall (elliptical hollow section for oval and aero tubes; butted ends
use the butt wall), moduli from the tube material.  Joints are rigid; stays
are joined to their neighbours by short rigid links where the centre-lines do
not meet; seatpost, stem, cranks and (unless ``fea_include_fork``) the fork
and front wheel are rigid links ("dummy" parts as in a test rig).

Boundary conditions (test-rig style): both rear dropouts are pinned
(translations held, rotations free), the front tyre contact point is held
vertically and laterally (vertically only for the head-tube torsion case).
Braking applies the tyre friction explicitly so the dropouts carry no
fore-aft load.

Units: N, mm, MPa (N/mm²), N·mm internally; torques are entered in N·m.
Results are first-order estimates: no lugs, fillets, butting transitions
other than the wall step, local joint flexibility, buckling or fatigue.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np

from ..geometry.solver import MATERIAL_YOUNG, Geometry, Tube

try:                                    # optional: faster symmetric solve when SciPy is installed
    from scipy.linalg import cho_factor as _cho_factor, cho_solve as _cho_solve
except ImportError:                     # pragma: no cover - numpy fallback
    _cho_factor = _cho_solve = None
from ..geometry.vec import arc_through
from ..model import params as P
from . import weight as _weight          # noqa: F401  (registers bb_shell_wall)

# --------------------------------------------------------------------------
# materials
# --------------------------------------------------------------------------
MATERIAL_SHEAR = {            # MPa (quasi-isotropic laminate for carbon; along-grain values for bamboo/wood)
    "steel": 80e3, "stainless": 77e3, "titanium": 38e3, "aluminium": 26e3, "aluminium7005": 27e3,
    "carbon": 26e3, "scandium": 26e3, "bamboo": 1.5e3, "wood": 0.9e3,
}
MATERIAL_YIELD = {            # MPa, typical tubing values (carbon / bamboo / wood: nominal allowable)
    "steel": 460.0, "stainless": 700.0, "titanium": 725.0, "aluminium": 276.0, "aluminium7005": 290.0,
    "carbon": 600.0, "scandium": 400.0, "bamboo": 60.0, "wood": 40.0,
}

G = "Analysis"
S = "Structure"
P.register([
    P.ParamDef("fea_rider_weight", "Rider weight (vertical case)", G, S, P.FLOAT, 800.0, "N", 0, 5000, 10),
    P.ParamDef("fea_saddle_share", "Share on saddle", G, S, P.FLOAT, 60.0, "%", 0, 100, 1),
    P.ParamDef("fea_bar_share", "Share on handlebar", G, S, P.FLOAT, 25.0, "%", 0, 100, 1,
               help="The remainder goes to the pedals"),
    P.ParamDef("fea_pedal_force", "Pedal force", G, S, P.FLOAT, 1000.0, "N", 0, 5000, 10,
               help="Pedalling and eccentric (crank horizontal, with chain pull) cases"),
    P.ParamDef("fea_ht_torque", "Head-tube torque", G, S, P.FLOAT, 50.0, "N·m", 0, 1000, 1,
               help="Torque about the frame's long axis applied at the head tube (rear dropouts held)"),
    P.ParamDef("fea_brake_force", "Front braking force", G, S, P.FLOAT, 600.0, "N", 0, 5000, 10,
               help="Rearward force at the front tyre; applied as forward inertia of the rider "
                    "(same shares as the rider weight)"),
    P.ParamDef("fea_inplane_force", "In-plane force at front axle", G, S, P.FLOAT, 600.0, "N", 0, 5000, 10,
               help="Horizontal forward force at the front axle"),
    P.ParamDef("fea_transverse_force", "Transverse force at seat cluster", G, S, P.FLOAT, 300.0, "N", 0, 5000, 10),
    P.ParamDef("fea_include_fork", "Include fork in the model", G, S, P.BOOL, False,
               help="Off: a rigid dummy fork, as in a frame test rig", morph=False),
] + [
    P.ParamDef(f"fea_yield_{m}", f"Yield strength: {label}", G, S, P.FLOAT, MATERIAL_YIELD[m], "MPa", 1, 3000, 5,
               help="Used for the static safety factor; check your tubing supplier's figure")
    for m, label in P.MATERIALS
])

CASES = ("vertical", "pedalling", "ht_torsion", "braking", "in_plane", "transverse", "eccentric")
CASE_TITLES = {
    "vertical": "Vertical (seated rider)",
    "pedalling": "Pedalling (force at spindle end)",
    "ht_torsion": "Head-tube torsion",
    "braking": "Front braking",
    "in_plane": "In-plane (fore-aft at front axle)",
    "transverse": "Transverse (lateral at seat cluster)",
    "eccentric": "Eccentric (crank horizontal + chain)",
}
NOTE = ("Linear-elastic beam model: rigid joints, no lugs / fillets / local joint flexibility, no buckling "
        "or fatigue.  Treat stiffness and stress values as comparative estimates")


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
@dataclass
class Section:
    """Beam section.  Local y = side-view depth direction (in-plane), local z =
    width direction (out of plane)."""
    A: float
    Iy: float               # about local y (out-of-plane bending, fibre distance cz)
    Iz: float               # about local z (in-plane bending, fibre distance cy)
    J: float
    E: float
    G: float
    cy: float
    cz: float
    Wt: float               # torsional modulus: tau = T / Wt
    round: bool = True
    yield_: float = 0.0
    material: str = ""
    rigid: bool = False


def tube_section(depth: float, width: float, wall: float, material: str = "steel",
                 profile: str = "round", yield_: float | None = None) -> Section:
    """Hollow round or elliptical section from outside depth/width and wall."""
    E = MATERIAL_YOUNG.get(material, MATERIAL_YOUNG["steel"])
    Gm = MATERIAL_SHEAR.get(material, E / 2.6)
    fy = MATERIAL_YIELD.get(material, 400.0) if yield_ is None else yield_
    depth = max(depth, 0.1)
    width = max(width, 0.1)
    if profile == "round" or abs(depth - width) < 1e-6:
        D = 0.5 * (depth + width) if profile != "round" else depth
        t = min(max(wall, 1e-3), D / 2)
        d = D - 2 * t
        A = math.pi / 4 * (D * D - d * d)
        I = math.pi / 64 * (D ** 4 - d ** 4)
        J = 2 * I
        return Section(A, I, I, J, E, Gm, D / 2, D / 2, J / (D / 2), True, fy, material)
    a, b = depth / 2, width / 2
    t = min(max(wall, 1e-3), min(a, b))
    ai, bi = a - t, b - t
    A = math.pi * (a * b - ai * bi)
    Iz = math.pi / 4 * (a ** 3 * b - ai ** 3 * bi)
    Iy = math.pi / 4 * (a * b ** 3 - ai * bi ** 3)
    am, bm = a - t / 2, b - t / 2
    Am = math.pi * am * bm
    per = math.pi * (3 * (am + bm) - math.sqrt((3 * am + bm) * (am + 3 * bm)))
    J = 4 * Am * Am * t / per                  # Bredt, thin-walled closed section
    return Section(A, Iy, Iz, J, E, Gm, a, b, 2 * Am * t, False, fy, material)


def rigid_section() -> Section:
    """Very stiff link (penalty) used for seatpost / stem / dummy fork / offsets."""
    D = 50.0
    I = math.pi * D ** 4 / 64
    return Section(math.pi * D * D / 4, I, I, 2 * I, 2.0e6, 8.0e5, D / 2, D / 2, 2 * I / (D / 2),
                   True, 1e9, "rigid", True)


# --------------------------------------------------------------------------
# generic 3-D frame solver
# --------------------------------------------------------------------------
class FrameModel:
    """Minimal 3-D beam FE model: nodes, beams, supports, nodal loads.

    DOF order per node: ux, uy, uz, rx, ry, rz.  ``node()`` merges points closer
    than ``merge_tol`` mm.
    """

    def __init__(self, merge_tol: float = 0.5):
        self.merge_tol = merge_tol
        self._xyz = np.zeros((64, 3))
        self.n = 0
        self.names: dict[str, int] = {}
        self.ei: list[int] = []
        self.ej: list[int] = []
        self.sec: list[Section] = []
        self.member: list[str] = []
        self.kind: list[str] = []
        self._cache: dict[str, Any] = {}

    @property
    def xyz(self) -> np.ndarray:
        return self._xyz[:self.n]

    def node(self, p: Iterable[float], name: str | None = None) -> int:
        p = np.asarray(p, dtype=float)
        if self.n:
            dd = np.abs(self._xyz[:self.n] - p).max(axis=1)
            k = int(np.argmin(dd))
            if dd[k] <= self.merge_tol:
                if name:
                    self.names.setdefault(name, k)
                return k
        if self.n == len(self._xyz):
            self._xyz = np.vstack([self._xyz, np.zeros_like(self._xyz)])
        self._xyz[self.n] = p
        self.n += 1
        if name:
            self.names[name] = self.n - 1
        self._cache.clear()
        return self.n - 1

    def beam(self, i: int, j: int, sec: Section, member: str = "", kind: str = "frame") -> int | None:
        if i == j:
            return None
        self.ei.append(i)
        self.ej.append(j)
        self.sec.append(sec)
        self.member.append(member)
        self.kind.append(kind)
        self._cache.clear()
        return len(self.ei) - 1

    @property
    def ndof(self) -> int:
        return 6 * self.n

    # -- element matrices --------------------------------------------------------
    def _elements(self):
        if "el" in self._cache:
            return self._cache["el"]
        X = self.xyz
        ei = np.asarray(self.ei, dtype=int)
        ej = np.asarray(self.ej, dtype=int)
        ne = len(ei)
        dx = X[ej] - X[ei]
        L = np.linalg.norm(dx, axis=1)
        ex = dx / L[:, None]
        ref = np.tile(np.array([0.0, 0.0, 1.0]), (ne, 1))
        near_z = np.abs(ex[:, 2]) > 0.95
        ref[near_z] = np.array([0.0, 1.0, 0.0])
        ez = ref - (ref * ex).sum(1)[:, None] * ex
        ez /= np.linalg.norm(ez, axis=1)[:, None]
        ey = np.cross(ez, ex)
        R = np.stack([ex, ey, ez], axis=1)                      # rows = local axes
        T = np.zeros((ne, 12, 12))
        for b in range(4):
            T[:, 3 * b:3 * b + 3, 3 * b:3 * b + 3] = R
        E = np.array([s.E for s in self.sec])
        Gm = np.array([s.G for s in self.sec])
        A = np.array([s.A for s in self.sec])
        Iy = np.array([s.Iy for s in self.sec])
        Iz = np.array([s.Iz for s in self.sec])
        J = np.array([s.J for s in self.sec])
        k = np.zeros((ne, 12, 12))
        ea, gj = E * A / L, Gm * J / L
        for (r, c, v) in ((0, 0, ea), (6, 6, ea), (0, 6, -ea), (6, 0, -ea),
                          (3, 3, gj), (9, 9, gj), (3, 9, -gj), (9, 3, -gj)):
            k[:, r, c] = v
        z12, z6, z4, z2 = 12 * E * Iz / L ** 3, 6 * E * Iz / L ** 2, 4 * E * Iz / L, 2 * E * Iz / L
        for (r, c, v) in ((1, 1, z12), (7, 7, z12), (1, 7, -z12), (7, 1, -z12),
                          (1, 5, z6), (5, 1, z6), (1, 11, z6), (11, 1, z6),
                          (5, 7, -z6), (7, 5, -z6), (7, 11, -z6), (11, 7, -z6),
                          (5, 5, z4), (11, 11, z4), (5, 11, z2), (11, 5, z2)):
            k[:, r, c] = v
        y12, y6, y4, y2 = 12 * E * Iy / L ** 3, 6 * E * Iy / L ** 2, 4 * E * Iy / L, 2 * E * Iy / L
        for (r, c, v) in ((2, 2, y12), (8, 8, y12), (2, 8, -y12), (8, 2, -y12),
                          (2, 4, -y6), (4, 2, -y6), (2, 10, -y6), (10, 2, -y6),
                          (4, 8, y6), (8, 4, y6), (8, 10, y6), (10, 8, y6),
                          (4, 4, y4), (10, 10, y4), (4, 10, y2), (10, 4, y2)):
            k[:, r, c] = v
        dofs = np.concatenate([6 * ei[:, None] + np.arange(6), 6 * ej[:, None] + np.arange(6)], axis=1)
        self._cache["el"] = (k, T, L, dofs)
        return self._cache["el"]

    def stiffness(self) -> np.ndarray:
        if "K" in self._cache:
            return self._cache["K"]
        k, T, _L, dofs = self._elements()
        Kg = np.transpose(T, (0, 2, 1)) @ k @ T
        K = np.zeros((self.ndof, self.ndof))
        np.add.at(K, (dofs[:, :, None], dofs[:, None, :]), Kg)
        self._cache["K"] = K
        return K

    def solve(self, fixed: Iterable[int], F: np.ndarray, active: np.ndarray | None = None) -> np.ndarray:
        """Displacements for load matrix ``F`` (ndof x ncases).  ``fixed`` are
        held DOF indices; ``active`` (bool per node) excludes unconnected nodes."""
        K = self.stiffness()
        free = np.ones(self.ndof, dtype=bool)
        free[list(fixed)] = False
        if active is not None:
            free &= np.repeat(active, 6)
        F = np.atleast_2d(F.T).T if F.ndim == 1 else F
        U = np.zeros((self.ndof, F.shape[1]))
        idx = np.flatnonzero(free)
        Kff = K[np.ix_(idx, idx)]
        if _cho_factor is not None:
            U[idx] = _cho_solve(_cho_factor(Kff, check_finite=False), F[idx], check_finite=False)
        else:
            U[idx] = np.linalg.solve(Kff, F[idx])
        return U

    def element_results(self, U: np.ndarray) -> dict[str, np.ndarray]:
        """Per element and case: axial, bending, shear and von Mises stress (MPa)."""
        k, T, _L, dofs = self._elements()
        ue = U[dofs]                                               # (ne, 12, nc)
        f = k @ (T @ ue)                                           # local end forces
        A = np.array([s.A for s in self.sec])[:, None]
        Iy = np.array([s.Iy for s in self.sec])[:, None]
        Iz = np.array([s.Iz for s in self.sec])[:, None]
        cy = np.array([s.cy for s in self.sec])[:, None]
        cz = np.array([s.cz for s in self.sec])[:, None]
        Wt = np.array([s.Wt for s in self.sec])[:, None]
        rnd = np.array([s.round for s in self.sec])[:, None]
        N = np.abs(f[:, 6])
        Tq = np.abs(f[:, 9])
        sb = np.zeros_like(N)
        for my, mz in ((f[:, 4], f[:, 5]), (f[:, 10], f[:, 11])):
            s_round = np.hypot(my, mz) * cy / Iz
            s_ell = np.abs(mz) * cy / Iz + np.abs(my) * cz / Iy
            sb = np.maximum(sb, np.where(rnd, s_round, s_ell))
        sa = N / A
        tau = Tq / Wt
        vm = np.sqrt((sa + sb) ** 2 + 3 * tau ** 2)
        return {"axial": sa, "bending": sb, "shear": tau, "von_mises": vm, "forces": f}


def cantilever_check(length: float = 500.0, od: float = 28.6, wall: float = 0.9, material: str = "steel",
                     force: float = 100.0, torque: float = 10_000.0, n_el: int = 5,
                     direction: tuple[float, float, float] = (0.8, 0.5, 0.2)) -> dict[str, float]:
    """Straight round cantilever along ``direction`` (clamped at the root) with a
    transverse tip force and a tip torque.  Returns FE and closed-form
    (P L³ / 3EI, T L / GJ) tip deflection / twist; used to verify the solver."""
    e = np.asarray(direction, float)
    e /= np.linalg.norm(e)
    sec = tube_section(od, od, wall, material)
    m = FrameModel()
    ids = [m.node(e * length * i / n_el) for i in range(n_el + 1)]
    for a, b in zip(ids, ids[1:]):
        m.beam(a, b, sec, "cantilever")
    perp = np.cross(e, [0.0, 0.0, 1.0])
    if np.linalg.norm(perp) < 1e-6:
        perp = np.cross(e, [0.0, 1.0, 0.0])
    perp /= np.linalg.norm(perp)
    tip = ids[-1]
    F = np.zeros((m.ndof, 2))
    F[6 * tip:6 * tip + 3, 0] = perp * force
    F[6 * tip + 3:6 * tip + 6, 1] = e * torque
    U = m.solve(range(6), F)
    defl = float(U[6 * tip:6 * tip + 3, 0] @ perp)
    twist = float(U[6 * tip + 3:6 * tip + 6, 1] @ e)
    return {"tip_deflection": defl, "tip_deflection_exact": force * length ** 3 / (3 * sec.E * sec.Iz),
            "tip_twist": twist, "tip_twist_exact": torque * length / (sec.G * sec.J)}


# --------------------------------------------------------------------------
# frame model from the geometry
# --------------------------------------------------------------------------
@dataclass
class _Mem:
    name: str
    pts: np.ndarray                                  # (k, 3) polyline
    sec: Callable[[float, float], Section]           # (s_mid, L) -> Section
    join_a: str | None = None
    join_b: str | None = None
    kind: str = "frame"                              # frame | fork | part | link
    target: bool = True                              # other members may attach to it
    group: str = ""                                  # source tube name (for join hints)
    stations: list[float] = field(default_factory=list)
    auto_link: str = ""                              # "" | "hint" (tube) | "nearest" (extra tube)

    def __post_init__(self):
        seg = np.linalg.norm(np.diff(self.pts, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.L = float(self.cum[-1])
        self.stations = [0.0, self.L] + list(self.stations)

    def point_at(self, s: float) -> np.ndarray:
        s = min(max(s, 0.0), self.L)
        k = int(np.searchsorted(self.cum, s, side="right") - 1)
        k = min(max(k, 0), len(self.pts) - 2)
        seg = self.cum[k + 1] - self.cum[k]
        t = 0.0 if seg < 1e-12 else (s - self.cum[k]) / seg
        return self.pts[k] + (self.pts[k + 1] - self.pts[k]) * t


def _yield(d, material: str) -> float:
    key = f"fea_yield_{material}"
    try:
        return d.f(key)
    except (KeyError, TypeError, ValueError):
        return MATERIAL_YIELD.get(material, 400.0)


def _tube_members(t: Tube, d) -> list[_Mem]:
    pts2 = arc_through(t.a, t.b, t.bend, 6) if abs(t.bend) > 1e-6 else [t.a, t.b]
    xy = np.array([[p.x, p.y] for p in pts2])
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    L = float(cum[-1]) or 1.0
    frac = cum / L
    fy = _yield(d, t.material)

    def secf(s: float, Lm: float, t=t, fy=fy) -> Section:
        tf = s / Lm if Lm > 0 else 0.5
        butt = min(t.butt_length, Lm / 2)
        wall = t.wall_end if (s < butt or s > Lm - butt) else t.wall_mid
        return tube_section(t.od_at(tf), t.w_at(tf), wall, t.material, t.profile, fy)

    sides = [(1.0, "_r"), (-1.0, "_l")] if t.mirrored else [(1.0, "")]
    out = []
    kind = "fork" if t.kind == "fork" else "frame"
    for sign, suf in sides:
        z = sign * (t.za + (t.zb - t.za) * frac)
        pts = np.column_stack([xy, z])
        butt = min(t.butt_length, L / 2)
        st = [float(c) for c in cum[1:-1]]
        if 0 < butt < L / 2 - 0.5:
            st += [butt, L - butt]
        out.append(_Mem(t.name + suf, pts, secf, t.join_a, t.join_b, kind, True, t.name, st,
                        "nearest" if t.kind == "extra" else "hint"))
    return out


def _line(name, a, b, sec_fn, kind="link", target=False, stations=()) -> _Mem:
    return _Mem(name, np.array([a, b], dtype=float), sec_fn, kind=kind, target=target, group=name,
                stations=list(stations))


def build_model(g: Geometry, include_fork: bool | None = None) -> tuple[FrameModel, dict[str, Any]]:
    """Build the frame FE model.  Returns (model, info) where info holds the
    named points, the members and the support / load node names."""
    d = g.design
    p = g.p
    if include_fork is None:
        include_fork = bool(d.get("fea_include_fork", False))
    mat = str(d["frame_material"])
    rigid = rigid_section()
    rig = lambda s, L: rigid                                  # noqa: E731
    mems: list[_Mem] = []

    # -- tubes ---------------------------------------------------------------------
    for name, t in g.tubes.items():
        if t.kind == "fork" and (not include_fork or d["fork_type"] == "suspension"):
            continue
        mems += _tube_members(t, d)

    # -- bottom-bracket shell -----------------------------------------------------------
    w = d.f("bb_shell_width")
    shell_sec = tube_section(d.f("bb_shell_od"), d.f("bb_shell_od"), d.f("bb_shell_wall"), mat,
                             yield_=_yield(d, mat))
    mems.append(_Mem("bb_shell", np.array([[0, 0, -w / 2], [0, 0, w / 2]], float), lambda s, L: shell_sec,
                     kind="frame", group="bb", stations=[w / 2]))

    # -- rear dropouts and axle --------------------------------------------------------------
    ra = p["rear_axle"]
    sn = p["stay_node"]
    hub_r = d.f("rear_hub_spacing") / 2 + 3.0
    axle_sec = tube_section(12.0, 12.0, 2.5, "steel")
    mems.append(_Mem("rear_axle", np.array([[ra.x, ra.y, -hub_r], [ra.x, ra.y, hub_r]]), lambda s, L: axle_sec,
                     kind="part", group="rear_axle", stations=[hub_r]))
    if sn.dist(ra) > 0.5:
        for sgn, suf in ((1, "_r"), (-1, "_l")):
            mems.append(_line("dropout" + suf, (sn.x, sn.y, sgn * hub_r), (ra.x, ra.y, sgn * hub_r), rig))

    # -- front end ----------------------------------------------------------------------
    fa = p["front_axle"]
    contact = (fa.x, g.ground_y, 0.0)
    if include_fork and d["fork_type"] != "suspension" and "fork" in g.tubes:
        ft = g.tubes["fork"]
        cb = p["crown_bottom"]
        cw = d.f("fork_crown_width") / 2
        bod = d.f("fork_blade_od")
        crown_sec = tube_section(bod * 1.3, bod * 1.3, 3.0, ft.material, yield_=_yield(d, ft.material))
        mems.append(_Mem("fork_crown", np.array([[cb.x, cb.y, -cw], [cb.x, cb.y, cw]]), lambda s, L: crown_sec,
                         kind="fork", group="crown", stations=[cw]))
        sod = d.f("steerer_od")
        swall = _weight._STEERER_WALL.get(ft.material, 1.6)
        steer_sec = tube_section(sod, sod, swall, ft.material, yield_=_yield(d, ft.material))
        cr = p["crown"]
        mems.append(_line("steerer", (cb.x, cb.y, 0), (cr.x, cr.y, 0), lambda s, L: steer_sec, kind="fork"))
        hb = p["ht_bottom"]
        mems.append(_line("crown_race", (cr.x, cr.y, 0), (hb.x, hb.y, 0), rig))
        fr = ft.za
        fax = tube_section(12.0, 12.0, 2.5, "steel")
        mems.append(_Mem("front_axle", np.array([[fa.x, fa.y, -fr], [fa.x, fa.y, fr]]), lambda s, L: fax,
                         kind="part", group="front_axle", target=True, stations=[fr]))
    else:
        hb = p["ht_bottom"]
        mems.append(_line("dummy_fork", (hb.x, hb.y, 0), (fa.x, fa.y, 0), rig))
    mems.append(_line("front_wheel", (fa.x, fa.y, 0), contact, rig))

    # -- load points (rigid levers to an anchor node; applied as force + moment) ------------------
    q = d.f("q_factor") / 2
    cl = d.f("crank_length")
    named: dict[str, tuple[float, float, float]] = {
        "bb": (0, 0, 0), "bb_r": (0, 0, w / 2), "bb_l": (0, 0, -w / 2),
        "dropout_r": (ra.x, ra.y, hub_r), "dropout_l": (ra.x, ra.y, -hub_r), "rear_axle": (ra.x, ra.y, 0),
        "front_axle": (fa.x, fa.y, 0), "contact_front": contact,
        "ht_top": (p["ht_top"].x, p["ht_top"].y, 0), "ht_bottom": (p["ht_bottom"].x, p["ht_bottom"].y, 0),
        "tt_ht": (p["tt_ht"].x, p["tt_ht"].y, 0), "dt_ht": (p["dt_ht"].x, p["dt_ht"].y, 0),
        "seat_cluster": (p["tt_st"].x, p["tt_st"].y, 0), "st_top": (p["st_top"].x, p["st_top"].y, 0),
    }
    virtual: dict[str, tuple[str, tuple[float, float, float]]] = {}     # name -> (anchor, point)
    st_anchor = "st_top" if "st" in g.tubes else ("seat_cluster" if "tt" in g.tubes else None)
    if st_anchor is not None:
        sad = p["saddle"]
        virtual["saddle"] = (st_anchor, (sad.x, sad.y, 0.0))            # seatpost
    hand = p.get("hand", p["bar"])
    virtual["hand"] = ("ht_top", (hand.x, hand.y, 0.0))                 # stem + steerer
    virtual["pedal_r"] = ("bb_r", (0.0, 0.0, q))                        # spindle ends
    virtual["pedal_l"] = ("bb_l", (0.0, 0.0, -q))
    virtual["crank_pedal"] = ("bb_r", (cl, 0.0, q))                     # crank horizontal forward
    rings = [r for r in d.lst("chainrings") if r >= 3] or [40.0]
    pitch = d.f("chain_pitch")
    r_ring = pitch / (2 * math.sin(math.pi / min(rings)))
    virtual["ring_top"] = ("bb_r", (0.0, r_ring, max(d.f("chainline"), w / 2 + 1)))

    # -- attach member ends --------------------------------------------------------------------
    seg_a, seg_b, seg_m, seg_c0 = [], [], [], []
    for mi, m in enumerate(mems):
        if not m.target:
            continue
        for k in range(len(m.pts) - 1):
            seg_a.append(m.pts[k])
            seg_b.append(m.pts[k + 1])
            seg_m.append(mi)
            seg_c0.append(m.cum[k])
    SA, SB = np.array(seg_a), np.array(seg_b)
    SM, SC0 = np.array(seg_m), np.array(seg_c0)
    AB = SB - SA
    L2 = np.maximum((AB * AB).sum(1), 1e-12)
    SL = np.sqrt(L2)
    groups: dict[str, list[int]] = {}
    for mi, m in enumerate(mems):
        groups.setdefault(m.group, []).append(mi)
    hint_map = {"bb": "bb", "ht": "ht", "st": "st", "tt": "tt", "ss_mono": "ss_mono", "crown": "crown"}

    def nearest(pt: np.ndarray, allowed: np.ndarray):
        t = np.clip(((pt - SA) * AB).sum(1) / L2, 0.0, 1.0)
        qq = SA + AB * t[:, None]
        dd = np.linalg.norm(qq - pt, axis=1)
        dd = np.where(allowed, dd, np.inf)
        return dd, t, qq

    extra_links: list[_Mem] = []
    tol = 1.0
    for mi, m in enumerate(mems):
        for end, join in ((m.pts[0], m.join_a), (m.pts[-1], m.join_b)):
            allowed = SM != mi
            dd, t, qq = nearest(end, allowed)
            hit = np.flatnonzero(dd <= tol)
            done = set()
            for h in hit:
                tm = int(SM[h])
                if tm in done:
                    continue
                cand = hit[SM[hit] == tm]
                best = cand[np.argmin(dd[cand])]
                mems[tm].stations.append(float(SC0[best] + t[best] * SL[best]))
                done.add(tm)
            # ends that do not lie on another member: rigid link to the member they join
            if done or not m.auto_link or join in ("dropout", "ss"):
                continue
            if join is None and m.auto_link != "nearest":
                continue                                  # free end (seat-tube top, head-tube faces)
            target = hint_map.get(join or "", None)
            tgt_idx = groups.get(target, []) if target else []
            sel = (np.isin(SM, tgt_idx) & allowed) if tgt_idx else np.zeros_like(allowed)
            if sel.any():
                max_gap = 250.0
            else:                                         # joined tube removed / extra tube
                sel = allowed & np.array([mems[x].kind in ("frame", "fork") for x in SM])
                max_gap = 80.0
            dd, t, qq = nearest(end, sel)
            h = int(np.argmin(dd))
            if not np.isfinite(dd[h]) or dd[h] > max_gap:
                continue
            tm = int(SM[h])
            mems[tm].stations.append(float(SC0[h] + t[h] * SL[h]))
            extra_links.append(_line(f"link_{m.name}", end, qq[h], rig))
    mems += extra_links

    # -- nodes and elements ---------------------------------------------------------------
    model = FrameModel(merge_tol=0.5)
    for m in mems:
        st = sorted(set(min(max(s, 0.0), m.L) for s in m.stations))
        keep = [st[0]]
        for s in st[1:]:
            if s - keep[-1] > 0.5:
                keep.append(s)
            elif s >= m.L - 1e-9:
                keep[-1] = m.L
        ids = [model.node(m.point_at(s)) for s in keep]
        for (s0, s1), (a, b) in zip(zip(keep, keep[1:]), zip(ids, ids[1:])):
            model.beam(a, b, m.sec(0.5 * (s0 + s1), m.L), m.name, m.kind)
    X = model.xyz
    for nm, pt in named.items():
        dd = np.abs(X - np.asarray(pt, float)).max(axis=1)
        k = int(np.argmin(dd))
        if dd[k] <= 0.75:
            model.names[nm] = k
    for nm, (anchor, pt) in list(virtual.items()):
        if anchor not in model.names:
            del virtual[nm]
    info = {"named": named, "virtual": virtual, "members": mems, "include_fork": include_fork,
            "r_ring": r_ring, "contact": contact}
    return model, info


def _connected(model: FrameModel, start: int) -> np.ndarray:
    adj: dict[int, list[int]] = {}
    for a, b in zip(model.ei, model.ej):
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen = np.zeros(model.n, dtype=bool)
    stack = [start]
    seen[start] = True
    while stack:
        u = stack.pop()
        for v in adj.get(u, ()):
            if not seen[v]:
                seen[v] = True
                stack.append(v)
    return seen


# --------------------------------------------------------------------------
# load cases
# --------------------------------------------------------------------------
def _cases(g: Geometry, info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    d = g.design
    W = d.f("fea_rider_weight")
    sh_s = min(max(d.f("fea_saddle_share"), 0.0), 100.0) / 100.0
    sh_b = min(max(d.f("fea_bar_share"), 0.0), 100.0 - sh_s * 100.0) / 100.0
    sh_p = max(1.0 - sh_s - sh_b, 0.0)
    Fp = d.f("fea_pedal_force")
    Tm = d.f("fea_ht_torque") * 1000.0
    out: dict[str, dict[str, Any]] = {}
    vert = [("hand", 1, -W * sh_b), ("pedal_r", 1, -W * sh_p / 2), ("pedal_l", 1, -W * sh_p / 2)]
    if "saddle" in info["virtual"]:
        vert.append(("saddle", 1, -W * sh_s))
    else:
        vert.append(("bb", 1, -W * sh_s))
    out["vertical"] = {"loads": vert, "bc": "std",
                       "desc": f"{W:.0f} N rider: {sh_s * 100:.0f} % saddle, {sh_b * 100:.0f} % bars, "
                               f"{sh_p * 100:.0f} % pedals"}
    out["pedalling"] = {"loads": [("pedal_r", 1, -Fp)], "bc": "std",
                        "desc": f"{Fp:.0f} N down at the drive-side pedal spindle (Q/2 from centre)"}
    out["ht_torsion"] = {"loads": [("ht_top", 3, Tm / 2), ("ht_bottom", 3, Tm / 2)], "bc": "torsion",
                         "desc": f"{Tm / 1000:.0f} N·m about the long (X) axis at the head tube, rear held"}
    # braking: rider weight + forward inertia (same shares), reacted by the front tyre
    Fb = d.f("fea_brake_force")
    brake = [(nm, dof, val) for nm, dof, val in vert]
    if W > 0:
        brake += [(nm, 0, -val * Fb / W) for nm, dof, val in vert]
    else:
        brake += [("hand", 0, Fb)]
    brake.append(("contact_front", 0, -Fb))       # tyre friction balances the inertia exactly
    out["braking"] = {"loads": brake, "bc": "std",
                      "desc": f"{Fb:.0f} N front braking: rider weight plus forward inertia, "
                              "reacted by the front tyre"}
    Fi = d.f("fea_inplane_force")
    out["in_plane"] = {"loads": [("front_axle", 0, Fi)], "bc": "std",
                       "desc": f"{Fi:.0f} N forward at the front axle"}
    Ft = d.f("fea_transverse_force")
    tn = "seat_cluster" if "tt" in g.tubes else "st_top"
    out["transverse"] = {"loads": [(tn, 2, Ft)], "bc": "std",
                         "desc": f"{Ft:.0f} N lateral at the seat cluster"}
    # eccentric: crank forward-horizontal; chain pull balances the crank torque exactly
    ra = g.p["rear_axle"]
    pitch = d.f("chain_pitch")
    cogs = [c for c in d.lst("cogs") if c >= 3] or [16.0]
    r_cog = pitch / (2 * math.sin(math.pi / max(cogs)))
    r_ring = info["r_ring"]
    cdir = np.array([ra.x, ra.y + r_cog]) - np.array([0.0, r_ring])
    cdir /= np.linalg.norm(cdir)
    arm = -r_ring * cdir[0]                       # z-moment of a unit chain force at the ring top
    cl = d.f("crank_length")
    Tc = cl * Fp / arm if arm > 1e-6 else 0.0
    out["eccentric"] = {"loads": [("crank_pedal", 1, -Fp), ("ring_top", 0, Tc * cdir[0]),
                                  ("ring_top", 1, Tc * cdir[1])], "bc": "std",
                        "desc": f"{Fp:.0f} N on the drive pedal, crank horizontal; chain pull {Tc:.0f} N"}
    return out


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
def analyse(g: Geometry, cases: Iterable[str] | None = None) -> dict[str, Any]:
    """Run the load cases (default: all of :data:`CASES`).

    Returns ``{"ok", "cases": {name: {...}}, "headline": {...}, "summary": str,
    "model": {...}, "time_ms", "notes"}``.  Per case: ``displacements``
    (named node -> (ux, uy, uz, rx, ry, rz) in mm / rad), ``members`` (member
    -> stress / bending / sf), ``max_stress``, ``critical_member``,
    ``min_sf`` and ``metric`` (the case's stiffness figure).

    The default (full) run is memoised on the geometry instance -- it is shared
    across the report builders and the UI, and replaced on every edit -- so the
    FEA solves once per geometry instead of once per consumer.
    """
    if cases is None:
        cached = getattr(g, "_analyse_cache", None)
        if cached is not None:
            return cached
        result = _analyse_impl(g, None)
        try:
            g._analyse_cache = result
        except Exception:                             # pragma: no cover
            pass
        return result
    return _analyse_impl(g, cases)


def _analyse_impl(g: Geometry, cases: Iterable[str] | None) -> dict[str, Any]:
    t0 = time.perf_counter()
    d = g.design
    want = [c for c in (cases or CASES) if c in CASES]
    try:
        model, info = build_model(g)
    except Exception as exc:                          # degenerate geometry
        return {"ok": False, "error": f"model build failed: {exc}", "cases": {}, "headline": {},
                "summary": "Structure estimate unavailable", "notes": [NOTE]}
    names = model.names
    missing = [n for n in ("bb", "dropout_r", "dropout_l", "contact_front") if n not in names]
    if missing:
        return {"ok": False, "error": "model incomplete: " + ", ".join(missing), "cases": {}, "headline": {},
                "summary": "Structure estimate unavailable (frame not connected to its supports)", "notes": [NOTE]}
    active = _connected(model, names["bb"])
    if not all(active[names[n]] for n in ("dropout_r", "dropout_l", "contact_front")):
        return {"ok": False, "error": "frame not connected to its supports", "cases": {}, "headline": {},
                "summary": "Structure estimate unavailable (frame not connected to its supports)", "notes": [NOTE]}
    defs = _cases(g, info)
    # supports: both dropouts pinned, front contact held vertically ("torsion" set); the
    # standard cases also hold the contact laterally (added below as a constraint)
    held = ([6 * names["dropout_r"] + k for k in range(3)] + [6 * names["dropout_l"] + k for k in range(3)]
            + [6 * names["contact_front"] + 1])
    virtual = info["virtual"]
    X = model.xyz

    def add_load(F: np.ndarray, ci: int, nm: str, dof: int, val: float) -> None:
        if nm in virtual:                          # rigid lever: force + moment at the anchor node
            anchor, pt = virtual[nm]
            a = names[anchor]
            if not active[a]:
                return
            f, m = np.zeros(3), np.zeros(3)
            if dof < 3:
                f[dof] = val
                m = np.cross(np.asarray(pt, float) - X[a], f)
            else:
                m[dof - 3] = val
            F[6 * a:6 * a + 3, ci] += f
            F[6 * a + 3:6 * a + 6, ci] += m
        elif nm in names and active[names[nm]]:
            F[6 * names[nm] + dof, ci] += val

    def disp_of(u: np.ndarray, nm: str) -> np.ndarray | None:
        if nm in virtual:
            anchor, pt = virtual[nm]
            ua = u[names[anchor]]
            r = np.asarray(pt, float) - X[names[anchor]]
            w = ua[3:]
            return np.concatenate([ua[:3] + np.array([w[1] * r[2] - w[2] * r[1], w[2] * r[0] - w[0] * r[2],
                                                      w[0] * r[1] - w[1] * r[0]]), w])
        if nm in names:
            return u[names[nm]]
        return None

    # One factorisation: solve with the torsion supports (fewest constraints) and add the
    # front lateral support of the standard cases as a Lagrange constraint.
    U_all: dict[str, np.ndarray] = {}
    cz = 6 * names["contact_front"] + 2
    F = np.zeros((model.ndof, len(want) + 1))
    for ci, c in enumerate(want):
        for nm, dof, val in defs[c]["loads"]:
            add_load(F, ci, nm, dof, val)
    F[cz, -1] = 1.0
    try:
        U = model.solve(held, F, active)
    except np.linalg.LinAlgError:
        return {"ok": False, "error": "singular stiffness matrix (mechanism)", "cases": {}, "headline": {},
                "summary": "Structure estimate unavailable (unstable model)", "notes": [NOTE]}
    if not np.all(np.isfinite(U)) or np.abs(U[0::6]).max(initial=0) > 1e4 or U[cz, -1] <= 0:
        return {"ok": False, "error": "unstable model", "cases": {}, "headline": {},
                "summary": "Structure estimate unavailable (unstable model)", "notes": [NOTE]}
    gcol = U[:, -1]
    for ci, c in enumerate(want):
        u = U[:, ci]
        if defs[c]["bc"] == "std":
            u = u - (u[cz] / gcol[cz]) * gcol
        U_all[c] = u
    order = [c for c in want if c in U_all]
    Umat = np.column_stack([U_all[c] for c in order]) if order else np.zeros((model.ndof, 0))
    er = model.element_results(Umat)
    member_names = model.member
    kinds = model.kind
    secs = model.sec
    results: dict[str, dict[str, Any]] = {}
    for ci, c in enumerate(order):
        u = U_all[c].reshape(-1, 6)
        disp = {nm: tuple(float(x) for x in disp_of(u, nm)) for nm in list(names) + list(virtual)}
        mem: dict[str, dict[str, float]] = {}
        for e in range(len(member_names)):
            if kinds[e] == "link" or secs[e].rigid:
                continue
            nm = member_names[e]
            vm = float(er["von_mises"][e, ci])
            rec = mem.setdefault(nm, {"stress": 0.0, "bending": 0.0, "axial": 0.0, "shear": 0.0,
                                      "yield": secs[e].yield_, "material": secs[e].material, "kind": kinds[e]})
            if vm > rec["stress"]:
                rec["stress"] = vm
                rec["yield"] = secs[e].yield_
            rec["bending"] = max(rec["bending"], float(er["bending"][e, ci]))
            rec["axial"] = max(rec["axial"], float(er["axial"][e, ci]))
            rec["shear"] = max(rec["shear"], float(er["shear"][e, ci]))
        for rec in mem.values():
            rec["sf"] = rec["yield"] / rec["stress"] if rec["stress"] > 1e-9 else float("inf")
        frame_mem = {k: v for k, v in mem.items() if v["kind"] in ("frame", "fork")}
        crit = min(frame_mem.items(), key=lambda kv: kv[1]["sf"]) if frame_mem else (None, {"sf": float("inf"),
                                                                                           "stress": 0.0})
        results[c] = {
            "title": CASE_TITLES[c], "description": defs[c]["desc"], "displacements": disp,
            "max_disp": float(np.abs(u[active, :3]).max(initial=0.0)),
            "members": mem, "max_stress": float(crit[1]["stress"]), "critical_member": crit[0],
            "min_sf": float(crit[1]["sf"]), "metric": {},
        }

    # -- headline stiffness figures -------------------------------------------------------------
    head: dict[str, float] = {}

    def U(case, nm, k):
        if case not in U_all:
            return float("nan")
        v = disp_of(U_all[case].reshape(-1, 6), nm)
        return float("nan") if v is None else float(v[k])

    def stiff(force, disp):
        return abs(force) / abs(disp) if disp == disp and abs(disp) > 1e-12 else float("nan")

    if "vertical" in U_all and "saddle" in virtual:
        Fs = d.f("fea_rider_weight") * d.f("fea_saddle_share") / 100.0
        v = stiff(Fs, U("vertical", "saddle", 1))
        head["saddle_vertical_stiffness"] = v
        results["vertical"]["metric"] = {"Saddle vertical deflection (mm)": abs(U("vertical", "saddle", 1)),
                                         "BB vertical deflection (mm)": abs(U("vertical", "bb", 1)),
                                         "Saddle vertical stiffness (N/mm)": v}
    if "pedalling" in U_all:
        v = stiff(d.f("fea_pedal_force"), U("pedalling", "bb", 2))
        head["bb_lateral_stiffness"] = v
        results["pedalling"]["metric"] = {"BB lateral deflection (mm)": abs(U("pedalling", "bb", 2)),
                                          "BB lateral stiffness (N/mm)": v}
    if "ht_torsion" in U_all:
        rot = 0.5 * (U("ht_torsion", "ht_top", 3) + U("ht_torsion", "ht_bottom", 3))
        deg = math.degrees(rot)
        v = stiff(d.f("fea_ht_torque"), deg)
        head["ht_torsional_stiffness"] = v
        results["ht_torsion"]["metric"] = {"Head-tube rotation (deg)": abs(deg),
                                           "Torsional stiffness (N·m/deg)": v}
    if "braking" in U_all:
        shorten = U("braking", "front_axle", 0) - 0.5 * (U("braking", "dropout_r", 0) + U("braking", "dropout_l", 0))
        rot = 0.5 * (U("braking", "ht_top", 5) + U("braking", "ht_bottom", 5))
        results["braking"]["metric"] = {"Wheelbase change (mm)": shorten,
                                        "Head-tube rotation in side view (deg)": math.degrees(rot)}
    if "in_plane" in U_all:
        v = stiff(d.f("fea_inplane_force"), U("in_plane", "front_axle", 0))
        head["inplane_stiffness"] = v
        results["in_plane"]["metric"] = {"Front axle fore-aft deflection (mm)": abs(U("in_plane", "front_axle", 0)),
                                         "In-plane stiffness (N/mm)": v}
    if "transverse" in U_all:
        tn = "seat_cluster" if "tt" in g.tubes else "st_top"
        v = stiff(d.f("fea_transverse_force"), U("transverse", tn, 2))
        head["transverse_stiffness"] = v
        results["transverse"]["metric"] = {"Seat cluster lateral deflection (mm)": abs(U("transverse", tn, 2)),
                                           "Lateral stiffness (N/mm)": v}
    if "eccentric" in U_all:
        results["eccentric"]["metric"] = {"BB lateral deflection (mm)": abs(U("eccentric", "bb", 2))}
    if results:
        worst = min(results.items(), key=lambda kv: kv[1]["min_sf"])
        head["min_safety_factor"] = worst[1]["min_sf"]
        head_crit = (worst[0], worst[1]["critical_member"])
    else:
        head_crit = (None, None)
    ms = (time.perf_counter() - t0) * 1000.0
    out = {
        "ok": True, "estimate": True, "cases": results, "headline": head, "critical": head_crit,
        "model": {"nodes": model.xyz.copy(), "elements": list(zip(model.ei, model.ej, model.member)),
                  "kinds": list(model.kind), "node_names": dict(names),
                  "u": {c: U_all[c].reshape(-1, 6) for c in order}, "include_fork": info["include_fork"]},
        "time_ms": ms, "notes": [NOTE],
    }
    out["summary"] = _summary(out)
    return out


def _fmt(v: float, unit: str, dec: int = 1) -> str:
    return "–" if v != v or v == float("inf") else f"{v:.{dec}f} {unit}"


def _summary(res: dict[str, Any]) -> str:
    h = res["headline"]
    lines = ["Frame structure (linear beam FE estimate):"]
    if "bb_lateral_stiffness" in h:
        lines.append(f"  BB lateral stiffness       {_fmt(h['bb_lateral_stiffness'], 'N/mm')}")
    if "ht_torsional_stiffness" in h:
        lines.append(f"  Head-tube torsion          {_fmt(h['ht_torsional_stiffness'], 'N·m/deg')}")
    if "saddle_vertical_stiffness" in h:
        lines.append(f"  Saddle vertical stiffness  {_fmt(h['saddle_vertical_stiffness'], 'N/mm')}")
    if "inplane_stiffness" in h:
        lines.append(f"  In-plane (front axle)      {_fmt(h['inplane_stiffness'], 'N/mm')}")
    if "transverse_stiffness" in h:
        lines.append(f"  Lateral (seat cluster)     {_fmt(h['transverse_stiffness'], 'N/mm')}")
    for c, r in res["cases"].items():
        lines.append(f"  {r['title']:<38s} max {_fmt(r['max_stress'], 'MPa', 0)} in "
                     f"{r['critical_member'] or '–'}, SF {_fmt(r['min_sf'], '', 2).strip()}")
    lines.append("  " + NOTE)
    return "\n".join(lines)
