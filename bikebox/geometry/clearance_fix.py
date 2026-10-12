"""Automatic tire-clearance fixes.

For every tire interference reported by :mod:`clearance` this finds the
smallest change that clears it (to the design's minimum tire clearance plus a
small margin) without creating a new clearance problem, trying the least
intrusive remedies first:

* chainstay to tire / chainring / crank (solved together, cheapest first): crimped
  (narrower) stays near the BB, a wider chainline, an outward top-view bend, a
  chainstay yoke, and only then longer chainstays
* seat tube to tire: longer chainstays (or a bigger tire gap in that mode)
* seat stay to tire: wider seat-stay spread
* fork crown to tire / fender / bottomed out: longer axle-to-crown, shortening the
  head tube by the same amount when that keeps stack and reach
* fork blade to tire: wider crown spacing
* bridges: move them clear of the tire (or automatic placement)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..model.design import Design
from . import clearance as C
from .solver import Geometry, solve

MARGIN = 1.0               # mm above the minimum clearance
WATCH = ("wheelbase", "chainstay_length", "stack", "reach", "front_center", "trail", "head_tube_length",
         "bb_height", "head_tube_angle")
WATCH_LABELS = {"wheelbase": "Wheelbase", "chainstay_length": "Chainstay", "stack": "Stack", "reach": "Reach",
                "front_center": "Front centre", "trail": "Trail", "head_tube_length": "Head tube",
                "bb_height": "BB height", "head_tube_angle": "Head angle"}


@dataclass
class Fix:
    key: str                      # clearance key that was fixed
    problem: str                  # human label of the clearance
    label: str                    # what the fix does
    changes: dict[str, Any]
    before: float
    after: float
    side_effects: list[str] = field(default_factory=list)


@dataclass
class Plan:
    fixes: list[Fix]
    remaining: list[str]          # problems that couldn't be fixed
    design: Design                # the design with every fix applied


def tire_problems(g: Geometry) -> dict[str, float]:
    vals = C.clearances(g)
    return {k: vals[k] for k in C.TIRE_KEYS if k in vals and C.is_problem(g, k, vals[k])}


def _target(g: Geometry, key: str) -> float:
    return (C.threshold(g, key) or 0.0) + MARGIN


def _problem_set(g: Geometry) -> set[str]:
    vals = C.clearances(g)
    return {k for k, v in vals.items() if C.is_problem(g, k, v)}


# --------------------------------------------------------------------------
# strategies: (description, change(design, geometry, t) -> dict) with t in [0, 1]
# --------------------------------------------------------------------------
Change = Callable[[Design, Geometry, float], dict[str, Any]]


def _cs_bend(d, g, t):
    cur = d.f("cs_top_bend") if d["cs_top_bend_style"] != "straight" else 0.0
    return {"cs_top_bend_style": "bent", "cs_top_bend": cur + (max(cur, 0.0) + 12.0 - cur) * t}


def _cs_yoke(d, g, t):
    tire = d.f("rear_tire_width")
    lo = max(d.f("cs_yoke_spread") if d["cs_yoke"] else 0.0, tire + d.f("cs_od_bb") + 8)
    return {"cs_yoke": True, "cs_yoke_length": 115.0, "cs_yoke_spread": lo + 40.0 * t}


def _cs_longer(d, g, t):
    if d["cs_mode"] == "tire_gap":
        return {"rear_tire_gap": d.f("rear_tire_gap") + 60.0 * t}
    return {"chainstay_length": d.f("chainstay_length") + 60.0 * t}


def _ss_spread(d, g, t):
    cur = g.v.get("ss_spread_top", d.f("ss_spread_top"))
    return {"ss_spread_top": cur + 50.0 * t}


def _fork_longer(d, g, t):
    delta = 60.0 * t
    out = {"fork_length": d.f("fork_length") + delta}
    if d["front_v_mode"] == "ht_length" and d.f("head_tube_length") - delta >= 90.0:
        out["head_tube_length"] = d.f("head_tube_length") - delta      # keeps stack and reach
    return out


def _crown_wider(d, g, t):
    return {"fork_crown_width": d.f("fork_crown_width") + 60.0 * t}


def _cs_bridge(d, g, t):
    cur = g.v.get("cs_bridge_pos", d.f("cs_bridge_pos"))
    return {"cs_bridge_pos": max(cur - 150.0 * t, 30.0)}


def _ss_bridge(d, g, t):
    from .vec import V
    ss = g.tubes.get("ss")
    cur = d.f("ss_bridge_pos") or (g.wheels["rear"].outer_r + 12.0)
    hi = ss.length if ss is not None else cur + 150
    return {"ss_bridge_pos": min(cur + 150.0 * t, hi)}


STRATEGIES: dict[str, list[tuple[str, Change]]] = {
    "st_tire": [("lengthen the chainstays", _cs_longer)],
    "ss_tire": [("widen the seat-stay spread", _ss_spread)],
    "fork_crown_tire": [("use a longer axle-to-crown", _fork_longer)],
    "fork_crown_tire_bottomed": [("use a longer axle-to-crown", _fork_longer)],
    "fork_crown_fender": [("use a longer axle-to-crown", _fork_longer)],
    "fork_blade_tire": [("widen the fork crown", _crown_wider)],
    "cs_bridge_tire": [("move the chainstay bridge forward", _cs_bridge)],
    "ss_bridge_tire": [("move the seat-stay bridge up", _ss_bridge)],
}


def _apply(d: Design, changes: dict[str, Any]) -> Design:
    d2 = d.copy()
    d2.update(changes)
    return d2


def _value(g: Geometry, key: str) -> float:
    return C.clearances(g).get(key, float("nan"))


def _search(d: Design, g: Geometry, key: str, change: Change, allowed: set[str]) -> tuple[dict, Geometry] | None:
    """Smallest t in (0, 1] for which ``key`` clears without new problems."""
    target = _target(g, key)

    def ok(t):
        ch = change(d, g, t)
        g2 = solve(_apply(d, ch))
        v = _value(g2, key)
        good = v == v and v >= target and _problem_set(g2) <= allowed
        return good, ch, g2

    good, ch, g2 = ok(1.0)
    if not good:
        return None
    lo, hi, best = 0.0, 1.0, (ch, g2)
    for _ in range(14):
        mid = (lo + hi) / 2
        good, ch, g2 = ok(mid)
        if good:
            hi, best = mid, (ch, g2)
        else:
            lo = mid
    return best


def _round(changes: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in changes.items():
        out[k] = round(v + 0.049, 1) if isinstance(v, float) else v      # round up to 0.1 mm
    return out


REAR_KEYS = ("cs_tire", "cs_chainring", "cs_crank")


def _rear_base(d: Design, g: Geometry, ch_extra: dict[str, Any]) -> dict[str, Any]:
    return dict(ch_extra)


def _fix_rear(d: Design, g: Geometry, allowed: set[str]):
    """Cheapest combination that clears every rear-end clearance.

    For each combination of crimp / chainline / yoke / chainstay length (in
    order of cost) the smallest outward bend that clears the tire is found by
    bisection (tire clearance grows with outward bend, chainring and crank
    clearance shrink), then the chainring and crank are checked.  Costs: crimp
    0.2/mm, bend 0.3/mm, chainline 1.5/mm, yoke 6, chainstay 1/mm."""
    targets = {k: (C.threshold(g, k) or 0.0) + (MARGIN if k in C.TIRE_KEYS else 0.0) for k in REAR_KEYS}
    allowed = allowed - set(REAR_KEYS)
    width0 = d.f("cs_width_bb") or d.f("cs_od_bb")
    style = "bent" if d["cs_top_bend_style"] == "straight" else d["cs_top_bend_style"]
    bend0 = d.f("cs_top_bend") if d["cs_top_bend_style"] != "straight" else 0.0
    combos = []
    for crimp in (0, 2, 4, 6):
        if crimp and width0 - crimp < 10:
            continue
        for dcl in (0, 1, 2, 3, 4):
            for yoke in (False, True):
                if yoke and d["cs_yoke"]:
                    continue
                for dcs in (0, 5, 10, 15, 20, 30, 40, 60):
                    base = 0.2 * crimp + 1.5 * dcl + (6 if yoke else 0) + dcs
                    ch: dict[str, Any] = {}
                    if crimp:
                        ch["cs_width_bb"] = width0 - crimp
                    if dcl:
                        ch["chainline"] = d.f("chainline") + dcl
                    if yoke:
                        ch.update({"cs_yoke": True, "cs_yoke_length": 115.0,
                                   "cs_yoke_spread": d.f("rear_tire_width") + d.f("cs_od_bb") + 14})
                    if dcs:
                        key = "rear_tire_gap" if d["cs_mode"] == "tire_gap" else "chainstay_length"
                        ch[key] = d.f(key) + dcs
                    combos.append((base, ch))
    combos.sort(key=lambda c: c[0])
    best = None

    def evaluate(ch, bend):
        full = dict(ch)
        if abs(bend - bend0) > 1e-9:
            full.update({"cs_top_bend_style": style, "cs_top_bend": round(bend, 1)})
        g2 = solve(_apply(d, full))
        return full, g2, C.rear_clearances(g2)

    for base, ch in combos:
        if best is not None and base >= best[0]:
            break
        lo, hi = bend0 - 6.0, bend0 + 12.0
        full, g2, vals = evaluate(ch, hi)
        if vals.get("cs_tire", -1e9) < targets["cs_tire"]:
            continue                                   # even the largest bend can't clear the tire
        full, g2, vals = evaluate(ch, lo)
        if vals.get("cs_tire", -1e9) < targets["cs_tire"]:
            for _ in range(7):                         # smallest bend that clears the tire (±0.15 mm)
                mid = (lo + hi) / 2
                _, _, v = evaluate(ch, mid)
                if v.get("cs_tire", -1e9) >= targets["cs_tire"]:
                    hi = mid
                else:
                    lo = mid
            bend = hi
        else:
            bend = lo if all(vals.get(k, 1e9) >= targets[k] for k in REAR_KEYS) else bend0
            if bend == bend0:
                bend = bend0                           # tire already clear: try keeping the bend
        full, g2, vals = evaluate(ch, round(bend + 0.049, 1))
        if all(vals.get(k, 1e9) >= targets[k] for k in REAR_KEYS) and _problem_set(g2) <= allowed:
            cost = base + 0.3 * abs(bend - bend0)
            if best is None or cost < best[0]:
                best = (cost, full, g2)
    return None if best is None else (best[1], best[2])


def _describe_rear(ch: dict[str, Any], d: Design) -> str:
    parts = []
    if "cs_width_bb" in ch:
        parts.append(f"crimp the chainstays to {ch['cs_width_bb']:.0f} mm wide at the BB")
    if "chainline" in ch:
        parts.append(f"widen the chainline to {ch['chainline']:.1f} mm")
    if "cs_top_bend" in ch:
        b0 = d.f("cs_top_bend") if d["cs_top_bend_style"] != "straight" else 0.0
        b = ch["cs_top_bend"]
        parts.append(f"change the chainstay top-view bend from {b0:+.1f} to {b:+.1f} mm "
                     f"({'more outward' if b > b0 else 'more inward'})")
    if "cs_yoke" in ch:
        parts.append("add a chainstay yoke")
    if "chainstay_length" in ch:
        parts.append(f"lengthen the chainstays to {ch['chainstay_length']:.0f} mm")
    if "rear_tire_gap" in ch:
        parts.append(f"increase the rear tire gap to {ch['rear_tire_gap']:.0f} mm")
    s = ", ".join(parts)
    return s[:1].upper() + s[1:]


def plan_fixes(design: Design, max_steps: int = 12) -> Plan:
    d = design.copy()
    fixes: list[Fix] = []
    unfixable: set[str] = set()
    g = solve(d)
    for _ in range(max_steps):
        probs = {k: v for k, v in tire_problems(g).items() if k not in unfixable}
        vals = C.clearances(g)
        rear_bad = [k for k in REAR_KEYS if k not in unfixable and C.is_problem(g, k, vals.get(k))]
        if rear_bad and (set(rear_bad) & set(probs) or not probs):
            allowed = _problem_set(g)
            res = _fix_rear(d, g, allowed)
            if res is None:
                unfixable.update(rear_bad)
                continue
            ch, g2 = res
            d2 = _apply(d, ch)
            effects = _effects(g, g2)
            key = min(rear_bad, key=lambda k: vals[k])
            name = " / ".join(C.LABELS.get(k, (k, "mm"))[0] for k in rear_bad)
            fixes.append(Fix(key, name, _describe_rear(ch, d), ch, vals[key], _value(g2, key), effects))
            d, g = d2, g2
            continue
        if not probs:
            break
        key = min(probs, key=lambda k: probs[k])          # worst first
        before = probs[key]
        allowed = _problem_set(g) - {key}
        done = False
        for label, change in STRATEGIES.get(key, []):
            res = _search(d, g, key, change, allowed)
            if res is None:
                continue
            changes = _round(res[0])
            if "fork_length" in changes and "head_tube_length" in changes:      # exact stack compensation
                changes["head_tube_length"] = d.f("head_tube_length") - (changes["fork_length"] - d.f("fork_length"))
            d2 = _apply(d, changes)
            g2 = solve(d2)
            if _value(g2, key) < _target(g, key) - MARGIN:      # rounding pushed it back under
                continue
            effects = _effects(g, g2)
            name = C.LABELS.get(key, (key, "mm"))[0]
            fixes.append(Fix(key, name, f"{label.capitalize()}: {_describe_changes(d, changes)}", changes, before,
                             _value(g2, key), effects))
            d, g = d2, g2
            done = True
            break
        if not done:
            unfixable.add(key)
    remaining = C.problems(g)
    return Plan(fixes, remaining, d)


def _describe_changes(d: Design, changes: dict[str, Any]) -> str:
    from ..model import params as P
    parts = []
    for k, v in changes.items():
        label = P.get(k).label if P.has(k) else k
        old = d.get(k)
        if isinstance(v, float) and isinstance(old, (int, float)):
            unit = "°" if P.has(k) and P.get(k).unit == "deg" else " mm"
            parts.append(f"{label.lower()} {old:.1f} → {v:.1f}{unit}")
        elif v != old:
            parts.append(f"{label.lower()} → {v}")
    if "head_tube_length" in changes and "fork_length" in changes:
        parts.append("(head tube shortened to keep stack and reach)")
    return ", ".join(parts)


def _effects(g: Geometry, g2: Geometry) -> list[str]:
    out = []
    for w in WATCH:
        a, b = g.v.get(w), g2.v.get(w)
        if a is not None and b is not None and abs(b - a) > 0.05:
            unit = "°" if w == "head_tube_angle" else " mm"
            out.append(f"{WATCH_LABELS[w]} {a:.1f} → {b:.1f}{unit}")
    return out


def merged_changes(fixes: list[Fix]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fixes:
        out.update(f.changes)
    return out
