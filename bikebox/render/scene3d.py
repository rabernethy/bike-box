"""3-D scene data for the clearance viewer.

Pure data (no OpenGL), so it can be built and tested headlessly. The GL widget
(:mod:`bikebox.gui.view3d`) turns this into mesh / line items.

Coordinates are the solver's: origin at the BB, +X forward, +Y up, +Z drive side,
in millimetres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..export import stl
from ..geometry import clearance as C
from ..geometry.solver import Geometry


@dataclass
class ClearanceLine:
    key: str
    label: str                 # e.g. "Chainstay to tire"
    p: tuple[float, float, float]
    q: tuple[float, float, float]
    value: float               # mm (or deg)
    unit: str
    ok: bool                   # True = meets its threshold / no overlap

    @property
    def text(self) -> str:
        if self.key == "toe_steer_angle":
            return f"{self.label}: {self.value:.1f}° steer"
        if self.unit == "deg":
            return f"{self.label}: {self.value:.1f}°"
        return f"{self.label}: {self.value:.1f} mm"

    @property
    def mid(self) -> tuple[float, float, float]:
        return tuple((a + b) / 2 for a, b in zip(self.p, self.q))


@dataclass
class Scene3D:
    triangles: list                              # [(v0, v1, v2), ...] frame + wheels
    clearances: list[ClearanceLine] = field(default_factory=list)
    circles: list[dict] = field(default_factory=list)   # chainrings etc: {center, normal, r, color}
    segments3: list[dict] = field(default_factory=list)  # crank arm etc: {a, b, color}
    bounds: tuple = ((0, 0, 0), (0, 0, 0))


def _v3(p) -> tuple[float, float, float]:
    return (p.x, p.y, p.z)


def build(g: Geometry, segments: int = 28) -> Scene3D:
    tris = stl.frame_mesh(g, segments=segments, include_wheels=True)
    lines: list[ClearanceLine] = []
    for key, c in C.clearance_details(g).items():
        if c.p is None or c.q is None:
            continue
        if not (math.isfinite(c.value)):
            continue
        label, unit = C.LABELS.get(key, (key, "mm"))
        lines.append(ClearanceLine(key, label, _v3(c.p), _v3(c.q), c.value, unit,
                                   not C.is_problem(g, key, c.value)))
    # chainrings as circles in the plane X-Y at their z
    circles = []
    try:
        for r in C.chainrings(g):
            circles.append({"center": (0.0, 0.0, r.z), "normal": (0.0, 0.0, 1.0),
                            "r": r.r_out, "color": (0.8, 0.8, 0.2, 1.0)})
    except Exception:
        pass
    # crank arms (drive + non-drive) as line segments from the BB axis to the pedals
    segs = []
    p = g.p
    if "crank_bb" in p and "pedal" in p and C.has_drivetrain(g):
        bb = p["crank_bb"]
        q = g.design.f("q_factor") / 2
        ped = p["pedal"]
        segs.append({"a": (bb.x, bb.y, q), "b": (ped.x, ped.y, q + 20), "color": (0.7, 0.7, 0.75, 1.0)})
        pl = p.get("pedal_l", ped)
        segs.append({"a": (bb.x, bb.y, -q), "b": (pl.x, pl.y, -(q + 20)), "color": (0.7, 0.7, 0.75, 1.0)})
    return Scene3D(triangles=tris, clearances=lines, circles=circles, segments3=segs,
                   bounds=stl.mesh_bounds(tris) if tris else ((0, 0, 0), (0, 0, 0)))
