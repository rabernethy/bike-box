"""Gearing table, chain / belt length and chainline.

Units: lengths in mm, angles in degrees, speeds in km/h.  Chain and belt
lengths are counted in *pitches* ("links" for a bicycle chain: a 112-link
chain has 112 rollers; without a half-link the count must be even).

The chain / belt length maths uses the exact two-sprocket open-belt wrap on
the sprocket pitch circles::

    beta = asin((r1 - r2) / C)
    L    = 2 sqrt(C^2 - (r1 - r2)^2) + wrap1 + wrap2
    wrapN = N_teeth * (pi +/- 2 beta) / (2 pi)          (in pitches)

with the pitch radius ``p / (2 sin(pi/N))`` for a roller chain and
``N p / (2 pi)`` for a toothed belt.  For equal sprockets this reduces to
``2C + N p``.  The inverse (centre distance for a given length) is solved
numerically; the length is monotonic in C so bisection is robust.
"""
from __future__ import annotations

import math
from typing import Any

from ..geometry.solver import Geometry, solve
from ..model import params as P
from ..model.design import Design

G = "Analysis"
P.register([
    P.ParamDef("hub_gear_ratios", "Internal hub / gearbox ratios", G, "Gearing", P.LIST,
               "0.53, 0.64, 0.75, 0.85, 1, 1.22, 1.42, 1.62",
               help="Output/input ratio of each hub or gearbox gear (1 = direct drive).  The default is an "
                    "example 8-speed spread; enter the figures published for your hub",
               visible_if=("drive_type", ("hub_gear", "gearbox")), morph=False),
    P.ParamDef("hub_belt", "Belt final drive", G, "Gearing", P.BOOL, False,
               help="Internal hub / gearbox driven by a toothed belt instead of a chain",
               visible_if=("drive_type", ("hub_gear", "gearbox")), morph=False),
    P.ParamDef("rear_chainline", "Rear chainline", G, "Chain & belt", P.FLOAT, 0.0, "mm", 0, 90, 0.5,
               help="Hub centre to the centre of the cassette (or the single cog).  0 = estimate from the "
                    "rear hub spacing (typical values only; measure your hub)"),
    P.ParamDef("ring_spacing", "Chainring spacing", G, "Chain & belt", P.FLOAT, 0.0, "mm", 0, 15, 0.1,
               help="Centre-to-centre spacing of adjacent chainrings.  0 = approximate typical value"),
    P.ParamDef("cog_spacing", "Cog spacing", G, "Chain & belt", P.FLOAT, 0.0, "mm", 0, 10, 0.01,
               help="Centre-to-centre spacing of adjacent cogs.  0 = approximate typical value for the "
                    "number of cogs"),
    P.ParamDef("max_chain_angle", "Chain angle limit (rule of thumb)", G, "Chain & belt", P.FLOAT, 2.5,
               "deg", 0.5, 10, 0.1, help="Lateral chain angle above which a combination is flagged"),
    P.ParamDef("axle_adjust", "Axle adjustment (±)", G, "Chain & belt", P.FLOAT, 8.0, "mm", 0, 60, 0.5,
               help="Usable chainstay adjustment either side of the design length (horizontal dropouts, "
                    "sliders or an eccentric BB).  Used to flag which chain / belt lengths fit"),
    P.ParamDef("belt_tooth_counts", "Available belt lengths (teeth)", G, "Chain & belt", P.LIST,
               "100, 104, 108, 111, 113, 115, 118, 120, 122, 125, 128, 132, 135, 138, 142, 145, 150",
               help="Typical belt tooth counts; replace with your supplier's list", morph=False),
])

MM_PER_IN = 25.4

# Approximate centre-to-centre cog spacing by number of cogs (mm).
_COG_SPACING = {1: 0.0, 2: 5.5, 3: 5.5, 4: 5.5, 5: 5.5, 6: 5.0, 7: 5.0, 8: 4.8, 9: 4.34, 10: 3.95,
                11: 3.74, 12: 3.65}
# Approximate chainring spacing by number of rings (mm).
_RING_SPACING = {1: 0.0, 2: 7.5, 3: 5.5}
# Typical rear chainline (cassette / cog centre) by rear hub spacing (mm).
_REAR_CHAINLINE = {120.0: 42.0, 126.0: 43.5, 130.0: 43.5, 135.0: 47.5, 142.0: 47.5, 148.0: 52.0, 157.0: 56.5}


# --------------------------------------------------------------------------
# sprocket wrap maths
# --------------------------------------------------------------------------
def pitch_radius(teeth: float, pitch: float, kind: str = "chain") -> float:
    """Pitch-circle radius of a chain sprocket (polygon) or belt pulley."""
    if kind == "belt":
        return teeth * pitch / (2 * math.pi)
    return pitch / (2 * math.sin(math.pi / teeth))


def wrap_length(c: float, n1: float, n2: float, pitch: float, kind: str = "chain") -> float:
    """Exact open-belt length around two sprockets at centre distance ``c``,
    in pitches (links or belt teeth).  NaN if the centre distance is too short."""
    r1, r2 = pitch_radius(n1, pitch, kind), pitch_radius(n2, pitch, kind)
    dr = r1 - r2
    if c <= abs(dr) + 1e-9:
        return float("nan")
    beta = math.asin(dr / c)
    span = math.sqrt(c * c - dr * dr)
    return (2 * span / pitch + n1 * (math.pi + 2 * beta) / (2 * math.pi)
            + n2 * (math.pi - 2 * beta) / (2 * math.pi))


def centre_for_length(length: float, n1: float, n2: float, pitch: float, kind: str = "chain") -> float:
    """Centre distance (mm) at which a chain / belt of ``length`` pitches fits
    the two sprockets exactly.  NaN when the length is too short."""
    r1, r2 = pitch_radius(n1, pitch, kind), pitch_radius(n2, pitch, kind)
    lo = abs(r1 - r2) + 1e-6
    f_lo = wrap_length(lo, n1, n2, pitch, kind)
    if not (length >= f_lo):
        return float("nan")
    hi = max(length * pitch / 2.0, lo * 2) + pitch
    while wrap_length(hi, n1, n2, pitch, kind) < length:
        hi *= 2.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if wrap_length(mid, n1, n2, pitch, kind) < length:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    return 0.5 * (lo + hi)


def _ceil_even(x: float) -> int:
    return int(2 * math.ceil(x / 2.0 - 1e-9))


def _round_even(x: float) -> int:
    return int(2 * round(x / 2.0))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _rings_cogs(d: Design) -> tuple[list[float], list[float]]:
    rings = [r for r in d.lst("chainrings") if r >= 3]
    cogs = [c for c in d.lst("cogs") if c >= 3]
    return rings, cogs


def rear_chainline(d: Design) -> tuple[float, bool]:
    """(rear chainline mm, estimated?) from the parameter or the hub spacing."""
    v = d.f("rear_chainline")
    if v > 0:
        return v, False
    old = d.f("rear_hub_spacing")
    for k, cl in _REAR_CHAINLINE.items():
        if abs(old - k) < 0.6:
            return cl, True
    return old / 2.0 - 21.5, True


def _layout(d: Design) -> tuple[dict[float, float], dict[float, float], float, bool]:
    """Lateral (Z) position of each chainring and cog: (ring_z, cog_z, rear_cl, estimated)."""
    rings, cogs = _rings_cogs(d)
    front = d.f("chainline")
    rear, est = rear_chainline(d)
    ur = sorted(set(rings))
    uc = sorted(set(cogs))
    rs = d.f("ring_spacing") or _RING_SPACING.get(len(ur), 5.5)
    cs = d.f("cog_spacing") or _COG_SPACING.get(len(uc), 3.5 if len(uc) > 12 else 5.5)
    # largest ring outermost; smallest cog outermost
    ring_z = {t: front + (i - (len(ur) - 1) / 2.0) * rs for i, t in enumerate(ur)}
    cog_z = {t: rear + ((len(uc) - 1) / 2.0 - i) * cs for i, t in enumerate(uc)}
    return ring_z, cog_z, rear, est


def _centre(g: Geometry) -> float:
    return float(g.v.get("chainstay_length", g.p["rear_axle"].length()))


# --------------------------------------------------------------------------
# gear table
# --------------------------------------------------------------------------
def gear_table(design: Design, g: Geometry | None = None) -> list[dict[str, Any]]:
    """One row per chainring x cog (x hub gear for internal hubs / gearboxes).

    Row keys: ``ring, cog, hub_ratio, ratio, gear_inches, development_m,
    gain_ratio, speed_kmh, chain_angle_deg`` (None unless derailleur), plus
    ``ring_index, cog_index, hub_index``.  Gear inches use the rear wheel's
    outside diameter (rim BSD + 2 x tyre height) from the solved geometry;
    gain ratio is Sheldon Brown's (wheel radius / crank length) x ratio.
    """
    d = design
    if g is None:
        g = solve(d)
    wheel = g.wheels["rear"]
    dia = wheel.diameter
    crank = max(d.f("crank_length"), 1e-6)
    cadence = d.f("cadence")
    rings, cogs = _rings_cogs(d)
    drive = d["drive_type"]
    hubs = [1.0]
    if drive in ("hub_gear", "gearbox"):
        hubs = [h for h in d.lst("hub_gear_ratios") if h > 0] or [1.0]
        rings, cogs = rings[:1], cogs[:1]
    angles = drive == "derailleur"
    if angles:
        ring_z, cog_z, _, _ = _layout(d)
        C = _centre(g)
    rows: list[dict[str, Any]] = []
    for i, ring in enumerate(rings):
        for j, cog in enumerate(cogs):
            for k, hub in enumerate(hubs):
                ratio = ring / cog * hub
                dev = ratio * math.pi * dia / 1000.0
                ang = None
                if angles:
                    ang = math.degrees(math.atan2(ring_z[ring] - cog_z[cog], C))
                rows.append({
                    "ring": ring, "cog": cog, "hub_ratio": hub,
                    "ring_index": i, "cog_index": j, "hub_index": k,
                    "ratio": ratio,
                    "gear_inches": ratio * dia / MM_PER_IN,
                    "development_m": dev,
                    "gain_ratio": (dia / 2.0) / crank * ratio,
                    "speed_kmh": dev * cadence * 60.0 / 1000.0,
                    "chain_angle_deg": ang,
                })
    return rows


def gearing_summary(design: Design, g: Geometry | None = None) -> dict[str, Any]:
    """Lowest / highest gear and overall range of :func:`gear_table`."""
    rows = gear_table(design, g)
    if not rows:
        return {"count": 0}
    lo = min(rows, key=lambda r: r["ratio"])
    hi = max(rows, key=lambda r: r["ratio"])
    distinct = sorted({round(r["ratio"], 4) for r in rows})
    return {"count": len(rows), "distinct": len(distinct), "lowest": lo, "highest": hi,
            "range_pct": hi["ratio"] / lo["ratio"] * 100.0}


# --------------------------------------------------------------------------
# chain / belt length
# --------------------------------------------------------------------------
def _auto_method(d: Design) -> str:
    dt = d["drive_type"]
    if dt == "derailleur":
        return "derailleur"
    if dt == "belt" or (dt in ("hub_gear", "gearbox") and d["hub_belt"]):
        return "belt"
    return "singlespeed"


def chain_length(g: Geometry, method: str = "auto") -> dict[str, Any]:
    """Chain or belt length for the current chainstay (BB-to-axle distance).

    ``method``: ``"auto"`` (from the drive type), ``"derailleur"`` (or its
    variants ``"geometric"`` / ``"formula"`` which pick the recommended
    figure), ``"singlespeed"`` or ``"belt"``.  Single speed and belt use the
    *first* chainring and cog in the lists.
    """
    d = g.design
    pick = "geometric"
    m = method
    if m == "auto":
        m = _auto_method(d)
    if m in ("geometric", "formula"):
        pick, m = m, "derailleur"
    rings, cogs = _rings_cogs(d)
    C = _centre(g)
    if not rings or not cogs:
        return {"method": m, "ok": False, "centre": C, "notes": ["No chainrings / cogs defined"]}
    if m == "derailleur":
        return _derailleur(d, C, rings, cogs, pick)
    if m == "belt":
        return _belt(d, C, rings[0], cogs[0])
    return _singlespeed(d, C, rings[0], cogs[0])


def _derailleur(d: Design, C: float, rings: list[float], cogs: list[float], pick: str) -> dict[str, Any]:
    p = d.f("chain_pitch")
    F, R = max(rings), max(cogs)
    wrap = wrap_length(C, F, R, p)
    geometric = _ceil_even(wrap) + 2
    raw = 2 * C / p + (F + R) / 2.0 + 2.0        # = 2 x (2C + F/4 + R/4 + 1) for a 1/2" pitch
    formula_in = raw * p / MM_PER_IN
    formula = _round_even(raw)
    cap = (max(rings) - min(rings)) + (max(cogs) - min(cogs))
    return {
        "method": "derailleur", "ok": True, "pitch": p, "centre": C,
        "big_ring": F, "big_cog": R, "small_ring": min(rings), "small_cog": min(cogs),
        "wrap_links": wrap, "geometric_links": geometric,
        "formula_inches": formula_in, "formula_links": formula,
        "links": formula if pick == "formula" else geometric,
        "length_mm": (formula if pick == "formula" else geometric) * p,
        "capacity": cap,
        "notes": [
            "Geometric: big ring + big cog wrapped without the derailleur (exact pitch-circle wrap), "
            "rounded up to a whole link pair, plus 2 links",
            "Formula: L = 2C + F/4 + R/4 + 1 (inches, C = chainstay), rounded to the nearest whole inch",
            f"Derailleur capacity needed: {cap:g} teeth (check the derailleur specification)",
            "Suspension frames and some derailleurs need their maker's sizing method",
        ],
    }


def _singlespeed(d: Design, C: float, ring: float, cog: float) -> dict[str, Any]:
    p = d.f("chain_pitch")
    adj = d.f("axle_adjust")
    exact = wrap_length(C, ring, cog, p)
    cands = sorted({2 * math.floor(exact / 2.0), 2 * math.ceil(exact / 2.0),
                    2 * math.floor((exact - 1) / 2.0) + 1, 2 * math.ceil((exact - 1) / 2.0) + 1})
    options = []
    for n in cands:
        cn = centre_for_length(n, ring, cog, p)
        options.append({"links": int(n), "half_link": n % 2 == 1, "chainstay": cn, "delta": cn - C,
                        "in_range": abs(cn - C) <= adj + 1e-9})
    evens = [o for o in options if not o["half_link"]]
    best_even = min(evens, key=lambda o: abs(o["delta"])) if evens else None
    best_any = min(options, key=lambda o: abs(o["delta"])) if options else None
    return {
        "method": "singlespeed", "ok": True, "pitch": p, "ring": ring, "cog": cog, "centre": C,
        "exact_links": exact, "options": options,
        "nearest_even": best_even["links"] if best_even else None,
        "nearest_any": best_any["links"] if best_any else None,
        "links": best_even["links"] if best_even else None,
        "notes": [
            "Chainstay = BB centre to rear axle centre at which each length fits exactly (no slack)",
            "Odd link counts need a half-link",
            f"'in range' = within ±{adj:g} mm axle adjustment",
        ],
    }


def _belt(d: Design, C: float, ring: float, cog: float) -> dict[str, Any]:
    p = d.f("belt_pitch")
    adj = d.f("axle_adjust")
    exact = wrap_length(C, ring, cog, p, "belt")
    r1, r2 = pitch_radius(ring, p, "belt"), pitch_radius(cog, p, "belt")
    options = []
    for n in sorted({int(round(t)) for t in d.lst("belt_tooth_counts") if t > 0}):
        cn = centre_for_length(n, ring, cog, p, "belt")
        if cn != cn or cn < r1 + r2:          # too short to fit both sprockets
            continue
        options.append({"teeth": n, "chainstay": cn, "delta": cn - C,
                        "in_range": abs(cn - C) <= adj + 1e-9})
    nearest = min(options, key=lambda o: abs(o["delta"])) if options else None
    for o in options:
        o["nearest"] = o is nearest
    return {
        "method": "belt", "ok": True, "pitch": p, "ring": ring, "cog": cog, "centre": C,
        "exact_teeth": exact, "length_mm": exact * p, "options": options,
        "nearest_teeth": nearest["teeth"] if nearest else None,
        "notes": [
            "Exact open-belt length on the pulley pitch circles",
            "Belts cannot be split: the rear triangle needs a frame split or coupler",
            "Set the chainstay to a listed length (or provide adjustment) and check the belt maker's "
            "tension and alignment guidance",
        ],
    }


# --------------------------------------------------------------------------
# chainline
# --------------------------------------------------------------------------
def chainline_check(design: Design) -> dict[str, Any]:
    """Front vs rear chainline and the lateral chain angle of every combination.

    Thresholds are rules of thumb (``max_chain_angle``); the rear chainline is
    estimated from the hub spacing unless ``rear_chainline`` is set.
    """
    d = design
    g = solve(d)
    C = _centre(g)
    method = _auto_method(d)
    rings, cogs = _rings_cogs(d)
    if method != "derailleur":
        rings, cogs = rings[:1], cogs[:1]
    front = d.f("chainline")
    ring_z, cog_z, rear, est = _layout(d) if method == "derailleur" else ({}, {}, *rear_chainline(d))
    if method != "derailleur":
        ring_z = {r: front for r in rings}
        cog_z = {c: rear for c in cogs}
    limit = d.f("max_chain_angle")
    combos = []
    for r in rings:
        for c in cogs:
            off = ring_z[r] - cog_z[c]
            ang = math.degrees(math.atan2(off, C))
            combos.append({"ring": r, "cog": c, "offset": off, "angle_deg": ang,
                           "status": "ok" if abs(ang) <= limit + 1e-9 else "warn"})
    offset = front - rear
    max_ang = max((abs(c["angle_deg"]) for c in combos), default=0.0)
    notes = []
    if est:
        notes.append(f"Rear chainline {rear:.1f} mm estimated from {d.f('rear_hub_spacing'):g} mm hub spacing; "
                     "measure the actual hub")
    if method == "derailleur":
        status = "ok" if abs(offset) <= 2.5 else "warn"
        if len(set(rings)) == 1 and max_ang > 1.4 * limit:
            status = "warn"
            notes.append("Single-ring drivetrain: extreme cogs exceed the chain angle guideline")
        n_cross = sum(1 for c in combos if c["status"] == "warn")
        if n_cross:
            notes.append(f"{n_cross} combination(s) beyond {limit:g}° chain angle (cross-chained)")
    else:
        ok_tol, warn_tol = (1.0, 2.0) if method == "belt" else (1.5, 3.0)
        a = abs(offset)
        status = "ok" if a <= ok_tol else ("warn" if a <= warn_tol else "fail")
        if method == "belt":
            notes.append("Belt makers specify tight alignment tolerances; check their guide")
    return {
        "method": method, "front": front, "rear": rear, "rear_estimated": est, "offset": offset,
        "centre_distance": C,
        "rings": [{"teeth": t, "z": z} for t, z in sorted(ring_z.items())],
        "cogs": [{"teeth": t, "z": z} for t, z in sorted(cog_z.items())],
        "combos": combos, "max_angle_deg": max_ang, "status": status, "notes": notes,
    }
