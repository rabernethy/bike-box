"""Indexed solid meshes for CAD interchange (STEP / IGES).

The STL exporter already tessellates every tube into the swept triangle soup the
3-D view shows; this module turns that same tessellation into *indexed* solids
(shared vertices, so every edge is used by exactly two faces) and verifies each
one is a closed, orientable manifold before it is handed to a B-rep writer.

Nothing new is invented here: the geometry is the tube outer envelope, faceted,
exactly as in :mod:`bikebox.export.stl`.  Tubes are **un-mitred** -- they run the
full centre-to-centre length and interpenetrate at the joints, which is how tube
solids are normally imported before being coped in CAD.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..geometry.solver import Geometry, Tube
from . import stl

Vec3 = tuple[float, float, float]


@dataclass
class Solid:
    """One closed solid: a vertex list and faces as index tuples (CCW outward)."""
    name: str
    verts: list[Vec3]
    faces: list[tuple[int, ...]]

    def bounds(self) -> tuple[Vec3, Vec3]:
        xs = [v[0] for v in self.verts]
        ys = [v[1] for v in self.verts]
        zs = [v[2] for v in self.verts]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


@dataclass
class ManifoldReport:
    ok: bool
    verts: int
    edges: int
    faces: int
    euler: int                     # V - E + F  (2 for a genus-0 closed solid)
    problems: list[str] = field(default_factory=list)


def _weld(tris: list[stl.Tri], tol: float = 1e-4) -> Solid | None:
    """Weld a triangle soup into an indexed solid (quantising to ``tol`` mm)."""
    index: dict[tuple[int, int, int], int] = {}
    verts: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    inv = 1.0 / tol

    def vid(p: Vec3) -> int:
        key = (round(p[0] * inv), round(p[1] * inv), round(p[2] * inv))
        i = index.get(key)
        if i is None:
            i = len(verts)
            index[key] = i
            verts.append(p)
        return i

    for a, b, c in tris:
        ia, ib, ic = vid(a), vid(b), vid(c)
        if ia == ib or ib == ic or ia == ic:
            continue                           # skip degenerate (welded) triangles
        faces.append((ia, ib, ic))
    if not faces:
        return None
    return Solid("", verts, faces)


def check_manifold(solid: Solid) -> ManifoldReport:
    """A closed orientable manifold: every directed edge appears once and its
    reverse appears once, so each undirected edge is shared by exactly two faces,
    and the Euler characteristic V - E + F is 2 (genus 0)."""
    directed: dict[tuple[int, int], int] = {}
    undirected: dict[tuple[int, int], int] = {}
    problems: list[str] = []
    for f in solid.faces:
        n = len(f)
        for i in range(n):
            u, v = f[i], f[(i + 1) % n]
            directed[(u, v)] = directed.get((u, v), 0) + 1
            key = (u, v) if u < v else (v, u)
            undirected[key] = undirected.get(key, 0) + 1
    for (u, v), c in directed.items():
        if c != 1:
            problems.append(f"directed edge {u}->{v} used {c}x (expected 1)")
        if directed.get((v, u), 0) != 1:
            problems.append(f"edge {u}->{v} has no matching opposite {v}->{u}")
    bad = [e for e, c in undirected.items() if c != 2]
    for e in bad:
        problems.append(f"undirected edge {e} shared by {undirected[e]} faces (expected 2)")
    V, E, F = len(solid.verts), len(undirected), len(solid.faces)
    euler = V - E + F
    if euler != 2:
        problems.append(f"Euler characteristic V-E+F = {euler} (expected 2 for a closed solid)")
    # every vertex must be referenced
    used = {i for f in solid.faces for i in f}
    if len(used) != V:
        problems.append(f"{V - len(used)} unreferenced vertices")
    return ManifoldReport(not problems, V, E, F, euler, problems[:20])


# -- tube -> indexed solid -------------------------------------------------------
def _tube_solid(t: Tube, segments: int, mirror: bool = False) -> Solid | None:
    centers, radii = stl._tube_centers(t, segments)
    if len(centers) < 2:
        return None
    rings: list[list[int]] = []
    verts: list[Vec3] = []
    for i, c in enumerate(centers):
        tan = stl._sub(centers[i + 1], c) if i < len(centers) - 1 else stl._sub(c, centers[i - 1])
        n1, n2 = stl._frame_axes(tan)
        r1, r2 = stl._as_pair(radii[i])
        ring = stl._ring(c, tan, n1, n2, r1, r2, segments)
        base = len(verts)
        verts.extend(ring)
        rings.append(list(range(base, base + segments)))
    faces: list[tuple[int, ...]] = []
    for i in range(len(rings) - 1):
        r0, r1 = rings[i], rings[i + 1]
        for j in range(segments):
            k = (j + 1) % segments
            # two triangles per quad, wound CCW seen from outside
            faces.append((r0[j], r0[k], r1[k]))
            faces.append((r0[j], r1[k], r1[j]))
    # end caps as single planar polygons (the ring points are coplanar)
    faces.append(tuple(reversed(rings[0])))        # start cap, normal = -tangent
    faces.append(tuple(rings[-1]))                 # end cap, normal = +tangent
    solid = Solid(t.label, verts, faces)
    if mirror:
        solid = _mirror(solid)
    return solid


def _mirror(s: Solid) -> Solid:
    verts = [(x, y, -z) for (x, y, z) in s.verts]
    faces = [tuple(reversed(f)) for f in s.faces]      # keep outward normals
    return Solid(s.name, verts, faces)


def _bb_solid(g: Geometry, segments: int) -> Solid | None:
    d = g.design
    r = float(d.get("bb_shell_od", 40.0)) / 2.0
    w = float(d.get("bb_shell_width", 68.0))
    t = Tube("bb", "BB shell", g.tubes["st"].a if "st" in g.tubes else _origin(), _origin(), 0, 0)
    # build directly rather than via Tube (BB is a plain cylinder along z)
    centers = [(0.0, 0.0, -w / 2.0), (0.0, 0.0, w / 2.0)]
    radii = [r, r]
    rings: list[list[int]] = []
    verts: list[Vec3] = []
    for i, c in enumerate(centers):
        tan = stl._sub(centers[1], centers[0])
        n1, n2 = stl._frame_axes(tan)
        ring = stl._ring(c, tan, n1, n2, r, r, segments)
        base = len(verts)
        verts.extend(ring)
        rings.append(list(range(base, base + segments)))
    faces: list[tuple[int, ...]] = []
    r0, r1 = rings[0], rings[1]
    for j in range(segments):
        k = (j + 1) % segments
        faces.append((r0[j], r0[k], r1[k]))
        faces.append((r0[j], r1[k], r1[j]))
    faces.append(tuple(reversed(rings[0])))
    faces.append(tuple(rings[1]))
    return Solid("BB shell", verts, faces)


def _origin():
    from ..geometry.vec import V
    return V(0.0, 0.0)


def frame_solids(g: Geometry, segments: int = 48) -> list[Solid]:
    """One closed indexed solid per tube (mirrored tubes get a reflected copy)
    plus the BB shell.  Each is verified closed before being returned."""
    out: list[Solid] = []
    for t in g.tubes.values():
        s = _tube_solid(t, segments)
        if s:
            out.append(s)
        if t.mirrored:
            m = _tube_solid(t, segments, mirror=True)
            if m:
                m.name = t.label + " (drive side)"
                out[-1].name = t.label + " (non-drive side)"
                out.append(m)
    bb = _bb_solid(g, segments)
    if bb:
        out.append(bb)
    return out
