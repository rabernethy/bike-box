"""Options for resolving geometry and clearance issues.

Where :mod:`clearance_fix` produces one automatic cheapest-first plan, this
module enumerates, for every issue in the current design, *several* independent
ways to address it.  Each option is solved and measured so the user can see
what it does to the clearance and to the rest of the geometry, then pick the
one they want.

An issue is a clearance below its threshold (tire, chainring, crank, heel, toe)
or a geometry warning the solver raises (seatpost insertion too shallow, top and
down tube overlapping on the head tube).  Each option is a concrete set of
parameter changes, found by searching the smallest change on one knob that
clears the issue, plus the resulting clearance, the effect on the watched
geometry numbers, and any new problem the change would introduce.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..model.design import Design
from . import clearance as C
from .clearance_fix import (MARGIN, WATCH, WATCH_LABELS, _apply, _describe_changes, _describe_rear, _effects,
                            _fix_rear, _round, _value)
from .solver import Geometry, solve

Change = Callable[[Design, Geometry, float], dict[str, Any]]


@dataclass
class Option:
    label: str                      # short name of the remedy
    detail: str                     # the parameter changes in words
    changes: dict[str, Any]
    after_text: str                 # the issue metric after this change
    resolves: bool                  # clears the issue on its own
    side_effects: list[str] = field(default_factory=list)   # watched geometry deltas
    new_problems: list[str] = field(default_factory=list)   # issues this change would introduce


@dataclass
class Issue:
    key: str
    label: str                      # e.g. "Seat tube to tire"
    message: str                    # current state, e.g. "1.9 mm (needs 6.0 mm)"
    options: list[Option] = field(default_factory=list)
    advice: str = ""                # shown when there are no automatic options


# --------------------------------------------------------------------------
# which issues are active, and how each is measured
# --------------------------------------------------------------------------
REAR_KEYS = ("cs_tire", "cs_chainring", "cs_crank")
TOE_KEYS = ("toe_steer_angle", "toe_clearance_3d")
HEEL_KEYS = ("heel", "heel_cs", "heel_ss")


def _insertion_short(g: Geometry) -> bool:
    return g.v.get("seatpost_insertion", 1e9) < g.design.f("seatpost_min_insertion")


def _ht_overlap(g: Geometry) -> bool:
    return g.v.get("ht_exposed", 1e9) < 0.0


def active_keys(g: Geometry) -> set[str]:
    """Every issue key that is currently a problem."""
    keys = {k for k, v in C.clearances(g).items() if C.is_problem(g, k, v)}
    if _insertion_short(g):
        keys.add("seatpost_insertion")
    if _ht_overlap(g):
        keys.add("ht_overlap")
    return keys


def _clearance_text(g: Geometry, key: str) -> str:
    if key == "toe_steer_angle":
        v = C.clearances(g).get(key)
        return "no overlap" if v is None or v != v or v == float("inf") else f"overlap at {v:.1f}°"
    if key == "seatpost_insertion":
        return f"{g.v.get('seatpost_insertion', 0):.0f} mm"
    if key == "ht_overlap":
        gap = g.v.get("ht_exposed", 0)
        return f"overlap {-gap:.0f} mm" if gap < 0 else f"{gap:.0f} mm clear"
    v = C.clearances(g).get(key, float("nan"))
    unit = C.LABELS.get(key, ("", "mm"))[1]
    return f"{v:.1f}°" if unit == "deg" else f"{v:.1f} mm"


def _target_text(g: Geometry, key: str) -> str:
    if key in ("toe_steer_angle", "toe_clearance_3d"):
        return "no overlap"
    if key == "ht_overlap":
        return "no overlap"
    if key == "seatpost_insertion":
        return f"≥ {g.design.f('seatpost_min_insertion'):.0f} mm"
    lim = C.threshold(g, key)
    if lim is None:
        return ""
    return f"≥ {lim + (MARGIN if key in C.TIRE_KEYS else 0):.0f} mm"


def _key_ok(g2: Geometry, key: str) -> bool:
    """A single issue key is resolved.  Tire clearances must reach the threshold
    plus the same margin the advertised target and the auto-planner use; other
    clearances just need to stop being a problem."""
    if key == "seatpost_insertion":
        return not _insertion_short(g2)
    if key == "ht_overlap":
        return g2.v.get("ht_exposed", 1e9) >= 0.0
    if key in C.TIRE_KEYS:
        v = C.clearances(g2).get(key, float("nan"))
        return v == v and v >= (C.threshold(g2, key) or 0.0) + MARGIN
    return not C.is_problem(g2, key)


def _resolved_fn(group: tuple[str, ...]):
    """A predicate: every key in ``group`` is resolved."""
    def ok(g2: Geometry) -> bool:
        return all(_key_ok(g2, k) for k in group)
    return ok


# --------------------------------------------------------------------------
# knobs: a single adjustment, linear in t, in the helpful direction
# --------------------------------------------------------------------------
def _cs_longer(d, g, t):
    if d["cs_mode"] == "tire_gap":
        return {"rear_tire_gap": d.f("rear_tire_gap") + 80.0 * t}
    return {"chainstay_length": d.f("chainstay_length") + 80.0 * t}


def _ss_spread(d, g, t):
    cur = g.v.get("ss_spread_top", d.f("ss_spread_top"))
    return {"ss_spread_top": cur + 60.0 * t}


def _fork_longer(d, g, t):
    delta = 70.0 * t
    out = {"fork_length": d.f("fork_length") + delta}
    if d["front_v_mode"] == "ht_length" and d.f("head_tube_length") - delta >= 90.0:
        out["head_tube_length"] = d.f("head_tube_length") - delta      # keeps stack and reach
    return out


def _fork_longer_plain(d, g, t):
    return {"fork_length": d.f("fork_length") + 70.0 * t}


def _crown_wider(d, g, t):
    return {"fork_crown_width": d.f("fork_crown_width") + 70.0 * t}


def _cs_bridge(d, g, t):
    cur = g.v.get("cs_bridge_pos", d.f("cs_bridge_pos"))
    return {"cs_bridge_pos": max(cur - 180.0 * t, 25.0)}


def _ss_bridge(d, g, t):
    ss = g.tubes.get("ss")
    cur = d.f("ss_bridge_pos") or (g.wheels["rear"].outer_r + 12.0)
    hi = ss.length if ss is not None else cur + 180
    return {"ss_bridge_pos": min(cur + 180.0 * t, hi)}


def _narrow(prefix: str) -> Change:
    def knob(d, g, t):
        w = d.f(f"{prefix}_tire_width")
        nw = max(w - 20.0 * t, 18.0)
        out = {f"{prefix}_tire_width": nw}
        h = d.f(f"{prefix}_tire_height")
        if h > 0:
            out[f"{prefix}_tire_height"] = max(h - 20.0 * t, 16.0)
        return out
    return knob


def _front_longer(d, g, t):
    hm = d["front_h_mode"]
    if hm == "front_center":
        return {"front_center": d.f("front_center") + 90.0 * t}
    if hm == "wheelbase":
        return {"wheelbase": d.f("wheelbase") + 90.0 * t}
    key = "top_tube_effective" if hm == "ett" else "reach"
    return {key: d.f(key) + 90.0 * t}


def _hta_slacker(d, g, t):
    return {"head_tube_angle": d.f("head_tube_angle") - 5.0 * t}


def _more_offset(d, g, t):
    return {"fork_offset": d.f("fork_offset") + 25.0 * t}


def _shorter_crank(d, g, t):
    return {"crank_length": max(d.f("crank_length") - 22.5 * t, 150.0)}


def _wider_q(d, g, t):
    return {"q_factor": d.f("q_factor") + 30.0 * t}


def _st_longer(d, g, t):
    return {"seat_tube_length": d.f("seat_tube_length") + 70.0 * t}


def _saddle_lower(d, g, t):
    return {"saddle_height": max(d.f("saddle_height") - 50.0 * t, 200.0)}


def _ht_longer(d, g, t):
    return {"head_tube_length": d.f("head_tube_length") + 60.0 * t}


def _ht_offsets_smaller(d, g, t):
    return {"tt_ht_offset": d.f("tt_ht_offset") * (1 - t), "dt_ht_offset": d.f("dt_ht_offset") * (1 - t)}


# per-issue remedies: (label, knob, t_max).  Order is the presentation order.
REMEDIES: dict[str, list[tuple[str, Change, float]]] = {
    "st_tire": [("Lengthen the chainstays", _cs_longer, 3.0),
                ("Use a narrower rear tire", _narrow("rear"), 1.0)],
    "ss_tire": [("Widen the seat-stay spread", _ss_spread, 3.0),
                ("Use a narrower rear tire", _narrow("rear"), 1.0)],
    "cs_bridge_tire": [("Move the chainstay bridge forward", _cs_bridge, 1.0),
                       ("Use a narrower rear tire", _narrow("rear"), 1.0)],
    "ss_bridge_tire": [("Move the seat-stay bridge up", _ss_bridge, 1.0),
                       ("Use a narrower rear tire", _narrow("rear"), 1.0)],
    "fork_crown_tire": [("Use a longer axle-to-crown (keep stack/reach)", _fork_longer, 2.0),
                        ("Use a longer axle-to-crown", _fork_longer_plain, 2.0),
                        ("Use a narrower front tire", _narrow("front"), 1.0)],
    "fork_crown_tire_bottomed": [("Use a longer axle-to-crown (keep stack/reach)", _fork_longer, 2.0),
                                 ("Use a narrower front tire", _narrow("front"), 1.0)],
    "fork_crown_fender": [("Use a longer axle-to-crown (keep stack/reach)", _fork_longer, 2.0),
                          ("Use a narrower front tire", _narrow("front"), 1.0)],
    "fork_blade_tire": [("Widen the fork crown", _crown_wider, 2.0),
                        ("Use a narrower front tire", _narrow("front"), 1.0)],
    "toe": [("Lengthen the front centre", _front_longer, 3.0),
            ("Slacken the head angle", _hta_slacker, 2.0),
            ("Add fork offset (rake)", _more_offset, 2.0),
            ("Use a shorter crank", _shorter_crank, 1.0),
            ("Use a narrower front tire", _narrow("front"), 1.0)],
    "heel": [("Widen the Q-factor", _wider_q, 2.0)],
    "seatpost_insertion": [("Lengthen the seat tube", _st_longer, 3.0),
                           ("Lower the saddle", _saddle_lower, 2.0)],
    "ht_overlap": [("Lengthen the head tube", _ht_longer, 2.0),
                   ("Reduce the tube/head-tube offsets", _ht_offsets_smaller, 1.0)],
}

ADVICE = {
    "lug_angle": "Change the frame angle to match the lugset, or set the lugset angle to the frame — both under "
                 "Joints.",
    "bend_radius": "Reduce the tube's bend (sagitta) or use a larger-diameter tube.",
    "short_tube": "Lengthen the tube or move the junction it meets.",
    "rail_adjust": "Fit a seatpost with a setback closer to what the saddle needs (Seatpost).",
}


def _new_problems(g0: Geometry, g2: Geometry, own: tuple[str, ...]) -> list[str]:
    before = active_keys(g0)
    out = []
    for k in sorted(active_keys(g2) - before):
        if k in own:
            continue
        label = {"seatpost_insertion": "Seatpost insertion", "ht_overlap": "Head-tube tube overlap"}.get(
            k) or C.LABELS.get(k, (k, ""))[0]
        out.append(label)
    return out


def _bisect(d: Design, g: Geometry, knob: Change, resolved, t_max: float):
    """Smallest t in (0, t_max] whose change resolves the issue, or None."""
    if not resolved(solve(_apply(d, knob(d, g, t_max)))):
        return None
    lo, hi = 0.0, t_max
    for _ in range(12):
        mid = (lo + hi) / 2
        if resolved(solve(_apply(d, knob(d, g, mid)))):
            hi = mid
        else:
            lo = mid
    # round the parameters up and make sure the rounding didn't drop back under
    for scale in (1.0, 1.05, 1.12, 1.25):
        changes = _round(knob(d, g, min(hi * scale, t_max)))
        g2 = solve(_apply(d, changes))
        if resolved(g2):
            return changes, g2
        if hi * scale >= t_max:
            break
    return None


def _option(d: Design, g0: Geometry, label: str, changes: dict, g2: Geometry, group: tuple[str, ...],
            metric_key: str) -> Option:
    if "fork_length" in changes and "head_tube_length" in changes:
        changes["head_tube_length"] = round(d.f("head_tube_length") - (changes["fork_length"] - d.f("fork_length")),
                                             1)
        g2 = solve(_apply(d, changes))
    return Option(label=label, detail=_describe_changes(d, changes), changes=changes,
                  after_text=_clearance_text(g2, metric_key), resolves=True,
                  side_effects=_effects(g0, g2), new_problems=_new_problems(g0, g2, group))


def _dedupe(options: list[Option]) -> list[Option]:
    seen, out = set(), []
    for o in options:
        sig = tuple(sorted((k, round(v, 2) if isinstance(v, float) else v) for k, v in o.changes.items()))
        if sig and sig not in seen:
            seen.add(sig)
            out.append(o)
    return out


def _issue(d: Design, g0: Geometry, key: str, group: tuple[str, ...], label: str, metric_key: str) -> Issue:
    msg = f"{_clearance_text(g0, metric_key)} (want {_target_text(g0, metric_key)})"
    iss = Issue(key=key, label=label, message=msg)
    resolved = _resolved_fn(group)
    for lbl, knob, t_max in REMEDIES.get(key, []):
        res = _bisect(d, g0, knob, resolved, t_max)
        if res is not None:
            iss.options.append(_option(d, g0, lbl, res[0], res[1], group, metric_key))
    iss.options = _dedupe(iss.options)
    return iss


def find_issues(design: Design) -> list[Issue]:
    """Every current issue, each with the options that resolve it."""
    d = design.copy()
    g0 = solve(d)
    active = active_keys(g0)
    issues: list[Issue] = []

    # rear end (chainstay to tire / chainring / crank): one issue, combined remedies
    rear = tuple(k for k in REAR_KEYS if k in active)
    if rear:
        label = " / ".join(C.LABELS[k][0] for k in rear)
        worst = min(rear, key=lambda k: C.clearances(g0).get(k, 1e9))
        iss = Issue(key="rear_end", label=label,
                    message=f"{_clearance_text(g0, worst)} (want {_target_text(g0, worst)})")
        res = _fix_rear(d, g0, active)
        resolved = _resolved_fn(rear)
        if res is not None:
            ch, g2 = _round(res[0]), None
            g2 = solve(_apply(d, ch))
            if resolved(g2):
                iss.options.append(Option("Reshape the rear end", _describe_rear(ch, d), ch,
                                          _clearance_text(g2, worst), True, _effects(g0, g2),
                                          _new_problems(g0, g2, rear)))
        for lbl, knob in (("Lengthen the chainstays", _cs_longer), ("Use a narrower rear tire", _narrow("rear"))):
            r = _bisect(d, g0, knob, resolved, 3.0 if knob is _cs_longer else 1.0)
            if r is not None:
                iss.options.append(_option(d, g0, lbl, r[0], r[1], rear, worst))
        iss.options = _dedupe(iss.options)
        issues.append(iss)

    # toe overlap: one issue
    toe = tuple(k for k in TOE_KEYS if k in active)
    if toe:
        issues.append(_issue(d, g0, "toe", toe, "Toe to front tire", "toe_steer_angle"
                             if "toe_steer_angle" in toe else "toe_clearance_3d"))

    # heel: one issue
    heel = tuple(k for k in HEEL_KEYS if k in active)
    if heel:
        worst = min(heel, key=lambda k: C.clearances(g0).get(k, 1e9))
        issues.append(_issue(d, g0, "heel", heel, " / ".join(C.LABELS[k][0] for k in heel), worst))

    # remaining single-key clearance issues
    done = set(REAR_KEYS) | set(TOE_KEYS) | set(HEEL_KEYS)
    for key in sorted(active - done - {"seatpost_insertion", "ht_overlap"}):
        issues.append(_issue(d, g0, key, (key,), C.LABELS.get(key, (key, ""))[0], key))

    # geometry warnings
    if "seatpost_insertion" in active:
        issues.append(_issue(d, g0, "seatpost_insertion", ("seatpost_insertion",), "Seatpost insertion too shallow",
                             "seatpost_insertion"))
    if "ht_overlap" in active:
        issues.append(_issue(d, g0, "ht_overlap", ("ht_overlap",), "Top & down tube overlap on the head tube",
                             "ht_overlap"))

    # issues we can detect but not auto-fix: attach advice so the dialog still lists them
    for iss in issues:
        if not iss.options:
            iss.advice = ADVICE.get(iss.key, "No automatic option; adjust the relevant parameters by hand.")
    return issues


def apply_choices(design: Design, chosen: list[Option]) -> dict[str, Any]:
    """Merge the changes of the chosen options (later options win on a shared key)."""
    out: dict[str, Any] = {}
    for o in chosen:
        out.update(o.changes)
    return out
