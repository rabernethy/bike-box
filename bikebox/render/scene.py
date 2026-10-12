"""Backend-neutral scene graph.

Builders (``bike_scene``, ``components``, ``rider`` ...) append primitives in
model coordinates (mm, +Y up).  Renderers (Qt painter, SVG, DXF, PDF) draw the
same scene, which keeps every output consistent.

Line widths and *annotative* text sizes are in paper millimetres: they stay
constant on paper / screen regardless of the drawing scale.  Non-annotative
text (decals) is sized in model millimetres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..geometry.vec import V, bbox

# draw order: lower z first
Z_PHOTO, Z_GRID, Z_GHOST, Z_GROUND, Z_WHEEL, Z_BACK, Z_STAY, Z_FRAME, Z_FRONT, Z_COMPONENT, \
    Z_RIDER, Z_OVER, Z_CENTERLINE, Z_DIM, Z_NOTE = range(0, 150, 10)


@dataclass(frozen=True)
class Gradient:
    """Linear gradient between two model points."""
    p0: tuple[float, float]
    p1: tuple[float, float]
    stops: tuple[tuple[float, str], ...]


@dataclass
class Style:
    stroke: str | None = "#000000"
    width: float = 0.35                 # paper mm
    fill: str | Gradient | None = None
    dash: tuple[float, ...] | None = None   # paper mm
    opacity: float = 1.0
    cap: str = "round"                   # round | flat | square
    join: str = "round"

    def with_(self, **kw) -> "Style":
        d = self.__dict__.copy()
        d.update(kw)
        return Style(**d)


@dataclass
class Prim:
    layer: str
    z: int
    style: Style
    tag: str = ""          # identifies the part (for hit-testing / selection)


@dataclass
class Polyline(Prim):
    pts: list[V] = field(default_factory=list)
    closed: bool = False
    holes: list[list[V]] = field(default_factory=list)


@dataclass
class Circle(Prim):
    c: V = field(default_factory=V)
    r: float = 1.0


@dataclass
class Arc(Prim):
    c: V = field(default_factory=V)
    r: float = 1.0
    start: float = 0.0    # degrees, CCW from +X
    span: float = 90.0


@dataclass
class Text(Prim):
    pos: V = field(default_factory=V)
    text: str = ""
    size: float = 3.0           # paper mm if annotative else model mm
    angle: float = 0.0          # degrees CCW
    anchor: str = "cm"          # [l|c|r][b|m|t]
    annotative: bool = True
    font: str = "Sans Serif"
    bold: bool = False
    italic: bool = False
    box: bool = False           # draw a background box (for dimension text)


@dataclass
class Image(Prim):
    path: str = ""
    origin: V = field(default_factory=V)     # model position of the image's top-left pixel
    mm_per_px: float = 1.0
    rotation: float = 0.0
    flip: bool = False


@dataclass
class LinearDim(Prim):
    """Linear dimension between p1 and p2.

    ``mode``: aligned | horizontal | vertical.  ``offset`` is the distance of
    the dimension line from the measured points (model mm; sign chooses side:
    positive = left of p1->p2 for aligned, above for horizontal, right for
    vertical).
    """
    p1: V = field(default_factory=V)
    p2: V = field(default_factory=V)
    offset: float = 40.0
    mode: str = "aligned"
    text: str = ""
    dim_id: str = ""
    text_size: float = 2.6
    text_horizontal: bool = False


@dataclass
class AngleDim(Prim):
    """Angle at ``vertex`` from direction a (degrees) sweeping CCW by span."""
    vertex: V = field(default_factory=V)
    start: float = 0.0
    span: float = 30.0
    radius: float = 60.0
    text: str = ""
    dim_id: str = ""
    text_size: float = 2.6
    text_horizontal: bool = True


class Scene:
    def __init__(self):
        self.prims: list[Prim] = []
        self.hidden_layers: set[str] = set()
        self.background = "#ffffff"

    def add(self, prim: Prim) -> Prim:
        self.prims.append(prim)
        return prim

    def extend(self, prims: Iterable[Prim]) -> None:
        self.prims.extend(prims)

    # convenience constructors ------------------------------------------------
    def line(self, a: V, b: V, style: Style, layer="frame", z=Z_FRAME, tag="") -> Polyline:
        return self.add(Polyline(layer, z, style, tag, [a, b]))

    def poly(self, pts: Sequence[V], style: Style, layer="frame", z=Z_FRAME, closed=False, tag="",
             holes=None) -> Polyline:
        return self.add(Polyline(layer, z, style, tag, list(pts), closed, holes or []))

    def circle(self, c: V, r: float, style: Style, layer="frame", z=Z_FRAME, tag="") -> Circle:
        return self.add(Circle(layer, z, style, tag, c, r))

    def arc(self, c: V, r: float, start: float, span: float, style: Style, layer="frame", z=Z_FRAME, tag="") -> Arc:
        return self.add(Arc(layer, z, style, tag, c, r, start, span))

    def text(self, pos: V, text: str, style: Style, size=3.0, angle=0.0, anchor="cm", layer="notes",
             z=Z_NOTE, annotative=True, **kw) -> Text:
        return self.add(Text(layer, z, style, kw.pop("tag", ""), pos, text, size, angle, anchor, annotative, **kw))

    # queries ---------------------------------------------------------------
    def visible(self) -> list[Prim]:
        prims = [p for p in self.prims if p.layer not in self.hidden_layers]
        prims.sort(key=lambda p: p.z)          # stable: insertion order within a z level
        return prims

    def bounds(self, layers: set[str] | None = None, include_dims: bool = True) -> tuple[float, float, float, float]:
        pts: list[V] = []
        for p in self.prims:
            if p.layer in self.hidden_layers or (layers is not None and p.layer not in layers):
                continue
            if isinstance(p, Polyline):
                pts.extend(p.pts)
            elif isinstance(p, (Circle, Arc)):
                pts.extend([p.c + V(p.r, p.r), p.c - V(p.r, p.r)])
            elif isinstance(p, Text) and not p.annotative:
                pts.append(p.pos)
            elif include_dims and isinstance(p, LinearDim):
                pts.extend(_dim_line(p)[0:2])
            elif include_dims and isinstance(p, AngleDim):
                pts.append(p.vertex + V.polar(p.radius, p.start + p.span / 2))
        return bbox(pts)


# --------------------------------------------------------------------------
# dimension geometry ("explode" into basic primitives)
# --------------------------------------------------------------------------
def _dim_line(dim: LinearDim) -> tuple[V, V, V, V, V]:
    """Return (d1, d2, e1_dir, normal, along) for a linear dimension."""
    p1, p2 = dim.p1, dim.p2
    if dim.mode == "horizontal":
        along = V(1, 0) if p2.x >= p1.x else V(-1, 0)
        nrm = V(0, 1)
        base = max(p1.y, p2.y) if dim.offset >= 0 else min(p1.y, p2.y)
        y = base + dim.offset
        d1, d2 = V(p1.x, y), V(p2.x, y)
    elif dim.mode == "vertical":
        along = V(0, 1) if p2.y >= p1.y else V(0, -1)
        nrm = V(1, 0)
        base = max(p1.x, p2.x) if dim.offset >= 0 else min(p1.x, p2.x)
        x = base + dim.offset
        d1, d2 = V(x, p1.y), V(x, p2.y)
    else:
        along = (p2 - p1).norm()
        nrm = along.perp()
        d1, d2 = p1 + nrm * dim.offset, p2 + nrm * dim.offset
    return d1, d2, along, nrm, along


def explode_dimension(dim: Prim, annot: float, font: str = "Sans Serif") -> list[Prim]:
    """Turn a dimension into lines/polygons/text.

    ``annot`` is model-mm per paper-mm (so arrows and text keep a constant
    printed size)."""
    st = dim.style
    out: list[Prim] = []
    text_size = getattr(dim, "text_size", 2.6)
    arrow_len, arrow_w = 2.8 * annot * text_size / 2.6, 0.9 * annot * text_size / 2.6
    horizontal = getattr(dim, "text_horizontal", False)
    gap, over = 1.0 * annot, 1.5 * annot
    fill = st.with_(fill=st.stroke, width=0.0)

    def arrow(tip: V, direction: V):
        dn = direction.norm()
        base = tip - dn * arrow_len
        out.append(Polyline(dim.layer, dim.z, fill, dim.tag,
                            [tip, base + dn.perp() * arrow_w, base - dn.perp() * arrow_w], True))

    if isinstance(dim, LinearDim):
        d1, d2, along, nrm, _ = _dim_line(dim)
        side = 1.0 if dim.offset >= 0 else -1.0
        # extension lines
        for p, d in ((dim.p1, d1), (dim.p2, d2)):
            ev = d - p
            L = ev.length()
            if L > gap:
                en = ev / L
                out.append(Polyline(dim.layer, dim.z, st, dim.tag, [p + en * gap, d + en * over]))
        out.append(Polyline(dim.layer, dim.z, st, dim.tag, [d1, d2]))
        span = d1.dist(d2)
        if span > 2.2 * arrow_len:
            arrow(d1, d1 - d2)
            arrow(d2, d2 - d1)
        else:                       # arrows outside for short dimensions
            dd = (d2 - d1).norm() if span > 1e-9 else along
            arrow(d1, dd)
            arrow(d2, dd * -1)
            out.append(Polyline(dim.layer, dim.z, st, dim.tag, [d1 - dd * arrow_len * 2, d1]))
            out.append(Polyline(dim.layer, dim.z, st, dim.tag, [d2, d2 + dd * arrow_len * 2]))
        mid = d1.lerp(d2, 0.5)
        ang = (d2 - d1).angle() if span > 1e-9 else along.angle()
        if ang > 90.0001 or ang <= -90:
            ang += 180
        if ang > 180:
            ang -= 360
        tdir = V.dir(ang)
        if horizontal:
            tpos = mid
            out.append(Text(dim.layer, dim.z + 1, st, dim.tag, tpos, dim.text, text_size, 0.0, "cm", True,
                            font, box=True))
        else:
            tpos = mid + tdir.perp() * (text_size * 0.5 + 0.8) * annot
            out.append(Text(dim.layer, dim.z + 1, st, dim.tag, tpos, dim.text, text_size, ang, "cb", True,
                            font, box=False))
    elif isinstance(dim, AngleDim):
        c, r = dim.vertex, dim.radius
        out.append(Arc(dim.layer, dim.z, st, dim.tag, c, r, dim.start, dim.span))
        a0 = c + V.polar(r, dim.start)
        a1 = c + V.polar(r, dim.start + dim.span)
        if abs(dim.span) * math.pi / 180 * r > 2.4 * arrow_len:
            sgn = 1 if dim.span >= 0 else -1
            arrow(a0, V.dir(dim.start - 90 * sgn))
            arrow(a1, V.dir(dim.start + dim.span + 90 * sgn))
        # extension lines from vertex region to arc ends
        for a in (dim.start, dim.start + dim.span):
            out.append(Polyline(dim.layer, dim.z, st.with_(dash=(1.5, 1.0)), dim.tag,
                                [c + V.polar(r * 0.15, a), c + V.polar(r + over, a)]))
        mid_a = dim.start + dim.span / 2
        tpos = c + V.polar(r + (text_size * 0.9) * annot, mid_a)
        out.append(Text(dim.layer, dim.z + 1, st, dim.tag, tpos, dim.text, text_size, 0.0, "cm", True, font))
    return out
