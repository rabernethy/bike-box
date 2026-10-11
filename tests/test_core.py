import math

import pytest

from framewright.geometry import dimensions as D
from framewright.geometry.solver import solve
from framewright.geometry.vec import V, arc_through, polyline_length
from framewright.model.design import Design


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_trail_matches_closed_form(design):
    g = solve(design)
    R = design.f("front_bsd") / 2 + design.f("front_tire_height")
    h = math.radians(design.f("head_tube_angle"))
    expected = (R * math.cos(h) - design.f("fork_offset")) / math.sin(h)
    assert close(g.v["trail"], expected, 1e-6)


@pytest.mark.parametrize("vmode,hmode", [
    ("stack", "reach"), ("ht_length", "front_center"), ("ht_length", "ett"), ("stack", "wheelbase"),
    ("bar_y", "bar_x"),
])
def test_front_end_modes_are_consistent(vmode, hmode):
    """Feeding the solved outputs back in through another mode reproduces the design."""
    base = Design()
    g0 = solve(base)
    d = base.copy()
    d.set("front_v_mode", vmode)
    d.set("front_h_mode", hmode)
    d.set("stack", g0.v["stack"])
    d.set("front_center", g0.v["front_center"])
    d.set("top_tube_effective", g0.v["top_tube_effective"])
    d.set("wheelbase", g0.v["wheelbase"])
    d.set("bar_x", g0.v["bar_x"])
    d.set("bar_y", g0.v["bar_y"])
    g = solve(d)
    for k in ("stack", "reach", "head_tube_length", "front_center", "wheelbase", "trail"):
        assert close(g.v[k], g0.v[k], 1e-6), k


def test_chainstay_and_bb_drop(design):
    g = solve(design)
    assert close(g.v["chainstay_length"], design.f("chainstay_length"))
    assert close(g.p["rear_axle"].y, design.f("bb_drop"))
    assert close(g.ground_y, -(design.f("rear_bsd") / 2 + design.f("rear_tire_height") - design.f("bb_drop")))


def test_bb_height_mode(design):
    design.set("bb_mode", "height")
    design.set("bb_height", 290)
    g = solve(design)
    assert close(g.v["bb_height"], 290)


def test_tire_gap_mode(design):
    design.set("cs_mode", "tire_gap")
    design.set("rear_tire_gap", 10)
    g = solve(design)
    assert close(g.v["rear_tire_clearance"] + 0.0, 10, 1.0)    # within taper approximation


def test_seat_tube_cc_and_extension(design):
    design.set("st_length_mode", "cc")
    design.set("seat_tube_length", 500)
    design.set("st_extension", 30)
    g = solve(design)
    assert close(g.v["seat_tube_cc"], 500)
    assert close(g.v["st_extension"], 30)


def test_top_tube_angle_mode(design):
    design.set("tt_mode", "angle")
    design.set("top_tube_angle", 4.0)
    design.set("seat_tube_length", 600)
    g = solve(design)
    assert close(g.v["top_tube_angle"], 4.0, 1e-6)


def test_saddle_height_along_seat_tube_has_no_setback(design):
    g = solve(design)
    assert abs(g.v["seatpost_setback"]) < 1e-6
    assert close(g.v["saddle_height"], design.f("saddle_height"))


def test_lug_angles_equal_frame_angles_for_level_top_tube(design):
    design.set("tt_mode", "angle")
    design.set("top_tube_angle", 0)
    design.set("seat_tube_length", 650)
    g = solve(design)
    assert close(g.v["angle_ht_tt"], design.f("head_tube_angle"), 1e-6)
    assert close(g.v["angle_st_tt"], design.f("seat_tube_angle"), 1e-6)


def test_arc_through_sagitta():
    a, b = V(0, 0), V(100, 0)
    pts = arc_through(a, b, 10, 64)
    assert close(pts[0].x, 0, 1e-9) and close(pts[-1].x, 100, 1e-9)
    mid = pts[32]
    assert close(mid.y, 10, 1e-6)
    pts2 = arc_through(a, b, -10, 64)
    assert close(pts2[32].y, -10, 1e-6)
    assert polyline_length(pts) > 100


def test_dimension_catalog_builds(geometry):
    for dd in D.CATALOG:
        out = dd.build(geometry)
        assert "value" in out and out["value"] == out["value"]


def test_design_roundtrip(tmp_path, design):
    design.set("stack", 600)
    design.extras["notes"].append({"id": "n1", "x": 1, "y": 2, "text": "hi"})
    p = tmp_path / "x.fwd"
    design.save(p)
    d2 = Design.load(p)
    assert d2["stack"] == 600
    assert d2.extras["notes"][0]["text"] == "hi"
    assert not d2.diff(design)


def test_lerp_interpolates(design):
    b = design.copy()
    b.set("head_tube_angle", 70)
    m = Design.lerp(design, b, 0.5)
    assert close(m["head_tube_angle"], (design.f("head_tube_angle") + 70) / 2)


def test_scene_builds_all_modes(qapp, design):
    from framewright.render.bike_scene import build_scene
    for mode in ("filled", "outline", "centerline", "blueprint"):
        for joint in ("tig", "lugged", "fillet"):
            design.set("display_mode", mode)
            design.set("joint_style", joint)
            sc = build_scene(solve(design))
            assert len(sc.prims) > 50


def test_tandem_geometry(design):
    single = solve(design)
    design.set("frame_type", "tandem")
    design.set("tandem_bb_distance", 760)
    g = solve(design)
    sb = g.p["drive_bb"]
    assert close(sb.x, -760) and close(sb.y, 0)
    # chainstay measured from the stoker BB; front end unchanged
    assert close(g.v["chainstay_length"], design.f("chainstay_length"))
    for k in ("stack", "reach", "front_center", "trail"):
        assert close(g.v[k], single.v[k]), k
    assert close(g.v["wheelbase"], single.v["wheelbase"] + 760)
    for t in ("st2", "tt2", "boom", "mid"):
        assert t in g.tubes
    assert g.tubes["cs"].join_b == "bb2" and g.tubes["ss"].join_b == "st2"
    assert "stoker_saddle" in g.p and "stoker_bar" in g.p
