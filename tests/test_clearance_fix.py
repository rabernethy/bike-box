"""Automatic tire-clearance fixes."""
import pytest

from bikebox.geometry import clearance as C
from bikebox.geometry.clearance_fix import merged_changes, plan_fixes, tire_problems
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def _wide(width, **kw):
    d = Design()
    d.update({"rear_tire_width": width, "rear_tire_height": width * 0.92, "front_tire_width": width,
              "front_tire_height": width * 0.92, **kw})
    return d


@pytest.mark.parametrize("width,extra", [(45, {}), (50, {}), (50, {"fenders": True}), (55, {})])
def test_fixes_make_the_tires_fit(width, extra):
    d = _wide(width, **extra)
    assert tire_problems(solve(d))
    plan = plan_fixes(d)
    assert plan.fixes
    d2 = d.copy()
    d2.update(merged_changes(plan.fixes))
    g2 = solve(d2)
    assert tire_problems(g2) == {}
    # no new non-toe problems appear
    before = {p.split(" ")[0] for p in C.problems(solve(d))}
    assert all("Toe" in p or p.split(" ")[0] in before for p in C.problems(g2))


def test_crown_fix_keeps_stack_and_reach():
    d = _wide(50, fenders=True)
    plan = plan_fixes(d)
    crown = [f for f in plan.fixes if f.key.startswith("fork_crown")]
    assert crown and "fork_length" in crown[0].changes
    g0, g1 = solve(d), solve(plan.design)
    assert abs(g1.v["stack"] - g0.v["stack"]) < 1e-6
    assert abs(g1.v["reach"] - g0.v["reach"]) < 1e-6


def test_cheap_remedies_before_geometry_changes():
    plan = plan_fixes(_wide(45))
    ch = merged_changes(plan.fixes)
    assert "chainstay_length" not in ch and "fork_length" not in ch


def test_nothing_to_fix_on_clean_design():
    plan = plan_fixes(Design())
    assert plan.fixes == [] and plan.remaining == []
