import math
import time

import numpy as np
import pytest

from bikebox.analysis import gearing, jig, report, structure, uci, weight
from bikebox.geometry.solver import MATERIAL_YOUNG, solve
from bikebox.model import params as P
from bikebox.model.design import Design


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


# --------------------------------------------------------------------------
# gearing
# --------------------------------------------------------------------------
@pytest.fixture
def road():
    """700c wheel with a 25 mm tyre height -> 672 mm outside diameter."""
    return Design({"rear_bsd": 622, "rear_tire_height": 25, "front_bsd": 622, "front_tire_height": 25,
                   "chainrings": "50, 34", "cogs": "11, 28", "crank_length": 172.5, "cadence": 90})


def _row(rows, ring, cog):
    return next(r for r in rows if r["ring"] == ring and r["cog"] == cog)


def test_gear_inches_development_gain_speed(road):
    rows = gearing.gear_table(road)
    assert len(rows) == 4
    r = _row(rows, 50, 11)
    dia_in = 672 / 25.4                               # 26.457"
    assert r["gear_inches"] == pytest.approx(dia_in * 50 / 11, rel=1e-9)
    assert r["gear_inches"] == pytest.approx(120.26, abs=0.01)
    dev = 50 / 11 * math.pi * 0.672                   # metres per crank revolution
    assert r["development_m"] == pytest.approx(dev, rel=1e-9)
    assert r["development_m"] == pytest.approx(9.596, abs=0.001)
    assert r["gain_ratio"] == pytest.approx(336 / 172.5 * 50 / 11, rel=1e-9)
    assert r["speed_kmh"] == pytest.approx(dev * 90 * 60 / 1000, rel=1e-9)


def test_hub_gear_multiplies_ratios(road):
    road.set("drive_type", "hub_gear")
    road.set("hub_gear_ratios", "0.5, 1, 2")
    rows = gearing.gear_table(road)
    assert [round(r["ratio"], 6) for r in rows] == [round(50 / 11 * h, 6) for h in (0.5, 1, 2)]


def test_chain_wrap_equal_sprockets_is_exact():
    p = 12.7
    assert gearing.wrap_length(400, 18, 18, p) == pytest.approx(2 * 400 / p + 18, rel=1e-12)


def test_chain_formula_vs_geometric(design):
    design.set("chainrings", "50, 34")                # 420 mm chainstay, 50/34 x 11-32
    g = solve(design)
    c = gearing.chain_length(g, "derailleur")
    C_in = 420 / 25.4
    assert c["formula_inches"] == pytest.approx(2 * C_in + 50 / 4 + 32 / 4 + 1, rel=1e-9)
    assert c["formula_links"] % 2 == 0 and c["geometric_links"] % 2 == 0
    assert abs(c["formula_links"] - c["geometric_links"]) <= 2
    assert c["geometric_links"] >= c["wrap_links"] + 2 - 1e-9
    assert c["capacity"] == (50 - 34) + (32 - 11)
    for C in (380, 405, 440, 470):                    # robust over chainstay lengths
        design.set("chainstay_length", C)
        c = gearing.chain_length(solve(design), "derailleur")
        assert abs(c["formula_links"] - c["geometric_links"]) <= 2


def test_singlespeed_exact_chainstay_fits_whole_links(design):
    design.set("drive_type", "singlespeed")
    design.set("chainrings", "46")
    design.set("cogs", "17")
    c = gearing.chain_length(solve(design))
    assert c["method"] == "singlespeed"
    whole = [o for o in c["options"] if not o["half_link"]]
    half = [o for o in c["options"] if o["half_link"]]
    assert whole and half
    assert all(o["links"] % 2 == 0 for o in whole) and all(o["links"] % 2 == 1 for o in half)
    lo = max(o["links"] for o in whole if o["links"] <= c["exact_links"])
    hi = min(o["links"] for o in whole if o["links"] >= c["exact_links"])
    assert hi - lo == 2
    for o in c["options"]:
        d2 = design.copy()
        d2.set("chainstay_length", o["chainstay"])
        c2 = gearing.chain_length(solve(d2))
        assert c2["exact_links"] == pytest.approx(o["links"], abs=1e-6)


def test_belt_length_symmetry_and_inverse():
    p, n, C = 11.0, 24, 420.0
    L = gearing.wrap_length(C, n, n, p, "belt") * p
    assert L == pytest.approx(2 * C + p * n, rel=1e-12)
    teeth = gearing.wrap_length(C, 55, 22, p, "belt")
    assert gearing.centre_for_length(teeth, 55, 22, p, "belt") == pytest.approx(C, abs=1e-6)
    assert math.isnan(gearing.centre_for_length(10, 55, 22, p, "belt"))


def test_belt_options_fit_standard_counts(design):
    design.set("drive_type", "belt")
    design.set("chainrings", "55")
    design.set("cogs", "22")
    c = gearing.chain_length(solve(design))
    assert c["method"] == "belt" and c["options"]
    for o in c["options"]:
        assert gearing.wrap_length(o["chainstay"], 55, 22, 11.0, "belt") == pytest.approx(o["teeth"], abs=1e-6)
    assert sum(o["nearest"] for o in c["options"]) == 1


def test_chainline_check_singlespeed(design):
    design.set("drive_type", "singlespeed")
    design.set("chainrings", "46")
    design.set("cogs", "17")
    design.set("chainline", 42.0)
    design.set("rear_chainline", 42.0)
    assert gearing.chainline_check(design)["status"] == "ok"
    design.set("rear_chainline", 47.0)
    cl = gearing.chainline_check(design)
    assert cl["status"] == "fail" and cl["offset"] == pytest.approx(-5.0)


# --------------------------------------------------------------------------
# UCI
# --------------------------------------------------------------------------
def _rule(rules, rid):
    return next(r for r in rules if r.id == rid)


def test_uci_saddle_setback_flips(design):
    assert _rule(uci.check_uci(solve(design)), "saddle_setback").status == "pass"
    design.set("saddle_mode", "xy")
    design.set("saddle_y", 700)
    nose = design.f("saddle_ref_to_nose")
    design.set("saddle_x", -nose + 20)                # nose 20 mm ahead of the BB vertical
    assert _rule(uci.check_uci(solve(design)), "saddle_setback").status == "fail"
    design.set("saddle_x", -nose - 30)                # 30 mm behind: morphological exemption only
    assert _rule(uci.check_uci(solve(design)), "saddle_setback").status == "warn"
    design.set("uci_morpho_exemption", True)
    assert _rule(uci.check_uci(solve(design)), "saddle_setback").status == "pass"
    design.set("saddle_x", -nose - 60)
    assert _rule(uci.check_uci(solve(design)), "saddle_setback").status == "pass"


def test_uci_rules_cover_the_list(geometry):
    rules = uci.check_uci(geometry)
    ids = {r.id for r in rules}
    for rid in ("saddle_setback", "saddle_length", "bb_height", "bb_front_axle", "bb_rear_axle", "overall_length",
                "wheel_diameter", "wheels_equal", "width", "tube_max_dim", "tube_min_dim", "min_weight",
                "rules_change"):
        assert rid in ids
    assert all(r.status in ("pass", "fail", "warn", "n/a") for r in rules)


def test_uci_bb_height_and_width_fail(design):
    design.set("bb_mode", "height")
    design.set("bb_height", 310)
    design.set("bar_width", 520)
    rules = uci.check_uci(solve(design))
    assert _rule(rules, "bb_height").status == "fail"
    assert _rule(rules, "width").status == "fail"


# --------------------------------------------------------------------------
# weight
# --------------------------------------------------------------------------
def test_weight_sums(geometry):
    fw = weight.frame_weight(geometry)
    assert fw["frame"] == pytest.approx(sum(fw["frame_items"].values()))
    assert fw["fork"] == pytest.approx(sum(fw["fork_items"].values()))
    assert fw["frame_and_fork"] == pytest.approx(fw["frame"] + fw["fork"])
    bw = weight.bike_weight(geometry)
    assert bw["total"] == pytest.approx(bw["frame"] + bw["fork"] + sum(bw["components"].values()))
    assert 1000 < fw["frame"] < 3000                  # steel frame, plausible range
    assert 6000 < bw["total"] < 14000


def test_weight_mirrored_and_joints(design):
    g = solve(design)
    cs = g.tubes["cs"]
    single = cs.mass(100.0) / 2
    assert cs.mass(100.0) == pytest.approx(2 * single)
    tig = weight.frame_weight(g)["frame"]
    design.set("joint_style", "lugged")
    lugged = weight.frame_weight(solve(design))
    assert lugged["frame"] > tig and lugged["frame_items"]["Lugs"] > 0
    design.set("frame_material", "aluminium")
    assert weight.frame_weight(solve(design))["frame"] < lugged["frame"]


def test_weight_component_override(design):
    g = solve(design)
    base = weight.bike_weight(g)["total"]
    design.set("wt_saddle", design.f("wt_saddle") + 100)
    assert weight.bike_weight(solve(design))["total"] == pytest.approx(base + 100)


# --------------------------------------------------------------------------
# structure (FEA)
# --------------------------------------------------------------------------
def test_fea_cantilever_closed_form():
    r = structure.cantilever_check(length=600, od=31.8, wall=0.9, force=150, torque=20_000, n_el=4)
    assert rel(r["tip_deflection"], r["tip_deflection_exact"]) < 1e-6
    assert rel(r["tip_twist"], r["tip_twist_exact"]) < 1e-6


def test_fea_oval_section_orientation():
    """Cantilever along X with an oval tube: depth (side view) along Y."""
    sec = structure.tube_section(40.0, 20.0, 1.0, "aluminium", profile="oval")
    assert sec.Iz > sec.Iy
    m = structure.FrameModel()
    n = [m.node((100.0 * i, 0, 0)) for i in range(6)]
    for a, b in zip(n, n[1:]):
        m.beam(a, b, sec)
    F = np.zeros((m.ndof, 2))
    F[6 * n[-1] + 1, 0] = 50.0                       # in-plane (Y)
    F[6 * n[-1] + 2, 1] = 50.0                       # out of plane (Z)
    U = m.solve(range(6), F)
    E, L = MATERIAL_YOUNG["aluminium"], 500.0
    assert rel(U[6 * n[-1] + 1, 0], 50 * L ** 3 / (3 * E * sec.Iz)) < 1e-6
    assert rel(U[6 * n[-1] + 2, 1], 50 * L ** 3 / (3 * E * sec.Iy)) < 1e-6


def test_fea_default_frame(geometry):
    res = structure.analyse(geometry)
    assert res["ok"], res.get("error")
    h = res["headline"]
    for key in ("bb_lateral_stiffness", "ht_torsional_stiffness", "saddle_vertical_stiffness",
                "inplane_stiffness", "transverse_stiffness"):
        assert math.isfinite(h[key]) and h[key] > 0, key
    assert set(res["cases"]) == set(structure.CASES)
    for c in res["cases"].values():
        assert math.isfinite(c["max_stress"]) and c["max_stress"] > 0
        assert c["min_sf"] > 0
    assert 0 < h["min_safety_factor"] < 100
    assert "estimate" in res["summary"].lower()


def test_fea_stiffer_tubes_are_stiffer(design):
    base = structure.analyse(solve(design))["headline"]
    design.set("dt_od", 38.0)
    design.set("dt_wall_mid", 0.8)
    stiff = structure.analyse(solve(design))["headline"]
    assert stiff["ht_torsional_stiffness"] > base["ht_torsional_stiffness"]


@pytest.mark.parametrize("vals", [
    {"fea_include_fork": True}, {"ss_style": "wishbone"}, {"ss_style": "mono"}, {"ss_attach": "top_tube"},
    {"remove_tubes": "tt"}, {"tt_bend": 12, "cs_bend": -6}, {"dt_profile": "oval", "dt_od2": 40},
])
def test_fea_variants_solve(vals):
    res = structure.analyse(solve(Design(vals)))
    assert res["ok"], res.get("error")
    assert res["headline"]["ht_torsional_stiffness"] > 0


def test_fea_runtime(geometry):
    # A regression guard that the FEA stays interactive, not a hard benchmark:
    # the threshold is generous because CI runners vary in speed. A healthy solve
    # is a few tens of ms locally; anything approaching this bound is a real
    # regression (e.g. an accidental O(n^2) assembly), not runner noise.
    structure.analyse(geometry)                       # warm-up (imports, caches)
    best = min(_timed(lambda: structure.analyse(geometry)) for _ in range(5))
    assert best < 0.25, f"FEA solve too slow ({best * 1e3:.0f} ms) -- possible regression"


def _timed(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


# --------------------------------------------------------------------------
# fixture & report
# --------------------------------------------------------------------------
def test_fixture_numbers(geometry):
    rows = jig.fixture_numbers(geometry)
    assert all(isinstance(r, tuple) and len(r) == 3 and all(isinstance(x, str) for x in r) for r in rows)
    labels = {r[0]: r[1] for r in rows}
    assert labels["Head tube angle"].startswith("72.00")
    assert "Chainstay phase (BB mitre to dropout slot)" in labels


def test_stay_phase_planar_and_bb():
    from bikebox.geometry.solver import Tube
    from bikebox.geometry.vec import V
    planar = Tube("ss", "Seat stay", V(-400, 70), V(-140, 480), 12, 16, za=30, zb=30, mirrored=True)
    splay, phase = jig.stay_angles(planar, (-0.28, 0.96, 0.0))
    assert splay == pytest.approx(0, abs=1e-9) and phase == pytest.approx(0, abs=1e-9)
    cs = Tube("cs", "Chainstay", V(-414, 70), V(0, 0), 16, 22, za=70, zb=40, mirrored=True)
    splay, phase = jig.stay_angles(cs, (0.0, 0.0, 1.0))
    assert splay > 0 and abs(phase) == pytest.approx(90, abs=1e-9)


def test_full_report(geometry):
    secs = report.full_report(geometry)
    titles = [s.title for s in secs]
    for t in ("Key geometry", "Clearances & warnings", "Gearing", "Chain", "Weight", "UCI (road)",
              "Structure (FEA estimate)", "Fixture"):
        assert t in titles
    for s in secs:
        assert s.rows, s.title
        for row in s.rows:
            assert len(row) == 3 and row[2] in ("ok", "warn", "fail", "info"), (s.title, row)
        assert not any(r[0] == "Error" for r in s.rows), (s.title, s.rows)


def test_report_honours_units(design):
    from bikebox.model.units import fmt_len
    design.set("units", "in")
    g = solve(design)
    secs = {s.title: s for s in report.full_report(g)}
    geo = dict((r[0], r[1]) for r in secs["Key geometry"].rows)
    assert geo["Stack"] == fmt_len(g.v["stack"], "in", suffix=True)
    assert geo["Stack"].endswith('"')


def test_params_registered_in_analysis_group():
    for key in ("hub_gear_ratios", "rear_chainline", "belt_tooth_counts", "wt_wheelset", "bb_shell_wall",
                "fea_pedal_force", "fea_yield_steel", "uci_morpho_exemption"):
        assert P.has(key) and P.get(key).group == "Analysis", key
