"""Checks against the commonly quoted UCI road-bicycle dimension rules.

The limits below are the well-known figures from the UCI Technical
Regulations (Part I, Chapter III "Equipment").  Regulations are revised from
time to time and some rules have exceptions and tolerances that are not
modelled here, so every result should be verified against the current edition
and the UCI's own clarification guide before a frame is built.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..geometry.solver import Geometry
from ..model import params as P
from ..model.units import fmt_len

SOURCE = ("UCI Technical Regulations, Part I Ch. 3 (Equipment) – verify against the current edition")

P.register([
    P.ParamDef("uci_morpho_exemption", "Morphological exemption claimed", "Analysis", "UCI", P.BOOL, False,
               help="The saddle-setback rule allows a closer saddle for morphological reasons under "
                    "conditions set by the regulations; tick to treat a setback between 0 and 5 cm as allowed",
               morph=False),
    P.ParamDef("uci_min_weight", "Minimum bicycle weight", "Analysis", "UCI", P.FLOAT, 6800.0, "g", 0, 20000, 10,
               help="Check the figure in the current regulations"),
])


@dataclass
class Rule:
    id: str
    title: str
    measured: str
    limit: str
    status: str          # "pass" | "fail" | "warn" | "n/a"
    note: str = ""


def _range(value: float, lo: float | None, hi: float | None) -> str:
    if value != value:
        return "n/a"
    if lo is not None and value < lo - 1e-9:
        return "fail"
    if hi is not None and value > hi + 1e-9:
        return "fail"
    return "pass"


def check_uci(g: Geometry) -> list[Rule]:
    """Evaluate the design against the commonly quoted UCI road rules."""
    d = g.design
    units = d.get("units", "mm")

    def L(mm: float) -> str:
        return fmt_len(mm, units, suffix=True)

    def LIM(mm: float) -> str:          # limits: whole mm, plus the rule's own cm when in inches
        if units == "in":
            return f"{fmt_len(mm, units, suffix=True)} ({mm / 10:g} cm)"
        return fmt_len(mm, units, 0, suffix=True)

    v = g.v
    rules: list[Rule] = []

    # -- saddle setback ---------------------------------------------------------
    nose = v.get("saddle_nose_setback", float("nan"))
    if nose >= 50 - 1e-9:
        st, note = "pass", ""
    elif nose >= 0:
        if d.get("uci_morpho_exemption", False):
            st, note = "pass", "Allowed only under the morphological exemption claimed for this rider"
        else:
            st, note = "warn", ("Saddle nose closer than 5 cm: permitted only under the morphological "
                                "exemption (conditions in the regulations)")
    else:
        st, note = "fail", "Saddle nose is ahead of the vertical through the BB"
    rules.append(Rule("saddle_setback", "Saddle nose behind BB vertical", L(nose) + " behind",
                      "≥ " + LIM(50), st, note))

    # -- saddle length ----------------------------------------------------------------
    sl = d.f("saddle_length")
    rules.append(Rule("saddle_length", "Saddle length", L(sl), f"{LIM(240)} – {LIM(300)}", _range(sl, 240, 300)))

    # -- bottom-bracket height ----------------------------------------------------------
    bbh = v.get("bb_height", float("nan"))
    rules.append(Rule("bb_height", "BB height above ground", L(bbh), f"{LIM(240)} – {LIM(300)}",
                      _range(bbh, 240, 300)))

    # -- BB to front axle (horizontal) ---------------------------------------------------
    fc = v.get("front_center_h", float("nan"))
    rules.append(Rule("bb_front_axle", "BB to front axle (horizontal)", L(fc), f"{LIM(540)} – {LIM(650)}",
                      _range(fc, 540, 650), "Measured between the verticals through the BB and the axle"))

    # -- BB to rear axle (horizontal) ----------------------------------------------------
    rc = v.get("rear_center_h", float("nan"))
    rules.append(Rule("bb_rear_axle", "BB to rear axle (horizontal)", L(rc), "≥ " + LIM(350),
                      _range(rc, 350, None)))

    # -- overall length -------------------------------------------------------------------
    rear, front = g.wheels["rear"], g.wheels["front"]
    xs_min = [rear.center.x - rear.outer_r]
    xs_max = [front.center.x + front.outer_r]
    if g.bar_path:
        xs_max.append(max(p.x for p in g.bar_path))
    if "saddle_tail" in g.p:
        xs_min.append(g.p["saddle_tail"].x)
    length = max(xs_max) - min(xs_min)
    rules.append(Rule("overall_length", "Overall length", L(length), "≤ " + LIM(1850), _range(length, None, 1850),
                      "Rear tyre to the furthest forward part (tyre or handlebar)"))

    # -- wheel diameters ------------------------------------------------------------------
    fd, rd = front.diameter, rear.diameter
    st = "pass" if _range(fd, 550, 700) == "pass" and _range(rd, 550, 700) == "pass" else "fail"
    rules.append(Rule("wheel_diameter", "Wheel diameter incl. tyre", f"front {L(fd)} / rear {L(rd)}",
                      f"{LIM(550)} – {LIM(700)}", st))
    same = abs(d.f("front_bsd") - d.f("rear_bsd")) < 0.5
    rules.append(Rule("wheels_equal", "Front and rear wheels of equal diameter",
                      f"BSD {d.f('front_bsd'):g} / {d.f('rear_bsd'):g}", "equal (massed-start road)",
                      "pass" if same else "warn",
                      "" if same else "Different diameters are not accepted for massed-start road events; "
                                      "other disciplines differ"))

    # -- width ------------------------------------------------------------------------------
    bw = d.f("bar_width")
    rules.append(Rule("width", "Overall width (handlebar)", L(bw), "≤ " + LIM(500), _range(bw, None, 500),
                      "Approximated by the handlebar width; levers or bar ends may add to it"))

    # -- tube section dimensions -------------------------------------------------------------
    frame_tubes = {n: t for n, t in g.tubes.items() if t.kind in ("main", "stay", "fork", "extra")}
    frame_tubes.setdefault("ht", g.tubes.get("ht"))
    frame_tubes = {n: t for n, t in frame_tubes.items() if t is not None}
    if frame_tubes:
        big = max(frame_tubes.items(), key=lambda kv: max(kv[1].od_a, kv[1].od_b, kv[1].w_a, kv[1].w_b))
        small = min(frame_tubes.items(), key=lambda kv: min(kv[1].od_a, kv[1].od_b, kv[1].w_a, kv[1].w_b))
        bmax = max(big[1].od_a, big[1].od_b, big[1].w_a, big[1].w_b)
        smin = min(small[1].od_a, small[1].od_b, small[1].w_a, small[1].w_b)
        rules.append(Rule("tube_max_dim", "Largest tube section dimension", f"{L(bmax)} ({big[1].label})",
                          "≤ " + LIM(80), _range(bmax, None, 80),
                          "Approximated by tube OD / width; lugs, junctions and fairings are not checked"))
        rules.append(Rule("tube_min_dim", "Smallest tube section dimension", f"{L(smin)} ({small[1].label})",
                          "≥ " + LIM(10), _range(smin, 10, None),
                          "Approximated by tube OD / width at the tube ends"))

    # -- minimum weight -------------------------------------------------------------------------
    try:
        from .weight import bike_weight
        w = bike_weight(g)["total"]
    except Exception:                                 # weight estimate unavailable
        w = float("nan")
    lim = d.f("uci_min_weight") if "uci_min_weight" in d else 6800.0
    if w != w:
        rules.append(Rule("min_weight", "Minimum bicycle weight", "n/a", f"≥ {lim / 1000:.2f} kg", "n/a",
                          "No weight estimate available"))
    else:
        if w < lim:
            st, note = "fail", "Estimate is below the minimum: weigh the built bike, add mass if needed"
        elif w < lim + 300:
            st, note = "warn", "Estimate is close to the minimum: weigh the built bike"
        else:
            st, note = "pass", "Based on the weight estimate (Analysis → Weight)"
        rules.append(Rule("min_weight", "Minimum bicycle weight", f"≈ {w / 1000:.2f} kg (estimate)",
                          f"≥ {lim / 1000:.2f} kg", st, note))

    rules.append(Rule("rules_change", "Regulations change", "–", "–", "n/a",
                      "Limits, tolerances and exceptions are revised periodically. " + SOURCE))
    return rules


def summary(rules: list[Rule]) -> dict[str, int]:
    """Count of rules by status."""
    out = {"pass": 0, "fail": 0, "warn": 0, "n/a": 0}
    for r in rules:
        out[r.status] = out.get(r.status, 0) + 1
    return out
