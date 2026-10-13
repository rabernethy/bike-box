"""Aggregated analysis report: geometry, clearances, gearing, chain / belt,
weight, UCI checks, structure and fixture numbers.

``full_report(g)`` returns a list of :class:`Section`; each row is
``(label, value text, status)`` with status ``ok | warn | fail | info``.
Every section is built independently so one failing analysis does not hide
the others.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..geometry.solver import Geometry
from ..model.units import fmt_angle, fmt_len
from . import aero as _aero  # noqa: F401  (registers the Aerodynamics params at import)

Row = tuple[str, str, str]


@dataclass
class Section:
    title: str
    rows: list[Row] = field(default_factory=list)


_UCI_STATUS = {"pass": "ok", "fail": "fail", "warn": "warn", "n/a": "info"}
_PART_LABELS = {"bb_shell": "BB shell", "rear_axle": "Rear axle", "front_axle": "Front axle",
                "fork_crown": "Fork crown", "steerer": "Steerer"}


def _units(g: Geometry) -> str:
    return g.design.get("units", "mm")


def _L(g: Geometry, mm: float) -> str:
    return fmt_len(mm, _units(g), suffix=True)


def _dL(g: Geometry, mm: float) -> str:
    """Signed length difference in display units."""
    return ("+" if mm >= 0 else "−") + fmt_len(abs(mm), _units(g))


def _speed(g: Geometry, kmh: float) -> str:
    if _units(g) == "in":
        return f"{kmh:.1f} km/h ({kmh / 1.609344:.1f} mph)"
    return f"{kmh:.1f} km/h"


def _member_label(g: Geometry, name: str | None) -> str:
    if not name:
        return "–"
    side = ""
    base = name
    if name.endswith("_r"):
        base, side = name[:-2], " (drive side)"
    elif name.endswith("_l"):
        base, side = name[:-2], " (non-drive side)"
    t = g.tubes.get(base)
    label = t.label if t is not None else _PART_LABELS.get(base, base)
    return label + side


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
_GEOM = (
    ("stack", "Stack", "L"), ("reach", "Reach", "L"), ("head_tube_angle", "Head tube angle", "A"),
    ("seat_tube_angle", "Seat tube angle", "A"), ("seat_angle_eff", "Effective seat angle", "A"),
    ("top_tube_effective", "Effective top tube", "L"), ("head_tube_length", "Head tube length", "L"),
    ("seat_tube_ct", "Seat tube (c-t)", "L"), ("chainstay_length", "Chainstay", "L"),
    ("bb_drop", "BB drop", "L"), ("bb_height", "BB height", "L"), ("wheelbase", "Wheelbase", "L"),
    ("front_center", "Front centre", "L"), ("fork_length", "Fork axle-to-crown", "L"),
    ("fork_offset", "Fork offset", "L"), ("trail", "Trail", "L"), ("standover", "Standover", "L"),
    ("saddle_height", "Saddle height", "L"), ("saddle_setback", "Saddle setback", "L"),
    ("saddle_bar_drop", "Saddle to bar drop", "L"),
)


def _geometry(g: Geometry) -> Section:
    rows: list[Row] = []
    for key, label, kind in _GEOM:
        if key in g.v:
            val = g.v[key]
            rows.append((label, fmt_angle(val, 1) if kind == "A" else _L(g, val), "info"))
    return Section("Key geometry", rows)


def _clearances(g: Geometry) -> Section:
    d = g.design
    v = g.v
    rows: list[Row] = []

    def clr(key, label, warn_below, fail_below=0.0):
        if key not in v:
            return
        x = v[key]
        st = "fail" if x < fail_below else ("warn" if x < warn_below else "ok")
        rows.append((label, _L(g, x), st))

    clr("rear_tire_clearance", "Rear tyre to seat tube", 3.0)
    clr("front_tire_clearance", "Front tyre to down tube", 3.0)
    if "toe_clearance" in v:
        x = v["toe_clearance"]
        lim = d.f("toe_clearance_min") if "toe_clearance_min" in d else 0.0
        rows.append(("Toe clearance", _L(g, x) + (" (overlap)" if x < 0 else ""), "warn" if x < lim else "ok"))
    clr("pedal_clearance", "Pedal to ground (crank down)", 60.0)
    if "lean_angle" in v:
        rows.append(("Pedal-strike lean angle", fmt_angle(v["lean_angle"]), "info"))
    if "seatpost_insertion" in v:
        x = v["seatpost_insertion"]
        rows.append(("Seatpost insertion", _L(g, x), "warn" if x < d.f("seatpost_min_insertion") else "ok"))
    if g.warnings:
        rows += [("Warning", w, "warn") for w in g.warnings]
    else:
        rows.append(("Design warnings", "None", "ok"))
    return Section("Clearances & warnings", rows)


def _gearing(g: Geometry) -> Section:
    from .gearing import gearing_summary
    d = g.design
    if d["frame_type"] == "balance":
        return Section("Gearing", [("Drivetrain", "None — balance / baby bike", "info")])
    s = gearing_summary(d, g)
    rows: list[Row] = []
    if not s.get("count"):
        return Section("Gearing", [("Gears", "No chainrings / cogs defined", "warn")])

    def gear(r) -> str:
        hub = f" × {r['hub_ratio']:g}" if r["hub_ratio"] != 1.0 else ""
        return (f"{r['ring']:g}×{r['cog']:g}{hub}: {r['gear_inches']:.1f} in, {r['development_m']:.2f} m, "
                f"{_speed(g, r['speed_kmh'])}")

    rows.append(("Gear combinations", f"{s['count']} ({s['distinct']} distinct ratios)", "info"))
    rows.append(("Highest gear", gear(s["highest"]), "info"))
    rows.append(("Lowest gear", gear(s["lowest"]), "info"))
    rows.append(("Range", f"{s['range_pct']:.0f} %", "info"))
    rows.append(("Gain ratio", f"{s['lowest']['gain_ratio']:.2f} – {s['highest']['gain_ratio']:.2f}", "info"))
    rows.append(("Speeds at", f"{d.f('cadence'):g} rpm", "info"))
    rows.append(("Rear wheel diameter used", _L(g, g.wheels["rear"].diameter), "info"))
    if d["drive_type"] == "derailleur":
        from .gearing import drivetrain_range
        dr = drivetrain_range(d)
        if dr:
            cap = d.get("rd_capacity") or 0
            over_cap = cap and dr["required_capacity"] > cap
            rows.append(("RD capacity needed", f"{dr['required_capacity']:.0f} T"
                         + (f" (RD rated {cap} T)" if cap else ""), "fail" if over_cap else "ok"))
            mx = d.get("rd_max_cog") or 0
            over_cog = mx and dr["max_cog"] > mx
            rows.append(("Largest cog", f"{dr['max_cog']:.0f} T"
                         + (f" (RD max {mx} T)" if mx else ""), "fail" if over_cog else "ok"))
    return Section("Gearing", rows)


def _chain(g: Geometry) -> Section:
    from .gearing import chain_length, chainline_check
    d = g.design
    if d["frame_type"] == "balance":
        return Section("Chain", [("Chain / belt", "None — balance / baby bike", "info")])
    rows: list[Row] = []
    c = chain_length(g)
    if not c.get("ok"):
        rows.append(("Chain / belt", "; ".join(c.get("notes", [])) or "n/a", "warn"))
    elif c["method"] == "derailleur":
        rows.append(("Chain length (big–big + 2 links)", f"{c['geometric_links']} links "
                     f"({_L(g, c['geometric_links'] * c['pitch'])})", "ok"))
        rows.append(("Classic formula (2C + F/4 + R/4 + 1)",
                     f"{c['formula_inches']:.2f} in → {c['formula_links']} links",
                     "ok" if abs(c["formula_links"] - c["geometric_links"]) <= 2 else "warn"))
        rows.append(("Exact big–big wrap", f"{c['wrap_links']:.2f} links", "info"))
        rows.append(("Derailleur capacity needed", f"{c['capacity']:g} teeth", "info"))
    elif c["method"] == "singlespeed":
        rows.append(("Exact chain length", f"{c['exact_links']:.2f} links ({c['ring']:g}×{c['cog']:g})", "info"))
        for o in c["options"]:
            lab = f"{o['links']} links" + (" (half-link)" if o["half_link"] else "")
            rows.append((lab, f"chainstay {_L(g, o['chainstay'])} ({_dL(g, o['delta'])})",
                         "ok" if o["in_range"] else "info"))
    else:
        rows.append(("Exact belt length", f"{c['exact_teeth']:.2f} teeth ({c['ring']:g}/{c['cog']:g}, "
                     f"{c['pitch']:g} mm pitch)", "info"))
        opts = sorted(c["options"], key=lambda o: abs(o["delta"]))[:4]
        for o in sorted(opts, key=lambda o: o["teeth"]):
            rows.append((f"Belt {o['teeth']} T", f"chainstay {_L(g, o['chainstay'])} ({_dL(g, o['delta'])})",
                         "ok" if o["in_range"] else "info"))
        if not any(o["in_range"] for o in c["options"]):
            rows.append(("Belt fit", "No listed belt fits within the axle adjustment", "warn"))
    try:
        cl = chainline_check(d)
        est = " (rear estimated)" if cl["rear_estimated"] else ""
        rows.append(("Chainline front / rear", f"{_L(g, cl['front'])} / {_L(g, cl['rear'])}{est}", cl["status"]))
        if cl["method"] == "derailleur":
            rows.append(("Largest chain angle", fmt_angle(cl["max_angle_deg"], 1), "info"))
        for n in cl["notes"]:
            rows.append(("Note", n, "info"))
    except Exception as exc:                      # chainline is secondary
        rows.append(("Chainline", f"unavailable: {exc}", "warn"))
    title = "Belt" if c.get("method") == "belt" else "Chain"
    return Section(title, rows)


def _weight(g: Geometry) -> Section:
    from .weight import bike_weight
    b = bike_weight(g)
    fw = b["frame_detail"]
    rows: list[Row] = [
        ("Frame (estimate)", f"{fw['frame']:.0f} g", "info"),
        ("Fork (estimate)", f"{fw['fork']:.0f} g", "info"),
        ("Frame + fork", f"{fw['frame_and_fork']:.0f} g", "info"),
        ("Components (typical values)", f"{b['components_total']:.0f} g", "info"),
        ("Complete bike (estimate)", f"{b['total'] / 1000:.2f} kg", "info"),
    ]
    top = sorted(fw["frame_items"].items(), key=lambda kv: -kv[1])[:4]
    rows.append(("Heaviest frame parts", ", ".join(f"{k} {v:.0f} g" for k, v in top), "info"))
    rows.append(("Note", "Estimates from tube dimensions and typical part masses", "info"))
    return Section("Weight", rows)


def _uci(g: Geometry) -> Section:
    from .uci import check_uci
    rows: list[Row] = []
    for r in check_uci(g):
        if r.id == "rules_change":
            rows.append((r.title, r.note, "info"))
            continue
        txt = r.measured if r.limit in ("", "–") else f"{r.measured} (limit {r.limit})"
        if r.note and r.status in ("warn", "fail"):
            txt += f" – {r.note}"
        rows.append((r.title, txt, _UCI_STATUS.get(r.status, "info")))
    return Section("UCI (road)", rows)


def _structure(g: Geometry) -> Section:
    from .structure import analyse
    res = analyse(g)
    if not res.get("ok"):
        return Section("Structure (FEA estimate)", [("Structure", res.get("error", "unavailable"), "warn")])
    h = res["headline"]
    rows: list[Row] = []

    def num(key, label, unit, dec=0):
        x = h.get(key, float("nan"))
        if x == x:
            rows.append((label, f"{x:.{dec}f} {unit}", "info"))

    num("bb_lateral_stiffness", "BB lateral stiffness", "N/mm")
    num("ht_torsional_stiffness", "Head-tube torsional stiffness", "N·m/deg", 1)
    num("saddle_vertical_stiffness", "Saddle vertical stiffness (frame only)", "N/mm")
    num("inplane_stiffness", "In-plane stiffness at front axle", "N/mm", 1)
    num("transverse_stiffness", "Lateral stiffness at seat cluster", "N/mm", 1)
    for c in res["cases"].values():
        sf = c["min_sf"]
        st = "fail" if sf < 1.0 else ("warn" if sf < 1.5 else "ok")
        sf_txt = "–" if sf == float("inf") else f"{sf:.2f}"
        rows.append((c["title"], f"max {c['max_stress']:.0f} MPa in {_member_label(g, c['critical_member'])}, "
                     f"SF {sf_txt}", st))
    rows.append(("Model", ("fork modelled" if res["model"]["include_fork"] else "rigid dummy fork")
                 + f", solved in {res['time_ms']:.0f} ms", "info"))
    rows.append(("Note", "Static linear estimate (rigid joints); fatigue governs real frames", "info"))
    return Section("Structure (FEA estimate)", rows)


def _fixture(g: Geometry) -> Section:
    from .jig import fixture_numbers
    rows = [(f"{lab} – {note}" if note else lab, val, "info") for lab, val, note in fixture_numbers(g)]
    return Section("Fixture", rows)


def _bom(g: Geometry) -> Section:
    from .bom import report_rows
    return Section("Bill of materials", report_rows(g.design, g))


def _compat(g: Geometry) -> Section:
    from .compat import check
    # report rows are (label, value, status); check() yields (status, label, message)
    return Section("Compatibility", [(label, msg, status) for status, label, msg in check(g)])


def _aero(g: Geometry) -> Section:
    from .aero import report_rows
    return Section("Aerodynamics (estimate)", report_rows(g))


def _tire_fit(g: Geometry) -> Section:
    from .tirefit import max_tire_width
    rows = []
    for end in ("rear", "front"):
        r = max_tire_width(g.design, end)
        cur = g.design.f(f"{end}_tire_width")
        if not r:
            rows.append((f"Max {end} tire", f"current {cur:.0f} mm already interferes", "warn"))
        else:
            note = f" (limited by {r['limited_by']})" if r.get("limited_by") and r["limited_by"] != "search limit" \
                else " (beyond 120 mm)"
            rows.append((f"Max {end} tire", f"{r['width']:.0f} mm{note}", "info"))
    return Section("Tire fit", rows)


_BUILDERS: list[tuple[str, Callable[[Geometry], Section]]] = [
    ("Key geometry", _geometry), ("Clearances & warnings", _clearances), ("Gearing", _gearing),
    ("Chain", _chain), ("Weight", _weight), ("UCI (road)", _uci), ("Structure (FEA estimate)", _structure),
    ("Fixture", _fixture), ("Tire fit", _tire_fit), ("Aerodynamics (estimate)", _aero),
    ("Compatibility", _compat), ("Bill of materials", _bom),
]


def full_report(g: Geometry) -> list[Section]:
    """All analysis sections for a solved geometry.

    The result is memoised on the geometry instance: a solved geometry is shared
    (and replaced on every edit) by the whole UI, so the several panels, dialogs
    and tab switches that want the report compute it once instead of each
    re-running the FEA, compatibility, aero and BOM builders."""
    cached = getattr(g, "_full_report_cache", None)
    if cached is not None:
        return cached
    out: list[Section] = []
    for title, fn in _BUILDERS:
        try:
            out.append(fn(g))
        except Exception as exc:                  # keep the rest of the report
            out.append(Section(title, [("Error", f"{type(exc).__name__}: {exc}", "fail")]))
    try:
        g._full_report_cache = out
    except Exception:                             # pragma: no cover (e.g. if Geometry gained __slots__)
        pass
    return out


def report_text(g: Geometry) -> str:
    """Plain-text rendering of :func:`full_report` (for copying / logs)."""
    lines: list[str] = []
    for sec in full_report(g):
        lines.append(f"== {sec.title} ==")
        for label, value, status in sec.rows:
            flag = {"warn": " [!]", "fail": " [X]"}.get(status, "")
            lines.append(f"  {label:44s} {value}{flag}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
