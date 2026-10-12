"""Dimension catalogue and user dimensions.

Each catalogue entry knows how to measure itself on a solved geometry and how
to place itself on the drawing.  Users choose which are visible (stored in
``design.extras['visible_dimensions']``), can drag them (offset overrides in
``extras['dimension_offsets']``), save named sets ("dimension states") and add
their own point-to-point dimensions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from ..model.units import fmt_angle, fmt_len
from .solver import Geometry
from .vec import V, cosd, project_on_line, sind


@dataclass(frozen=True)
class DimDef:
    id: str
    label: str
    kind: str                 # linear | angle
    default: bool
    build: Callable[[Geometry], dict]   # returns kwargs for LinearDim/AngleDim plus 'value'
    category: str = "Frame"


def _lin(p1, p2, offset, mode="aligned", value=None):
    return {"p1": p1, "p2": p2, "offset": offset, "mode": mode,
            "value": value if value is not None else
            (abs(p2.x - p1.x) if mode == "horizontal" else abs(p2.y - p1.y) if mode == "vertical" else p1.dist(p2))}


def _ang(vertex, start, span, radius, value=None):
    return {"vertex": vertex, "start": start, "span": span, "radius": radius,
            "value": abs(span) if value is None else value}


def _span(a0: float, a1: float) -> float:
    """Signed sweep from angle a0 to a1 in (-180, 180]."""
    return (a1 - a0 + 540.0) % 360.0 - 180.0


def _foot(pt: V, a: V, d: V) -> V:
    return a + d.norm() * project_on_line(pt, a, d)


def _st_x(g: Geometry, y: float) -> V:
    p0 = g.p["st_bottom"]
    s = g.s
    t = (y - p0.y) / s.y
    return p0 + s * t


CATALOG: list[DimDef] = [
    DimDef("stack", "Stack", "linear", True,
           lambda g: _lin(g.p["bb"], g.p["ht_top"], 70, "vertical")),
    DimDef("reach", "Reach", "linear", True,
           lambda g: _lin(g.p["bb"], g.p["ht_top"], 70, "horizontal")),
    DimDef("ett", "Effective top tube", "linear", True,
           lambda g: _lin(_st_x(g, g.p["ht_top"].y), g.p["ht_top"], 25, "horizontal")),
    DimDef("tt_cc", "Top tube (c-c)", "linear", False,
           lambda g: _lin(g.p["tt_st"], g.p["tt_ht"], -30)),
    DimDef("st_ct", "Seat tube (c-t)", "linear", True,
           lambda g: _lin(g.p["st_bottom"], g.p["st_top"], 55)),
    DimDef("st_cc", "Seat tube (c-c)", "linear", False,
           lambda g: _lin(g.p["st_bottom"], g.p["tt_st"], 85)),
    DimDef("st_ext", "Seat tube extension", "linear", False,
           lambda g: _lin(g.p["tt_st"], g.p["st_top"], -30)),
    DimDef("ht_length", "Head tube length", "linear", True,
           lambda g: _lin(g.p["ht_bottom"], g.p["ht_top"], -45)),
    DimDef("hta", "Head tube angle", "angle", True,
           lambda g: _ang(g.p["ht_top"], (g.u * -1).angle(), -(g.u * -1).angle(), 75,
                          g.v["head_tube_angle"])),
    DimDef("sta", "Seat tube angle", "angle", True,
           lambda g: _ang(g.p["st_bottom"], g.s.angle(), 180 - g.s.angle(), 95, g.v["seat_tube_angle"])),
    DimDef("seat_angle_eff", "Effective seat angle", "angle", False,
           lambda g: _ang(g.p["bb"], g.p["saddle"].angle(), 180 - g.p["saddle"].angle(), 140,
                          g.v["seat_angle_eff"]), "Fit"),
    DimDef("chainstay", "Chainstay length", "linear", True,
           lambda g: _lin(g.p["rear_axle"], g.p["drive_bb"], -40)),
    DimDef("rear_center", "Rear centre (horizontal)", "linear", False,
           lambda g: _lin(g.p["rear_axle"], g.p["drive_bb"], g.ground_y + 25 - min(g.p["rear_axle"].y, g.p["drive_bb"].y),
                          "horizontal")),
    DimDef("front_center", "Front centre", "linear", True,
           lambda g: _lin(g.p["bb"], g.p["front_axle"], -40)),
    DimDef("wheelbase", "Wheelbase", "linear", True,
           lambda g: _lin(g.p["rear_axle"], g.p["front_axle"],
                          g.ground_y - 45 - min(g.p["rear_axle"].y, g.p["front_axle"].y), "horizontal")),
    DimDef("bb_drop", "BB drop", "linear", True,
           lambda g: _lin(g.p["rear_axle"], g.p["drive_bb"], 40, "vertical")),
    DimDef("bb_height", "BB height", "linear", False,
           lambda g: _lin(g.p["ground_bb"], g.p["bb"], -60, "vertical")),
    DimDef("trail", "Trail", "linear", True,
           lambda g: _lin(g.p["ground_front"], g.p["axis_ground"], -25, "horizontal", g.v["trail"])),
    DimDef("fork_offset", "Fork offset", "linear", True,
           lambda g: _lin(_foot(g.p["front_axle"], g.p["ht_top"], g.u), g.p["front_axle"], 0.0, "aligned",
                          g.v["fork_offset"])),
    DimDef("fork_ac", "Fork axle-to-crown", "linear", True,
           lambda g: _lin(_foot(g.p["front_axle"], g.p["ht_top"], g.u), g.p["crown"],
                          -(g.v["fork_offset"] + 45), "aligned", g.v["fork_length"])),
    DimDef("standover", "Standover height", "linear", False,
           lambda g: _lin(V(g.p.get("standover", V()).x, g.ground_y), g.p.get("standover", V()), 25, "vertical",
                          g.v["standover"])),
    DimDef("dt_cc", "Down tube (c-c)", "linear", False,
           lambda g: _lin(g.p["dt_bb"], g.p["dt_ht"], -35)),
    DimDef("toe", "Toe clearance", "linear", False,
           lambda g: _lin(g.p["front_axle"].norm() * g.v["toe_radius"],
                          g.p["front_axle"] - g.p["front_axle"].norm() * g.wheels["front"].outer_r, 25, "aligned",
                          g.v["toe_clearance"]), "Fit"),
    DimDef("saddle_height", "Saddle height", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["saddle"], 120), "Fit"),
    DimDef("saddle_setback", "Saddle setback", "linear", False,
           lambda g: _lin(g.p["saddle"], g.p["bb"], 40, "horizontal", g.v["saddle_setback"]), "Fit"),
    DimDef("saddle_bar_drop", "Saddle to bar drop", "linear", False,
           lambda g: _lin(g.p["saddle"], g.p["bar"], 60, "vertical", g.v["saddle_bar_drop"]), "Fit"),
    DimDef("saddle_bar_reach", "Saddle to bar (horizontal)", "linear", False,
           lambda g: _lin(g.p["saddle"], g.p["bar"], 60, "horizontal", g.v["saddle_bar_reach_h"]), "Fit"),
    DimDef("nose_to_bar", "Saddle nose to bar", "linear", False,
           lambda g: _lin(g.p["saddle_nose"], g.p["bar"], 30), "Fit"),
    DimDef("bar_x", "Handlebar reach from BB", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["bar"], 160, "horizontal"), "Fit"),
    DimDef("bar_y", "Handlebar stack from BB", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["bar"], 120, "vertical"), "Fit"),
    DimDef("hand_x", "Hand reach from BB", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["hand"], 200, "horizontal"), "Fit"),
    DimDef("hand_y", "Hand stack from BB", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["hand"], 160, "vertical"), "Fit"),
    DimDef("stem", "Stem length", "linear", False,
           lambda g: _lin(g.p["stem_clamp"], g.p["bar"], 30), "Cockpit"),
    DimDef("crank", "Crank length", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["pedal"], 20), "Drivetrain"),
    DimDef("ss_len", "Seat stay length", "linear", False,
           lambda g: _lin(g.p["rear_axle"], g.p["ss_top"], 35)),
    DimDef("stack_headset", "Stack to top of headset", "linear", False,
           lambda g: _lin(g.p["bb"], g.p["headset_top"], 110, "vertical")),
    DimDef("tandem_bb", "Captain BB to stoker BB", "linear", False,
           lambda g: _lin(g.p["drive_bb"], g.p["bb"], -60, "horizontal"), "Tandem"),
    DimDef("rear_wheel", "Rear wheel diameter", "linear", False,
           lambda g: _lin(g.p["rear_axle"] - V(0, g.wheels["rear"].outer_r),
                          g.p["rear_axle"] + V(0, g.wheels["rear"].outer_r),
                          -g.wheels["rear"].outer_r - 25, "vertical"), "Wheels"),
    DimDef("front_wheel", "Front wheel diameter", "linear", False,
           lambda g: _lin(g.p["front_axle"] - V(0, g.wheels["front"].outer_r),
                          g.p["front_axle"] + V(0, g.wheels["front"].outer_r),
                          g.wheels["front"].outer_r + 25, "vertical"), "Wheels"),
    DimDef("ht_tt_angle", "Head tube / top tube angle", "angle", False,
           lambda g: _ang(g.p["tt_ht"], g.u.angle(), _span(g.u.angle(), (g.p["tt_st"] - g.p["tt_ht"]).angle()),
                          45, g.v["angle_ht_tt"]), "Joints"),
    DimDef("st_tt_angle", "Seat tube / top tube angle", "angle", False,
           lambda g: _ang(g.p["tt_st"], (g.s * -1).angle(),
                          _span((g.s * -1).angle(), (g.p["tt_ht"] - g.p["tt_st"]).angle()), 45, g.v["angle_st_tt"]),
           "Joints"),
]
BY_ID = {d.id: d for d in CATALOG}
DEFAULT_VISIBLE = [d.id for d in CATALOG if d.default]

USER_KINDS = (("aligned", "Aligned distance"), ("horizontal", "Horizontal distance"),
              ("vertical", "Vertical distance"), ("angle3", "Angle at middle point"),
              ("angle_h", "Angle from horizontal"))


def visible_ids(g: Geometry) -> list[str]:
    ids = g.design.extras.get("visible_dimensions")
    return list(DEFAULT_VISIBLE if ids is None else ids)


def resolve(g: Geometry, spec) -> V:
    if isinstance(spec, str):
        return g.p[spec]
    if isinstance(spec, dict):
        if "point" in spec:
            return g.p[spec["point"]] + V(float(spec.get("dx", 0)), float(spec.get("dy", 0)))
        if "tube" in spec:                         # a position along a tube (incl. extra tubes)
            from .solver import _resolve_point
            return _resolve_point(g, spec)
        return V(float(spec["x"]), float(spec["y"]))
    return V(float(spec[0]), float(spec[1]))


def format_value(value: float, kind: str, units: str) -> str:
    return fmt_angle(value) if kind == "angle" else fmt_len(value, units)


def measure(g: Geometry, dim_id: str) -> float:
    d = BY_ID[dim_id]
    return d.build(g)["value"]


def build_user(g: Geometry, ud: dict) -> tuple[str, dict] | None:
    """Return (kind, kwargs) for a user dimension, or None if it can't be built."""
    try:
        pts = [resolve(g, s) for s in ud.get("points", [])]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    k = ud.get("kind", "aligned")
    off = float(ud.get("offset", 30))
    if k in ("aligned", "horizontal", "vertical") and len(pts) >= 2:
        return "linear", _lin(pts[0], pts[1], off, k)
    if k == "angle3" and len(pts) >= 3:
        a0 = (pts[0] - pts[1]).angle()
        a1 = (pts[2] - pts[1]).angle()
        span = (a1 - a0 + 540) % 360 - 180
        return "angle", _ang(pts[1], a0, span, abs(off) or 40, abs(span))
    if k == "angle_h" and len(pts) >= 2:
        a = (pts[1] - pts[0]).angle()
        span = (a + 540) % 360 - 180
        if abs(span) > 90:
            start, span = 180.0, (a - 180 + 540) % 360 - 180
        else:
            start = 0.0
        return "angle", _ang(pts[0], start, span, abs(off) or 40, abs(span))
    return None
