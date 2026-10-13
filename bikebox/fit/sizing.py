"""Fit-to-rider sizing: pick the frame size that best matches a rider.

Uses the fit advisor to get the rider's target stack & reach from their body
measurements and chosen scheme, then scores candidate sizes by how close their
front-end lands, with a standover feasibility check.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import advisor
from ..geometry.solver import solve


@dataclass
class SizeScore:
    name: str
    stack: float
    reach: float
    dist: float            # mm from the rider's target stack/reach
    standover_ok: bool


@dataclass
class SizeRecommendation:
    best: str | None
    target_stack: float | None
    target_reach: float | None
    scores: list[SizeScore]
    note: str = ""


def rider_target(design, scheme: str | None = None) -> tuple[float | None, float | None]:
    """The rider's recommended frame stack & reach (mm) from the fit scheme, or
    (None, None) if the scheme doesn't resolve them (e.g. no rider measurements)."""
    name = scheme or design.get("fit_scheme") or "Classic road"
    try:
        recs = advisor.evaluate(name, design)
    except Exception:
        return (None, None)
    by = {r.param: r.value for r in recs if r.param}
    return (by.get("stack"), by.get("reach"))


def recommend(design, sizes: list[tuple[str, object]], scheme: str | None = None,
              standover_clear: float = 25.0) -> SizeRecommendation:
    """Best of ``sizes`` (name, Design) for the rider described by ``design``."""
    ts, tr = rider_target(design, scheme)
    inseam = design.f("inseam") if design.f("inseam") > 0 else 0.47 * design.f("rider_height")
    scores: list[SizeScore] = []
    for name, d in sizes:
        try:
            g = solve(d)
        except Exception:
            continue
        stack, reach = g.v.get("stack", 0.0), g.v.get("reach", 0.0)
        dist = math.hypot(stack - ts, reach - tr) if (ts and tr) else float("nan")
        so = g.v.get("standover_min", g.v.get("standover", 0.0))
        standover_ok = (so <= inseam - standover_clear) if inseam else True
        scores.append(SizeScore(name, stack, reach, dist, standover_ok))
    if not (ts and tr) or not scores:
        return SizeRecommendation(None, ts, tr, scores,
                                  "Enter the rider's measurements (height/inseam) to get a size recommendation.")
    # prefer a size that also clears standover; among those, the closest front end
    ok = [s for s in scores if s.standover_ok]
    pool = ok or scores
    best = min(pool, key=lambda s: s.dist)
    note = "" if ok else "No size clears standover for this rider; showing the closest front-end match."
    return SizeRecommendation(best.name, ts, tr, scores, note)
