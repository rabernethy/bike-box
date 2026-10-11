"""Switching between equivalent ways of specifying a dimension.

Several parts of a design can be driven by different measurements (BB drop
or BB height, head tube length or stack, reach or front centre ...).  When the
user switches mode, the newly driving parameter is filled in from the current
solved geometry so the bike does not move: only *how* it is specified changes.

:func:`mode_switch_values` returns every parameter to set (including the mode
itself) so the GUI can apply them as one undo step.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from ..model.design import Design
from .solver import Geometry, solve

# mode parameter -> {mode value -> function(design, geometry) -> {param: value}}
_Rule = Callable[[Design, Geometry], dict[str, Any]]


def _saddle_height_angle(d: Design, g: Geometry) -> dict[str, Any]:
    S = g.p["saddle"]
    eff = g.v["seat_angle_eff"]
    out: dict[str, Any] = {"saddle_height": S.length()}
    if abs(eff - d.f("seat_tube_angle")) < 1e-9:
        out["seat_angle_source"] = "seat_tube"
    else:
        out.update({"seat_angle_source": "custom", "seat_angle_eff": eff})
    return out


def _st_cc(d: Design, g: Geometry) -> dict[str, Any]:
    return {"seat_tube_length": g.v["seat_tube_cc"], "st_extension": g.v["st_extension"]}


def _st_ct(d: Design, g: Geometry) -> dict[str, Any]:
    out: dict[str, Any] = {"seat_tube_length": g.v["seat_tube_ct"]}
    if d["tt_mode"] == "st_extension":
        out["st_extension"] = g.v["st_extension"]
    return out


RULES: dict[str, dict[str, _Rule]] = {
    "bb_mode": {
        "drop": lambda d, g: {"bb_drop": g.v["bb_drop"]},
        "height": lambda d, g: {"bb_height": g.v["bb_height"]},
    },
    "cs_mode": {
        "length": lambda d, g: {"chainstay_length": g.v["chainstay_length"]},
        "tire_gap": lambda d, g: {"rear_tire_gap": g.v["rear_tire_gap"]},
    },
    "front_v_mode": {
        "ht_length": lambda d, g: {"head_tube_length": g.v["head_tube_length"]},
        "stack": lambda d, g: {"stack": g.v["stack"]},
        "bar_y": lambda d, g: {"bar_y": g.v["bar_y"]},
    },
    "front_h_mode": {
        "reach": lambda d, g: {"reach": g.v["reach"]},
        "front_center": lambda d, g: {"front_center": g.v["front_center"]},
        "ett": lambda d, g: {"top_tube_effective": g.v["top_tube_effective"]},
        "wheelbase": lambda d, g: {"wheelbase": g.v["wheelbase"]},
        "bar_x": lambda d, g: {"bar_x": g.v["bar_x"]},
    },
    "st_length_mode": {"ct": _st_ct, "cc": _st_cc},
    "tt_mode": {
        "angle": lambda d, g: {"top_tube_angle": g.v["top_tube_angle"]},
        "st_extension": lambda d, g: {"st_extension": g.v["st_extension"]},
    },
    "saddle_mode": {
        "xy": lambda d, g: {"saddle_x": g.p["saddle"].x, "saddle_y": g.p["saddle"].y},
        "height_angle": _saddle_height_angle,
    },
    "seat_angle_source": {
        "custom": lambda d, g: {"seat_angle_eff": g.v["seat_angle_eff"]},
        # back to "same as seat tube": keep the saddle's height above the BB
        "seat_tube": lambda d, g: {"saddle_height": g.p["saddle"].y / max(math.sin(math.radians(
            d.f("seat_tube_angle"))), 1e-6)},
    },
    "stem_type": {
        "quill": lambda d, g: {"quill_height": d.f("spacers") + d.f("stem_clamp_height") / 2},
        "threadless": lambda d, g: {"spacers": max(d.f("quill_height") - d.f("stem_clamp_height") / 2, 0.0)},
    },
}
MODE_KEYS = frozenset(RULES)


def mode_switch_values(design: Design, key: str, value: Any, geometry: Geometry | None = None) -> dict[str, Any]:
    """Parameters to set when ``key`` changes to ``value`` so the geometry is
    preserved.  Always includes ``{key: value}``; empty extras for keys that are
    not mode switches or when the value doesn't change."""
    out: dict[str, Any] = {key: value}
    rule = RULES.get(key, {}).get(str(value))
    if rule is None or design.get(key) == value:
        return out
    g = geometry or solve(design)
    try:
        extra = rule(design, g)
    except (KeyError, ZeroDivisionError, ValueError):
        return out
    out.update({k: v for k, v in extra.items() if not (isinstance(v, float) and (v != v or math.isinf(v)))})
    return out
