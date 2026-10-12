import math

import pytest

from bikebox.geometry import dimensions as D
from bikebox.geometry.solver import solve
from bikebox.geometry.vec import V, arc_through, polyline_length
from bikebox.model.design import Design


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
    p = tmp_path / "x.bikebox"
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
    from bikebox.render.bike_scene import build_scene
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


def _dxf_pairs(text):
    lines = text.splitlines()
    assert len(lines) % 2 == 0
    return [(int(lines[i].strip()), lines[i + 1]) for i in range(0, len(lines), 2)]


def test_dxf_structure(qapp, design):
    """Group-code pairs, balanced sections and POLYLINE/VERTEX/SEQEND nesting."""
    from bikebox.export.dxf import scene_to_dxf
    from bikebox.render.bike_scene import build_scene
    pairs = _dxf_pairs(scene_to_dxf(build_scene(solve(design))))
    depth, in_poly, layers, ents = 0, False, set(), 0
    for code, val in pairs:
        if code == 0 and val == "SECTION":
            depth += 1
        elif code == 0 and val == "ENDSEC":
            depth -= 1
        elif code == 0 and val == "POLYLINE":
            assert not in_poly
            in_poly = True
        elif code == 0 and val == "SEQEND":
            assert in_poly
            in_poly = False
        elif code == 0 and val == "VERTEX":
            assert in_poly
        elif code == 0 and val in ("LINE", "CIRCLE", "ARC", "TEXT"):
            assert not in_poly
            ents += 1
        elif code == 8:
            layers.add(val)
    assert depth == 0 and not in_poly and pairs[-1] == (0, "EOF")
    assert {"FRAME", "WHEELS", "DIMENSIONS"} <= layers and ents > 20


def test_svg_uses_generic_font_fallback(qapp, design):
    from bikebox.export.svg import scene_to_svg
    from bikebox.render.bike_scene import build_scene
    s = scene_to_svg(build_scene(solve(design)))
    assert 'font-family="sans-serif"' in s


def test_head_tube_stickout_mode(design):
    from bikebox.geometry.modes import mode_switch_values
    g0 = solve(design)
    design.update(mode_switch_values(design, "ht_junction_mode", "stickout"))
    g1 = solve(design)
    assert g1.p["tt_ht"].dist(g0.p["tt_ht"]) < 1e-6 and g1.p["dt_ht"].dist(g0.p["dt_ht"]) < 1e-6
    design.set("ht_top_stickout", 10.0)
    design.set("ht_bottom_stickout", 12.0)
    g2 = solve(design)
    assert close(g2.v["ht_top_stickout"], 10.0, 1e-6) and close(g2.v["ht_bottom_stickout"], 12.0, 1e-6)
    assert g2.v["tt_ht_offset"] > 10.0 + design.f("tt_od") / 2      # centre-line sits below the edge


def test_extra_tube_surface_attachment(design):
    from bikebox.geometry.vec import point_line_distance
    design.extras["extra_tubes"] = [
        {"name": "lat", "a": {"tube": "ht", "s": 40, "surface": "above"}, "b": "stay_node", "od": 19},
        {"name": "top", "a": {"tube": "tt", "pos": 0.2, "surface": "above"},
         "b": {"tube": "tt", "s": 50, "from": "b", "surface": "above", "side": 5}, "od": 25.4}]
    g = solve(design)
    ht, tt = g.tubes["ht"], g.tubes["tt"]
    lat, top = g.tubes["x0_lat"], g.tubes["x1_top"]
    assert close(abs(point_line_distance(lat.a, ht.a, ht.b - ht.a)), ht.od_at(40 / ht.length) / 2 + 9.5, 1e-6)
    assert close(abs(point_line_distance(top.a, tt.a, tt.b - tt.a)), tt.od_b / 2 + 12.7, 1e-6)
    assert close(abs(point_line_distance(top.b, tt.a, tt.b - tt.a)), tt.od_b / 2 + 12.7 + 5, 1e-6)
    assert lat.join_a == "ht" and top.join_a == "tt"


def test_tall_bike(design):
    single = solve(design)
    design.set("frame_type", "tall")
    g = solve(design)
    R = g.p["crank_bb"]
    assert close(R.dist(V(0, 0)), design.f("tall_offset"))
    for t in ("uht", "utt", "udt", "ust", "strut_rear"):
        assert t in g.tubes
    # upper head tube coaxial with the lower one
    from bikebox.geometry.vec import point_line_distance
    ht, uht = g.tubes["ht"], g.tubes["uht"]
    assert abs(point_line_distance(uht.a, ht.a, ht.b - ht.a)) < 1e-6
    # the rider moves up as a whole: fit numbers relative to the crank BB are unchanged
    for k in ("saddle_height", "saddle_setback", "saddle_bar_drop", "nose_to_bar"):
        assert close(g.v[k], single.v[k], 1e-6), k
    assert close(g.p["saddle"].dist(R), single.p["saddle"].length(), 1e-6)
    # frame geometry of the lower bike is unchanged
    for k in ("stack", "reach", "wheelbase", "trail", "chainstay_length"):
        assert close(g.v[k], single.v[k], 1e-6), k
    assert g.v["standover"] > single.v["standover"] + 300
    assert g.v["pedal_clearance"] > single.v["pedal_clearance"] + 300


def test_tall_bike_drag_rider_tracks_cursor(design):
    """Dragging the lifted rider points (saddle, pedal) on a tall bike must land
    where the cursor is, not hundreds of mm away because of the frame lift."""
    from bikebox.gui.canvas import drag_point_changes
    design.set("frame_type", "tall")
    g = solve(design)
    # saddle: moving it up 10 mm along the seat axis should raise it ~10 mm
    s0 = g.p["saddle"]
    seat_up = (g.p["st_top"] - g.p["st_bottom"]).norm()
    ch, _ = drag_point_changes("saddle", s0 + seat_up * 10, design, g, False)
    d2 = design.copy(); d2.update(ch)
    assert close(solve(d2).p["saddle"].dist(s0 + seat_up * 10), 0.0, 0.5)
    # pedal: setting crank angle to straight-down puts the pedal below the upper BB
    R = g.p["crank_bb"]
    ch, _ = drag_point_changes("pedal", R + V(0, -100), design, g, False)
    d2 = design.copy(); d2.update(ch)
    ped = solve(d2).p["pedal"]
    assert ped.y < R.y and abs(ped.x - R.x) < 5


def test_tall_bike_rider_pedals_at_upper_bb(design):
    from bikebox.fit.rider import solve_pose
    design.update({"frame_type": "tall", "show_rider": True})
    g = solve(design)
    pose = solve_pose(g)
    assert pose.joints["pedal"].dist(g.p["pedal"]) < 1e-6
    assert 130 < pose.angles["knee_extension_bdc"] < 160


def test_bcad_import_synthetic(tmp_path):
    from bikebox.export.bcad_import import load_bcad
    entries = {"Head angle": 73.0, "Seat angle": 73.5, "Head tube length textfield": 145.0, "FORK0L": 375.0,
               "FORK0R": 45.0, "Fork type": 0, "Lower stack height": 12.0, "BSD rear": 622.0, "BSD front": 622.0,
               "Wheel diameter rear": 674.0, "Wheel diameter front": 674.0, "Wheel width rear": 23.0,
               "Wheel width front": 23.0, "BB measure style": 0, "BB textfield": 70.0, "CS measure style": 0,
               "CS textfield": 405.0, "Top tube front center measure style": 1, "FCD textfield": 595.0,
               "ST measure style": 0, "Seat tube length": 466.0, "Seat tube extension2": 49.2,
               "Head tube upper extension2": 28.9, "Head tube lower extension2": 49.2, "Saddle height": 718.0}
    entries.update({f"pad{i}": 0 for i in range(20)})
    xml = ('<?xml version="1.0" encoding="UTF-8"?><properties>'
           + "".join(f'<entry key="{k}">{v}</entry>' for k, v in entries.items()) + "</properties>")
    p = tmp_path / "x.bcad"
    p.write_text(xml)
    g = solve(load_bcad(p))
    assert close(g.v["stack"], 565.6, 0.05)            # BikeCAD stored 565.6 for this geometry
    assert close(g.v["reach"], 392.3, 0.05)            # same design saved in stack/reach mode stores 392.3
    assert close(g.v["seat_tube_cc"], 466.0) and close(g.v["st_extension"], 49.2)


def test_bcad_import_real_file():
    """A real BikeCAD-saved design (BIKED project, MIT licence; see tests/fixtures/BIKED-LICENSE.txt).
    It is driven by front centre + head tube length; BikeCAD's stored stack (565.6) and the reach it
    stores for the same bike in stack/reach mode (392.3) must come out of Bike Box's solver."""
    from pathlib import Path
    from bikebox.model.design import Design
    d = Design.load(Path(__file__).parent / "fixtures" / "biked_plain_road.bcad")
    g = solve(d)
    assert d["front_v_mode"] == "ht_length" and d["front_h_mode"] == "front_center"
    assert close(g.v["head_tube_length"], 145.0) and close(g.v["front_center"], 595.0)
    assert close(g.v["stack"], 565.6, 0.05)
    assert close(g.v["reach"], 392.3, 0.05)
    assert close(g.v["seat_tube_ct"], 515.2, 1e-6) and close(g.v["seat_tube_cc"], 466.0, 1e-6)
    assert close(d.f("crank_length"), 172.5) and close(g.v["saddle_height"], 718.0)
    assert d.extras["bcad_import"]["entries"] > 6000


def test_bcad_export_round_trip(tmp_path):
    """Writing a design to .bcad and reading it back reproduces the core geometry."""
    from bikebox.export.bcad_import import load_bcad
    d = Design()
    d.update({"title": "RT", "head_tube_angle": 71.5, "seat_tube_angle": 73.5, "chainstay_length": 425,
              "fork_length": 398, "fork_offset": 47, "rear_tire_width": 35, "rear_tire_height": 33,
              "front_tire_width": 35, "front_tire_height": 33, "paint_frame": "#2277cc"})
    g0 = solve(d)
    p = tmp_path / "out.bcad"
    d.save(p)                                   # Design.save dispatches .bcad to the exporter
    g1 = solve(load_bcad(p))
    for k in ("stack", "reach", "head_tube_angle", "seat_tube_angle", "chainstay_length", "bb_drop",
              "wheelbase", "front_center", "trail", "seat_tube_cc"):
        assert close(g0.v[k], g1.v[k], 0.2), f"{k}: {g0.v[k]} vs {g1.v[k]}"
    d2 = load_bcad(p)
    assert d2.get("title") == "RT" and d2.get("paint_frame") == "#2277cc"


def test_bcad_export_is_bikecad_readable(tmp_path):
    from bikebox.export.bcad_import import read_properties
    d = Design()
    p = tmp_path / "out.bcad"
    d.save(p)
    props = read_properties(p)                  # parses as a Java properties XML
    assert "Head angle" in props and len(props) >= 20
