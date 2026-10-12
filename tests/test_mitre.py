"""Mitre (coping) geometry, templates and G-code."""
import math
import re
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from bikebox.geometry import mitre as M
from bikebox.geometry.solver import solve
from bikebox.model.design import Design

X3, Y3, Z3 = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])


def _profile(receivers, a, b=None, samples=360, **kw):
    """Cut tube along +X ending at the origin; e1 = +Y (reference), e2 = +Z (drive side)."""
    return M.cope_profile(np.zeros(3), X3, Y3, Z3, a, a if b is None else b, receivers, samples, **kw)


def closed_form(phi, R, r, theta_deg, e=0.0):
    """v(φ) = sqrt(R² − (r sinφ + e)²)/sinθ + r cosφ/tanθ for a cylinder of radius R whose
    axis lies along (cosθ, −sinθ, 0) through (0, 0, −e), φ measured from +Y toward +Z."""
    th = math.radians(theta_deg)
    return np.sqrt(R ** 2 - (r * np.sin(phi) + e) ** 2) / math.sin(th) + r * np.cos(phi) / math.tan(th)


# ---------------------------------------------------------------------------- closed forms
def test_equal_perpendicular_cylinders():
    r = 14.3
    rec = M.Receiver.cylinder((0, 0, 0), Y3, r)
    p = _profile([rec], r)
    expected = np.sqrt(np.maximum(r ** 2 - (r * np.sin(p.phi)) ** 2, 0.0))
    assert np.max(np.abs(p.v - expected)) < 1e-6
    assert p.perimeter == pytest.approx(2 * math.pi * r)
    assert p.v.min() == pytest.approx(0.0, abs=1e-6) and p.v.max() == pytest.approx(r)
    assert not p.missed.any()                   # grazing lines at the sides count as contact


@pytest.mark.parametrize("theta", [45.0, 60.0, 72.0, 90.0, 110.0])
@pytest.mark.parametrize("e", [0.0, 3.0, -4.5])
def test_angled_and_offset_cylinder_joint(theta, e):
    R, r = 18.0, 12.7
    th = math.radians(theta)
    rec = M.Receiver.cylinder((0, 0, -e), (math.cos(th), -math.sin(th), 0), R)
    p = _profile([rec], r)
    assert np.max(np.abs(p.v - closed_form(p.phi, R, r, theta, e))) < 1e-6


def test_offset_axes_reported_in_compute_mitres():
    d = Design()
    d.set("dt_bb_offset", 8.0)
    cut = _cut(M.compute_mitres(solve(d)), "dt", "a")
    assert cut.angle == pytest.approx(90.0)
    assert cut.offset == pytest.approx(8.0, abs=1e-6)
    assert cut.holesaw_offset == pytest.approx(cut.offset)
    assert cut.offset_dir in ("TOP", "BOTTOM")


def test_cone_equal_ends_is_cylinder_and_taper_closed_form():
    R, r = 18.0, 12.7
    th = math.radians(72)
    axis = (math.cos(th), -math.sin(th), 0)
    cyl = _profile([M.Receiver.cylinder((0, 0, 0), axis, R)], r)
    cone = _profile([M.Receiver.cone(-np.array(axis) * 75.0, axis, R, R, 150.0)], r)
    assert np.max(np.abs(cyl.v - cone.v)) < 1e-9
    # perpendicular joint on a real cone (axis +Y, radius R0 at y = 0, growing k per mm)
    R0, k = 20.0, 0.04
    cone = M.Receiver.cone((0, -75, 0), Y3, R0 - 75 * k, R0 + 75 * k, 150.0)
    p = _profile([cone], r, samples=360)
    assert p.v[0] == pytest.approx(R0 + k * r, abs=1e-6)         # top line passes the axis at y = r
    assert p.v[180] == pytest.approx(R0 - k * r, abs=1e-6)       # bottom line at y = -r
    assert p.v[90] == pytest.approx(math.sqrt(R0 ** 2 - r ** 2), abs=1e-6)   # sides at y = 0


def test_oval_receiver_and_oval_cut_tube():
    r = 12.0
    A, B = 22.0, 15.0                      # receiver semi-axes along X (cut axis) and Z (lateral)
    rec = M.Receiver.loft((0, -50, 0), Y3, X3, A, A, B, B, length=100.0)
    p = _profile([rec], r)
    expected = A * np.sqrt(1 - (r * np.sin(p.phi)) ** 2 / B ** 2)
    assert np.max(np.abs(p.v - expected)) < 1e-6
    # elliptical cut tube (semi-depth a along Y, semi-width b along Z) into a round receiver
    a, b, R = 10.0, 16.0, 20.0
    p = _profile([M.Receiver.cylinder((0, 0, 0), Y3, R)], a, b)
    assert np.max(np.abs(p.v - np.sqrt(R ** 2 - (b * np.sin(p.phi)) ** 2))) < 1e-6
    h = ((a - b) / (a + b)) ** 2
    ramanujan = math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))
    assert p.perimeter == pytest.approx(ramanujan, rel=1e-6)
    assert np.all(np.diff(p.u) > 0)


def test_multiple_receivers_take_the_cut_closest_to_the_body():
    r = 12.0
    near = M.Receiver.cylinder((0, 0, 0), Y3, 15.0)
    far = M.Receiver.cylinder((-3.0, 0, 0), Z3, 10.0, length=40.0, cap_lo=False, cap_hi=False)
    p = _profile([near, far], r)
    single = _profile([near], r)
    assert np.all(p.v >= single.v - 1e-9)
    assert (p.winner == 1).any() and (p.winner == 0).any()


# ---------------------------------------------------------------------------- frame cuts
def _cut(cuts, tube, end):
    return next(c for c in cuts if c.tube == tube and c.end == end)


def _level_tt_design():
    d = Design()
    d.set("tt_mode", "angle")
    d.set("top_tube_angle", 0.0)
    d.set("seat_tube_length", 600)
    return d


def test_top_tube_head_tube_matches_closed_form():
    d = _level_tt_design()
    g = solve(d)
    cut = _cut(M.compute_mitres(g), "tt", "b")
    R, r = d.f("ht_od_top") / 2, d.f("tt_od") / 2
    phi = np.array([u for u, _ in cut.points]) / r
    v = np.array([v for _, v in cut.points])
    assert cut.angle == pytest.approx(d.f("head_tube_angle"))
    assert np.max(np.abs(v - closed_form(phi, R, r, d.f("head_tube_angle")))) < 1e-6
    assert cut.receivers == ["ht"] and cut.phase == 0.0 and cut.offset == 0.0
    assert cut.holesaw_diameter == pytest.approx(2 * R)
    assert cut.long_point == pytest.approx(v.min()) and cut.short_point == pytest.approx(v.max())


def test_tapered_head_tube():
    d = _level_tt_design()
    d.set("ht_od_top", 36.0)
    d.set("ht_od_bottom", 36.0)
    base = M.compute_mitres(solve(d))
    d.set("ht_od_bottom", 56.0)
    tapered = M.compute_mitres(solve(d))
    for tube in ("tt", "dt"):
        a, b = _cut(base, tube, "b"), _cut(tapered, tube, "b")
        side = len(a.points) // 4                     # side lines pass the head tube at the joint height
        assert b.points[side][1] > a.points[side][1]  # wider head tube there: deeper cope
        assert b.holesaw_diameter > a.holesaw_diameter
    assert _cut(tapered, "dt", "b").short_point > _cut(base, "dt", "b").short_point
    assert _cut(tapered, "dt", "b").holesaw_diameter > _cut(tapered, "tt", "b").holesaw_diameter
    assert _cut(tapered, "dt", "b").holesaw_diameter < 56.0


def test_in_plane_cuts_are_laterally_symmetric(geometry):
    for c in M.compute_mitres(geometry):
        if c.tube not in ("tt", "dt", "st"):
            continue
        u = np.array([p[0] for p in c.points])
        v = np.array([p[1] for p in c.points])
        mirrored = np.interp(c.perimeter - u, u, v)
        assert np.max(np.abs(v - mirrored)) < 1e-6, (c.tube, c.end)
        assert c.phase == 0.0


def test_stays_are_three_dimensional(geometry):
    cuts = M.compute_mitres(geometry)
    cs, ss = _cut(cuts, "cs", "b"), _cut(cuts, "ss", "b")
    for c in (cs, ss):
        assert c.mirrored and np.all(np.isfinite(c.v))
        assert c.axis[2] != 0.0                       # the stay axis has a lateral component
    assert cs.receivers == ["bb"] and cs.saw_rotation == pytest.approx(90.0, abs=1e-6)
    assert cs.angle < 90.0
    assert abs(ss.phase) > 0.5 and abs(ss.phase) < 45.0
    u = np.array(ss.u)
    v = np.array(ss.v)
    assert np.max(np.abs(v - np.interp(ss.perimeter - u, u, v))) > 0.01   # not mirror-symmetric
    m = ss.mirror()
    assert m.phase == pytest.approx(-ss.phase)
    assert np.allclose(sorted(m.v), sorted(ss.v))


def test_stays_meeting_the_seat_tube_and_wishbone():
    d = Design()
    d.set("ss_spread_top", 30.0)               # stays now overlap the seat tube
    ss = _cut(M.compute_mitres(solve(d)), "ss", "b")
    assert 0.2 < ss.contact < 1.0                  # inner half wraps the seat tube, outer half trimmed
    assert ss.depth > 1.0
    wide = Design()
    wide.set("ss_spread_top", 46.0)
    assert _cut(M.compute_mitres(solve(wide)), "ss", "b").contact == 0.0       # 46 mm spread: clear of it
    assert _cut(M.compute_mitres(solve(Design())), "ss", "b").contact > 0.2    # automatic spread: wraps the ST
    d.set("ss_style", "wishbone")
    cuts = M.compute_mitres(solve(d))
    assert _cut(cuts, "ss", "b").receivers[0] == "ss_mono"
    assert _cut(cuts, "ss_mono", "b").receivers[0] == "st"


def test_down_tube_coped_to_head_tube_and_top_tube():
    d = Design()
    d.set("head_tube_length", 90.0)
    d.set("tt_ht_offset", 20.0)
    d.set("dt_ht_offset", 65.0)                 # junctions 5 mm apart: the tubes overlap at the head tube
    g = solve(d)
    dt = _cut(M.compute_mitres(g), "dt", "b")
    assert dt.receivers == ["ht", "tt"] and "top tube" in dt.label
    only_ht = M.cope_profile(dt.end_point, dt.axis, dt.ref_dir, dt.side_dir, dt.od / 2, dt.width / 2,
                             [M.receiver_from_tube(g.tubes["ht"], np.array(dt.end_point))], 360)
    v = np.array(dt.v)
    assert np.all(v >= only_ht.v - 1e-6) and np.max(v - only_ht.v) > 0.5
    assert v[0] - only_ht.v[0] > 0.5             # the top-tube side (reference line) is cut deeper


def test_cut_lengths(geometry):
    cuts = M.compute_mitres(geometry)
    L = M.cut_lengths(geometry, cuts)
    assert {"tt", "dt", "st", "cs", "ss"} <= set(L)
    for name, info in L.items():
        assert {"cc", "long_to_long", "short_to_short", "min_stock", "phase"} <= set(info)
        assert info["cc"] >= info["long_to_long"] >= info["short_to_short"]
        assert info["min_stock"] > info["long_to_long"]
    tt = L["tt"]
    a, b = _cut(cuts, "tt", "a"), _cut(cuts, "tt", "b")
    assert tt["cc"] == pytest.approx(geometry.tubes["tt"].length)
    assert tt["long_to_long"] == pytest.approx(tt["cc"] - a.long_point - b.long_point)


VARIANTS = {
    "default": {},
    "lugged": {"joint_style": "lugged"},
    "oval": {"tt_profile": "oval", "tt_od2": 40.0, "dt_profile": "oval", "dt_od2": 45.0, "st_profile": "aero",
             "st_od2": 22.0},
    "tapered": {"ht_od_bottom": 56.0, "ht_od_top": 44.0, "st_od_end": 34.9, "dt_od_end": 38.0},
    "wishbone": {"ss_style": "wishbone"},
    "mono": {"ss_style": "mono"},
    "tt_stays": {"ss_attach": "top_tube", "ss_offset": 40},
    "bent": {"tt_bend": 15.0, "cs_bend": 8.0, "ss_bend": -6.0},
    "step_through": {"remove_tubes": "tt"},
    "big_offsets": {"dt_bb_offset": 20.0, "st_bb_offset": -15.0, "dt_ht_offset": 5.0, "tt_ht_offset": 2.0},
}


@pytest.mark.parametrize("name", list(VARIANTS))
def test_compute_mitres_variants(name):
    d = Design()
    for k, v in VARIANTS[name].items():
        d.set(k, v)
    if name == "default":
        d.extras["extra_tubes"] = [{"name": "brace", "a": {"tube": "tt", "pos": 0.5},
                                    "b": {"tube": "dt", "pos": 0.5}, "od": 19.0}]
    g = solve(d)
    cuts = M.compute_mitres(g, samples=180)
    assert cuts
    for c in cuts:
        assert len(c.points) == 181
        v = np.array(c.v)
        assert np.all(np.isfinite(v)) and c.perimeter > 0
        assert c.points[0][0] == 0.0 and c.points[-1][0] == pytest.approx(c.perimeter)
        assert c.long_point <= c.short_point
        assert 0.0 <= c.angle <= 90.0 and c.offset >= 0.0
        assert c.receivers and c.label
    M.cut_lengths(g, cuts)
    if name == "default":
        brace = [c for c in cuts if c.tube.startswith("x0_")]
        assert {c.end for c in brace} == {"a", "b"}
        assert {c.receivers[0] for c in brace} == {"tt", "dt"}
    if name == "oval":
        tt = _cut(cuts, "tt", "b")
        assert tt.width == pytest.approx(40.0) and tt.perimeter > math.pi * 28.6
    if name == "step_through":
        assert not any(c.tube == "tt" for c in cuts)


# ---------------------------------------------------------------------------- outputs
def _big_cut():
    r = 60.0
    rec = M.Receiver.cylinder((0, 0, 0), (math.cos(math.radians(35)), -math.sin(math.radians(35)), 0), 62.0)
    p = _profile([rec], r, samples=180)
    return M.MitreCut("x", "b", "Big tube → big receiver", ["r"], 2 * r, 2 * r, 2.0, p.perimeter,
                      [(float(u), float(v)) for u, v in zip(p.u, p.v)], 35.0, 0.0, float(p.v.min()),
                      float(p.v.max()), 124.0, 55.0, 0.0, 0.0, polar=list(map(float, p.polar)),
                      radius=list(map(float, p.radius)))


def _pages(path):
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", path.read_bytes()))


def test_template_scene(geometry):
    from bikebox.export.mitre_output import mitre_template_scene
    from bikebox.render.scene import Polyline, Text
    cut = _cut(M.compute_mitres(geometry), "tt", "b")
    sc = mitre_template_scene(cut, "Test")
    texts = " ".join(p.text for p in sc.prims if isinstance(p, Text))
    for word in ("TOP", "DRIVE SIDE", "BOTTOM", "NON-DRIVE SIDE", "print at 100% — verify 50 mm", "LONG",
                 "SHORT", "Hole saw", "Phase", "head tube"):
        assert word in texts, word
    cal = [p for p in sc.prims if isinstance(p, Polyline) and p.layer == "mitre_calibration" and p.closed]
    xs = [q.x for q in cal[0].pts]
    ys = [q.y for q in cal[0].pts]
    assert max(xs) - min(xs) == pytest.approx(50.0) and max(ys) - min(ys) == pytest.approx(50.0)
    outline = next(p for p in sc.prims if isinstance(p, Polyline) and p.layer == "mitre_outline")
    assert max(q.x for q in outline.pts) - min(q.x for q in outline.pts) == pytest.approx(cut.perimeter)
    assert any(p.layer == "mitre_hatch" for p in sc.prims)


def test_pdf_true_scale_and_tiling(qapp, tmp_path, geometry):
    from bikebox.export.mitre_output import save_mitre_pdf
    cuts = M.compute_mitres(geometry)
    small = tmp_path / "small.pdf"
    n = save_mitre_pdf(cuts, small, "A4", True, "Test")
    assert n == _pages(small) and 1 <= n <= len(cuts)       # several templates share pages
    assert b"/MediaBox [0 0 842" in small.read_bytes()
    big = tmp_path / "big.pdf"
    n = save_mitre_pdf([_big_cut()], big, "A4", True, "Big")
    assert n > 1 and _pages(big) == n


def test_svg_and_dxf(tmp_path, geometry):
    from bikebox.export.mitre_output import save_mitre_dxf, save_mitre_svg
    cuts = M.compute_mitres(geometry)
    svg = tmp_path / "m.svg"
    save_mitre_svg(cuts, svg, "Test")
    root = ET.parse(svg).getroot()
    assert root.tag.endswith("svg") and root.attrib["width"].endswith("mm")
    w = float(root.attrib["width"][:-2])
    assert w == pytest.approx(float(root.attrib["viewBox"].split()[2]))      # 1 user unit = 1 mm
    assert len(root.findall(".//{http://www.w3.org/2000/svg}path")) > 50
    dxf = tmp_path / "m.dxf"
    save_mitre_dxf(cuts, dxf)
    text = dxf.read_text(encoding="ascii")
    assert "ENTITIES" in text and "POLYLINE" in text and "MITRE_CUT" in text and text.endswith("EOF\n")


def test_cut_list_rows(geometry):
    from bikebox.export.mitre_output import cut_list_rows
    cuts = M.compute_mitres(geometry)
    rows = cut_list_rows(geometry, cuts)
    assert rows[0][0] == "Tube" and "Phase" in rows[0] and "Long-to-long" in rows[0]
    assert len(rows) == 1 + len({c.tube for c in cuts})
    assert all(len(r) == len(rows[0]) for r in rows)


def test_gcode(tmp_path, geometry):
    from bikebox.export.gcode import mitre_gcode, save_gcode, toolpath
    cuts = M.compute_mitres(geometry)
    cut = _cut(cuts, "tt", "b")
    s = mitre_gcode(cut, kerf=1.2, lead_in=3.0)
    assert "SIMULATOR" in s and "G93" in s and "M3" in s and "M5" in s
    moves = [l for l in s.splitlines() if l.startswith("G1 ")]
    assert len(moves) > 300
    assert all(re.search(r" X-?\d", l) and re.search(r" A-?\d", l) and " F" in l for l in moves)
    a_vals = [float(re.search(r" A(-?[\d.]+)", l).group(1)) for l in moves]
    assert a_vals[-1] >= 360.0                     # once round plus overcut
    assert all(ord(ch) < 128 for ch in s)
    # kerf offset moves the path into the waste (toward the tube end, smaller v)
    plain, comp = toolpath(cut, 0.0, 0.0, 0.0), toolpath(cut, 2.0, 0.0, 0.0)
    assert np.mean(comp[:, 1]) < np.mean(plain[:, 1])
    inch = mitre_gcode(cut, units="in", mode="wrapped", rotary_axis="Y")
    assert "G20" in inch and "G94" in inch and re.search(r"^G1 X[\d.]+ Y[\d.]+ F", inch, re.M)
    flat = mitre_gcode(cut, mode="flat")
    assert re.search(r"^G1 X[\d.]+ Y-?[\d.]+ F", flat, re.M)
    paths = save_gcode(cuts, tmp_path / "nc")
    assert len(paths) == len(cuts) and all(p.exists() and p.suffix == ".nc" for p in paths)
    assert len({p.name for p in paths}) == len(paths)
