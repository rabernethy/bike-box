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
