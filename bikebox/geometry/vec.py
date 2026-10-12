"""Small, fast 2-D / 3-D vector types and planar helpers."""
from __future__ import annotations

import math
from typing import Iterable, Sequence


class V:
    """Immutable 2-D vector."""
    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0):
        self.x = float(x)
        self.y = float(y)

    @staticmethod
    def polar(r: float, deg: float) -> "V":
        a = math.radians(deg)
        return V(r * math.cos(a), r * math.sin(a))

    @staticmethod
    def dir(deg: float) -> "V":
        a = math.radians(deg)
        return V(math.cos(a), math.sin(a))

    def __add__(self, o: "V") -> "V":
        return V(self.x + o.x, self.y + o.y)

    def __sub__(self, o: "V") -> "V":
        return V(self.x - o.x, self.y - o.y)

    def __mul__(self, k: float) -> "V":
        return V(self.x * k, self.y * k)

    __rmul__ = __mul__

    def __truediv__(self, k: float) -> "V":
        return V(self.x / k, self.y / k)

    def __neg__(self) -> "V":
        return V(-self.x, -self.y)

    def __iter__(self):
        yield self.x
        yield self.y

    def __getitem__(self, i: int) -> float:
        return (self.x, self.y)[i]

    def __eq__(self, o: object) -> bool:
        return isinstance(o, V) and abs(self.x - o.x) < 1e-9 and abs(self.y - o.y) < 1e-9

    def __hash__(self) -> int:
        return hash((round(self.x, 6), round(self.y, 6)))

    def __repr__(self) -> str:
        return f"V({self.x:.3f}, {self.y:.3f})"

    def dot(self, o: "V") -> float:
        return self.x * o.x + self.y * o.y

    def cross(self, o: "V") -> float:
        return self.x * o.y - self.y * o.x

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def norm(self) -> "V":
        n = math.hypot(self.x, self.y)
        return V(self.x / n, self.y / n) if n > 1e-12 else V(0.0, 0.0)

    def perp(self) -> "V":
        """Rotate +90 degrees (counter-clockwise)."""
        return V(-self.y, self.x)

    def rot(self, deg: float) -> "V":
        a = math.radians(deg)
        c, s = math.cos(a), math.sin(a)
        return V(self.x * c - self.y * s, self.x * s + self.y * c)

    def angle(self) -> float:
        """Angle from +X in degrees."""
        return math.degrees(math.atan2(self.y, self.x))

    def dist(self, o: "V") -> float:
        return math.hypot(self.x - o.x, self.y - o.y)

    def lerp(self, o: "V", t: float) -> "V":
        return V(self.x + (o.x - self.x) * t, self.y + (o.y - self.y) * t)

    def tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


class V3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    @staticmethod
    def of(v: V, z: float = 0.0) -> "V3":
        return V3(v.x, v.y, z)

    def __add__(self, o): return V3(self.x + o.x, self.y + o.y, self.z + o.z)
    def __sub__(self, o): return V3(self.x - o.x, self.y - o.y, self.z - o.z)
    def __mul__(self, k): return V3(self.x * k, self.y * k, self.z * k)
    __rmul__ = __mul__
    def __truediv__(self, k): return V3(self.x / k, self.y / k, self.z / k)
    def __neg__(self): return V3(-self.x, -self.y, -self.z)
    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z
    def __repr__(self): return f"V3({self.x:.3f}, {self.y:.3f}, {self.z:.3f})"

    def dot(self, o): return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o):
        return V3(self.y * o.z - self.z * o.y, self.z * o.x - self.x * o.z, self.x * o.y - self.y * o.x)

    def length(self): return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def norm(self):
        n = self.length()
        return self / n if n > 1e-12 else V3()

    def xy(self) -> V: return V(self.x, self.y)
    def tuple(self): return (self.x, self.y, self.z)


# --------------------------------------------------------------------------
# planar helpers
# --------------------------------------------------------------------------
def line_intersect(p: V, d: V, q: V, e: V) -> V | None:
    """Intersection of lines p + t d and q + s e (None if parallel)."""
    den = d.cross(e)
    if abs(den) < 1e-12:
        return None
    t = (q - p).cross(e) / den
    return p + d * t


def line_param(p: V, d: V, q: V, e: V) -> tuple[float, float] | None:
    den = d.cross(e)
    if abs(den) < 1e-12:
        return None
    w = q - p
    return w.cross(e) / den, w.cross(d) / den


def point_line_distance(pt: V, p: V, d: V) -> float:
    """Signed distance from ``pt`` to the line through ``p`` with direction ``d``
    (positive on the left of ``d``)."""
    dn = d.norm()
    return dn.cross(pt - p)


def project_on_line(pt: V, p: V, d: V) -> float:
    dn = d.norm()
    return (pt - p).dot(dn)


def point_segment_distance(pt: V, a: V, b: V) -> float:
    ab = b - a
    L2 = ab.dot(ab)
    if L2 < 1e-12:
        return pt.dist(a)
    t = max(0.0, min(1.0, (pt - a).dot(ab) / L2))
    return pt.dist(a + ab * t)


def circle_line_intersections(c: V, r: float, p: V, d: V) -> list[float]:
    """Parameters t where p + t d meets the circle (d need not be unit)."""
    f = p - c
    a = d.dot(d)
    b = 2 * f.dot(d)
    cc = f.dot(f) - r * r
    disc = b * b - 4 * a * cc
    if disc < 0 or a < 1e-15:
        return []
    s = math.sqrt(disc)
    return sorted([(-b - s) / (2 * a), (-b + s) / (2 * a)])


def circle_circle_intersections(c0: V, r0: float, c1: V, r1: float) -> list[V]:
    d = c0.dist(c1)
    if d < 1e-12 or d > r0 + r1 or d < abs(r0 - r1):
        return []
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h2 = r0 * r0 - a * a
    h = math.sqrt(max(h2, 0.0))
    u = (c1 - c0) / d
    m = c0 + u * a
    return [m + u.perp() * h, m - u.perp() * h]


def arc_through(a: V, b: V, sagitta: float, segments: int = 24) -> list[V]:
    """Polyline approximating a circular arc from ``a`` to ``b`` whose midpoint
    is displaced ``sagitta`` to the left of the chord a->b."""
    if abs(sagitta) < 1e-6 or segments < 2:
        return [a, b]
    chord = b - a
    L = chord.length()
    if L < 1e-9:
        return [a, b]
    h = sagitta
    R = (L * L / 4 + h * h) / (2 * h)       # signed radius
    mid = a.lerp(b, 0.5)
    n = chord.perp().norm()
    centre = mid + n * (h - R)
    apex = mid + n * h
    a0 = math.atan2(a.y - centre.y, a.x - centre.x)
    am = math.atan2(apex.y - centre.y, apex.x - centre.x)
    half = (am - a0 + math.pi) % (2 * math.pi) - math.pi   # apex is half way round
    sweep = 2 * half
    r = abs(R)
    return [V(centre.x + r * math.cos(a0 + sweep * i / segments),
              centre.y + r * math.sin(a0 + sweep * i / segments)) for i in range(segments + 1)]


def polyline_length(pts: Sequence[V]) -> float:
    return sum(pts[i].dist(pts[i + 1]) for i in range(len(pts) - 1))


def polyline_point_at(pts: Sequence[V], s: float) -> tuple[V, V]:
    """Point and unit tangent at arc length ``s`` along a polyline (clamped)."""
    if s <= 0:
        return pts[0], (pts[1] - pts[0]).norm()
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = pts[i].dist(pts[i + 1])
        if acc + seg >= s and seg > 1e-12:
            t = (s - acc) / seg
            return pts[i].lerp(pts[i + 1], t), (pts[i + 1] - pts[i]).norm()
        acc += seg
    return pts[-1], (pts[-1] - pts[-2]).norm()


def offset_polyline(pts: Sequence[V], dist: float | Sequence[float]) -> list[V]:
    """Offset a polyline to the left by ``dist`` (scalar or one value per vertex)."""
    n = len(pts)
    if n < 2:
        return list(pts)
    ds = [dist] * n if isinstance(dist, (int, float)) else list(dist)
    out = []
    for i in range(n):
        if i == 0:
            t = (pts[1] - pts[0]).norm()
        elif i == n - 1:
            t = (pts[-1] - pts[-2]).norm()
        else:
            t = ((pts[i] - pts[i - 1]).norm() + (pts[i + 1] - pts[i]).norm()).norm()
        out.append(pts[i] + t.perp() * ds[i])
    return out


def circle_points(c: V, r: float, n: int = 64, a0: float = 0.0, a1: float = 360.0) -> list[V]:
    step = (a1 - a0) / n
    return [c + V.polar(r, a0 + step * i) for i in range(n + 1)]


def bbox(points: Iterable[V]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for p in points:
        xs.append(p.x)
        ys.append(p.y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def angle_between(u: V, v: V) -> float:
    """Unsigned angle between two vectors in degrees."""
    c = max(-1.0, min(1.0, u.norm().dot(v.norm())))
    return math.degrees(math.acos(c))


def sind(a): return math.sin(math.radians(a))
def cosd(a): return math.cos(math.radians(a))
def tand(a): return math.tan(math.radians(a))
