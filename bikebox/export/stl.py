"""Triangle-mesh (STL) export of the frame tubes and BB shell.

Vertices are in model millimetres ``(x, y, z)`` -- +X forward, +Y up, +Z to the
drive side -- so the STL bounds match the frame's own extent.  Each tube is a
swept circular section along its centreline (bends are approximated by the
centreline's arc segments); the lateral offset of the centreline interpolates
from ``za`` to ``zb`` and the radius from ``od_a/2`` to ``od_b/2``.  Oval/aero
tubes are approximated as round.  Mirrored tubes (stays, fork blades) get a
reflected copy at ``-z``.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

from ..geometry.solver import Geometry, Tube

Vec3 = tuple[float, float, float]
Tri = tuple[Vec3, Vec3, Vec3]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec3) -> Vec3:
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 0.0, 1.0)


def _ring(center: Vec3, tangent: Vec3, n1: Vec3, n2: Vec3, r: float, segs: int) -> list[Vec3]:
    out = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        c, s = math.cos(a), math.sin(a)
        out.append((center[0] + r * (c * n1[0] + s * n2[0]),
                    center[1] + r * (c * n1[1] + s * n2[1]),
                    center[2] + r * (c * n1[2] + s * n2[2])))
    return out


def _frame_axes(tangent: Vec3) -> tuple[Vec3, Vec3]:
    """Two unit normals perpendicular to ``tangent``."""
    t = _norm(tangent)
    ref = (0.0, 0.0, 1.0)
    if abs(t[2]) > 0.9:
        ref = (0.0, 1.0, 0.0)
    n1 = _norm(_cross(t, ref))
    n2 = _norm(_cross(t, n1))
    return n1, n2


def _sweep(centers: list[Vec3], radii: list[float], segs: int, cap: bool = True) -> list[Tri]:
    tris: list[Tri] = []
    if len(centers) < 2:
        return tris
    rings: list[list[Vec3]] = []
    for i in range(len(centers)):
        if i < len(centers) - 1:
            tan = _sub(centers[i + 1], centers[i])
        else:
            tan = _sub(centers[i], centers[i - 1])
        n1, n2 = _frame_axes(tan)
        rings.append(_ring(centers[i], tan, n1, n2, radii[i], segs))
    for i in range(len(rings) - 1):
        r0, r1 = rings[i], rings[i + 1]
        for j in range(segs):
            k = (j + 1) % segs
            tris.append((r0[j], r0[k], r1[k]))
            tris.append((r0[j], r1[k], r1[j]))
    if cap:
        c0, c1 = centers[0], centers[-1]
        r0, r1 = rings[0], rings[-1]
        for j in range(segs):
            k = (j + 1) % segs
            tris.append((c0, r0[k], r0[j]))
            tris.append((c1, r1[j], r1[k]))
    return tris


def _mirror_z(tris: list[Tri]) -> list[Tri]:
    out: list[Tri] = []
    for a, b, c in tris:
        # reflect z and flip winding to keep outward normals
        ma = (a[0], a[1], -a[2])
        mb = (b[0], b[1], -b[2])
        mc = (c[0], c[1], -c[2])
        out.append((ma, mc, mb))
    return out


def _tube_centers(t: Tube, segments: int) -> tuple[list[Vec3], list[float]]:
    pts = t.points(segments if abs(t.bend) > 1e-6 else 2)
    L = sum(pts[i].dist(pts[i + 1]) for i in range(len(pts) - 1)) or 1.0
    centers: list[Vec3] = []
    radii: list[float] = []
    acc = 0.0
    for i, p in enumerate(pts):
        if i:
            acc += pts[i - 1].dist(p)
        f = acc / L
        z = t.za + (t.zb - t.za) * f
        centers.append((p.x, p.y, z))
        radii.append(max(t.od_at(f) / 2.0, 0.2))
    return centers, radii


def _bb_mesh(g: Geometry, segs: int) -> list[Tri]:
    d = g.design
    r = float(d.get("bb_shell_od", 40.0)) / 2.0
    w = float(d.get("bb_shell_width", 68.0))
    centers = [(0.0, 0.0, -w / 2.0), (0.0, 0.0, w / 2.0)]
    return _sweep(centers, [r, r], segs, cap=True)


def _wheel_mesh(center, outer_r: float, tire_r: float, segs: int, minor: int = 12) -> list[Tri]:
    """A torus in the x-y (wheel) plane at z=0."""
    tris: list[Tri] = []
    rings: list[list[Vec3]] = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        cx, cy = center.x + outer_r * math.cos(a), center.y + outer_r * math.sin(a)
        ring = []
        for j in range(minor):
            b = 2 * math.pi * j / minor
            rr = outer_r + tire_r * math.cos(b)
            ring.append((center.x + rr * math.cos(a), center.y + rr * math.sin(a),
                         tire_r * math.sin(b)))
        rings.append(ring)
    for i in range(segs):
        r0 = rings[i]
        r1 = rings[(i + 1) % segs]
        for j in range(minor):
            k = (j + 1) % minor
            tris.append((r0[j], r0[k], r1[k]))
            tris.append((r0[j], r1[k], r1[j]))
    return tris


def frame_mesh(g: Geometry, segments: int = 32, include_wheels: bool = False) -> list[Tri]:
    """All frame triangles as ``[(v0, v1, v2), ...]`` with ``v = (x, y, z)``."""
    tris: list[Tri] = []
    for t in g.tubes.values():
        centers, radii = _tube_centers(t, segments)
        tube_tris = _sweep(centers, radii, segments)
        tris.extend(tube_tris)
        if t.mirrored:
            tris.extend(_mirror_z(tube_tris))
    tris.extend(_bb_mesh(g, segments))
    if include_wheels:
        for w in g.wheels.values():
            tris.extend(_wheel_mesh(w.center, w.outer_r, max(w.tire_h, 10.0) / 2.0, segments))
    return tris


def mesh_bounds(tris: list[Tri]) -> tuple[Vec3, Vec3]:
    xs = [v[0] for t in tris for v in t]
    ys = [v[1] for t in tris for v in t]
    zs = [v[2] for t in tris for v in t]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def save_stl(g: Geometry, path, binary: bool = True, segments: int = 32,
             include_wheels: bool = False) -> Path:
    tris = frame_mesh(g, segments, include_wheels)
    path = Path(path)
    if binary:
        _write_binary(tris, path)
    else:
        _write_ascii(tris, path)
    return path


def _write_binary(tris: list[Tri], path: Path) -> None:
    with path.open("wb") as fh:
        fh.write(b"Bike Box binary STL".ljust(80, b"\0")[:80])
        fh.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = _norm(_cross(_sub(b, a), _sub(c, a)))
            fh.write(struct.pack("<3f", *n))
            fh.write(struct.pack("<3f", *a))
            fh.write(struct.pack("<3f", *b))
            fh.write(struct.pack("<3f", *c))
            fh.write(struct.pack("<H", 0))


def _write_ascii(tris: list[Tri], path: Path) -> None:
    lines = ["solid bikebox"]
    for a, b, c in tris:
        n = _norm(_cross(_sub(b, a), _sub(c, a)))
        lines.append(f"facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
        lines.append("outer loop")
        for v in (a, b, c):
            lines.append(f"vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}")
        lines.append("endloop")
        lines.append("endfacet")
    lines.append("endsolid bikebox")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
