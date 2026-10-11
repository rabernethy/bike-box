"""Build a :class:`Scene` from a solved :class:`Geometry`.

Everything that appears on the side-view drawing is produced here: frame,
fork, wheels, drivetrain, cockpit, saddle, brakes, accessories, joints,
paint/decals, centre-lines, dimensions, notes and comparison ghosts.  Optional
modules (rider) hook in through ``EXTRA_BUILDERS``.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from ..geometry import dimensions as DIM
from ..geometry.solver import Geometry, Tube, Wheel
from ..geometry.vec import (V, circle_points, cosd, line_intersect, offset_polyline, polyline_length,
                            polyline_point_at, sind)
from ..model import params as P
from .scene import (Z_BACK, Z_CENTERLINE, Z_COMPONENT, Z_DIM, Z_FRAME, Z_FRONT, Z_GHOST, Z_GRID,
                    Z_GROUND, Z_NOTE, Z_OVER, Z_PHOTO, Z_RIDER, Z_STAY, Z_WHEEL, AngleDim, Gradient,
                    Image, LinearDim, Scene, Style)
from .theme import Theme

# Other modules can register functions ``f(scene, geometry, theme)`` that run
# after the bike is drawn (e.g. the rider).
EXTRA_BUILDERS: list[Callable[[Scene, Geometry, Theme], None]] = []
_PLUGINS_LOADED = False


def load_plugins() -> None:
    """Import optional modules that register scene builders (rider, centre of
    mass), so headless exports draw them too."""
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    import importlib
    for mod in ("framewright.fit",):
        try:
            importlib.import_module(mod)
        except ImportError:
            pass


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
def stroke_polygon(pts: Sequence[V], half: float | Sequence[float], caps: bool = False) -> list[V]:
    """Outline polygon of a thick polyline (half-width per vertex)."""
    left = offset_polyline(pts, half)
    hw = [half] * len(pts) if isinstance(half, (int, float)) else list(half)
    right = offset_polyline(pts, [-h for h in hw])
    out = list(left)
    if caps:
        d = (pts[-1] - pts[-2]).norm()
        out += [pts[-1] + d.rot(a) * hw[-1] for a in range(90, -91, -30)][1:-1]
    out += list(reversed(right))
    if caps:
        d = (pts[0] - pts[1]).norm()
        out += [pts[0] + d.rot(a) * hw[0] for a in range(90, -91, -30)][1:-1]
    return out


def rect_along(a: V, b: V, half: float) -> list[V]:
    d = (b - a).norm().perp() * half
    return [a + d, b + d, b - d, a - d]


def rounded_rect_along(a: V, b: V, half: float, r: float | None = None) -> list[V]:
    """Rectangle from a to b (width 2*half) with rounded ends."""
    r = half if r is None else min(r, half)
    d = (b - a).norm()
    n = d.perp()
    pts = []
    for c, a0 in ((b - d * r, -90), (a + d * r, 90)):
        for i in range(0, 181, 20):
            ang = math.radians(a0 + i) + math.atan2(d.y, d.x)
            pts.append(V(c.x + r * math.cos(ang), c.y + r * math.sin(ang)) + n * 0.0)
    # widen straight sides when half > r
    if half > r + 1e-6:
        return [a + n * half, b + n * half, b - n * half, a - n * half]
    return pts


def convex_hull(points: Iterable[V]) -> list[V]:
    pts = sorted(set((p.x, p.y) for p in points))
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


def external_tangents(c1: V, r1: float, c2: V, r2: float) -> list[tuple[V, V]]:
    d = c2 - c1
    L = d.length()
    if L <= abs(r1 - r2) + 1e-9:
        return []
    phi = math.atan2(d.y, d.x)
    beta = math.acos(max(-1.0, min(1.0, (r1 - r2) / L)))
    out = []
    for sgn in (1, -1):
        a = phi + sgn * beta
        u = V(math.cos(a), math.sin(a))
        out.append((c1 + u * r1, c2 + u * r2))
    return out


def pitch_radius(teeth: float, pitch: float = 12.7) -> float:
    return pitch / (2 * math.sin(math.pi / max(teeth, 3)))


def tube_outline(t: Tube, pts: Sequence[V] | None = None) -> list[V]:
    pts = list(pts if pts is not None else t.draw_points())
    L = polyline_length(t.points()) or 1.0
    # per-vertex half width following the taper
    acc = 0.0
    full = t.points()
    s0 = 0.0
    if t.draw_a is not None:
        from ..geometry.vec import project_on_line
        s0 = max(0.0, project_on_line(pts[0], t.a, t.b - t.a))
    halves = []
    for i, p in enumerate(pts):
        if i:
            acc += pts[i - 1].dist(p)
        halves.append(t.od_at(min(1.0, (s0 + acc) / L)) / 2)
    return stroke_polygon(pts, halves)


# --------------------------------------------------------------------------
# builder
# --------------------------------------------------------------------------
class BikeSceneBuilder:
    def __init__(self, g: Geometry, theme: Theme | None = None, scene: Scene | None = None):
        self.g = g
        self.d = g.design
        self.t = theme or Theme.from_design(g.design)
        self.sc = scene or Scene()
        self.sc.background = self.t.bg

    # entry point ---------------------------------------------------------------
    def build(self, dimensions: bool | None = None, ghosts: Sequence[tuple[Geometry, str]] = ()) -> Scene:
        d = self.d
        if d.get("show_rider") or d.get("show_com"):
            load_plugins()
        on = lambda k: bool(d.get(k, True))
        if on("show_grid"):
            self.grid()
        if on("show_photo"):
            self.photo()
        for gg, color in (ghosts if on("show_ghost") else ()):
            self.ghost(gg, color)
        if on("show_ground"):
            self.ground()
        if on("show_wheels"):
            self.wheels()
        if on("show_brakes"):
            self.brakes()
        if on("show_saddle"):
            self.saddle()
        if on("show_frame"):
            self.frame()
        if on("show_fork"):
            self.fork()
        if on("show_cockpit"):
            self.cockpit()
        if on("show_drivetrain"):
            self.drivetrain()
        if on("show_accessories"):
            self.accessories()
        if on("show_centerlines") or d["display_mode"] == "centerline":
            self.centerlines()
        if on("show_toe_circle"):
            self.toe_circle()
        for fn in EXTRA_BUILDERS:
            try:
                fn(self.sc, self.g, self.t)
            except Exception as exc:          # a broken plug-in must not kill drawing
                self.g.warn(f"{getattr(fn, '__name__', 'builder')} failed: {exc}")
        if dimensions if dimensions is not None else on("show_dimensions"):
            self.dimensions()
        if on("show_notes"):
            self.notes()
        return self.sc

    # background ------------------------------------------------------------------
    def grid(self, step: float = 50.0):
        x0, y0, x1, y1 = -900, self.g.ground_y - 100, 1600, 1300
        st = Style("#d8dde6", 0.12)
        x = math.floor(x0 / step) * step
        while x <= x1:
            self.sc.line(V(x, y0), V(x, y1), st if x % 250 else st.with_(stroke="#b8c0cc"), "grid", Z_GRID)
            x += step
        y = math.floor(y0 / step) * step
        while y <= y1:
            self.sc.line(V(x0, y), V(x1, y), st if y % 250 else st.with_(stroke="#b8c0cc"), "grid", Z_GRID)
            y += step

    def photo(self):
        ph = self.d.extras.get("photo")
        if not ph or not ph.get("path"):
            return
        self.sc.add(Image("photo", Z_PHOTO, Style(None, 0, None, opacity=float(ph.get("opacity", 0.5))), "photo",
                          str(ph["path"]), V(float(ph.get("x", -900)), float(ph.get("y", 900))),
                          float(ph.get("mm_per_px", 1.0)), float(ph.get("rotation", 0.0)), bool(ph.get("flip", False))))

    def ground(self):
        g = self.g
        x0 = g.p["rear_axle"].x - g.wheels["rear"].outer_r - 80
        x1 = g.p["front_axle"].x + g.wheels["front"].outer_r + 80
        self.sc.line(V(x0, g.ground_y), V(x1, g.ground_y), Style(self.t.outline, self.t.width * 0.8), "ground", Z_GROUND)
        st = Style(self.t.outline, self.t.width * 0.4)
        x = x0
        while x < x1:
            self.sc.line(V(x, g.ground_y), V(x - 12, g.ground_y - 12), st, "ground", Z_GROUND)
            x += 25

    # wheels ------------------------------------------------------------------------
    def wheels(self):
        for key in ("rear", "front"):
            self.wheel(self.g.wheels[key], key)

    def wheel(self, w: Wheel, key: str):
        sc, t, d = self.sc, self.t, self.d
        detail = int(d["wheel_detail"])
        c = w.center
        layer = "wheels"
        if detail <= 0:
            sc.circle(c, w.outer_r, t.thin(t.outline, 1.0), layer, Z_WHEEL, f"wheel:{key}")
            sc.circle(c, w.rim_r, t.thin(t.outline, 0.6), layer, Z_WHEEL, f"wheel:{key}")
            return
        tire_fill = t.tire if t.mode == "filled" else None
        ring = circle_points(c, w.outer_r, 96)
        hole = circle_points(c, w.rim_r, 96)
        sc.poly(ring, Style(t.outline, t.width, tire_fill), layer, Z_WHEEL, True, f"wheel:{key}", holes=[hole])
        # tread hint
        sc.circle(c, w.outer_r - 1.8, t.thin("#555555" if t.mode == "filled" else t.outline, 0.3), layer, Z_WHEEL)
        rim_fill = t.rim if t.mode == "filled" else None
        sc.poly(circle_points(c, w.rim_r, 96), Style(t.outline, t.width * 0.8, rim_fill), layer, Z_WHEEL, True,
                f"wheel:{key}", holes=[circle_points(c, w.rim_inner_r, 96)])
        if detail >= 2:
            fl = d.f("hub_flange_front" if key == "front" else "hub_flange_rear")
            sc.circle(c, fl / 2, t.comp("#b0b0b0"), layer, Z_WHEEL + 2, f"wheel:{key}")
            sc.circle(c, 9, t.comp("#d0d0d0"), layer, Z_WHEEL + 3)
            sc.circle(c, 4, t.comp("#707070"), layer, Z_WHEEL + 3)
        if detail >= 3:
            n = int(d["spokes_front" if key == "front" else "spokes_rear"])
            x = int(d["cross_front" if key == "front" else "cross_rear"])
            fl = d.f("hub_flange_front" if key == "front" else "hub_flange_rear")
            if n >= 4:
                alpha = x * 720.0 / n
                st = Style("#777777" if t.mode == "filled" else t.outline, 0.13)
                for flange in (0, 1):
                    for j in range(n // 2):
                        h = 720.0 * j / n + flange * 360.0 / n
                        sgn = 1 if (j % 2 == 0) else -1
                        r_ang = h + sgn * alpha
                        a = c + V.polar(fl / 2, h)
                        b = c + V.polar(w.rim_inner_r, r_ang)
                        sc.line(a, b, st, layer, Z_WHEEL + 1)

    # frame --------------------------------------------------------------------------
    def _paint(self, t: Tube, base: str | None) -> str | Gradient | None:
        if base is None or self.t.mode != "filled":
            return base
        if self.d["paint_per_tube"] and t.name in ("tt", "dt", "st", "cs", "ss", "ss_mono"):
            base = self.d["paint_ss" if t.name == "ss_mono" else f"paint_{t.name}"]
        fade = self.d["fade_style"]
        to = self.d["paint_fade_to"]
        pos = self.d.f("fade_position") / 100.0
        if fade == "none" or t.name not in ("dt", "tt", "st", "ht", "cs", "ss"):
            return base
        if fade == "dt" and t.name != "dt":
            return base
        if fade == "panel":
            if t.name not in ("dt", "st"):
                return base
            a, b = t.a, t.b
            stops = ((0.0, base), (max(pos - 0.2, 0.0), base), (max(pos - 0.2, 0.0) + 1e-3, to),
                     (min(pos + 0.2, 1.0), to), (min(pos + 0.2, 1.0) + 1e-3, base), (1.0, base))
            return Gradient(a.tuple(), b.tuple(), stops)
        return Gradient(t.a.tuple(), t.b.tuple(), ((0.0, base), (max(pos - 0.15, 0), base),
                                                    (min(pos + 0.15, 1), to), (1.0, to)))

    def frame(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        tubes = g.tubes
        mode = t.mode
        if mode == "centerline":
            st = Style(t.outline, 1.2, None)
            for name, tb in tubes.items():
                if tb.kind == "fork":
                    continue
                sc.poly(tb.points(), st, "frame", Z_FRAME, tag=f"tube:{name}")
            sc.circle(V(0, 0), d.f("bb_shell_od") / 2, Style(t.outline, 1.2, None), "frame", Z_FRAME, "tube:bb")
            return
        base = t.frame_fill
        order = (["cs", "ss", "ss_mono", "lat"] + [n for n in tubes if n.startswith("x")]
                 + ["boom", "mid", "tt2", "dt", "tt", "st2", "st"])
        for name in order:
            tb = tubes.get(name)
            if tb is None:
                continue
            z = Z_STAY if tb.kind == "stay" else Z_FRAME
            sc.poly(tube_outline(tb), t.frame(self._paint(tb, base)), "frame", z, True, f"tube:{name}")
        self.dropout()
        # head tube on top of TT/DT
        ht = tubes["ht"]
        sc.poly(tube_outline(ht), t.frame(self._paint(ht, t.ht_fill or base)), "frame", Z_FRAME + 2, True, "tube:ht")
        # BB shell(s)
        shells = [V(0, 0)] + ([g.p["drive_bb"]] if g.p["drive_bb"].length() > 1e-6 else [])
        for c in shells:
            sc.circle(c, d.f("bb_shell_od") / 2, t.frame(base), "frame", Z_FRAME + 2, "tube:bb")
            sc.circle(c, d.f("bb_shell_od") / 2 - 4, t.thin(t.outline, 0.5), "frame", Z_FRAME + 2, "tube:bb")
        if d["bb_housing"] != "none":
            self.drive_unit()
        js = d["joint_style"]
        if js == "lugged":
            self.lugs()
        elif js == "fillet":
            self.fillets()
        self.decals()
        self.braze_ons()
        if d["couplers"]:
            for name in ("tt", "dt"):
                q = g.p.get(f"coupler_{name}")
                tb = tubes.get(name)
                if q is None or tb is None:
                    continue
                tan = tb.dir_a()
                L = d.f("coupler_length") / 2
                sc.poly(rect_along(q - tan * L, q + tan * L, tb.od_b / 2 + 2.2), t.comp("#c9c9c9"), "frame",
                        Z_FRAME + 6, True, f"coupler:{name}")
                sc.line(q - tan.perp() * (tb.od_b / 2 + 2.2), q + tan.perp() * (tb.od_b / 2 + 2.2),
                        t.thin(t.outline, 0.8), "frame", Z_FRAME + 6)

    def drive_unit(self):
        """Gearbox or mid-drive motor housing around the BB (+ battery)."""
        g, sc, t, d = self.g, self.sc, self.t, self.d
        c = g.p["drive_bb"] + V(d.f("housing_dx"), d.f("housing_dy"))
        L, H, rot = d.f("housing_length"), d.f("housing_height"), d.f("housing_rotation")
        r = min(L, H) * 0.28
        pts = []
        for cx, cy, a0 in ((L / 2 - r, H / 2 - r, 0), (-L / 2 + r, H / 2 - r, 90), (-L / 2 + r, -H / 2 + r, 180),
                           (L / 2 - r, -H / 2 + r, 270)):
            pts += [V(cx, cy) + V.polar(r, a0 + k * 15) for k in range(7)]
        pts = [c + q.rot(rot) for q in pts]
        fill = "#3a3a3a" if t.mode == "filled" else t.component_fill
        sc.poly(pts, t.frame(fill), "frame", Z_FRAME + 3, True, "housing")
        sc.circle(g.p["drive_bb"], 22, t.comp("#555555"), "frame", Z_FRAME + 4, "housing")
        g.p["housing_center"] = c
        bat = d["battery"]
        dt = g.tubes.get("dt")
        if bat in ("downtube", "integrated") and dt is not None:
            p0, tan = dt.point_at(d.f("battery_pos"))
            p1, _ = dt.point_at(min(dt.length, d.f("battery_pos") + d.f("battery_length")))
            th = d.f("battery_thickness")
            off = tan.perp() * ((dt.od_b / 2 + th / 2 + 2) if bat == "downtube" else 0.0)
            body = rounded_rect_along(p0 + off, p1 + off, th / 2 if bat == "downtube" else dt.od_b * 0.42, th * 0.2)
            sc.poly(body, t.frame("#262626" if t.mode == "filled" else None), "frame", Z_FRAME + 4, True, "battery")
        elif bat == "rack":
            ax = g.p["rear_axle"]
            top = ax.y + d.f("rack_height")
            th = d.f("battery_thickness") * 0.6
            sc.poly(rounded_rect_along(V(ax.x - 200, top + th / 2 + 3), V(ax.x - 200 + d.f("battery_length"),
                                                                            top + th / 2 + 3), th / 2, 6),
                    t.frame("#262626" if t.mode == "filled" else None), "accessories", Z_OVER, True, "battery")

    def dropout(self):
        g, t = self.g, self.t
        ax = g.p["rear_axle"]
        node = g.p["stay_node"]
        pts = [ax + V.polar(13, a) for a in range(0, 360, 30)] + [node + V.polar(11, a) for a in range(0, 360, 45)]
        for name in ("cs", "ss"):
            tb = g.tubes.get(name)
            if tb is None or tb.draw_a is None:
                continue
            dirn = tb.dir_a()
            e = tb.draw_a + dirn * 8
            pts += [e + dirn.perp() * (tb.od_a / 2), e - dirn.perp() * (tb.od_a / 2)]
        slot = (g.p.get("slot_closed"), g.p.get("slot_open"))
        if slot[0] is not None:
            pts += [slot[0] + V.polar(13, a) for a in range(0, 360, 30)]
            pts += [slot[1] + V.polar(13, a) for a in range(0, 360, 30)]
        hull = convex_hull(pts)
        fill = t.frame_fill if t.mode == "filled" else t.component_fill
        self.sc.poly(hull, t.frame("#9a9a9a" if t.mode == "filled" else fill), "frame", Z_STAY + 1, True, "dropout")
        if slot[0] is not None:
            # the slot itself, open at one end
            sdir = (slot[1] - slot[0]).norm()
            open_end = slot[1] + sdir * 14
            self.sc.poly(rounded_rect_along(slot[0], open_end, 5.2), Style(t.outline, t.width * 0.6, t.bg),
                         "frame", Z_STAY + 2, True, "dropout")
        elif self.d["dropout_type"] == "vertical":
            open_end = ax + V(6, -26)
            self.sc.poly(rounded_rect_along(ax, open_end, 5.2), Style(t.outline, t.width * 0.6, t.bg),
                         "frame", Z_STAY + 2, True, "dropout")
        self.sc.circle(ax, 5, t.comp("#555555"), "frame", Z_STAY + 3, "dropout")
        # derailleur hanger
        if self.d["drive_type"] == "derailleur":
            h = ax + V(4, -22)
            self.sc.poly(convex_hull([ax + V.polar(9, a) for a in range(0, 360, 30)] +
                                     [h + V.polar(6, a) for a in range(0, 360, 30)]),
                         t.comp("#8a8a8a"), "frame", Z_STAY + 1, True, "dropout")

    def _junctions(self) -> list[tuple[str, str, V, V]]:
        """(tube, receiving, point, direction away from joint) for every joint."""
        g = self.g
        out = []
        tb = g.tubes
        if "tt" in tb:
            out.append(("tt", "ht", g.p["tt_ht"], tb["tt"].dir_b() * -1))
            out.append(("tt", "st", g.p["tt_st"], tb["tt"].dir_a()))
        if "dt" in tb:
            out.append(("dt", "ht", g.p["dt_ht"], tb["dt"].dir_b() * -1))
            out.append(("dt", "bb", g.p["dt_bb"], tb["dt"].dir_a()))
        if "st" in tb:
            out.append(("st", "bb", g.p["st_bottom"], tb["st"].dir_a()))
        if "cs" in tb:
            out.append(("cs", "bb", V(0, 0), tb["cs"].dir_b() * -1))
        if "ss" in tb and tb["ss"].join_b in ("st", "tt"):
            out.append(("ss", tb["ss"].join_b, g.p["ss_top"], tb["ss"].dir_b() * -1))
        return out

    def _receiver_half(self, name: str, at: V) -> float:
        if name == "bb":
            return self.d.f("bb_shell_od") / 2
        tb = self.g.tubes.get(name)
        if tb is None:
            return 0.0
        from ..geometry.vec import project_on_line
        f = max(0.0, min(1.0, project_on_line(at, tb.a, tb.b - tb.a) / max(tb.chord, 1e-9)))
        return tb.od_at(f) / 2

    def lugs(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        sock = d.f("lug_socket_length")
        pt_len = d.f("lug_point_length")
        wall = d.f("lug_wall")
        style = d["lug_style"]
        fill = t.lug_fill if t.mode == "filled" else t.component_fill
        st = t.frame(fill)
        for name, recv, J, away in self._junctions():
            tb = g.tubes[name]
            half = (tb.od_b if name in ("tt",) else tb.od_a if name != "cs" else tb.od_b) / 2 + wall
            start = J + away * self._receiver_half(recv, J)
            end = start + away * sock
            n_ = away.perp()
            tip = end + away * pt_len
            if style == "rounded":
                pts = [start + n_ * half, end + n_ * half]
                pts += [end + V.polar(half, away.angle() + a) for a in range(90, -91, -15)]
                pts += [end - n_ * half, start - n_ * half]
            elif style == "long_point":
                pts = [start + n_ * half, end + n_ * half, tip + away * pt_len * 0.8, end - n_ * half, start - n_ * half]
            elif style == "heart":
                pts = [start + n_ * half, end + n_ * half, tip, end - n_ * half, start - n_ * half]
            else:
                pts = [start + n_ * half, end + n_ * half, tip, end - n_ * half, start - n_ * half]
            sc.poly(pts, st, "frame", Z_FRAME + 3, True, f"lug:{name}-{recv}")
            if style == "heart":
                c = end + away * (pt_len * 0.25)
                sc.circle(c, half * 0.3, t.frame(t.frame_fill), "frame", Z_FRAME + 3)
        # head-tube lug sleeves
        ht = g.tubes["ht"]
        for J in (g.p["tt_ht"], g.p["dt_ht"]):
            if J is g.p["tt_ht"] and "tt" not in g.tubes:
                continue
            a = J - g.u * 22
            b = J + g.u * 22
            sc.poly(rect_along(a, b, ht.od_b / 2 + wall), st, "frame", Z_FRAME + 4, True, "lug:ht")
        # seat lug sleeve
        if "st" in g.tubes:
            J = g.p["tt_st"]
            a = J - g.s * 26
            b = g.p["st_top"]
            sc.poly(rect_along(a, b, g.tubes["st"].od_b / 2 + wall), st, "frame", Z_FRAME + 4, True, "lug:st")
        sc.circle(V(0, 0), d.f("bb_shell_od") / 2 + wall, st, "frame", Z_FRAME + 1, "lug:bb")

    def fillets(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        rf = d.f("fillet_radius")
        fill = t.frame_fill if t.mode == "filled" else t.component_fill
        st = Style(None, 0, fill) if t.mode == "filled" else t.thin(t.outline, 0.6)
        for name, recv, J, away in self._junctions():
            if recv == "bb" and name == "cs":
                continue
            tb = g.tubes[name]
            if recv == "bb":
                continue
            rt = g.tubes.get(recv)
            if rt is None:
                continue
            half_t = tb.od_at(0.0 if away.dot(tb.b - tb.a) > 0 else 1.0) / 2
            half_r = self._receiver_half(recv, J)
            rdir = (rt.b - rt.a).norm()
            for side in (1, -1):
                # edge of the joining tube on this side
                e_pt = J + away.perp() * (half_t * side)
                # receiving edge on the side the joining tube comes from
                rs = 1 if rdir.perp().dot(away) > 0 else -1
                r_pt = J + rdir.perp() * (half_r * rs)
                corner = line_intersect(e_pt, away, r_pt, rdir)
                if corner is None:
                    continue
                # directions from corner along each edge, away from the joint interior
                a_dir = away
                b_dir = rdir if (corner + rdir - J).dot(away.perp() * side) > (corner - rdir - J).dot(away.perp() * side) else rdir * -1
                ang = math.acos(max(-1, min(1, a_dir.dot(b_dir))))
                if ang < math.radians(5) or ang > math.radians(175):
                    continue
                dist = rf / math.tan(ang / 2)
                p1 = corner + a_dir * dist
                p2 = corner + b_dir * dist
                bis = (a_dir + b_dir).norm()
                centre = corner + bis * (rf / math.sin(ang / 2))
                a1 = (p1 - centre).angle()
                a2 = (p2 - centre).angle()
                sweep = (a2 - a1 + 540) % 360 - 180
                arc = [centre + V.polar(rf, a1 + sweep * i / 10) for i in range(11)]
                sc.poly([corner] + arc, st, "frame", Z_FRAME + 3, True, f"fillet:{name}-{recv}")

    def decals(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        if t.mode not in ("filled",):
            return
        dt = g.tubes.get("dt")
        text = str(d["decal_text"]).strip()
        if dt is not None and text:
            size = d.f("decal_size") or dt.od_b * 0.62
            mid = dt.a.lerp(dt.b, 0.55)
            ang = (dt.b - dt.a).angle()
            sc.text(mid, text, Style(d["paint_decal"], 0, None), size, ang, "cm", "frame", Z_FRAME + 5,
                    annotative=False, font=str(d["decal_font"]), bold=bool(d["decal_bold"]),
                    italic=bool(d["decal_italic"]), tag="decal:dt")
        for i, dc in enumerate(d.extras.get("decals") or []):
            self._custom_decal(i, dc)
        badge = str(d["ht_badge_text"]).strip()
        if badge:
            ht = g.tubes["ht"]
            mid = ht.a.lerp(ht.b, 0.5)
            sc.text(mid, badge, Style(d["paint_frame"] if t.ht_fill != t.frame_fill else d["paint_decal"], 0, None),
                    min(ht.od_b * 0.55, 22), (ht.b - ht.a).angle(), "cm", "frame", Z_FRAME + 5,
                    annotative=False, font=str(d["decal_font"]), bold=True, tag="decal:ht")

    def _custom_decal(self, i: int, dc: dict) -> None:
        """A user decal: text or image placed along a tube (extras['decals'])."""
        g, sc = self.g, self.sc
        tb = g.tubes.get(str(dc.get("tube", "dt")))
        if tb is None:
            return
        try:
            pos = float(dc.get("pos", 0.5))
            p, tan = tb.point_at(max(0.0, min(1.0, pos)) * tb.length)
            frac = max(0.0, min(1.0, pos))
            size = float(dc.get("size", 0) or 0) or tb.od_at(frac) * 0.6
            ang = tan.angle() + float(dc.get("angle", 0.0))
            p = p + tan.perp() * float(dc.get("offset", 0.0))
        except (TypeError, ValueError):
            return
        if bool(dc.get("flip")):
            ang += 180
        img = str(dc.get("image", "") or "")
        if img:
            from pathlib import Path as _P
            if _P(img).exists():
                try:
                    from ..qt import QtGui
                    q = QtGui.QImage(img)
                    w, h = q.width(), q.height()
                except Exception:
                    return
                if w and h:
                    k = size / h                               # image height = decal size (mm)
                    origin = p - V.dir(ang) * (w * k / 2) + V.dir(ang + 90) * (h * k / 2)
                    sc.add(Image("frame", Z_FRAME + 5, Style(None, 0, None, opacity=float(dc.get("opacity", 1.0))),
                                 f"decal:{i}", img, origin, k, ang))
            return
        text = str(dc.get("text", "")).strip()
        if text:
            sc.text(p, text, Style(str(dc.get("color", self.d["paint_decal"])), 0, None), size, ang, "cm", "frame",
                    Z_FRAME + 5, annotative=False, font=str(dc.get("font", self.d["decal_font"])),
                    bold=bool(dc.get("bold", True)), italic=bool(dc.get("italic", False)), tag=f"decal:{i}")

    def braze_ons(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        st = t.comp("#9a9a9a")
        tubes = g.tubes
        # bottle bosses
        for key, tname, side in (("bottle_dt", "dt", 1), ("bottle_st", "st", -1)):
            tb = tubes.get(tname)
            if not d[key] or tb is None:
                continue
            s0 = d.f(f"{tname}_pos" if False else ("bottle_dt_pos" if tname == "dt" else "bottle_st_pos"))
            for s in (s0, s0 + d.f("boss_spacing")):
                p, tan = tb.point_at(s)
                sc.circle(p + tan.perp() * (tb.od_b / 2 * side), 2.5, st, "frame", Z_FRAME + 6, f"boss:{tname}")
        if d["dt_cable_stops"] and "dt" in tubes:
            dt = tubes["dt"]
            p, tan = dt.point_at(dt.length - d.f("dt_cable_stop_pos"))
            e = p + tan.perp() * (dt.od_b / 2)
            sc.poly(rect_along(e - tan * 6, e + tan * 6, 2.5), st, "frame", Z_FRAME + 6, True, "brazeon:cable")
        if d["cs_bridge"] and "cs" in tubes:
            cs = tubes["cs"]
            p, _ = cs.point_at(cs.length - g.v.get("cs_bridge_pos", d.f("cs_bridge_pos")))
            sc.circle(p, cs.od_b * 0.42, t.frame(t.frame_fill), "frame", Z_STAY + 2, "brazeon:cs_bridge")
        if d["ss_bridge"] and "ss" in tubes:
            ss = tubes["ss"]
            pos = d.f("ss_bridge_pos")
            if pos <= 0:
                w = g.wheels["rear"]
                if d["brake_rear"] in ("caliper",):
                    target = w.rim_r - 6 + d.f("brake_reach")
                else:
                    target = w.outer_r + 12
                # distance along the stay from the axle where the radius equals target
                pos = target
            p, _ = ss.point_at(max(0.0, min(ss.length, pos)))
            sc.circle(p, ss.od_b * 0.45, t.frame(t.frame_fill), "frame", Z_STAY + 2, "brazeon:ss_bridge")
            self.g.p["ss_bridge"] = p
        if d["pump_pegs"] and "st" in tubes:
            p, tan = tubes["st"].point_at(tubes["st"].length * 0.85)
            sc.circle(p - tan.perp() * (tubes["st"].od_b / 2), 2.5, st, "frame", Z_FRAME + 6, "brazeon:pump")
        if d["kickstand_plate"] and "cs" in tubes:
            cs = tubes["cs"]
            p, tan = cs.point_at(cs.length - 50)
            sc.poly(rect_along(p - tan * 20, p + tan * 20, cs.od_b / 2 + 2), t.frame(t.frame_fill), "frame",
                    Z_STAY + 2, True, "brazeon:kickstand")
        # seat binder
        if "st" in tubes:
            top = g.p["st_top"]
            st_t = tubes["st"]
            clamp = d["seat_clamp"]
            if clamp == "clamp":
                sc.poly(rect_along(top - g.s * 14, top + g.s * 1, st_t.od_b / 2 + 2.5), t.comp("#303030"),
                        "frame", Z_FRAME + 6, True, "brazeon:seatclamp")
            elif clamp == "binder":
                e = top - g.s * 12 - g.n_st * (st_t.od_b / 2 + 4)
                sc.poly(rect_along(e - g.s * 10, e + g.s * 10, 5), t.frame(t.frame_fill), "frame", Z_FRAME + 6, True,
                        "brazeon:binder")
                sc.circle(e, 2.2, t.comp("#bbbbbb"), "frame", Z_FRAME + 7)

    # fork --------------------------------------------------------------------------
    def fork(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        u, n = g.u, g.n
        crown = g.p["crown"]
        cb = g.p["crown_bottom"]
        fork = g.tubes["fork"]
        fill = t.fork_fill if t.mode == "filled" else t.component_fill
        if t.mode == "centerline":
            sc.poly(fork.points(), Style(t.outline, 1.2), "fork", Z_FRONT, tag="fork")
            sc.line(crown, g.p["steerer_top"], Style(t.outline, 1.2), "fork", Z_FRONT, "fork")
            return
        # steerer (behind the head tube)
        sc.poly(rect_along(crown, g.p["steerer_top"], d.f("steerer_od") / 2), t.comp("#9a9a9a"), "fork", Z_BACK,
                True, "fork:steerer")
        if d["fork_type"] == "suspension":
            ax = g.p["front_axle"]
            AC = g.v["fork_length"]
            st_od = d.f("fork_stanchion_od")
            # stanchions are parallel to the steering axis through the axle
            top = ax + u * (AC - d.f("fork_crown_height"))
            low_top = ax + u * (AC * 0.55)
            sc.poly(rect_along(low_top - u * 5, top, st_od / 2), t.comp("#d9d9d9"), "fork", Z_FRONT, True, "fork")
            sc.poly(rounded_rect_along(ax - u * 12, low_top, st_od / 2 + 5), t.frame(fill), "fork", Z_FRONT + 1, True,
                    "fork")
            # arch
            arch = low_top - u * 18 - n * (st_od / 2 + 4)
            sc.poly(stroke_polygon([low_top - u * 6, arch, low_top - u * 40 - n * (st_od + 12)], 5),
                    t.frame(fill), "fork", Z_FRONT, True, "fork")
            # crown spans steerer to stanchion
            c0 = crown
            c1 = top + u * d.f("fork_crown_height")
            poly = [c0 + u * 0, c1, top - n * 0, cb]
            sc.poly(convex_hull([c0 - n * (d.f("steerer_od") / 2 + 6), c0 + n * 6, c1 + n * (st_od / 2 + 6),
                                 top + n * (st_od / 2 + 6), top - n * (st_od / 2 + 2), cb - n * (d.f("steerer_od") / 2 + 6)]),
                    t.frame(fill), "fork", Z_FRONT + 2, True, "fork:crown")
            sc.circle(ax, 7, t.comp("#555555"), "fork", Z_FRONT + 3, "fork")
            return
        # rigid blade
        sc.poly(tube_outline(fork), t.frame(fill), "fork", Z_FRONT, True, "fork")
        # crown
        cw = d.f("fork_blade_od") / 2 + 7
        pts = [crown - n * cw, crown + n * cw, cb + n * (cw + 3), cb - n * (cw - 2)]
        sc.poly(pts, t.frame(fill), "fork", Z_FRONT + 1, True, "fork:crown")
        # fork end
        ax = g.p["front_axle"]
        tip_dir = fork.dir_a()
        sc.poly(convex_hull([ax + V.polar(10, a) for a in range(0, 360, 30)] +
                            [ax + tip_dir * 26 + tip_dir.perp() * 7, ax + tip_dir * 26 - tip_dir.perp() * 7]),
                t.frame("#9a9a9a" if t.mode == "filled" else fill), "fork", Z_FRONT + 1, True, "fork:end")
        sc.circle(ax, 5, t.comp("#555555"), "fork", Z_FRONT + 2, "fork")

    # cockpit -------------------------------------------------------------------------
    def cockpit(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        u, n = g.u, g.n
        T = g.p["ht_top"]
        B = g.p["ht_bottom"]
        ht_top_r = d.f("ht_od_top") / 2
        hs = t.comp("#4d4d4d")
        # headset cups
        if d.f("lower_stack") > 0:
            sc.poly(rect_along(B - u * d.f("lower_stack"), B, d.f("ht_od_bottom") / 2 + 1.5), hs, "cockpit",
                    Z_FRONT + 3, True, "headset")
        if d.f("upper_stack") > 0:
            sc.poly(rect_along(T, T + u * d.f("upper_stack"), ht_top_r + 1.5), hs, "cockpit", Z_FRONT + 3, True,
                    "headset")
        base = T + u * d.f("upper_stack")
        clamp = g.p["stem_clamp"]
        bar = g.p["bar"]
        stem_fill = "#2e2e2e"
        if d["stem_type"] == "quill":
            q0 = base
            q1 = clamp + u * 15
            sc.poly(rect_along(q0 - u * 60, q1, d.f("steerer_od") / 2 - 3), t.comp("#c0c0c0"), "cockpit", Z_BACK,
                    True, "stem")
            sc.poly(rect_along(q0, q1, d.f("steerer_od") / 2 - 2), t.comp("#c0c0c0"), "cockpit", Z_COMPONENT, True, "stem")
            ext_dir = (bar - clamp).norm()
            sc.poly(stroke_polygon([clamp, bar], 11), t.comp("#c0c0c0"), "cockpit", Z_COMPONENT, True, "stem")
        else:
            if d.f("spacers") > 0:
                y0 = base
                k = 0
                remaining = d.f("spacers")
                while remaining > 0.01 and k < 30:
                    h = min(10.0, remaining) if remaining > 15 else remaining
                    sc.poly(rect_along(y0, y0 + u * h, d.f("steerer_od") / 2 + 4), t.comp("#3a3a3a"), "cockpit",
                            Z_COMPONENT, True, "spacers")
                    y0 = y0 + u * h
                    remaining -= h
                    k += 1
            ch = d.f("stem_clamp_height")
            c0 = clamp - u * (ch / 2)
            c1 = clamp + u * (ch / 2)
            sr = d.f("steerer_od") / 2 + 5
            sc.poly(rect_along(c0, c1, sr), t.comp(stem_fill), "cockpit", Z_COMPONENT + 1, True, "stem")
            sdir = (bar - clamp).norm()
            body = [c1 - n * sr * 0.2, c1 + n * sr, bar + sdir.perp() * 15, bar - sdir.perp() * 15, c0 + n * sr,
                    c0 - n * sr * 0.2]
            sc.poly(convex_hull(body), t.comp(stem_fill), "cockpit", Z_COMPONENT + 1, True, "stem")
            # steerer top cap
            st_top = g.p["steerer_top"]
            sc.poly(rect_along(st_top - u * 2, st_top + u * 4, sr - 2), t.comp("#202020"), "cockpit", Z_COMPONENT + 2,
                    True, "stem")
        # bar
        bar_fill = "#1f1f1f"
        sc.poly(stroke_polygon(g.bar_path, d.f("bar_od") / 2 * 0.75, caps=True), t.comp(bar_fill), "cockpit",
                Z_COMPONENT + 3, True, "bar")
        sc.circle(bar, d.f("bar_od") / 2 + 3, t.comp(stem_fill), "cockpit", Z_COMPONENT + 4, "stem")
        # levers
        lt = d["lever_type"]
        if lt == "road_sti" and d["bar_type"] == "drop" and "lever" in g.p:
            L = g.p["lever"]
            rot = d.f("bar_rotation")
            k = d.f("hood_reach") / 40.0
            loc = lambda x, y: L + V(x * k, y).rot(rot)
            body = [loc(-4, -9), loc(4, 12), loc(18, 28), loc(42, 36), loc(58, 34), loc(66, 24), loc(58, 14),
                    loc(32, 6), loc(12, -14)]
            sc.poly(body, t.comp("#262626"), "cockpit", Z_COMPONENT + 5, True, "lever")
            blade = [loc(54, 16), loc(64, 18), loc(44, -80), loc(33, -84), loc(38, -40)]
            sc.poly(blade, t.comp("#555555"), "cockpit", Z_COMPONENT + 4, True, "lever")
        elif lt == "flat":
            G = g.p["hoods"]
            sc.poly(stroke_polygon([G + V(-8, 0), G + V(40, -12)], 4, caps=True), t.comp("#555555"), "cockpit",
                    Z_COMPONENT + 4, True, "lever")
            sc.poly(stroke_polygon([G + V(-30, 0), G + V(30, 0)], 16, caps=True), t.comp("#2a2a2a"), "cockpit",
                    Z_COMPONENT + 5, True, "grip")

    # saddle --------------------------------------------------------------------------
    def saddle(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        s = g.s
        post_top = g.p["seatpost_top"]
        post_bottom = g.p["seatpost_bottom"]
        r = d.f("seatpost_od") / 2
        st_top = g.p["st_top"]
        # hidden part of the post (inside the seat tube) drawn dashed
        sc.poly(rect_along(post_bottom, st_top, r), Style(t.outline, t.width * 0.4, None, dash=(2, 1.5)),
                "saddle", Z_FRAME + 1, True, "seatpost")
        sc.poly(rect_along(st_top, post_top, r), t.comp("#1c1c1c" if d["seatpost_type"] != "seatmast" else t.frame_fill),
                "saddle", Z_COMPONENT, True, "seatpost")
        if d["seatpost_type"] == "dropper":
            mid = st_top + s * 35
            sc.poly(rect_along(st_top, mid, r + 2.5), t.comp("#3a3a3a"), "saddle", Z_COMPONENT + 1, True, "seatpost")
        rails = g.p["saddle_rails"]
        head = convex_hull([post_top + V.polar(r + 2, a) for a in range(0, 360, 45)] +
                           [rails + V.polar(9, a) for a in range(0, 360, 45)])
        sc.poly(head, t.comp("#2a2a2a"), "saddle", Z_COMPONENT + 1, True, "seatpost")
        # saddle profile
        nose, tail = g.p["saddle_nose"], g.p["saddle_tail"]
        S = g.p["saddle"]
        L = d.f("saddle_length")
        ax = (nose - tail).norm()
        up = ax.perp()
        stack = d.f("saddle_stack")
        top_y = S + up * 0  # top surface passes through S
        top_line = lambda k: tail + ax * (L * k) + up * ((S - tail).dot(up))
        prof = []
        # top surface: slight dip, rounded tail
        for k, h in ((0.0, -14), (0.02, -4), (0.08, 1.5), (0.35, 0.0), (0.55, -1.5), (0.8, -3), (0.97, -6), (1.0, -10)):
            prof.append(top_line(k) + up * h)
        # underside shell
        for k, h in ((0.99, -15), (0.85, -14), (0.55, -20), (0.25, -26), (0.06, -28), (0.0, -20)):
            prof.append(top_line(k) + up * h)
        sc.poly(prof, t.comp("#1a1a1a"), "saddle", Z_COMPONENT + 2, True, "saddle")
        rail_y = rails
        sc.line(top_line(0.22) + up * (-27), rail_y - ax * 50, t.thin(t.outline, 1.2), "saddle", Z_COMPONENT + 1)
        sc.line(rail_y - ax * 50, rail_y + ax * 50, t.thin(t.outline, 1.6), "saddle", Z_COMPONENT + 1)
        sc.line(rail_y + ax * 50, top_line(0.8) + up * (-14), t.thin(t.outline, 1.2), "saddle", Z_COMPONENT + 1)

    # drivetrain ------------------------------------------------------------------------
    def drivetrain(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        rings = sorted(d.lst("chainrings") or [42], reverse=True)
        cogs = sorted(d.lst("cogs") or [16])
        drive = d["drive_type"]
        pitch = d.f("belt_pitch") if drive == "belt" else d.f("chain_pitch")
        bb = g.p["drive_bb"]
        if bb.length() > 1e-6:
            self._tandem_drive(pitch)
        ax = g.p["rear_axle"]
        R = pitch_radius(rings[0], pitch)
        st_ring = t.comp("#9c9c9c" if t.mode == "filled" else None)
        # cassette
        for c in cogs:
            sc.circle(ax, pitch_radius(c, pitch) + 2.5, t.thin("#666666" if t.mode == "filled" else t.outline, 0.5),
                      "drivetrain", Z_COMPONENT)
        sc.circle(ax, pitch_radius(cogs[-1], pitch) + 3, Style(t.outline, t.width * 0.6,
                                                              "#bdbdbd" if t.mode == "filled" else None),
                  "drivetrain", Z_STAY - 2, "cassette")
        # chain / belt runs
        cog_mid = cogs[len(cogs) // 2] if drive == "derailleur" else cogs[0]
        r_cog = pitch_radius(cog_mid, pitch)
        chain = Style("#3b3b3b" if t.mode == "filled" else t.outline, 0.9 if drive == "belt" else 0.6)
        tangents = external_tangents(bb, R, ax, r_cog)
        if tangents:
            top = max(tangents, key=lambda tp: tp[0].y + tp[1].y)
            bot = min(tangents, key=lambda tp: tp[0].y + tp[1].y)
            sc.line(top[0], top[1], chain, "drivetrain", Z_COMPONENT + 1, "chain")
            if drive == "derailleur":
                p_up = ax + V(8, -48)
                p_lo = ax + V(28, -112)
                jt = external_tangents(bb, R, p_lo, 6)
                if jt:
                    jb = min(jt, key=lambda tp: tp[0].y)
                    sc.line(jb[0], jb[1], chain, "drivetrain", Z_COMPONENT + 1, "chain")
                cage = Style(t.outline, t.width * 0.8, "#4a4a4a" if t.mode == "filled" else None)
                sc.poly(stroke_polygon([p_up, p_lo], 11, caps=True), cage, "drivetrain", Z_COMPONENT + 2, True, "rd")
                sc.circle(p_up, 6.5, t.comp("#bbbbbb"), "drivetrain", Z_COMPONENT + 3, "rd")
                sc.circle(p_lo, 6.5, t.comp("#bbbbbb"), "drivetrain", Z_COMPONENT + 3, "rd")
                knuckle = ax + V(4, -22)
                sc.poly(stroke_polygon([knuckle, ax + V(-6, -36), p_up], 7, caps=True), cage, "drivetrain",
                        Z_COMPONENT + 2, True, "rd")
            else:
                sc.line(bot[0], bot[1], chain, "drivetrain", Z_COMPONENT + 1, "chain")
        # chainrings
        for i, teeth in enumerate(rings):
            r = pitch_radius(teeth, pitch)
            if i == 0:
                pts = []
                nt = int(teeth)
                for k in range(nt * 2):
                    a = 360.0 * k / (nt * 2)
                    pts.append(bb + V.polar(r + (3.2 if k % 2 == 0 else -1.0), a))
                sc.poly(pts, st_ring, "drivetrain", Z_COMPONENT + 2, True, "chainring",
                        holes=[circle_points(bb, r - 11, 72)])
            else:
                sc.circle(bb, r + 2, t.thin(t.outline, 0.6), "drivetrain", Z_COMPONENT + 2, "chainring")
        # front derailleur
        if drive == "derailleur" and d["front_derailleur"] and len(rings) > 1 and "st" in g.tubes \
                and bb.length() < 1e-6:
            s = g.s
            # clamp on the seat tube ~ 2-3 mm above the big ring
            base = s * ((R + 15) / max(s.y, 0.3) * 0.98)
            cage = [base + V(6, -8), base + V(30, -4), base + V(40, -22), base + V(8, -26)]
            sc.poly(cage, t.comp("#5a5a5a"), "drivetrain", Z_COMPONENT + 3, True, "fd")
        # cranks
        cl = d.f("crank_length")
        pedal = g.p["pedal"] + bb
        crank_fill = "#2b2b2b" if t.mode == "filled" else None
        lp = bb - (pedal - bb)
        sc.poly(stroke_polygon([bb + (pedal - bb) * 0.12, lp], [11, 8], caps=True), Style(t.outline, t.width * 0.5, "#777777" if crank_fill else None),
                "drivetrain", Z_STAY - 1, True, "crank:left")
        spider = [bb + V.polar(R * 0.62, d.f("crank_angle") + a) for a in range(0, 360, 72)]
        for sp in spider:
            sc.poly(stroke_polygon([bb, sp], 6, caps=True), t.comp(crank_fill), "drivetrain", Z_COMPONENT + 3, True,
                    "crank")
        sc.poly(stroke_polygon([bb, pedal], [12, 8], caps=True), t.comp(crank_fill), "drivetrain", Z_COMPONENT + 4,
                True, "crank")
        sc.circle(bb, 13, t.comp("#555555"), "drivetrain", Z_COMPONENT + 5, "crank")
        if d["pedal_type"] != "none":
            for p_, z in ((pedal, Z_COMPONENT + 5), (bb - (pedal - bb), Z_STAY - 1)):
                w = 50 if d["pedal_type"] == "flat" else 36
                h = 18 if d["pedal_type"] == "flat" else 12
                sc.poly([p_ + V(-w / 2, -h / 2), p_ + V(w / 2, -h / 2), p_ + V(w / 2, h / 2), p_ + V(-w / 2, h / 2)],
                        t.comp("#3a3a3a"), "drivetrain", z, True, "pedal")

    def _tandem_drive(self, pitch: float):
        """Captain cranks with timing ring and the timing chain (non-drive side)."""
        g, sc, t, d = self.g, self.sc, self.t, self.d
        bb2 = g.p["drive_bb"]
        r = pitch_radius(int(d["timing_ring"]), pitch)
        st = Style("#3b3b3b" if t.mode == "filled" else t.outline, 0.5, None, dash=(3, 2))
        for c in (V(0, 0), bb2):
            sc.circle(c, r + 2, Style(t.outline, t.width * 0.5, None, dash=(2, 1.5)), "drivetrain", Z_STAY - 2,
                      "timing")
        for a_, b_ in external_tangents(V(0, 0), r, bb2, r):
            sc.line(a_, b_, st, "drivetrain", Z_STAY - 2, "timing")
        pedal = g.p["pedal"]
        fill = "#2b2b2b" if t.mode == "filled" else None
        sc.poly(stroke_polygon([V(0, 0), pedal], [12, 8], caps=True), t.comp(fill), "drivetrain", Z_COMPONENT + 4,
                True, "crank:captain")
        sc.poly(stroke_polygon([V(0, 0), -pedal], [11, 8], caps=True), Style(t.outline, t.width * 0.5,
                "#777777" if fill else None), "drivetrain", Z_STAY - 1, True, "crank:captain")
        sc.circle(V(0, 0), 13, t.comp("#555555"), "drivetrain", Z_COMPONENT + 5, "crank:captain")
        if d["pedal_type"] != "none":
            for p_, z in ((pedal, Z_COMPONENT + 5), (-pedal, Z_STAY - 1)):
                sc.poly([p_ + V(-18, -6), p_ + V(18, -6), p_ + V(18, 6), p_ + V(-18, 6)], t.comp("#3a3a3a"),
                        "drivetrain", z, True, "pedal")
        # stoker saddle, post and bars
        if "stoker_saddle" in g.p:
            S2 = g.p["stoker_saddle"]
            s2 = (g.p["stoker_st_top"] - g.p["stoker_bb"]).norm()
            r_post = d.f("seatpost_od") / 2
            rails = g.p["stoker_saddle_rails"]
            sc.poly(rect_along(g.p["stoker_st_top"], rails, r_post), t.comp("#1c1c1c"), "saddle", Z_COMPONENT, True,
                    "seatpost:stoker")
            nose, tail = g.p["stoker_saddle_nose"], g.p["stoker_saddle_tail"]
            prof = [tail + V(0, -14), tail + V(6, 0), nose + V(-30, 0), nose + V(0, -8), nose + V(-10, -16),
                    tail + V(30, -26), tail + V(0, -20)]
            sc.poly(prof, t.comp("#1a1a1a"), "saddle", Z_COMPONENT + 2, True, "saddle:stoker")
            clamp, bar = g.p["stoker_stem_clamp"], g.p["stoker_bar"]
            sc.poly(stroke_polygon([clamp, bar], 9, caps=True), t.comp("#2e2e2e"), "cockpit", Z_COMPONENT + 1, True,
                    "stem:stoker")
            sc.poly(stroke_polygon([bar, bar + V(-25, -10)], 11, caps=True), t.comp("#1f1f1f"), "cockpit",
                    Z_COMPONENT + 2, True, "bar:stoker")

    # brakes ------------------------------------------------------------------------------
    def brakes(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        for key, axle, wheel in (("front", g.p["front_axle"], g.wheels["front"]),
                                 ("rear", g.p["rear_axle"], g.wheels["rear"])):
            kind = d[f"brake_{key}"]
            if kind == "disc":
                r = d.f(f"rotor_{key}") / 2
                sc.poly(circle_points(axle, r, 72), Style(t.outline, t.width * 0.6, "#c9c9c9" if t.mode == "filled" else None),
                        "brakes", Z_WHEEL + 4, True, f"rotor:{key}", holes=[circle_points(axle, r - 14, 72)])
                if key == "front":
                    ang = (g.u * -1).angle() + 180 + 40
                else:
                    cs = g.tubes.get("cs")
                    ang = (cs.dir_a().angle() + 18) if cs else 20
                c = axle + V.polar(r - 6, ang)
                dirn = V.dir(ang + 90)
                sc.poly(rounded_rect_along(c - dirn * 26, c + dirn * 26, 13, 6), t.comp("#303030"), "brakes",
                        Z_COMPONENT, True, f"caliper:{key}")
            elif kind in ("caliper",):
                if key == "front":
                    mount = g.p["crown_bottom"] + g.n * 8
                else:
                    mount = g.p.get("ss_bridge", g.p["ss_top"])
                top = wheel.rim_r
                pad_c = axle + (mount - axle).norm() * (top - 6)
                sc.poly(rounded_rect_along(mount, pad_c, 9, 4), t.comp("#b5b5b5"), "brakes", Z_COMPONENT, True,
                        f"caliper:{key}")
            elif kind in ("cantilever", "v"):
                if key == "front":
                    fork = g.tubes["fork"]
                    boss, tan = fork.point_at(wheel.rim_r - 15)
                    boss = fork.a + (fork.points()[-1] - fork.a).norm() * (wheel.rim_r - 15)
                    dirv = (g.n * 1.0) if kind == "v" else (g.n + g.u).norm()
                else:
                    ss = g.tubes.get("ss")
                    if ss is None:
                        continue
                    boss = ss.a + ss.dir_a() * (wheel.rim_r - 15)
                    dirv = (ss.dir_a().perp() * -1) if kind == "v" else (ss.dir_a().perp() * -1 + ss.dir_a()).norm()
                arm = boss + dirv * (85 if kind == "v" else 45)
                sc.poly(stroke_polygon([boss, arm], 5, caps=True), t.comp("#b5b5b5"), "brakes", Z_COMPONENT, True,
                        f"caliper:{key}")

    # accessories ---------------------------------------------------------------------------
    def accessories(self):
        g, sc, t, d = self.g, self.sc, self.t, self.d
        tubes = g.tubes
        bd = d.f("bottle_diameter")
        bl = d.f("bottle_length")
        bottle_fill = "#2f6db5" if t.mode == "filled" else None
        for key, tname, side in (("bottle_dt", "dt", 1), ("bottle_st", "st", -1)):
            tb = tubes.get(tname)
            if not d[key] or tb is None:
                continue
            s0 = d.f("bottle_dt_pos" if tname == "dt" else "bottle_st_pos")
            mid_s = s0 - 35 + bl / 2          # bottle base sits ~35 mm below the lower boss
            p, tan = tb.point_at(mid_s)
            off = tan.perp() * (side * (tb.od_b / 2 + 5 + bd / 2))
            c = p + off
            a = c - tan * (bl / 2)
            b = c + tan * (bl / 2)
            body = rounded_rect_along(a, b, bd / 2, bd * 0.35)
            sc.poly(body, Style(t.outline, t.width * 0.6, bottle_fill, opacity=0.9), "accessories", Z_OVER, True,
                    f"bottle:{tname}")
            cap = b if tname == "dt" else b
            sc.poly(rect_along(cap, cap + tan * 14, bd * 0.18), t.comp("#dddddd"), "accessories", Z_OVER, True,
                    f"bottle:{tname}")
            pb, _ = tb.point_at(s0)
            cage = [pb - tan * 30, pb + tan * (d.f("boss_spacing") + 25)]
            sc.poly(stroke_polygon([q + tan.perp() * (side * (tb.od_b / 2 + 3)) for q in cage], 1.6),
                    t.comp("#444444"), "accessories", Z_OVER + 1, True, f"cage:{tname}")
        if d["fenders"]:
            for key, a0, a1 in (("rear", -10, 200), ("front", -20, 220)):
                w = g.wheels[key]
                r0 = w.outer_r + d.f("fender_clearance")
                c = w.center
                outer = [c + V.polar(r0 + 2.5, a0 + (a1 - a0) * i / 40) for i in range(41)]
                inner = [c + V.polar(r0, a1 - (a1 - a0) * i / 40) for i in range(41)]
                sc.poly(outer + inner, t.comp("#262626"), "accessories", Z_WHEEL + 5, True, f"fender:{key}")
        if d["rack_rear"]:
            ax = g.p["rear_axle"]
            top_y = ax.y + d.f("rack_height")
            front_x = ax.x + 120
            back_x = ax.x - 230
            st = t.comp("#3a3a3a")
            sc.poly(stroke_polygon([V(back_x, top_y), V(front_x, top_y)], 4, caps=True), st, "accessories", Z_OVER,
                    True, "rack")
            sc.poly(stroke_polygon([ax + V(-6, 8), V(back_x + 60, top_y)], 3, caps=True), st, "accessories", Z_OVER,
                    True, "rack")
            sc.poly(stroke_polygon([ax + V(-2, 8), V(ax.x - 30, top_y)], 3, caps=True), st, "accessories", Z_OVER,
                    True, "rack")
            ss = g.tubes.get("ss")
            if ss is not None:
                p, _ = ss.point_at(ss.length * 0.72)
                sc.poly(stroke_polygon([V(front_x - 20, top_y), p], 2.5, caps=True), st, "accessories", Z_OVER, True,
                        "rack")
        if d["rack_front"]:
            ax = g.p["front_axle"]
            top_y = g.p["crown"].y - 30
            st = t.comp("#3a3a3a")
            sc.poly(stroke_polygon([V(ax.x - 60, top_y), V(ax.x + 160, top_y)], 4, caps=True), st, "accessories",
                    Z_OVER, True, "rack")
            sc.poly(stroke_polygon([ax + V(4, 8), V(ax.x + 120, top_y)], 3, caps=True), st, "accessories", Z_OVER,
                    True, "rack")
            sc.poly(stroke_polygon([g.p["crown_bottom"], V(ax.x - 40, top_y)], 3, caps=True), st, "accessories",
                    Z_OVER, True, "rack")

    # overlays --------------------------------------------------------------------------------
    def centerlines(self):
        g, sc, t = self.g, self.sc, self.t
        st = t.centre()
        lay = "centerlines"
        for name, tb in g.tubes.items():
            pts = tb.points()
            sc.poly(pts, st, lay, Z_CENTERLINE, tag=f"cl:{name}")
        # steering axis to the ground and seat tube axis to the saddle
        sc.line(g.p["axis_ground"], g.p["steerer_top"], st, lay, Z_CENTERLINE)
        sc.line(g.p["st_bottom"], g.p["st_bottom"] + g.s * (g.p["saddle"] - g.p["st_bottom"]).dot(g.s), st, lay,
                Z_CENTERLINE)
        sc.line(g.p["bb"], g.p["rear_axle"], st, lay, Z_CENTERLINE)
        for name in ("bb", "rear_axle", "front_axle", "ht_top", "saddle", "bar"):
            p = g.p[name]
            sc.line(p - V(8, 0), p + V(8, 0), t.thin(t.centerline, 0.6), lay, Z_CENTERLINE)
            sc.line(p - V(0, 8), p + V(0, 8), t.thin(t.centerline, 0.6), lay, Z_CENTERLINE)

    def toe_circle(self):
        g = self.g
        r = g.v["toe_radius"]
        color = "#d02020" if g.v["toe_clearance"] < 0 else "#20a040"
        a_c = g.p["front_axle"].angle()
        self.sc.arc(V(0, 0), r, a_c - 35, 70, Style(color, 0.35, None, dash=(3, 2)), "analysis", Z_OVER + 5, "toe")
        w = g.wheels["front"]
        self.sc.arc(w.center, w.outer_r, a_c + 180 - 30, 60, Style(color, 0.35, None, dash=(3, 2)), "analysis",
                    Z_OVER + 5, "toe")

    def dimensions(self):
        g, sc, t = self.g, self.sc, self.t
        units = self.d["units"]
        offsets = self.d.extras.get("dimension_offsets") or {}
        st = t.dimension()
        tsize = self.d.f("dimension_text_size")
        thoriz = bool(self.d["dimension_text_horizontal"])
        for dim_id in DIM.visible_ids(g):
            dd = DIM.BY_ID.get(dim_id)
            if dd is None:
                continue
            try:
                kw = dd.build(g)
            except (KeyError, ZeroDivisionError, ValueError):
                continue
            value = kw.pop("value")
            txt = DIM.format_value(value, dd.kind, units)
            if dd.kind == "linear":
                if dim_id in offsets:
                    kw["offset"] = float(offsets[dim_id])
                sc.add(LinearDim("dimensions", Z_DIM, st, f"dim:{dim_id}", text=txt, dim_id=dim_id,
                                 text_size=tsize, text_horizontal=thoriz, **kw))
            else:
                if dim_id in offsets:
                    kw["radius"] = abs(float(offsets[dim_id]))
                sc.add(AngleDim("dimensions", Z_DIM, st, f"dim:{dim_id}", text=txt, dim_id=dim_id,
                                text_size=tsize, **kw))
        for ud in self.d.extras.get("user_dimensions") or []:
            res = DIM.build_user(g, ud)
            if res is None:
                continue
            kind, kw = res
            value = kw.pop("value")
            label = str(ud.get("label") or "")
            txt = (label + " " if label else "") + DIM.format_value(value, kind, units)
            uid = str(ud.get("id", "u"))
            st_u = st.with_(stroke="#8a2be2")
            if kind == "linear":
                sc.add(LinearDim("dimensions", Z_DIM, st_u, f"udim:{uid}", text=txt, dim_id=uid,
                                 text_size=tsize, text_horizontal=thoriz, **kw))
            else:
                sc.add(AngleDim("dimensions", Z_DIM, st_u, f"udim:{uid}", text=txt, dim_id=uid,
                                text_size=tsize, **kw))

    def notes(self):
        sc = self.sc
        for note in self.d.extras.get("notes") or []:
            try:
                pos = V(float(note["x"]), float(note["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            color = str(note.get("color", "#b03000"))
            st = Style(color, 0.3, None)
            leader = note.get("leader")
            if leader:
                tip = V(float(leader[0]), float(leader[1]))
                sc.line(pos, tip, st, "notes", Z_NOTE, f"note:{note.get('id', '')}")
                sc.circle(tip, 2.0, st.with_(fill=color), "notes", Z_NOTE)
            sc.text(pos, str(note.get("text", "")), st, float(note.get("size", 3.5)), 0.0, "lb", "notes", Z_NOTE,
                    tag=f"note:{note.get('id', '')}", box=True)

    def ghost(self, gg: Geometry, color: str):
        sc = self.sc
        st = Style(color, 0.5, None, opacity=0.85)
        for name, tb in gg.tubes.items():
            sc.poly(tube_outline(tb), st, "ghost", Z_GHOST, True, "ghost")
        for w in gg.wheels.values():
            sc.circle(w.center, w.outer_r, st, "ghost", Z_GHOST, "ghost")
        sc.circle(V(0, 0), gg.design.f("bb_shell_od") / 2, st, "ghost", Z_GHOST, "ghost")
        sc.poly(gg.bar_path, st, "ghost", Z_GHOST, tag="ghost")
        for a, b in (("seatpost_top", "saddle"), ("saddle_tail", "saddle_nose"), ("ht_top", "stem_clamp"),
                     ("stem_clamp", "bar")):
            sc.line(gg.p[a], gg.p[b], st, "ghost", Z_GHOST, "ghost")


def build_scene(g: Geometry, dimensions: bool | None = None, ghosts=(), theme: Theme | None = None) -> Scene:
    return BikeSceneBuilder(g, theme).build(dimensions=dimensions, ghosts=ghosts)
