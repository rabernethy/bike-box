"""Numbers for setting a frame up in a generic frame fixture.

Two datums are given: the horizontal through the BB centre (X forward, Y up,
the usual drawing datum) and the seat-tube axis (distance along the axis
from the BB, and perpendicular distance forward of it), which suits fixtures
whose main beam follows the seat tube.  Stay "phase" angles are the rotation
about each stay's own axis between its far-end mitre and the dropout slot
(the dropout plate lies parallel to the frame plane).
"""
from __future__ import annotations

import math

from ..geometry.solver import Geometry, Tube
from ..geometry.vec import V
from ..model.units import fmt_angle, fmt_len


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 1e-12 else (0.0, 0.0, 0.0)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def stay_angles(t: Tube, axis: tuple[float, float, float]) -> tuple[float, float]:
    """(splay, phase) in degrees for the drive-side copy of a stay.

    *splay*: angle between the stay axis and the frame plane (magnitude; stays
    converge from the dropouts).
    *phase*: angle about the stay axis from the dropout-slot plane (the plane
    through the stay axis closest to parallel with the frame plane) to the
    axis of the tube the far end is mitred to; 0° = that tube's axis lies in
    the slot plane, 90° = square to it.  Folded to -90..90°.
    """
    a3 = (t.a.x, t.a.y, abs(t.za))
    b3 = (t.b.x, t.b.y, abs(t.zb))
    d = _unit(_sub(b3, a3))
    splay = abs(math.degrees(math.asin(max(-1.0, min(1.0, d[2])))))
    Z = (0.0, 0.0, 1.0)
    e = _unit(_cross(Z, d))                     # in the slot plane, square to the stay
    n = _unit(_sub(Z, tuple(d[i] * d[2] for i in range(3))))   # slot-plane normal
    A = _unit(axis)
    m = _unit(_sub(A, tuple(d[i] * _dot(A, d) for i in range(3))))
    phase = math.degrees(math.atan2(_dot(m, n), _dot(m, e)))
    if phase > 90:
        phase -= 180
    elif phase < -90:
        phase += 180
    return splay, phase


def fixture_numbers(g: Geometry) -> list[tuple[str, str, str]]:
    """(label, value, note) rows for setting the frame in a fixture.

    Lengths honour ``design["units"]``; coordinates are from the BB centre.
    """
    d = g.design
    units = d.get("units", "mm")
    v, p = g.v, g.p

    def L(mm: float) -> str:
        return fmt_len(mm, units, suffix=True)

    def XY(pt: V) -> str:
        return f"X {fmt_len(pt.x, units)}, Y {fmt_len(pt.y, units)}" + (' "' if units == "in" else " mm")

    P0 = p["st_bottom"]
    s, n_st = g.s, g.n_st

    def on_st(pt: V) -> str:
        r = pt - P0
        return (f"along {fmt_len(r.dot(s), units)}, forward {fmt_len(r.dot(n_st), units)}"
                + (' "' if units == "in" else " mm"))

    rows: list[tuple[str, str, str]] = [
        ("Head tube angle", fmt_angle(v["head_tube_angle"], 2), "From horizontal"),
        ("Seat tube angle", fmt_angle(v["seat_tube_angle"], 2), "Actual tube angle (not effective)"),
        ("BB drop", L(v["bb_drop"]), "Rear axle centre above the BB centre"),
        ("Chainstay length (c-c)", L(v["chainstay_length"]), "BB centre to rear axle centre"),
        ("Rear centre (horizontal)", L(v["rear_center_h"]), "BB vertical to rear axle"),
        ("Rear axle", XY(p["rear_axle"]), "From the BB centre"),
        ("Front axle", XY(p["front_axle"]), "From the BB centre (fork fitted)"),
    ]
    T, B = p["ht_top"], p["ht_bottom"]
    rows += [
        ("Head tube top face centre", XY(T), "From the BB centre"),
        ("Head tube bottom face centre", XY(B), "From the BB centre"),
    ]
    u = g.u
    if abs(u.y) > 1e-9:
        x0 = T.x - T.y * u.x / u.y
        rows.append(("Steering axis at BB height", f"X {L(x0)}", "Where the head-tube axis crosses the BB horizontal"))
    perp = abs((V(0, 0) - T).cross(u))
    rows.append(("BB centre to steering axis (perpendicular)", L(perp), ""))
    rows += [
        ("Head tube length", L(v["head_tube_length"]), "Face to face"),
        ("Top face to top-tube centreline", L(d.f("tt_ht_offset")), "Along the head-tube axis"),
        ("Bottom face to down-tube centreline", L(d.f("dt_ht_offset")), "Along the head-tube axis"),
    ]
    # seat-tube datum
    rows += [
        ("TT / HT-axis intersection (seat-tube datum)", on_st(p["tt_ht"]),
         "Distance along the seat-tube axis from the BB, and perpendicular forward of it"),
        ("DT / HT-axis intersection (seat-tube datum)", on_st(p["dt_ht"]), "As above"),
        ("Head tube top face (seat-tube datum)", on_st(T), "As above"),
        ("Head tube bottom face (seat-tube datum)", on_st(B), "As above"),
    ]
    if "tt" in g.tubes:
        rows.append(("Seat cluster height", L(p["tt_st"].y), "TT / ST centreline junction above the BB"))
    rows += [
        ("Seat tube c-c (to top-tube centreline)", L(v["seat_tube_cc"]), "Along the seat-tube axis"),
        ("Seat tube c-t", L(v["seat_tube_ct"]), "BB centre to the top of the seat tube"),
    ]
    if "ss" in g.tubes:
        ssj = p["ss_top"]
        rows.append(("Seat-stay junction (seat-tube datum)", on_st(ssj), "Stay centrelines meet the tube here"))
    if "tt" in g.tubes:
        rows.append(("Top tube c-c", L(v["top_tube_cc"]), f"Slope {fmt_angle(v['top_tube_angle'])}"))
    if "dt" in g.tubes:
        rows.append(("Down tube c-c", L(v["down_tube_cc"]), "BB centre to the head-tube axis"))
    rows += [
        ("Rear dropout spacing (OLD)", L(d.f("rear_hub_spacing")), "Inside faces"),
        ("Front dropout spacing", L(d.f("front_hub_spacing")), "Inside faces"),
        ("Chainstay spread at BB (c-c)", L(v.get("cs_spread_bb", d.f("cs_spread_bb"))), ""),
    ]
    if "ss" in g.tubes and d["ss_style"] == "conventional":
        rows.append(("Seat-stay spread at top (c-c)", L(v.get("ss_spread_top", d.f("ss_spread_top"))), ""))
    # stay splay / phase
    if "cs" in g.tubes:
        splay, phase = stay_angles(g.tubes["cs"], (0.0, 0.0, 1.0))
        rows.append(("Chainstay splay", fmt_angle(splay, 2), "Angle of the stay to the frame plane (top view)"))
        rows.append(("Chainstay phase (BB mitre to dropout slot)", fmt_angle(phase, 1),
                     "Rotation about the stay axis; 90° = BB-shell mitre square to the slot"))
    if "ss" in g.tubes:
        t = g.tubes["ss"]
        join = t.join_b
        if join == "tt" and "tt" in g.tubes:
            tt = g.tubes["tt"]
            ax = (tt.b.x - tt.a.x, tt.b.y - tt.a.y, 0.0)
        else:
            ax = (s.x, s.y, 0.0)
        splay, phase = stay_angles(t, ax)
        rows.append(("Seat-stay splay", fmt_angle(splay, 2), "Angle of the stay to the frame plane (top view)"))
        if join == "ss_mono":
            rows.append(("Seat-stay phase (top mitre to dropout slot)", "n/a",
                         "Stays meet a wishbone / mono yoke: set the phase from the yoke drawing"))
        else:
            rows.append(("Seat-stay phase (top mitre to dropout slot)", fmt_angle(phase, 1),
                         "Rotation about the stay axis; 0° = mitre aligned with the slot"))
    rows += [
        ("Fork axle-to-crown", L(v["fork_length"]), "Along the steering axis"),
        ("Fork offset", L(v["fork_offset"]), ""),
    ]
    return rows
