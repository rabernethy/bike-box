import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from bikebox.fit import advisor as A
from bikebox.fit import com as C
from bikebox.fit import expr as X
from bikebox.fit import rider as R
from bikebox.geometry.solver import solve
from bikebox.geometry.vec import V
from bikebox.model.design import Design
from bikebox.render.bike_scene import EXTRA_BUILDERS, build_scene
from bikebox.render.scene import Scene
from bikebox.render.theme import Theme


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# --------------------------------------------------------------------------
# anatomy
# --------------------------------------------------------------------------
def test_estimate_from_basic_proportions():
    a = R.estimate_from_basic(1800)
    assert close(a["inseam"], 0.47 * 1800)
    assert close(a["foot"], 0.152 * 1800)
    assert close(a["thigh"] + a["lower_leg"] + a["ankle_height"], a["hip_height"])
    assert close(a["upper_arm"] + a["forearm"] + a["hand"], a["arm"])
    assert 0.27 * 1800 < a["torso_seg"] < 0.31 * 1800
    b = R.estimate_from_basic(1800, inseam=900, arm=700)
    assert b["inseam"] == 900 and b["thigh"] > a["thigh"]
    assert close(b["upper_arm"] + b["forearm"] + b["hand"], 700)


def test_anatomy_overrides():
    d = Design()
    d.set("thigh_length", 470)
    d.set("rider_mass", 80)
    a = R.anatomy(d)
    assert a["thigh"] == 470 and a["mass"] == 80
    assert close(a["hip_height"], 470 + a["lower_leg"] + a["ankle_height"])
    assert close(a["hip_above_saddle"], R.HIP_ABOVE_SADDLE_K * a["inseam"])


# --------------------------------------------------------------------------
# pose / IK
# --------------------------------------------------------------------------
def test_two_link_reach_and_side():
    a, b = V(0, 0), V(0, -500)
    j, err = R.two_link(a, b, 300, 300, 1.0)
    assert err == 0 and close(j.dist(a), 300) and close(j.dist(b), 300) and j.x > 0
    j2, _ = R.two_link(a, b, 300, 300, -1.0)
    assert j2.x < 0
    j3, err3 = R.two_link(a, V(0, -700), 300, 300)
    assert err3 > 0 and close(j3.dist(a), 300)


@pytest.mark.parametrize("crank", [None, 0, 45, 90, 135, 180, 225, 270, 315])
def test_ik_closure(crank):
    d = Design()
    g = solve(d)
    a = R.anatomy(d)
    pose = R.solve_pose(g, crank)
    J = pose.joints
    assert not pose.warnings
    tol = 1e-6
    for suffix in ("", "_far"):
        assert close(J["hip"].dist(J["knee" + suffix]), a["thigh"], tol)
        assert close(J["knee" + suffix].dist(J["ankle" + suffix]), a["lower_leg"], tol)
        # ball of the foot sits on the pedal (cleat stack along the sole normal, cleat offset 0)
        assert close(J["ball" + suffix].dist(J["pedal" + suffix]), d.f("pedal_stack"), tol)
    assert close(J["hip"].dist(J["shoulder"]), a["torso_seg"], tol)
    assert close(J["shoulder"].dist(J["elbow"]), a["upper_arm"], tol)
    assert close(J["elbow"].dist(J["wrist"]), a["forearm"], tol)
    assert close(J["wrist"].dist(J["hand"]), a["hand"], tol)
    assert close(J["hand"].dist(g.p["hand"]), 0.0, tol)
    c = d.f("crank_angle") if crank is None else crank
    assert close(J["pedal"].dist(V.polar(d.f("crank_length"), c)), 0.0, tol)
    assert close(J["pedal_far"].dist(V(0, 0) - J["pedal"]), 0.0, tol)
    # knee in front of the hip-ankle line, elbow below the shoulder-hand line
    assert (J["ankle"] - J["hip"]).cross(J["knee"] - J["hip"]) > 0
    assert (J["hand"] - J["shoulder"]).cross(J["elbow"] - J["shoulder"]) < 0
    # preferred elbow bend is honoured when reachable
    assert close(pose.angles["elbow_angle"], 180 - d.f("elbow_bend"), 1e-6)


def test_hip_offset_from_saddle():
    d = Design()
    g = solve(d)
    pose = R.solve_pose(g)
    a = R.anatomy(d)
    expected = g.p["saddle"] + V(d.f("hip_forward"), a["hip_above_saddle"])
    assert close(pose.joints["hip"].dist(expected), 0.0)


def test_cleat_offset_moves_ball_forward():
    d = Design()
    d.set("cleat_offset", 30)
    d.set("crank_angle", -90)
    d.set("ankle_angle", 0)
    d.set("ankling", 0)
    pose = R.solve_pose(solve(d))
    ball, pedal = pose.joints["ball"], pose.joints["pedal"]
    assert close(ball.x - pedal.x, 30, 1e-6) and close(ball.y - pedal.y, d.f("pedal_stack"), 1e-6)


def test_default_knee_angles_plausible():
    pose = R.solve_pose(solve(Design()))
    ang = pose.angles
    assert 135 <= ang["knee_extension_bdc"] <= 155
    assert 60 <= ang["knee_flexion_tdc"] <= 85
    assert close(ang["knee_flexion_bdc"], 180 - ang["knee_extension_bdc"])
    assert ang["knee_flexion_tdc"] <= ang["knee_angle"] <= ang["knee_extension_bdc"]
    assert ang["hip_angle_min"] <= ang["hip_angle"]
    assert 25 <= ang["torso_angle"] <= 65
    assert abs(ang["kops"]) < 40
    for k in ("shoulder_angle", "elbow_angle", "saddle_to_hand_reach"):
        assert math.isfinite(ang[k])


def test_raising_saddle_extends_knee():
    vals = []
    for h in (700, 730, 760):
        d = Design()
        d.set("saddle_height", h)
        vals.append(R.solve_pose(solve(d)).angles["knee_extension_bdc"])
    assert vals[0] < vals[1] < vals[2]


def test_unreachable_hands_warn_not_raise():
    d = Design()
    d.set("arm_length", 380)
    d.set("torso_length", 420)
    g = solve(d)
    pose = R.solve_pose(g)
    assert any("out of reach" in w for w in pose.warnings)
    a = R.anatomy(d)
    J = pose.joints
    assert close(J["shoulder"].dist(J["elbow"]), a["upper_arm"])     # clamped, still a valid chain
    sc = Scene()
    d.set("show_rider", True)
    R.draw_rider(sc, g, Theme.from_design(d))
    assert any(w.startswith("Rider:") for w in g.warnings)
    assert sc.prims


def test_saddle_too_high_warns():
    d = Design()
    d.set("saddle_height", 1000)
    pose = R.solve_pose(solve(d))
    assert any("cannot reach the pedal" in w for w in pose.warnings)
    assert pose.angles["knee_extension_bdc"] == pytest.approx(180.0, abs=1e-6)


# --------------------------------------------------------------------------
# expression evaluator
# --------------------------------------------------------------------------
@pytest.mark.parametrize("expr,expected", [
    ("0.883 * inseam", 0.883 * 850),
    ("sin(30)", 0.5),
    ("cos(60) + tan(45)", 1.5),
    ("asin(0.5)", 30.0),
    ("atan2(1, 1)", 45.0),
    ("sqrt(16) ** 2 // 3 % 4", 1.0),
    ("-inseam + +10", -840.0),
    ("clamp(200, 150, 180)", 180.0),
    ("lerp(10, 20, 0.25)", 12.5),
    ("round(172.4 / 2.5) * 2.5", 172.5),
    ("round(171.2 / 2.5) * 2.5", 170.0),
    ("round(1.2345, 2)", 1.23),
    ("min(1, 2, 3) + max(4, 5) + abs(-1)", 7.0),
    ("100 if inseam > 800 else 50", 100.0),
    ("1 < 2 < 3", 1.0),
    ("1 < 3 < 2", 0.0),
    ("not 0 and (0 or 5)", 5.0),
    ("pi", math.pi),
    ("True + 1", 2.0),
])
def test_expr_valid(expr, expected):
    assert X.validate(expr) == []
    assert X.evaluate(expr, {"inseam": 850}) == pytest.approx(expected)


@pytest.mark.parametrize("attack", [
    "__import__('os')", "__import__('os').system('true')", "().__class__", "().__class__.__bases__[0]",
    "x.y", "[1][0]", "open('f')", "eval('1')", "exec('1')", "getattr(x, 'y')", "lambda: 1",
    "[i for i in range(3)]", "{1: 2}", "{1, 2}", "(1, 2)", "'abc'", "b'x'", "f'{x}'", "x[0]",
    "__builtins__", "_x", "x.__dict__", "min(*x)", "round(x, ndigits=2)", "type(x)", "globals()",
    "(y := 2)", "1 if x else open('f')", "sqrt(1, 2)", "1j", "await x", "x @ y", "~1", "1 << 2", "1 & 1",
    "a = 1", "import os", "",
])
def test_expr_rejects_attacks(attack):
    assert X.validate(attack)
    with pytest.raises(X.ExprError):
        X.evaluate(attack, {"x": 1.0, "y": 2.0})


@pytest.mark.parametrize("bad", ["9 ** 9 ** 9", "1 / 0", "5 % 0", "sqrt(-1)", "acos(2)", "unknown + 1", "1e308 * 10"])
def test_expr_runtime_errors(bad):
    with pytest.raises(X.ExprError):
        X.evaluate(bad, {})


def test_expr_names_and_extra_functions():
    assert X.validate("a + b", names={"a"}) == ["unknown name 'b'"]
    assert X.names_used("max(a, b) + sin(c)") == {"a", "b", "c"}
    assert X.evaluate("double(x)", {"x": 2}, {"double": lambda v: 2 * v}) == 4.0
    with pytest.raises(X.ExprError):
        X.evaluate("double(x)", {"x": 2})
    with pytest.raises(X.ExprError):
        X.evaluate("x", {"x": "text"})


# --------------------------------------------------------------------------
# fit advisor
# --------------------------------------------------------------------------
REQUIRED = ("saddle_height", "saddle_setback", "crank_length", "stack", "reach", "hand_x", "hand_y",
            "saddle_bar_drop", "nose_to_bar", "seat_tube_length")


@pytest.mark.parametrize("name", list(A.SCHEMES))
def test_builtin_schemes_evaluate(name):
    scheme = A.SCHEMES[name]
    assert A.validate_scheme(scheme) == []
    errors = []
    recs = A.evaluate(scheme, Design(), errors)
    assert errors == []
    keys = {r.key for r in recs}
    assert set(REQUIRED) <= keys
    for r in recs:
        assert math.isfinite(r.value) and r.low <= r.value + 1e-9 and r.high >= r.value - 1e-9, r
    by = {r.key: r for r in recs}
    assert 600 < by["saddle_height"].value < 800
    assert 140 <= by["crank_length"].value <= 180
    assert by["saddle_height"].current == pytest.approx(730.0)


def test_required_builtin_names():
    for n in ("Classic road", "Endurance / comfort", "Gravel & touring", "Mountain", "Time trial"):
        assert n in A.SCHEMES
    assert "0.883" in A.SCHEMES["Classic road"]["description"]


def test_lemond_value():
    d = Design()
    d.set("inseam", 850)
    recs = {r.key: r for r in A.evaluate(A.SCHEMES["Classic road"], d)}
    assert recs["saddle_height"].value == pytest.approx(0.883 * 850)
    assert recs["saddle_height"].param == "saddle_height"
    assert recs["seat_tube_length"].value == pytest.approx(0.65 * 850)


def test_kops_setback_puts_knee_over_spindle():
    d = Design()
    f = A.model_functions(d)
    h = 740.0
    s = f["kops_setback"](h)
    d.set("saddle_mode", "xy")
    d.set("saddle_x", -s)
    d.set("saddle_y", math.sqrt(h * h - s * s))
    pose = R.solve_pose(solve(d))
    assert abs(pose.angles["kops"]) < 0.5
    h150 = f["saddle_for_knee"](150, s)
    assert f["knee_ext"](h150, s) == pytest.approx(150, abs=0.2)


def test_apply_changes_saddle_height():
    d = Design()
    recs = A.evaluate(A.SCHEMES["Classic road"], d)
    target = next(r for r in recs if r.key == "saddle_height").value
    changed = A.apply(recs, d, keys=["saddle_height"])
    assert changed == ["saddle_height"]
    assert d.f("saddle_height") == pytest.approx(target)
    assert A.apply(recs, d, keys=["saddle_height"]) == []      # already applied


def test_apply_all_hits_geometry_targets():
    d = Design()                                 # front end by head-tube length + reach
    recs = {r.key: r for r in A.evaluate(A.SCHEMES["Endurance / comfort"], d)}
    changed = A.apply(recs.values(), d)
    assert "head_tube_length" in changed and "saddle_height" in changed
    assert "seat_angle_eff" in changed and d["seat_angle_source"] == "custom"
    g = solve(d)
    assert g.v["stack"] == pytest.approx(recs["stack"].value, abs=0.1)
    assert g.v["reach"] == pytest.approx(recs["reach"].value, abs=0.1)
    assert g.v["saddle_height"] == pytest.approx(recs["saddle_height"].value, abs=0.1)
    assert g.v["saddle_setback"] == pytest.approx(recs["saddle_setback"].value, abs=0.1)
    assert d.f("crank_length") == pytest.approx(recs["crank_length"].value)


def test_apply_xy_saddle_mode():
    d = Design()
    d.set("saddle_mode", "xy")
    recs = [A.Recommendation("saddle_height", "", 750, 740, 760, "mm", "saddle_height"),
            A.Recommendation("saddle_setback", "", 190, 180, 200, "mm", "saddle_setback")]
    changed = A.apply(recs, d)
    assert set(changed) == {"saddle_x", "saddle_y"}
    g = solve(d)
    assert g.v["saddle_height"] == pytest.approx(750, abs=1e-6)
    assert g.v["saddle_setback"] == pytest.approx(190, abs=1e-6)


def test_custom_formula_overrides_and_safety():
    d = Design()
    d.set("inseam", 850)
    d.extras["fit_formulas"] = {
        "Classic road": {"formulas": {"saddle_height": {"expr": "0.9 * inseam"}, "bar_width": None}},
        "My scheme": {"description": "x", "formulas": {
            "saddle_height": {"label": "SH", "expr": "inseam - 100", "unit": "mm", "param": "saddle_height"}}},
        "Evil": {"formulas": {"saddle_height": {"expr": "__import__('os').system('true')"}}},
    }
    schemes = A.load_schemes(d, directory=Path("/nonexistent-bikebox-dir"))
    road = {r.key: r for r in A.evaluate(schemes["Classic road"], d)}
    assert road["saddle_height"].value == pytest.approx(765)
    assert road["saddle_height"].label.startswith("Saddle height")      # merged, label kept
    assert "bar_width" not in road
    assert A.evaluate(schemes["My scheme"], d)[0].value == pytest.approx(750)
    assert "Evil" not in schemes
    assert A.SCHEMES["Classic road"]["formulas"]["saddle_height"]["expr"] == "0.883 * inseam"   # untouched


def test_scheme_files_round_trip(tmp_path):
    scheme = {"name": "Shop fit", "description": "test",
              "inputs": {"flexibility": {"default": 4}},
              "formulas": {"saddle_height": {"label": "Saddle", "expr": "0.88 * inseam + flexibility",
                                             "range": ["value - 5", "value + 5"], "unit": "mm",
                                             "param": "saddle_height"}}}
    path = A.save_custom_scheme(scheme, tmp_path / "shop.json")
    assert json.loads(path.read_text())["name"] == "Shop fit"
    (tmp_path / "broken.json").write_text("{not json")
    schemes = A.load_schemes(Design(), directory=tmp_path)
    assert "Shop fit" in schemes and "Classic road" in schemes
    d = Design()
    d.set("inseam", 800)
    r = A.evaluate(schemes["Shop fit"], d)[0]
    assert r.value == pytest.approx(0.88 * 800 + 4)          # the scheme's own input spec (no param) applies
    d.extras["fit_inputs"] = {"flexibility": 2}
    assert A.evaluate(schemes["Shop fit"], d)[0].value == pytest.approx(0.88 * 800 + 2)
    with pytest.raises(ValueError):
        A.save_custom_scheme({"name": "bad", "formulas": {"x": {"expr": "open('f')"}}}, tmp_path / "bad.json")
    assert not (tmp_path / "bad.json").exists()


def test_failing_formula_is_reported_not_raised():
    errors = []
    scheme = {"name": "t", "formulas": {"a": {"expr": "1 / 0"}, "b": {"expr": "a + 1"}, "c": {"expr": "2"}}}
    recs = A.evaluate(scheme, Design(), errors)
    assert [r.key for r in recs] == ["c"] and len(errors) == 2


def test_fit_report_rows():
    rows = dict(A.fit_report(solve(Design())))
    for k in ("Saddle height (BB to top)", "Knee angle at bottom of stroke", "Torso angle",
              "Knee ahead of pedal spindle (KOPS)", "Weight on front / rear wheel"):
        assert k in rows


# --------------------------------------------------------------------------
# centre of mass
# --------------------------------------------------------------------------
@pytest.mark.parametrize("with_rider", [True, False])
def test_com_between_axles_above_bb(with_rider):
    g = solve(Design())
    c, total, front = C.centre_of_mass(g, with_rider)
    assert g.p["rear_axle"].x < c.x < g.p["front_axle"].x
    assert c.y > 0
    if with_rider:
        assert 0.30 <= front <= 0.55
        assert 70_000 < total < 100_000
    else:
        assert 6_000 < total < 15_000


def test_component_masses_and_overrides():
    d = Design()
    g = solve(d)
    parts = C.component_masses(g, include_rider=True)
    names = {n for n, _, _ in parts}
    for n in ("tube:tt", "tube:dt", "bb_shell", "wheel_front", "wheel_rear", "crankset", "saddle", "rider:trunk"):
        assert n in names
    rider = sum(m for n, m, _ in parts if n.startswith("rider:"))
    assert rider == pytest.approx(R.anatomy(d)["mass"] * 1000.0)
    tt = next(m for n, m, _ in parts if n == "tube:tt")
    assert tt == pytest.approx(g.tubes["tt"].mass())
    _, t0, _ = C.centre_of_mass(g, False)
    d.extras["component_masses"] = {"saddle": 1250.0}
    _, t1, _ = C.centre_of_mass(solve(d), False)
    assert t1 - t0 == pytest.approx(1000.0)


def test_rider_moves_weight_forward_when_bars_lower():
    d = Design()
    f0 = C.centre_of_mass(solve(d), True)[2]
    d.set("spacers", 0)
    d.set("stem_angle", -17)
    d.set("stem_length", 130)
    f1 = C.centre_of_mass(solve(d), True)[2]
    assert f1 > f0


# --------------------------------------------------------------------------
# drawing
# --------------------------------------------------------------------------
def test_hooks_registered():
    names = [(f.__module__, f.__name__) for f in EXTRA_BUILDERS]
    assert ("bikebox.fit.rider", "draw_rider") in names
    assert ("bikebox.fit.com", "draw_com") in names


@pytest.mark.parametrize("style", ["silhouette", "outline", "skeleton"])
@pytest.mark.parametrize("helmet", ["none", "road", "aero", "cap"])
def test_draw_rider_styles(style, helmet):
    d = Design()
    d.set("show_rider", True)
    d.set("rider_style", style)
    d.set("helmet", helmet)
    sc = Scene()
    R.draw_rider(sc, solve(d), Theme.from_design(d))
    rider = [p for p in sc.prims if p.layer == "rider"]
    assert len(rider) >= 8
    if style != "skeleton" and helmet != "none":
        assert any(p.tag.startswith("rider:helmet") for p in rider)


def test_build_scene_layers():
    d = Design()
    sc = build_scene(solve(d))
    assert not [p for p in sc.prims if p.layer in ("rider", "analysis") and p.tag.startswith(("rider", "com"))]
    d.set("show_rider", True)
    d.set("show_com", True)
    g = solve(d)
    sc = build_scene(g)
    assert [p for p in sc.prims if p.layer == "rider"]
    assert [p for p in sc.prims if p.layer == "analysis" and p.tag.startswith("com")]
    assert not [w for w in g.warnings if "failed" in w]


def test_fit_modules_do_not_import_qt():
    root = Path(__file__).resolve().parents[1]
    code = ("import sys, bikebox.fit\n"
            "bad = [m for m in sys.modules if m.startswith(('PyQt', 'PySide')) or m == 'bikebox.qt']\n"
            "assert not bad, bad\n")
    res = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
