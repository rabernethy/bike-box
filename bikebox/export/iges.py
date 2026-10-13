"""IGES 5.3 export of the frame tubes as B-rep solids.

The same tessellated tube solids as the STEP export, written as an IGES Manifold
Solid B-Rep Object (entity type 186) built from a vertex list (502), edge list
(504), loops (508), faces (510, each on an unbounded plane 108) and a shell
(514).  Tubes are the outer envelope and **un-mitred**.

No kernel is used; the writer is validated by re-parsing its own output
(:func:`parse_iges_solids`) and confirming the solids come back as closed,
orientable manifolds matching the source mesh.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from .. import __version__
from ..geometry.solver import Geometry
from . import mesh
from .mesh import Solid

_D = ","        # parameter delimiter
_T = ";"        # record delimiter


class _IgesBuilder:
    """Accumulates entities and renders the Directory Entry and Parameter Data
    sections with correct cross-pointers and sequence numbers."""

    def __init__(self):
        self._pd_params: list[list[str]] = []     # per entity: parameter fields (incl. type no.)
        self._types: list[int] = []
        self._forms: list[int] = []
        self._labels: list[str] = []

    def add(self, type_no: int, params: list[str], form: int = 0, label: str = "") -> int:
        """Add an entity; returns its 1-based DE sequence number (odd: 1,3,5…)."""
        self._pd_params.append([str(type_no)] + params)
        self._types.append(type_no)
        self._forms.append(form)
        self._labels.append(label)
        return len(self._types) * 2 - 1           # DE pointers are the odd line numbers

    def render(self) -> str:
        # -- Parameter Data section: build lines, track first-line seq per entity
        pd_lines: list[str] = []
        pd_first: list[int] = []
        for idx, params in enumerate(self._pd_params):
            de_ptr = idx * 2 + 1
            text = _D.join(params) + _T
            pd_first.append(len(pd_lines) + 1)
            # wrap data to <=64 cols, each line carries the DE back-pointer + P seq
            chunk = ""
            pieces = text.split(_D)
            parts: list[str] = []
            for i, p in enumerate(pieces):
                seg = p + (_D if i < len(pieces) - 1 else "")
                if len(chunk) + len(seg) > 64:
                    parts.append(chunk)
                    chunk = seg
                else:
                    chunk += seg
            if chunk:
                parts.append(chunk)
            for part in parts:
                seq = len(pd_lines) + 1
                pd_lines.append(f"{part:<64} {de_ptr:>7}P{seq:>7}")
        # -- Directory Entry section (2 lines per entity)
        de_lines: list[str] = []
        for idx in range(len(self._types)):
            t = self._types[idx]
            pdp = pd_first[idx]
            pcount = self._pd_lines_for(idx, pd_first, len(pd_lines))
            dseq1 = idx * 2 + 1
            dseq2 = idx * 2 + 2
            label = (self._labels[idx] or "")[:8]
            line1 = f"{t:>8}{pdp:>8}{0:>8}{0:>8}{0:>8}{0:>8}{0:>8}{0:>8}{0:>8}D{dseq1:>7}"
            line2 = (f"{t:>8}{0:>8}{0:>8}{pcount:>8}{self._forms[idx]:>8}"
                     f"{'':>8}{'':>8}{label:>8}{0:>8}D{dseq2:>7}")
            de_lines.append(line1)
            de_lines.append(line2)
        return de_lines, pd_lines

    def _pd_lines_for(self, idx: int, pd_first: list[int], total: int) -> int:
        start = pd_first[idx]
        end = pd_first[idx + 1] - 1 if idx + 1 < len(pd_first) else total
        return end - start + 1


def _flt(x: float) -> str:
    return f"{float(x):.6f}"


def build_iges(g: Geometry, segments: int = 48) -> str:
    solids = mesh.frame_solids(g, segments)
    b = _IgesBuilder()

    for s in solids:
        verts = s.verts
        # 502 VERTEX LIST: N then x,y,z triples
        vparams = [str(len(verts))]
        for (x, y, z) in verts:
            vparams += [_flt(x), _flt(y), _flt(z)]
        vlist = b.add(502, vparams, form=1, label="VERTS")

        # one undirected edge per face-pair; direction low->high index
        edge_keys: list[tuple[int, int]] = []
        edge_index: dict[tuple[int, int], int] = {}
        for f in s.faces:
            k = len(f)
            for i in range(k):
                u, v = f[i], f[(i + 1) % k]
                key = (u, v) if u < v else (v, u)
                if key not in edge_index:
                    edge_index[key] = len(edge_keys) + 1     # 1-based list index
                    edge_keys.append(key)

        # 110 LINE per edge (model-space curve)
        line_de: dict[tuple[int, int], int] = {}
        for (a, c) in edge_keys:
            pa, pc = verts[a], verts[c]
            line_de[(a, c)] = b.add(110, [_flt(pa[0]), _flt(pa[1]), _flt(pa[2]),
                                          _flt(pc[0]), _flt(pc[1]), _flt(pc[2])])

        # 504 EDGE LIST: N then per edge (curve_ptr, svtx_ptr, svtx_idx, evtx_ptr, evtx_idx)
        eparams = [str(len(edge_keys))]
        for (a, c) in edge_keys:
            eparams += [str(line_de[(a, c)]), str(vlist), str(a + 1), str(vlist), str(c + 1)]
        elist = b.add(504, eparams, form=1, label="EDGES")

        # 108 PLANE (unbounded) per face + 508 LOOP + 510 FACE
        face_de: list[int] = []
        for f in s.faces:
            nrm = _normal(verts, f)
            p0 = verts[f[0]]
            d = -(nrm[0] * p0[0] + nrm[1] * p0[1] + nrm[2] * p0[2])
            plane = b.add(108, [_flt(nrm[0]), _flt(nrm[1]), _flt(nrm[2]), _flt(d),
                                "0", "0.", "0.", "0.", "0."])     # no bounding curve
            # 508 LOOP: N then per edge (type=1 edge, edge_list_ptr, idx, orient, k=0)
            k = len(f)
            lp = [str(k)]
            for i in range(k):
                u, v = f[i], f[(i + 1) % k]
                key = (u, v) if u < v else (v, u)
                orient = 1 if u < v else 0
                lp += ["1", str(elist), str(edge_index[key]), str(orient), "0"]
            loop = b.add(508, lp, form=1, label="LOOP")
            # 510 FACE: surface_ptr, n_loops, outer_flag, loop_ptr...
            face_de.append(b.add(510, [str(plane), "1", "1", str(loop)], form=1, label="FACE"))

        # 514 SHELL: N then per face (face_ptr, orient)
        shparams = [str(len(face_de))]
        for fd in face_de:
            shparams += [str(fd), "1"]
        shell = b.add(514, shparams, form=1, label="SHELL")
        # 186 MSBO: shell_ptr, orient, n_void(0)
        name = (s.name.replace(",", " ")[:8]) or "SOLID"
        b.add(186, [str(shell), "1", "0"], form=0, label=name)

    de_lines, pd_lines = b.render()

    stamp = _dt.datetime.now().strftime("%Y%m%d.%H%M%S")
    # -- Start section
    start = [f"Bike Box {__version__} -- frame tubes as B-rep solids (un-mitred)."]
    start_lines = [f"{s:<72}S{i + 1:>7}" for i, s in enumerate(start)]
    # -- Global section (comma/semicolon delimited); units flag 2 = millimetres
    g_fields = [
        "1H,", "1H;", _h("BikeBox"), _h("frame.iges"), _h(f"Bike Box {__version__}"),
        _h("IGES 5.3"), "32", "38", "6", "308", "15", _h("frame"), "1.0",
        "2", "2HMM", "1", "0.001", _h(stamp), "1.0E-07", "1000.0",
        _h("Bike Box"), _h("Bike Box"), "11", "0", _h(stamp),
    ]
    gtext = _D.join(g_fields[:-1]) + _D + g_fields[-1] + _T
    global_lines = _wrap_section(gtext, "G")
    # -- Terminate section
    term = (f"S{len(start_lines):>7}G{len(global_lines):>7}"
            f"D{len(de_lines):>7}P{len(pd_lines):>7}")
    term_line = f"{term:<72}T{1:>7}"
    return "\n".join(start_lines + global_lines + de_lines + pd_lines + [term_line]) + "\n"


def _h(text: str) -> str:
    """IGES Hollerith string: nHtext."""
    return f"{len(text)}H{text}"


def _wrap_section(text: str, code: str) -> list[str]:
    pieces = text.split(_D)
    lines: list[str] = []
    chunk = ""
    for i, p in enumerate(pieces):
        seg = p + (_D if i < len(pieces) - 1 else "")
        if len(chunk) + len(seg) > 72:
            lines.append(chunk)
            chunk = seg
        else:
            chunk += seg
    if chunk:
        lines.append(chunk)
    return [f"{ln:<72}{code}{i + 1:>7}" for i, ln in enumerate(lines)]


def _normal(verts: list, loop: tuple[int, ...]) -> tuple[float, float, float]:
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        a = verts[loop[i]]
        c = verts[loop[(i + 1) % n]]
        nx += (a[1] - c[1]) * (a[2] + c[2])
        ny += (a[2] - c[2]) * (a[0] + c[0])
        nz += (a[0] - c[0]) * (a[1] + c[1])
    m = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return (nx / m, ny / m, nz / m)


def save_iges(g: Geometry, path, segments: int = 48) -> Path:
    path = Path(path)
    path.write_text(build_iges(g, segments), encoding="ascii")
    return path


# -- independent re-parser, used to validate output -----------------------------
def parse_iges_solids(text: str) -> list[Solid]:
    lines = text.splitlines()
    de = [ln for ln in lines if len(ln) >= 73 and ln[72] == "D"]
    pd = [ln for ln in lines if len(ln) >= 73 and ln[72] == "P"]
    # entity by DE sequence number (odd line) -> (type, pd_first_seq)
    ent_type: dict[int, int] = {}
    ent_pd: dict[int, int] = {}
    for i in range(0, len(de), 2):
        d1 = de[i]
        seq = i + 1                                 # odd DE sequence
        ent_type[seq] = int(d1[0:8])
        ent_pd[seq] = int(d1[8:16])
    # group PD lines by owning DE pointer
    params_by_de: dict[int, list[str]] = {}
    for ln in pd:
        de_ptr = int(ln[65:72])
        data = ln[:64].rstrip()
        params_by_de.setdefault(de_ptr, []).append(data)

    def params(de_ptr: int) -> list[str]:
        joined = "".join(params_by_de.get(de_ptr, []))
        joined = joined.rstrip(";")
        return [p for p in joined.split(",")]

    solids: list[Solid] = []
    for seq, t in ent_type.items():
        if t != 186:
            continue
        msbo = params(seq)
        shell_ptr = int(msbo[1])
        sh = params(shell_ptr)
        nfaces = int(sh[1])
        face_ptrs = [int(sh[2 + 2 * j]) for j in range(nfaces)]
        verts: list[tuple[float, float, float]] = []
        faces: list[tuple[int, ...]] = []
        vcache: dict[int, int] = {}

        def local(vlist_ptr: int, idx1: int) -> int:
            vp = params(vlist_ptr)
            # 502: type,N, then x,y,z triples (idx1 is 1-based)
            base = 2 + (idx1 - 1) * 3
            x, y, z = float(vp[base]), float(vp[base + 1]), float(vp[base + 2])
            key = (vlist_ptr, idx1)
            if key not in vcache:
                vcache[key] = len(verts)
                verts.append((x, y, z))
            return vcache[key]

        for fptr in face_ptrs:
            fp = params(fptr)                       # type, surf, n_loops, outer, loop...
            n_loops = int(fp[2])
            loop_ptr = int(fp[4])                   # first loop
            lp = params(loop_ptr)                   # type, N, then per edge 5 fields
            nedges = int(lp[1])
            loop_verts: list[int] = []
            for j in range(nedges):
                o = 2 + 5 * j
                elist_ptr = int(lp[o + 1])
                eidx = int(lp[o + 2])
                orient = int(lp[o + 3])
                ep = params(elist_ptr)              # 504: type,N, then per edge 5 fields
                eo = 2 + 5 * (eidx - 1)
                svtx, sidx = int(ep[eo + 1]), int(ep[eo + 2])
                evtx, eidx2 = int(ep[eo + 3]), int(ep[eo + 4])
                if orient:
                    loop_verts.append(local(svtx, sidx))
                else:
                    loop_verts.append(local(evtx, eidx2))
            faces.append(tuple(loop_verts))
        solids.append(Solid("", verts, faces))
    return solids
