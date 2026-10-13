"""Aerodynamic CdA / power estimate."""
import bikebox.fit.rider       # noqa: F401  (rider params)
import bikebox.analysis.report  # noqa: F401  (aero params)
import math

from bikebox.analysis import aero
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_bsa_du_bois_reference():
    # 1.75 m, 70 kg -> ~1.84 m^2
    assert abs(aero.bsa(1.75, 70) - 1.84) < 0.03


def test_default_cda_reasonable():
    e = aero.estimate(solve(Design()))
    assert 0.30 < e["cda"] < 0.45                 # road hoods-ish
    assert 250 < e["p_total"] < 500               # ~40 km/h solo


def test_power_scales_with_cube_of_speed():
    d = Design()
    d.update({"aero_speed": 20})
    p20 = aero.estimate(solve(d))["p_aero"]
    d.update({"aero_speed": 40})
    p40 = aero.estimate(solve(d))["p_aero"]
    assert abs(p40 / p20 - 8) < 0.2               # 2x speed -> ~8x aero power


def test_bigger_rider_more_drag():
    small = Design(); small.update({"rider_height": 1620, "rider_mass": 60})
    big = Design(); big.update({"rider_height": 1950, "rider_mass": 95})
    assert aero.estimate(solve(big))["cda"] > aero.estimate(solve(small))["cda"]


def test_lower_front_end_lowers_cda():
    low = Design(); low.update({"front_v_mode": "stack", "stack": 520})
    hi = Design(); hi.update({"front_v_mode": "stack", "stack": 620})
    assert aero.estimate(solve(low))["cda"] < aero.estimate(solve(hi))["cda"]


def test_report_has_aero_section():
    from bikebox.analysis.report import full_report
    assert "Aerodynamics (estimate)" in [s.title for s in full_report(solve(Design()))]
