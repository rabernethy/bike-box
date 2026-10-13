"""Aerodynamic drag estimate (CdA) and power.

A first-order estimate, clearly labelled as such:

* body surface area from the Du Bois formula (BSA = 0.007184·mass^0.425·height_cm^0.725);
* a position-dependent drag area per the rider's saddle-to-bar drop, interpolating
  typical published bike+rider CdA values (upright ~0.45, hoods ~0.40, drops ~0.32,
  aero ~0.27 for a ~1.75 m / 70 kg rider — Bassett et al., J. Appl. Physiol. 1999
  and common field-test values), scaled by BSA relative to that reference rider;
* steady-state power P = ½·rho·CdA·v³ for air drag, plus rolling and a drivetrain loss.

Real CdA must be measured (wind tunnel / field test); this is for comparison only.
"""
from __future__ import annotations

from ..geometry.solver import Geometry
from ..model import params as P

G, S = "Analysis", "Aerodynamics"
P.register([
    P.ParamDef("aero_speed", "Speed for power estimate", G, S, P.FLOAT, 40.0, "km/h", 5, 80, 1, morph=False),
    P.ParamDef("air_density", "Air density", G, S, P.FLOAT, 1.225, "kg/m^3", 0.9, 1.4, 0.005, morph=False),
    P.ParamDef("crr", "Rolling resistance coefficient", G, S, P.FLOAT, 0.005, "", 0.002, 0.02, 0.0005, morph=False),
    P.ParamDef("drivetrain_eff", "Drivetrain efficiency", G, S, P.FLOAT, 0.97, "", 0.9, 1.0, 0.005, morph=False),
])

BSA_REF = 1.84          # m^2, a 1.75 m / 70 kg rider (Du Bois)
CD = 0.88               # typical bike+rider drag coefficient
# saddle-to-bar drop (mm) -> reference CdA (m^2) for the reference rider
_DROP_CDA = [(-20, 0.45), (40, 0.40), (90, 0.34), (140, 0.30), (190, 0.27)]


def _val(design, key, default):
    v = design.values.get(key, default)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


def anatomy(design) -> tuple[float, float]:
    """(height_m, mass_kg) with estimates when unset."""
    h_mm = _val(design, "rider_height", 1750.0)
    h = h_mm / 1000.0
    m = _val(design, "rider_mass", 0.0)
    if m <= 0:
        m = 22.5 * h * h            # BMI 22.5
    return h, m


def bsa(height_m: float, mass_kg: float) -> float:
    return 0.007184 * (mass_kg ** 0.425) * ((height_m * 100) ** 0.725)


def _interp(x: float, table) -> float:
    if x <= table[0][0]:
        return table[0][1]
    if x >= table[-1][0]:
        return table[-1][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x0 <= x <= x1:
            f = (x - x0) / (x1 - x0)
            return y0 + (y1 - y0) * f
    return table[-1][1]


def estimate(g: Geometry) -> dict:
    d = g.design
    h, m = anatomy(d)
    area = bsa(h, m)
    drop = g.v.get("saddle_bar_drop", 50.0)
    cda_ref = _interp(drop, _DROP_CDA)
    cda = max(0.20, min(0.60, cda_ref * area / BSA_REF))
    frontal = cda / CD
    rho = _val(d, "air_density", 1.225)
    v = _val(d, "aero_speed", 40.0) / 3.6
    g0 = 9.81
    crr = d.values.get("crr", 0.005) or 0.005
    eff = d.values.get("drivetrain_eff", 0.97) or 0.97
    drag = 0.5 * rho * cda * v * v
    p_aero = drag * v
    p_roll = crr * m * g0 * v
    p_total = (p_aero + p_roll) / eff
    return {"height_m": h, "mass_kg": m, "bsa": area, "cda": cda, "frontal_area": frontal,
            "speed_kmh": v * 3.6, "drag_n": drag, "p_aero": p_aero, "p_roll": p_roll, "p_total": p_total,
            "drop_mm": drop}


def report_rows(g: Geometry):
    e = estimate(g)
    return [
        ("Estimated CdA", f"{e['cda']:.3f} m² (frontal ≈ {e['frontal_area']:.3f} m²)", "info"),
        ("Position (saddle-to-bar drop)", f"{e['drop_mm']:.0f} mm", "info"),
        ("Body surface area (Du Bois)", f"{e['bsa']:.2f} m² ({e['height_m']:.2f} m, {e['mass_kg']:.0f} kg)", "info"),
        (f"Air drag at {e['speed_kmh']:.0f} km/h", f"{e['drag_n']:.1f} N · {e['p_aero']:.0f} W", "info"),
        (f"Total power at {e['speed_kmh']:.0f} km/h", f"{e['p_total']:.0f} W (incl. rolling + drivetrain)", "info"),
    ]
