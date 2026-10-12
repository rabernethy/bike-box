"""G-code for CNC tube coping (rotary 4th-axis plasma / laser / rotary notchers).

The path follows the cut line of a :class:`~bikebox.geometry.mitre.MitreCut`
once around the tube, starting on the reference line with a lead-in from the
waste side and finishing with a short overcut.

Modes
-----
* ``rotary``  : ``X`` = axial position, rotary word (``A`` by default) =
  tube rotation in degrees.  Feeds use inverse-time mode (``G93``) by
  default so the surface speed is right for combined linear/rotary moves.
* ``wrapped`` : ``X`` = axial position, the rotary word carries the surface
  distance in length units (machines that treat the rotary as a linear axis).
* ``flat``    : ``X``/``Y`` plot of the unrolled template (pen plotter / laser
  cutting a paper or sheet template), ``Y`` up = toward the tube end.

Zero points: ``X0`` is the tube's centre-to-centre end point, ``+X`` points
toward the tube body.  Rotation ``0`` puts the reference line (see
``MitreCut.ref_name``, usually TOP) under the torch; increasing rotation
moves the torch from the reference line toward the drive side.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

import numpy as np

from ..geometry.mitre import MitreCut
from ..model import params as P

G, S = "Manufacturing", "G-code (tube cutting)"
P.register([
    P.ParamDef("gcode_mode", "Machine type", G, S, P.CHOICE, "rotary",
               choices=(("rotary", "Rotary 4th axis (degrees)"), ("wrapped", "Rotary as linear axis (mm)"),
                        ("flat", "Flat template plot (X/Y)")), morph=False),
    P.ParamDef("gcode_rotary_axis", "Rotary axis letter", G, S, P.CHOICE, "A",
               choices=(("A", "A"), ("B", "B"), ("C", "C"), ("Y", "Y"), ("Z", "Z")), morph=False),
    P.ParamDef("gcode_units", "G-code units", G, S, P.CHOICE, "mm",
               choices=(("mm", "Millimetres (G21)"), ("in", "Inches (G20)")), morph=False),
    P.ParamDef("gcode_feed", "Cutting feed", G, S, P.FLOAT, 600.0, "", 1, 20000, 10,
               help="Surface speed in G-code units per minute", morph=False),
    P.ParamDef("gcode_plunge_feed", "Lead-in feed", G, S, P.FLOAT, 200.0, "", 1, 20000, 10, morph=False),
    P.ParamDef("gcode_kerf", "Kerf width", G, S, P.FLOAT, 0.0, "mm", 0, 10, 0.05,
               help="The path is offset by half the kerf into the waste", morph=False),
    P.ParamDef("gcode_lead_in", "Lead-in length", G, S, P.FLOAT, 3.0, "mm", 0, 30, 0.5, morph=False),
    P.ParamDef("gcode_pierce_delay", "Pierce delay", G, S, P.FLOAT, 0.0, "s", 0, 10, 0.1, morph=False),
    P.ParamDef("gcode_inverse_time", "Inverse-time feed (G93) for rotary", G, S, P.BOOL, True, morph=False),
])

SAFETY = ("*** SAFETY: CHECK THIS PROGRAM IN A SIMULATOR / DRY RUN BEFORE CUTTING ***",
          "Nominal geometry only. Verify tube size, zero points, axis directions,",
          "kerf, torch height and clearances on YOUR machine. Use at your own risk.")

_ASCII = {"→": "->", "×": "x", "°": " deg", "—": "-", "–": "-", "Ø": "dia ", "•": "-", "±": "+/-"}


def _clean(s: str) -> str:
    for a, b in _ASCII.items():
        s = s.replace(a, b)
    s = s.replace("(", "[").replace(")", "]")
    return s.encode("ascii", "replace").decode("ascii")


def _comment(s: str) -> str:
    return f"({_clean(s)})"


def gcode_options(design) -> dict:
    """``mitre_gcode`` keyword arguments from a design's Manufacturing parameters."""
    return {
        "mode": design.get("gcode_mode", "rotary"), "rotary_axis": design.get("gcode_rotary_axis", "A"),
        "units": design.get("gcode_units", "mm"), "feed": float(design.get("gcode_feed", 600.0)),
        "plunge_feed": float(design.get("gcode_plunge_feed", 200.0)), "kerf": float(design.get("gcode_kerf", 0.0)),
        "lead_in": float(design.get("gcode_lead_in", 3.0)),
        "pierce_delay": float(design.get("gcode_pierce_delay", 0.0)),
        "inverse_time": bool(design.get("gcode_inverse_time", True)),
    }


def toolpath(cut: MitreCut, kerf: float = 0.0, lead_in: float = 3.0, overcut: float = 1.0) -> np.ndarray:
    """Unrolled path (u, v) in mm: lead-in point, the cut (once round), overcut.

    The cut line is offset by ``kerf / 2`` toward the waste (smaller ``v``)."""
    pts = np.asarray(cut.points, float)[:-1]             # drop the repeated closing point
    u, v = pts[:, 0], pts[:, 1]
    Pm = cut.perimeter
    if kerf > 0:
        du = np.roll(u, -1) - np.roll(u, 1)
        du[0] += Pm
        du[-1] += Pm
        dv = np.roll(v, -1) - np.roll(v, 1)
        n = np.hypot(du, dv)
        n[n < 1e-12] = 1.0
        u = u + (dv / n) * kerf / 2               # normal (dv, -du) points toward smaller v
        v = v - (du / n) * kerf / 2
    path = [(u[0], v[0] - lead_in)] if lead_in > 0 else []
    path += list(zip(u, v))
    path.append((u[0] + Pm, v[0]))
    acc = 0.0
    for i in range(1, len(u)):                  # overcut past the start
        seg = float(np.hypot(u[i] - u[i - 1], v[i] - v[i - 1]))
        if acc + seg > overcut or overcut <= 0:
            if overcut > 0 and seg > 1e-12:
                t = (overcut - acc) / seg
                path.append((u[i - 1] + Pm + (u[i] - u[i - 1]) * t, v[i - 1] + (v[i] - v[i - 1]) * t))
            break
        acc += seg
        path.append((u[i] + Pm, v[i]))
    return np.asarray(path, float)


def _rotation(cut: MitreCut, u: np.ndarray) -> np.ndarray:
    """Tube rotation (deg) that brings the surface point at ``u`` under the torch."""
    pts = np.asarray(cut.points, float)
    uu = pts[:, 0]
    pol = np.asarray(cut.polar, float) if len(cut.polar) == len(uu) else uu / cut.perimeter * 360.0
    ext_u = np.concatenate([uu[:-1] - cut.perimeter, uu, uu[1:] + cut.perimeter, uu[1:] + 2 * cut.perimeter])
    ext_a = np.concatenate([pol[:-1] - 360.0, pol, pol[1:] + 360.0, pol[1:] + 720.0])
    return np.interp(u, ext_u, ext_a)


def mitre_gcode(cut: MitreCut, *, rotary_axis: str = "A", feed: float = 600.0, plunge_feed: float = 200.0,
                units: str = "mm", kerf: float = 0.0, lead_in: float = 3.0, header: str | None = None,
                footer: str | None = None, mode: str = "rotary", inverse_time: bool | None = None,
                pierce_delay: float = 0.0, overcut: float = 1.0, torch_on: str = "M3",
                torch_off: str = "M5", clearance: float = 10.0) -> str:
    """G-code program for one cut.

    ``feed``/``plunge_feed`` are in output units per minute; ``kerf``,
    ``lead_in``, ``overcut`` and ``clearance`` are millimetres.  ``header`` /
    ``footer`` replace the default modal set-up / end blocks (the safety and
    set-up comments are always written)."""
    mode = mode if mode in ("rotary", "wrapped", "flat") else "rotary"
    ax = (rotary_axis or "A").strip().upper()[:1] or "A"
    inch = units == "in"
    k = 1 / 25.4 if inch else 1.0
    nd = 4 if inch else 3
    inv = (mode == "rotary") if inverse_time is None else (bool(inverse_time) and mode == "rotary")
    path = toolpath(cut, kerf, lead_in, overcut)
    pu, pv = path[:, 0], path[:, 1]

    if mode == "rotary":
        rot = _rotation(cut, pu)
        words = [{"X": v * k, ax: a} for v, a in zip(pv, rot)]
    elif mode == "wrapped":
        words = [{"X": v * k, ax: u * k} for u, v in zip(pu, pv)]
    else:
        words = [{"X": u * k, "Y": -v * k} for u, v in zip(pu, pv)]

    def fmt(w: dict) -> str:
        return " ".join(f"{key}{val:.{3 if key == ax and mode == 'rotary' else nd}f}" for key, val in w.items())

    lu = "in" if inch else "mm"
    out = ["%", _comment(f"Bike Box mitre cut: {cut.label}"), "(" + "=" * 66 + ")"]
    out += [_comment(s) for s in SAFETY]
    out.append("(" + "=" * 66 + ")")
    sec = (f"OD {cut.od:.2f}" if abs(cut.od - cut.width) < 1e-6 else f"{cut.od:.2f} deep x {cut.width:.2f} wide")
    out += [
        _comment(f"Tube: {cut.tube_label or cut.tube} [{cut.tube}] end {cut.end} {cut.end_label}".rstrip()),
        _comment(f"Section: {sec} mm, wall {cut.wall:.2f} mm, perimeter {cut.perimeter:.2f} mm"),
        _comment(f"Receivers: {', '.join(cut.receiver_labels or cut.receivers)}; angle {cut.angle:.2f} deg, "
                 f"axis offset {cut.offset:.2f} mm {('toward ' + cut.offset_dir.lower()) if cut.offset_dir else ''}"
                 .rstrip()),
        _comment(f"Long point {cut.long_point:.2f} mm, short point {cut.short_point:.2f} mm from the c-c end point"),
        _comment(f"SETUP ({mode}):"),
    ]
    if mode == "flat":
        out += [_comment("  Plots the unrolled template: X = around the tube from the reference line, "
                         "Y = -axial, Y0 = c-c end point."),
                _comment(f"  X0 = the {cut.ref_name} reference line; X+ toward the {cut.side_name.lower()}.")]
    else:
        out += [_comment("  X0 = the tube's centre-to-centre end point; X+ = toward the tube body."),
                _comment(f"  {ax}0 = {cut.ref_name} reference line under the torch; increasing {ax} moves the torch "
                         f"from {cut.ref_name} toward {cut.side_name}."),
                _comment(f"  If your rotary turns the other way, negate {ax} or mirror the axis."),
                _comment("  Torch on the tube axis, square to the surface; tube clamped with the cut end free.")]
        if mode == "rotary":
            out.append(_comment(f"  {ax} = tube rotation in degrees"
                                + (" [polar angle of the surface point]" if cut.profile != "round" else "")))
        else:
            out.append(_comment(f"  {ax} = surface distance around the tube in {lu} [rotary set up as linear]"))
        if cut.radius and max(cut.radius) - min(cut.radius) > 0.01:
            out.append(_comment(f"  Non-round section: surface radius {min(cut.radius):.2f}-{max(cut.radius):.2f} mm;"
                                f" torch height control required."))
    out.append(_comment(f"Kerf comp {kerf / 2:.2f} mm into the waste; lead-in {lead_in:.1f} mm; "
                        f"overcut {overcut:.1f} mm; feed {feed:g} {lu}/min"
                        + ("; G93 inverse-time F = 1/minutes per move" if inv else "")))
    for n in cut.notes:
        out.append(_comment("Note: " + n))

    if header is None:
        out += ["G21" if not inch else "G20", "G90", "G93" if inv else "G94"]
    else:
        out += [_clean(line) for line in header.splitlines()]

    def feed_word(i: int, f: float) -> str:
        if not inv:
            return f" F{f:g}"
        seg = float(np.hypot(pu[i] - pu[i - 1], pv[i] - pv[i - 1])) * k     # surface distance (output units)
        return f" F{f / max(seg, 1e-6):.4f}"

    out.append("G0 " + fmt(words[0]))
    out.append(torch_on)
    if pierce_delay > 0:
        out.append(f"G4 P{pierce_delay:g}")
    first = 1
    if lead_in > 0:
        out.append("G1 " + fmt(words[1]) + feed_word(1, plunge_feed))
        first = 2
    for i in range(first, len(words)):
        out.append("G1 " + fmt(words[i]) + feed_word(i, feed))
    out.append(torch_off)
    retreat = dict(words[-1])
    if mode == "flat":
        retreat["Y"] = retreat["Y"] + clearance * k
    else:
        retreat["X"] = retreat["X"] - clearance * k             # move off toward the waste
    out.append("G0 " + fmt(retreat))
    if footer is None:
        out += ["G94"] if inv else []
        out += ["M30"]
    else:
        out += [_clean(line) for line in footer.splitlines()]
    out.append("%")
    return "\n".join(out) + "\n"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", _clean(s)).strip("_").lower() or "cut"


def save_gcode(cuts: Sequence[MitreCut], directory, **kwargs) -> list[Path]:
    """Write one ``.nc`` file per cut into ``directory``; returns the paths.
    Keyword arguments are passed to :func:`mitre_gcode`."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, c in enumerate(cuts, 1):
        p = d / f"{i:02d}_{c.tube}_{c.end}_{_slug('_'.join(c.receivers))}.nc"
        p.write_text(mitre_gcode(c, **kwargs), encoding="ascii")
        paths.append(p)
    return paths
