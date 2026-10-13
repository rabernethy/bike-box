"""Maximum tire size."""
from bikebox.analysis import tirefit
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_max_tire_width_reasonable():
    d = Design()
    rear = tirefit.max_tire_width(d, "rear")
    front = tirefit.max_tire_width(d, "front")
    assert rear and rear["width"] > d.f("rear_tire_width")      # room to grow from 32 mm
    assert front and front["width"] >= rear["width"]            # fork usually fits wider than the rear triangle
    assert rear["limited_by"]


def test_max_tire_empty_when_current_interferes():
    d = Design()
    d.update({"rear_tire_width": 70, "rear_tire_height": 63})
    assert tirefit.max_tire_width(d, "rear") == {}


def test_report_has_tire_fit_section():
    from bikebox.analysis.report import full_report
    titles = [s.title for s in full_report(solve(Design()))]
    assert "Tire fit" in titles
