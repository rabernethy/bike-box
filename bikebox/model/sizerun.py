"""Size-run generator: a family of frame sizes from one base design.

A builder or brand rarely makes a single frame — they make a size run. Given a
base design and a per-size list of driving dimensions (stack, reach, seat-tube
length, head-tube length…), this produces one :class:`Design` per size that
shares everything else with the base. The results feed the geometry comparison
chart (CSV) and the ghost overlay.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import params as P
from .design import Design

# the dimensions a size run usually varies, with sensible stack/reach front-end mode
DEFAULT_DRIVERS = ["seat_tube_length", "stack", "reach", "head_tube_length", "top_tube_effective"]


@dataclass
class SizeSpec:
    name: str
    overrides: dict = field(default_factory=dict)      # {param_key: value}


def generate(base: Design, sizes: list[SizeSpec]) -> list[tuple[str, Design]]:
    """One Design per size: a copy of ``base`` with that size's overrides applied.
    Setting stack/reach also switches the front end into stack+reach mode so the
    values take effect."""
    out: list[tuple[str, Design]] = []
    for spec in sizes:
        d = base.copy()
        ov = spec.overrides
        if "stack" in ov or "reach" in ov:
            d.set("front_v_mode", "stack")
            d.set("front_h_mode", "reach")
        if "top_tube_effective" in ov and "reach" not in ov:
            d.set("front_h_mode", "ett")
        for k, v in ov.items():
            if P.has(k) and v is not None and str(v) != "":
                try:
                    d.set(k, v)
                except (TypeError, ValueError):
                    pass
        out.append((spec.name, d))
    return out


def linear_run(base: Design, count: int, ranges: dict[str, tuple[float, float]],
               names: list[str] | None = None) -> list[SizeSpec]:
    """Build ``count`` size specs by linearly interpolating each driver in
    ``ranges`` ({key: (small, large)}) from the smallest to the largest size."""
    count = max(count, 1)
    default_names = names or _auto_names(count)
    specs: list[SizeSpec] = []
    for i in range(count):
        f = i / (count - 1) if count > 1 else 0.0
        ov = {k: round(lo + (hi - lo) * f, 1) for k, (lo, hi) in ranges.items()}
        specs.append(SizeSpec(default_names[i] if i < len(default_names) else f"Size {i + 1}", ov))
    return specs


def _auto_names(count: int) -> list[str]:
    presets = {1: ["M"], 2: ["S", "L"], 3: ["S", "M", "L"], 4: ["XS", "S", "M", "L"],
               5: ["XS", "S", "M", "L", "XL"], 6: ["XS", "S", "M", "L", "XL", "XXL"],
               7: ["XXS", "XS", "S", "M", "L", "XL", "XXL"]}
    return presets.get(count, [f"Size {i + 1}" for i in range(count)])


def suggest_ranges(base: Design) -> dict[str, tuple[float, float]]:
    """A starting ±spread around the base for the common drivers, so the dialog
    opens with a plausible run the user can edit."""
    from ..geometry.solver import solve
    g = solve(base)
    st = base.f("seat_tube_length")
    stack = g.v.get("stack", base.f("stack") if P.has("stack") else 560)
    reach = g.v.get("reach", base.f("reach") if P.has("reach") else 390)
    return {"seat_tube_length": (st - 60, st + 60),
            "stack": (stack - 40, stack + 50),
            "reach": (reach - 25, reach + 25)}
