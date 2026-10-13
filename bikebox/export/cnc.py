"""CNC / shop-floor numbers: tube-notcher setup and tube-bender specs.

Built on the validated mitre engine (:mod:`bikebox.geometry.mitre`) and the
tube bend geometry, so the numbers match what the drawing and cut list show.
Flat-pattern dropout/gusset outlines are intentionally not produced — the model
does not carry those plate outlines, so they would be invented, not derived.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..geometry.mitre import compute_mitres
from ..geometry.solver import Geometry
from ..model.units import fmt_angle, fmt_len


def notcher_rows(g: Geometry, units: str | None = None) -> list[list[str]]:
    """Header + one row per coped tube end: hole-saw Ø, notch angle, offset,
    saw rotation around the tube, long/short points."""
    units = units or g.design["units"]
    rows = [["Tube end", "Receiver", "Hole-saw Ø", "Notch angle", "Offset", "Saw rotation", "Long pt", "Short pt"]]
    for c in compute_mitres(g, samples=120):
        label = f"{c.tube_label or c.tube} ({c.end_label or c.end})"
        rows.append([label, " + ".join(c.receiver_labels or c.receivers),
                     fmt_len(c.holesaw_diameter, units, suffix=True), fmt_angle(c.holesaw_angle),
                     fmt_len(c.holesaw_offset, units, suffix=True),
                     fmt_angle(c.saw_rotation) + (f" ({c.offset_dir})" if c.offset_dir else ""),
                     fmt_len(c.long_point, units, suffix=True), fmt_len(c.short_point, units, suffix=True)])
    return rows


def bend_spec(chord: float, sag: float) -> dict:
    """Bend geometry from the chord length and sagitta (max offset from the chord)."""
    sag = abs(sag)
    if sag < 1e-6:
        return {}
    R = (chord * chord / 4 + sag * sag) / (2 * sag)          # radius through the two ends and the apex
    half = min(chord / (2 * R), 1.0)
    angle = 2 * math.degrees(math.asin(half))                # included (sweep) angle
    arc = math.radians(angle) * R
    return {"radius": R, "angle": angle, "arc": arc, "chord": chord, "sag": sag}


def bender_rows(g: Geometry, units: str | None = None) -> list[list[str]]:
    """Header + one row per bent tube: bend radius, included angle, arc length."""
    units = units or g.design["units"]
    rows = [["Tube", "OD", "Bend radius", "Included angle", "Arc length", "Sagitta"]]
    for name, t in g.tubes.items():
        if abs(t.bend) < 1e-6:
            continue
        s = bend_spec(t.chord, t.bend)
        if not s:
            continue
        rows.append([t.label, fmt_len(max(t.od_a, t.od_b), units, suffix=True),
                     fmt_len(s["radius"], units, suffix=True), fmt_angle(s["angle"]),
                     fmt_len(s["arc"], units, suffix=True), fmt_len(s["sag"], units, suffix=True)])
    return rows


def to_csv(g: Geometry, units: str | None = None) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# Tube notcher setup"])
    for r in notcher_rows(g, units):
        w.writerow(r)
    bends = bender_rows(g, units)
    if len(bends) > 1:
        w.writerow([])
        w.writerow(["# Tube bender"])
        for r in bends:
            w.writerow(r)
    else:
        w.writerow([])
        w.writerow(["# Tube bender", "(no bent tubes)"])
    return buf.getvalue()


def save_csv(g: Geometry, path, units: str | None = None) -> Path:
    path = Path(path)
    path.write_text(to_csv(g, units), encoding="utf-8")
    return path
