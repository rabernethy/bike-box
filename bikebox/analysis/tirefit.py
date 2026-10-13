"""Maximum tire size: the widest tire that still clears everywhere.

Answers the common builder/buyer question "what's the biggest tire I can run?"
by growing the tire (width and height together, keeping the aspect) until a
frame/fork clearance drops to its minimum.
"""
from __future__ import annotations

from ..geometry import clearance as C
from ..geometry.solver import solve

REAR_KEYS = ("cs_tire", "ss_tire", "st_tire", "cs_bridge_tire", "ss_bridge_tire")
FRONT_KEYS = ("fork_crown_tire", "fork_crown_tire_bottomed", "fork_crown_fender", "fork_blade_tire")


def _clears(g, keys) -> bool:
    vals = C.clearances(g)
    return not any(C.is_problem(g, k, vals.get(k)) for k in keys)


def max_tire_width(design, end: str, hi: float = 120.0) -> dict:
    """Largest ``end`` ('rear'/'front') tire width (mm) that still clears.

    Returns {width, limited_by} or {} if even the current tire doesn't clear.
    Width and height grow together (constant aspect from the current tire).
    """
    keys = REAR_KEYS if end == "rear" else FRONT_KEYS
    w0 = design.f(f"{end}_tire_width")
    h0 = design.f(f"{end}_tire_height")
    aspect = (h0 / w0) if w0 > 0 else 0.9

    def probe(w: float):
        d = design.copy()
        d.set(f"{end}_tire_width", w)
        d.set(f"{end}_tire_height", round(w * aspect, 2))
        return solve(d)

    if not _clears(probe(w0), keys):
        return {}                                   # current tire already interferes
    lo = w0
    if _clears(probe(hi), keys):
        return {"width": hi, "limited_by": "search limit"}
    for _ in range(18):
        mid = (lo + hi) / 2
        if _clears(probe(mid), keys):
            lo = mid
        else:
            hi = mid
    g = probe(lo)
    vals = C.clearances(g)
    thr = {k: (C.threshold(g, k) or 0.0) for k in keys}
    tight = min((k for k in keys if k in vals), key=lambda k: vals[k] - thr[k], default="")
    return {"width": round(lo, 1), "limited_by": C.LABELS.get(tight, (tight, ""))[0]}


def summary(g) -> dict:
    return {"rear": max_tire_width(g.design, "rear"), "front": max_tire_width(g.design, "front")}
