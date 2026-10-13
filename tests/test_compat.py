"""Component-compatibility checks."""
from bikebox.analysis import compat
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def _levels(d):
    return {(l, s) for s, l, _m in compat.check(solve(d))}


def test_clean_design_is_compatible():
    res = compat.check(solve(Design()))
    assert all(s != "fail" for s, _l, _m in res)


def test_seatpost_too_big_fails():
    d = Design()
    d.update({"seatpost_od": 31.6, "st_od": 28.6, "st_wall_end": 0.9})
    assert ("Seatpost", "fail") in _levels(d)


def test_thru_axle_spacing_mismatch_warns():
    d = Design()
    d.update({"dropout_type": "thru", "rear_hub_spacing": 135})
    assert ("Rear axle", "warn") in _levels(d)


def test_belt_drive_needs_frame_break():
    d = Design()
    d.update({"drive_type": "belt", "dropout_type": "vertical", "couplers": False})
    assert ("Belt drive", "warn") in _levels(d)
    d.update({"dropout_type": "sliding"})
    assert ("Belt drive", "warn") not in _levels(d)


def test_report_includes_compatibility_section():
    from bikebox.analysis.report import full_report
    titles = [s.title for s in full_report(solve(Design()))]
    assert "Compatibility" in titles


def test_derailleur_capacity_and_max_cog():
    d = Design()
    d.update({"chainrings": "50, 34", "cogs": "11, 13, 15, 17, 19, 21, 24, 28, 32, 36, 40",
              "rd_capacity": 39, "rd_max_cog": 34})
    levels = _levels(d)
    assert ("Derailleur capacity", "fail") in levels
    assert ("Derailleur max cog", "fail") in levels
    # a matching big-capacity RD clears it
    d.update({"rd_capacity": 45, "rd_max_cog": 40})
    levels = _levels(d)
    assert ("Derailleur capacity", "fail") not in levels


def test_drivetrain_range_math():
    from bikebox.analysis.gearing import drivetrain_range
    d = Design()
    d.update({"chainrings": "46, 30", "cogs": "11, 28"})
    dr = drivetrain_range(d)
    assert dr["front_range"] == 16 and dr["rear_range"] == 17 and dr["required_capacity"] == 33
    assert dr["max_cog"] == 28
