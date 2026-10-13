"""Travel couplings: S&S torque couplers and Ritchey Break-Away."""
import pytest

from bikebox.analysis.report import full_report
from bikebox.geometry.solver import solve
from bikebox.model.design import Design
from bikebox.render.bike_scene import build_scene


def _g(**vals):
    return solve(Design(vals))


def _section(g):
    return next((s for s in full_report(g) if s.title == "Travel coupling"), None)


def test_no_couplers_by_default():
    g = _g()
    assert "coupler_tt" not in g.p
    assert _section(g) is None


def test_s_and_s_places_couplers_on_tube_positions():
    g = _g(couplers=True, coupler_style="s_and_s", coupler_tt_pos=120, coupler_dt_pos=160)
    tt, dt = g.tubes["tt"], g.tubes["dt"]
    # the coupler points sit the requested distance along each tube
    assert g.p["coupler_tt"].dist(tt.point_at(120)[0]) < 1e-6
    assert g.p["coupler_dt"].dist(dt.point_at(160)[0]) < 1e-6
    sec = _section(g)
    assert sec and "S&S" in sec.rows[0][1]


def test_ritchey_splits_at_bb_and_seat_cluster():
    g = _g(couplers=True, coupler_style="ritchey")
    tt, dt = g.tubes["tt"], g.tubes["dt"]
    # down-tube coupler is just above the BB (dt.a), top-tube joint at the seat cluster (tt.a)
    assert g.p["coupler_dt"].dist(dt.a) < 90
    assert g.p["coupler_tt"].dist(tt.a) < 40
    # and distinctly nearer those ends than a mid-tube S&S coupler would be
    assert g.p["coupler_dt"].dist(dt.a) < g.p["coupler_dt"].dist(dt.b)
    sec = _section(g)
    assert sec and "Ritchey" in sec.rows[0][1]


def test_travel_case_fit_warns_when_too_small():
    big = _g(couplers=True, coupler_style="s_and_s", case_length=300, case_width=300)
    assert any("travel case" in w.lower() for w in big.warnings)
    ok = _g(couplers=True, coupler_style="s_and_s", case_length=700, case_width=700)
    assert not any("travel case" in w.lower() for w in ok.warnings)


@pytest.mark.parametrize("style", ["s_and_s", "ritchey"])
def test_coupled_frame_renders(style):
    g = _g(couplers=True, coupler_style=style)
    build_scene(g)                                   # must not raise
    assert "coupler_tt" in g.p and "coupler_dt" in g.p
