import math
import subprocess
import sys
from pathlib import Path

import pytest

from framewright.geometry import clearance as C
from framewright.geometry.solver import solve
from framewright.geometry.vec import V3
from framewright.model.design import Design
from framewright.render import aux_views as AV
from framewright.render.scene import AngleDim, LinearDim, Text

MTB = dict(rear_bsd=622, front_bsd=622, rear_tire_width=60, rear_tire_height=58, front_tire_width=60,
           front_tire_height=58, rear_hub_spacing=148, front_hub_spacing=110, bb_shell_width=73,
           fork_type="suspension", fork_length=545, fork_travel=120, fork_sag=20, fork_offset=44,
           fork_crown_width=130, fork_stanchion_od=34, head_tube_angle=66, chainstay_length=435, bb_drop=45,
           chainline=52, chainrings="32", q_factor=168, bar_type="riser", bar_width=780, stem_length=50,
           crank_length=170, tire_profile="square", brake_rear="disc", reach=460, seat_tube_angle=76,
           seat_tube_length=430, ss_bridge=False)

VARIANTS = {
    "default": {},
    "mtb": MTB,
    "toe_fender": {"front_h_mode": "front_center", "front_center": 560, "fenders": True},
    "wishbone_yoke": {"ss_style": "wishbone", "cs_yoke": True, "cs_top_bend_style": "s_bend", "cs_top_bend": 6,
                      "tire_profile": "elliptical"},
    "mono_outline": {"ss_style": "mono", "display_mode": "outline", "units": "in"},
    "no_seat_stays": {"ss_attach": "none", "display_mode": "blueprint"},
    "tandem": {"frame_type": "tandem"},
}


def clear(**kw) -> dict:
    return C.clearances(solve(Design(kw)))


# -- clearance numbers ------------------------------------------------------
def test_default_clearances_are_finite():
    r = clear()
    for k in ("cs_tire", "cs_chainring", "cs_crank", "ss_tire", "st_tire", "fork_crown_tire", "fork_blade_tire",
              "heel", "toe_clearance_3d", "lean_angle_3d", "cs_true_length", "ss_true_length"):
        assert math.isfinite(r[k]), k
    assert r["fork_crown_tire"] > 0 and r["fork_blade_tire"] > 0


def test_wider_rear_tire_reduces_stay_clearance():
    a, b = clear(), clear(rear_tire_width=42)
    assert b["cs_tire"] < a["cs_tire"]
    assert b["ss_tire"] < a["ss_tire"]
    # a round section 10 mm wider loses ~5 mm per side where the gap is lateral
    assert 2.0 < a["ss_tire"] - b["ss_tire"] < 6.0


def test_front_tire_size_moves_fork_clearances():
    a = clear()
    assert clear(front_tire_width=42)["fork_blade_tire"] < a["fork_blade_tire"]
    taller = clear(front_tire_height=40)
    assert taller["fork_crown_tire"] == pytest.approx(a["fork_crown_tire"] - 10.0, abs=0.5)


def test_chainstay_spread_trades_tire_for_chainring_clearance():
    narrow, wide = clear(cs_spread_bb=50), clear(cs_spread_bb=70)
    assert wide["cs_tire"] > narrow["cs_tire"]
    assert wide["cs_chainring"] < narrow["cs_chainring"]
    assert wide["cs_crank"] < narrow["cs_crank"]


def test_longer_chainstays_increase_tire_clearance():
    a, b = clear(chainstay_length=420), clear(chainstay_length=450)
    assert b["cs_tire"] > a["cs_tire"]
    assert b["st_tire"] > a["st_tire"] + 25
    assert b["heel"] > a["heel"]


def test_top_view_bend_and_yoke_open_up_the_tire():
    base = clear()["cs_tire"]
    assert clear(cs_top_bend_style="bent", cs_top_bend=8)["cs_tire"] > base + 4
    assert clear(cs_top_bend_style="bent", cs_top_bend=-5)["cs_tire"] < base
    assert clear(cs_yoke=True, cs_yoke_spread=90)["cs_tire"] > base


def test_heel_in_reduces_heel_clearance():
    assert clear(heel_in_angle=10)["heel"] < clear()["heel"] - 20


def test_suspension_fork_bottom_out():
    r = clear(**MTB)
    rem = MTB["fork_travel"] * (1 - MTB["fork_sag"] / 100)
    assert r["fork_crown_tire_bottomed"] == pytest.approx(r["fork_crown_tire"] - rem)


def test_toe_overlap_steer_angle():
    clear_toe = Design({"front_h_mode": "front_center", "front_center": 680})
    g = solve(clear_toe)
    assert g.v["toe_clearance"] > 0
    assert C.toe_steer_angle(g) is None
    assert C.clearances(g)["toe_steer_angle"] == math.inf

    overlap = Design({"front_h_mode": "front_center", "front_center": 560})
    g = solve(overlap)
    assert g.v["toe_clearance"] < 0
    ang = C.toe_steer_angle(g)
    assert ang is not None and 0.0 < ang < 90.0
    assert C.clearances(g)["toe_steer_angle"] == pytest.approx(ang)
    assert C.toe_gap(g, ang).value == pytest.approx(0.0, abs=0.05)
    assert C.toe_gap(g, ang - 1.0).value > 0
    # marginal overlap: the wheel moves forward as it swings out, so the bare
    # tire misses the toe, but a fender (further out) reaches it
    marginal = Design({"front_h_mode": "front_center", "front_center": 600})
    assert C.toe_steer_angle(solve(marginal)) is None
    marginal.set("fenders", True)
    with_fender = C.toe_steer_angle(solve(marginal))
    assert with_fender is not None and 0.0 < with_fender < 45.0


def test_steering_rotates_about_the_head_tube_axis():
    g = solve(Design())
    H = g.p["ht_top"]
    on_axis = V3(H.x + g.u.x * 100, H.y + g.u.y * 100, 0.0)
    p = C.steer_point(g, on_axis, 30.0)
    assert (p - on_axis).length() < 1e-9
    ax = g.p["front_axle"]
    q = C.steer_point(g, V3(ax.x, ax.y, 0.0), 20.0)
    assert q.z < 0                     # + steers left: the front wheel goes to -Z


def test_lean_angle_reduces_to_planar_for_a_thin_tire():
    g = solve(Design({"rear_tire_width": 10, "front_tire_width": 10}))
    r = C.clearances(g)
    assert r["lean_angle_3d"] >= g.v["lean_angle"]
    assert r["lean_angle_3d"] == pytest.approx(g.v["lean_angle"], abs=1.0)
    assert clear(crank_length=180)["lean_angle_3d"] < clear(crank_length=165)["lean_angle_3d"]


def test_stay_fabrication_numbers():
    d = Design()
    d.set("cs_top_bend_style", "straight")          # closed-form checks below assume straight stays
    g = solve(d)
    cs = C.stay_fabrication(g, "cs")
    path = C.stay_path(g, "cs")
    a3, b3 = path.point(0.0), path.point(1.0)
    assert cs["chord"] == pytest.approx((b3 - a3).length())
    assert cs["true_length"] >= cs["chord"] - 1e-6
    assert cs["visible_length"] < cs["true_length"]
    assert cs["plane_angle"] == pytest.approx(math.degrees(math.asin(abs(b3.z - a3.z) / cs["chord"])))
    assert cs["phase"] == pytest.approx(90.0, abs=1e-6)       # BB mitre is square to the dropout slot
    assert cs["mitre_angle"] == pytest.approx(90.0 - cs["plane_angle"], abs=0.2)
    ss = C.stay_fabrication(g, "ss")
    assert 0.0 <= ss["phase"] < 15.0
    assert ss["mitre_angle"] == pytest.approx(g.v["angle_st_ss"], abs=1.0)


def test_ellipse_distance_matches_brute_force():
    for a, b, u, v in ((20, 12, 30, 25), (15, 15, -4, 3), (25, 10, 5, -2), (10, 30, -40, 0.5)):
        d = C._ellipse_sdf(u, v, a, b)[0]
        best = min(math.hypot(u - a * math.cos(t), v - b * math.sin(t))
                   for t in (2 * math.pi * i / 20000 for i in range(20000)))
        inside = (u / a) ** 2 + (v / b) ** 2 < 1
        assert d == pytest.approx(-best if inside else best, abs=0.01)


def test_problems_are_reported():
    g = solve(Design({"rear_tire_width": 50}))
    assert C.is_problem(g, "cs_tire")
    assert any("Chainstay to tire" in m for m in C.problems(g))


# -- views ------------------------------------------------------------------
def test_aux_view_registry():
    assert len(AV.AUX_VIEWS) == 6
    assert all(isinstance(t, str) and callable(f) for t, f in AV.AUX_VIEWS)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_views_build(variant):
    g = solve(Design(VARIANTS[variant]))
    for title, fn in AV.AUX_VIEWS:
        sc = fn(g)
        assert sc.prims, title
        x0, y0, x1, y1 = sc.bounds()
        assert all(math.isfinite(v) for v in (x0, y0, x1, y1)), title
        assert x1 - x0 > 50 and y1 - y0 > 50, title
        if title != "Stay true lengths" or variant != "no_seat_stays":
            assert any(isinstance(p, (LinearDim, AngleDim)) for p in sc.prims), title


def test_problems_are_drawn_in_red():
    g = solve(Design({"rear_tire_width": 50}))
    sc = AV.top_view_scene(g)
    reds = [p for p in sc.prims if p.style.stroke == AV.PROBLEM]
    assert reds
    assert any(isinstance(p, Text) and "CS-tire" in p.text and p.style.stroke == AV.PROBLEM for p in sc.prims)


def test_toe_view_marks_the_contact():
    g = solve(Design(VARIANTS["toe_fender"]))
    sc = AV.toe_view_scene(g)
    assert any(p.tag == "toe:contact" for p in sc.prims)
    assert any(isinstance(p, AngleDim) and p.tag == "dim:steer" for p in sc.prims)


@pytest.mark.parametrize("variant", ["default", "mtb"])
def test_views_render_to_png(qapp, tmp_path, variant):
    from framewright.render.qt_render import render_image
    g = solve(Design(VARIANTS[variant]))
    for i, (title, fn) in enumerate(AV.AUX_VIEWS):
        img = render_image(fn(g), 800, 600)
        assert not img.isNull()
        path = tmp_path / f"{variant}_{i}.png"
        assert img.save(str(path)), title
        assert path.stat().st_size > 2000, title
        # something other than the background was drawn
        bg = img.pixel(0, 0)
        assert any(img.pixel(x, y) != bg for x in range(0, 800, 7) for y in range(0, 600, 7)), title


def test_modules_do_not_import_qt():
    code = ("import sys; import framewright.geometry.clearance, framewright.render.aux_views; "
            "bad = [m for m in sys.modules if m.startswith(('PyQt', 'PySide'))]; "
            "sys.exit(1 if bad else 0)")
    root = Path(__file__).resolve().parents[1]
    res = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
