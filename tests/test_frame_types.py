"""Frame types added beyond single/tandem/tall: balance (baby) bike, cargo
longtail and folder."""
import pytest

from bikebox.analysis.report import full_report
from bikebox.export import mesh
from bikebox.geometry import clearance as C
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def _solve(ft, **extra):
    return solve(Design({"frame_type": ft, **extra}))


# -- balance / baby bike ---------------------------------------------------------
def test_balance_bike_has_no_drivetrain():
    g = _solve("balance", rear_bsd=305, front_bsd=305)   # 16" kid wheels
    assert C.chainrings(g) == []
    assert not C.has_drivetrain(g)
    cl = C.clearances(g)
    # the drivetrain-only clearances are simply absent (not interferences)
    for k in ("cs_chainring", "cs_crank", "heel", "heel_cs", "heel_ss", "lean_angle_3d"):
        assert k not in cl
    # still a valid single-style frame with a tire clearance
    assert "cs_tire" in cl


def test_balance_bike_report_states_no_drivetrain():
    g = _solve("balance")
    secs = {s.title: s for s in full_report(g)}
    assert "balance" in secs["Gearing"].rows[0][1].lower()
    assert "balance" in secs["Chain"].rows[0][1].lower()


def test_geared_bike_still_has_drivetrain():
    g = _solve("single")
    assert C.chainrings(g)
    assert C.has_drivetrain(g)
    assert "cs_crank" in C.clearances(g)


# -- cargo longtail --------------------------------------------------------------
def test_longtail_adds_rear_deck():
    g = _solve("longtail")
    deck = [n for n in g.tubes if n.startswith("lt_")]
    assert set(deck) == {"lt_deck", "lt_lower", "lt_rear", "lt_brace"}
    # the deck extends behind the rear axle
    assert g.v["longtail_deck_x"] < g.p["rear_axle"].x
    assert g.v["longtail_length"] == pytest.approx(g.design.f("longtail_length"))


def test_longtail_deck_length_param():
    short = _solve("longtail", longtail_length=300)
    long = _solve("longtail", longtail_length=700)
    assert long.v["longtail_deck_x"] < short.v["longtail_deck_x"]   # longer = further back


def test_longtail_solids_are_closed():
    g = _solve("longtail")
    solids = mesh.frame_solids(g, segments=16)
    assert len(solids) > len(mesh.frame_solids(_solve("single"), segments=16))
    for s in solids:
        assert mesh.check_manifold(s).ok, s.name


# -- folder ----------------------------------------------------------------------
def test_folder_marks_hinge_on_down_tube():
    g = _solve("folder", fold_hinge_pos=0.4)
    hinges = [b for b in g.brazeons if b["type"] == "hinge"]
    assert len(hinges) == 1
    assert hinges[0]["tube"] == "dt"
    assert g.v["fold_hinge_pos"] == pytest.approx(0.4)
    # the hinge point lies on the down-tube centreline
    dt = g.tubes["dt"]
    expect = dt.a.lerp(dt.b, 0.4)
    assert g.p["fold_hinge"].dist(expect) < 1e-6


# -- all new types solve & report cleanly ----------------------------------------
@pytest.mark.parametrize("ft", ["balance", "longtail", "folder"])
def test_new_frame_types_solve_and_report(ft):
    g = _solve(ft)
    assert not g.warnings
    sections = full_report(g)
    assert sections and all(s.title for s in sections)
