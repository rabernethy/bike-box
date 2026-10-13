"""STEP AP214 export of the frame tubes as B-rep solids.

Each tube is written as a faceted ``manifold_solid_brep`` (a closed shell of
planar ``advanced_face``s with straight ``edge_curve``s) built from the same
tessellation the STL export and 3-D view use.  The facets approximate the round
section; a higher ``segments`` count makes them smoother.  Tubes are the outer
envelope and are **un-mitred** -- they run full length and interpenetrate at the
joints, ready to be coped in CAD.

No solid-modelling kernel is used.  The output is validated structurally by
re-parsing it (:func:`parse_step_solids`) and confirming every solid comes back
as a closed, orientable manifold identical to the source mesh.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .. import __version__
from ..geometry.solver import Geometry
from . import mesh
from .mesh import Solid


def _r(x: float) -> str:
    """A Part-21 real literal: always a decimal point, uppercase exponent."""
    s = f"{float(x):.9g}".replace("E", "e")
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += "."
        return f"{mant}E{int(exp):+03d}"
    if "." not in s:
        s += "."
    return s


def _normal(verts: list, loop: tuple[int, ...]) -> tuple[float, float, float]:
    """Outward face normal via Newell's method (robust for any planar polygon)."""
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        a = verts[loop[i]]
        b = verts[loop[(i + 1) % n]]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    m = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return (nx / m, ny / m, nz / m)


class _Writer:
    def __init__(self):
        self.lines: list[str] = []
        self.n = 0

    def add(self, body: str) -> int:
        self.n += 1
        self.lines.append(f"#{self.n}={body};")
        return self.n

    # geometry primitives, de-duplicated where cheap
    def point(self, p) -> int:
        return self.add(f"CARTESIAN_POINT('',({_r(p[0])},{_r(p[1])},{_r(p[2])}))")

    def direction(self, d) -> int:
        return self.add(f"DIRECTION('',({_r(d[0])},{_r(d[1])},{_r(d[2])}))")


def _emit_solid(w: _Writer, solid: Solid, cp: list[int], vp: list[int]) -> int:
    """Emit one manifold_solid_brep; returns its id. ``cp``/``vp`` are the
    cartesian_point / vertex_point ids for this solid's vertices."""
    verts = solid.verts
    # one edge_curve per undirected edge, keyed (min,max); direction min->max
    edge_id: dict[tuple[int, int], int] = {}
    for f in solid.faces:
        k = len(f)
        for i in range(k):
            u, v = f[i], f[(i + 1) % k]
            key = (u, v) if u < v else (v, u)
            if key in edge_id:
                continue
            a, b = key
            d = (verts[b][0] - verts[a][0], verts[b][1] - verts[a][1], verts[b][2] - verts[a][2])
            length = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5 or 1.0
            dir_id = w.direction((d[0] / length, d[1] / length, d[2] / length))
            vec_id = w.add(f"VECTOR('',#{dir_id},{_r(length)})")
            line_id = w.add(f"LINE('',#{cp[a]},#{vec_id})")
            edge_id[key] = w.add(f"EDGE_CURVE('',#{vp[a]},#{vp[b]},#{line_id},.T.)")
    # faces
    face_ids: list[int] = []
    for f in solid.faces:
        nrm = _normal(verts, f)
        a0, a1 = verts[f[0]], verts[f[1]]
        ref = (a1[0] - a0[0], a1[1] - a0[1], a1[2] - a0[2])
        # project ref perpendicular to normal
        dp = ref[0] * nrm[0] + ref[1] * nrm[1] + ref[2] * nrm[2]
        ref = (ref[0] - dp * nrm[0], ref[1] - dp * nrm[1], ref[2] - dp * nrm[2])
        rl = (ref[0] ** 2 + ref[1] ** 2 + ref[2] ** 2) ** 0.5 or 1.0
        ref = (ref[0] / rl, ref[1] / rl, ref[2] / rl)
        axis_dir = w.direction(nrm)
        ref_dir = w.direction(ref)
        axis = w.add(f"AXIS2_PLACEMENT_3D('',#{cp[f[0]]},#{axis_dir},#{ref_dir})")
        plane = w.add(f"PLANE('',#{axis})")
        oriented: list[int] = []
        k = len(f)
        for i in range(k):
            u, v = f[i], f[(i + 1) % k]
            key = (u, v) if u < v else (v, u)
            sense = ".T." if u < v else ".F."
            oriented.append(w.add(f"ORIENTED_EDGE('',*,*,#{edge_id[key]},{sense})"))
        loop = w.add("EDGE_LOOP(''," + "(" + ",".join(f"#{o}" for o in oriented) + "))")
        bound = w.add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
        face_ids.append(w.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)"))
    shell = w.add("CLOSED_SHELL(''," + "(" + ",".join(f"#{i}" for i in face_ids) + "))")
    name = solid.name.replace("'", "")
    return w.add(f"MANIFOLD_SOLID_BREP('{name}',#{shell})")


def build_step(g: Geometry, segments: int = 48) -> str:
    solids = mesh.frame_solids(g, segments)
    w = _Writer()
    solid_ids: list[int] = []
    for s in solids:
        cp = [w.point(p) for p in s.verts]
        vp = [w.add(f"VERTEX_POINT('',#{cp[i]})") for i in range(len(s.verts))]
        solid_ids.append(_emit_solid(w, s, cp, vp))
    # units + geometric context
    len_u = w.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    ang_u = w.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sol_u = w.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),#{len_u},"
                "'distance_accuracy_value','confusion accuracy')")
    ctx = w.add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{len_u},#{ang_u},#{sol_u})) REPRESENTATION_CONTEXT('','') )")
    origin = w.point((0.0, 0.0, 0.0))
    zdir = w.direction((0.0, 0.0, 1.0))
    xdir = w.direction((1.0, 0.0, 0.0))
    axis = w.add(f"AXIS2_PLACEMENT_3D('',#{origin},#{zdir},#{xdir})")
    items = ",".join(f"#{i}" for i in [axis] + solid_ids)
    absr = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('Bike Box frame',({items}),#{ctx})")
    # product structure
    appctx = w.add("APPLICATION_CONTEXT('automotive design')")
    w.add("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2010,#%d)" % appctx)
    pctx = w.add(f"PRODUCT_CONTEXT('',#{appctx},'mechanical')")
    prod = w.add(f"PRODUCT('BikeBoxFrame','Bike Box frame','',(#{pctx}))")
    pdf = w.add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{prod},.NOT_KNOWN.)")
    pdctx = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{appctx},'design')")
    pd = w.add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdctx})")
    pds = w.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{absr})")
    cat = w.add("PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#%d))" % prod)
    _ = cat

    stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    header = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('Bike Box frame tubes -- faceted B-rep solids, un-mitred'),'2;1');",
        f"FILE_NAME('frame.step','{stamp}',('Bike Box'),(''),"
        f"'Bike Box {__version__}','Bike Box','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));",
        "ENDSEC;",
        "DATA;",
    ]
    footer = ["ENDSEC;", "END-ISO-10303-21;"]
    return "\n".join(header + w.lines + footer) + "\n"


def save_step(g: Geometry, path, segments: int = 48) -> Path:
    path = Path(path)
    path.write_text(build_step(g, segments), encoding="ascii")
    return path


# -- independent re-parser, used to validate output -----------------------------
_ENT = re.compile(r"#(\d+)\s*=\s*([A-Z_0-9]+|\()\s*(.*?)\s*;", re.S)
_REFS = re.compile(r"#(\d+)")


def parse_step_solids(text: str) -> list[Solid]:
    """Reconstruct the solids from STEP text by walking the entity graph --
    deliberately independent of the writer, so a round-trip proves validity."""
    kind: dict[int, str] = {}
    body: dict[int, str] = {}
    for m in _ENT.finditer(text.split("DATA;", 1)[-1]):
        eid = int(m.group(1))
        head = m.group(2)
        kind[eid] = "COMPLEX" if head == "(" else head
        body[eid] = m.group(3)

    def refs(eid: int) -> list[int]:
        return [int(x) for x in _REFS.findall(body[eid])]

    points: dict[int, tuple[float, float, float]] = {}
    for eid, k in kind.items():
        if k == "CARTESIAN_POINT":
            nums = re.findall(r"[-+]?\d*\.?\d+(?:E[-+]?\d+)?", body[eid].split("(", 1)[1])
            points[eid] = (float(nums[0]), float(nums[1]), float(nums[2]))
    vertex_pt = {eid: refs(eid)[0] for eid, k in kind.items() if k == "VERTEX_POINT"}
    edge_curve = {}
    for eid, k in kind.items():
        if k == "EDGE_CURVE":
            r = refs(eid)                       # v_start, v_end, line
            edge_curve[eid] = (r[0], r[1])
    oriented = {}
    for eid, k in kind.items():
        if k == "ORIENTED_EDGE":
            ec = refs(eid)[-1]
            sense = body[eid].rstrip().endswith(".T.)")
            oriented[eid] = (ec, sense)

    solids: list[Solid] = []
    for eid, k in kind.items():
        if k != "MANIFOLD_SOLID_BREP":
            continue
        shell = refs(eid)[0]
        pt_index: dict[int, int] = {}          # cartesian_point id -> local index
        verts: list[tuple[float, float, float]] = []

        def local(cp_id: int) -> int:
            if cp_id not in pt_index:
                pt_index[cp_id] = len(verts)
                verts.append(points[cp_id])
            return pt_index[cp_id]

        faces: list[tuple[int, ...]] = []
        for face in refs(shell):
            if kind.get(face) != "ADVANCED_FACE":
                continue
            bound = next(r for r in refs(face) if kind.get(r) in ("FACE_OUTER_BOUND", "FACE_BOUND"))
            loop = next(r for r in refs(bound) if kind.get(r) == "EDGE_LOOP")
            loop_verts: list[int] = []
            for oe in refs(loop):
                ec, sense = oriented[oe]
                vs, ve = edge_curve[ec]
                a = vertex_pt[vs]
                b = vertex_pt[ve]
                start = a if sense else b
                loop_verts.append(local(start))
            faces.append(tuple(loop_verts))
        solids.append(Solid(body[eid].split("'", 2)[1] if "'" in body[eid] else "", verts, faces))
    return solids
