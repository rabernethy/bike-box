"""STEP / IGES B-rep solid export.

The tube solids are faceted and un-mitred (the STL tessellation), and there is
no CAD kernel to validate against, so each writer is proven correct by an
independent re-parser that must reconstruct the *same* closed, orientable
manifolds with the *same* bounds.
"""
import math

import pytest

from bikebox.export import iges, mesh, step
from bikebox.geometry.solver import solve
from bikebox.model.design import Design

VARIANTS = [
    {},                                                   # default road frame
    {"tt_bend": 12, "cs_bend": -6},                       # bent tubes
    {"dt_profile": "oval", "dt_od2": 40},                 # oval section
    {"ss_style": "wishbone"},
    {"frame_type": "step-through"},
]


def _geom(vals):
    return solve(Design(vals))


# -- mesh core -------------------------------------------------------------------
@pytest.mark.parametrize("vals", VARIANTS)
def test_frame_solids_are_closed_manifolds(vals):
    solids = mesh.frame_solids(_geom(vals), segments=24)
    assert solids, "expected at least the main tubes + BB"
    for s in solids:
        r = mesh.check_manifold(s)
        assert r.ok, f"{s.name}: {r.problems}"
        assert r.euler == 2                               # genus-0 closed solid


def test_mirrored_tubes_give_two_solids():
    names = [s.name for s in mesh.frame_solids(_geom({}), segments=12)]
    assert any("drive side" in n for n in names)
    assert any("non-drive side" in n for n in names)


def test_check_manifold_rejects_open_mesh():
    # a single triangle is not closed
    s = mesh.Solid("t", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
    assert not mesh.check_manifold(s).ok


def test_higher_segments_more_facets():
    a = mesh.frame_solids(_geom({}), segments=16)[0]
    b = mesh.frame_solids(_geom({}), segments=48)[0]
    assert len(b.verts) > len(a.verts)


# -- STEP ------------------------------------------------------------------------
@pytest.mark.parametrize("vals", VARIANTS)
def test_step_round_trips(vals):
    g = _geom(vals)
    txt = step.build_step(g, segments=24)
    assert txt.startswith("ISO-10303-21;")
    assert txt.rstrip().endswith("END-ISO-10303-21;")
    assert "MANIFOLD_SOLID_BREP" in txt and "ADVANCED_BREP_SHAPE_REPRESENTATION" in txt

    src = mesh.frame_solids(g, segments=24)
    back = step.parse_step_solids(txt)
    assert len(back) == len(src)
    for a, b in zip(src, back):
        assert len(a.verts) == len(b.verts)
        assert len(a.faces) == len(b.faces)
        assert mesh.check_manifold(b).ok
    assert _bounds(src) == pytest.approx(_bounds(back), abs=1e-3)


def test_step_reals_are_valid_part21():
    # no bare integers where reals belong, exponents uppercase with a decimal point
    assert step._r(5) == "5."
    assert step._r(1e-5) == "1.E-05"
    assert step._r(-12.5) == "-12.5"
    assert "e" not in step._r(1e12)


def test_step_declares_millimetres():
    txt = step.build_step(_geom({}), segments=12)
    assert "SI_UNIT(.MILLI.,.METRE.)" in txt


# -- IGES ------------------------------------------------------------------------
@pytest.mark.parametrize("vals", VARIANTS)
def test_iges_round_trips(vals):
    g = _geom(vals)
    txt = iges.build_iges(g, segments=24)
    lines = txt.splitlines()
    assert all(len(ln) == 80 for ln in lines), "every IGES line must be 80 columns"
    codes = {ln[72] for ln in lines}
    assert {"S", "G", "D", "P", "T"} <= codes

    src = mesh.frame_solids(g, segments=24)
    back = iges.parse_iges_solids(txt)
    assert len(back) == len(src)
    for a, b in zip(src, back):
        assert len(a.verts) == len(b.verts)
        assert len(a.faces) == len(b.faces)
        assert mesh.check_manifold(b).ok
    assert _bounds(src) == pytest.approx(_bounds(back), abs=1e-3)


def test_iges_terminate_counts_match():
    txt = iges.build_iges(_geom({}), segments=12)
    lines = txt.splitlines()
    term = lines[-1]
    assert term[72] == "T"
    s = sum(1 for ln in lines if ln[72] == "S")
    gg = sum(1 for ln in lines if ln[72] == "G")
    d = sum(1 for ln in lines if ln[72] == "D")
    p = sum(1 for ln in lines if ln[72] == "P")
    assert term[0:8].replace(" ", "") == f"S{s}"
    assert term[8:16].replace(" ", "") == f"G{gg}"
    assert term[16:24].replace(" ", "") == f"D{d}"
    assert term[24:32].replace(" ", "") == f"P{p}"


# -- file writers ----------------------------------------------------------------
def test_save_step_and_iges(tmp_path):
    g = _geom({})
    sp = step.save_step(g, tmp_path / "frame.step", segments=12)
    ip = iges.save_iges(g, tmp_path / "frame.iges", segments=12)
    assert sp.exists() and sp.read_text().startswith("ISO-10303-21;")
    assert ip.exists() and ip.read_text().splitlines()[-1][72] == "T"


def _bounds(solids):
    allv = [v for s in solids for v in s.verts]
    xs, ys, zs = zip(*allv)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
