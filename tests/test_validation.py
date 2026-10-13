"""P0 core-math validation: independent cross-checks (not just regression).

Each check recomputes a quantity from first principles and asserts the app
agrees, so a wrong formula fails here even if it's self-consistent elsewhere.
"""
import math

import numpy as np
import pytest

from bikebox.export.bcad_export import save_bcad
from bikebox.export.bcad_import import load_bcad
from bikebox.geometry.mitre import Receiver, compute_mitres, cope_profile
from bikebox.geometry.solver import solve
from bikebox.model.design import Design
from bikebox.model.templates import list_templates, load_template

TEMPLATES = ["default"] + [t.name for t in list_templates()]


def _design(name):
    return Design() if name == "default" else load_template(name)


@pytest.mark.parametrize("name", TEMPLATES)
def test_geometry_identities(name):
    d = _design(name)
    if d["frame_type"] != "single":          # tandem/tall use different front/rear-centre datums
        pytest.skip("identities are for the single diamond frame")
    g = solve(d)
    v = g.v
    Rf = g.wheels["front"].diameter / 2
    Rr = g.wheels["rear"].diameter / 2
    hta = math.radians(v["head_tube_angle"])
    # wheelbase = front centre (horiz) + rear centre (horiz)
    assert abs(v["wheelbase"] - (v["front_center_h"] + v["rear_center_h"])) < 0.2
    # front centre (3-D) = hypot(horizontal, vertical drop to the front axle)
    assert abs(v["front_center"] - math.hypot(v["front_center_h"], v["bb_drop_front"])) < 0.2
    # BB drop = rear wheel radius - BB height
    assert abs(v["bb_drop"] - (Rr - v["bb_height"])) < 0.2
    # seat tube centre-to-top = centre-to-centre + extension (collinear)
    assert abs(v["seat_tube_ct"] - (v["seat_tube_cc"] + v["st_extension"])) < 0.2
    # trail = (Rf*cos(hta) - offset) / sin(hta)  [standard bicycle-trail formula]
    assert abs(v["trail"] - (Rf * math.cos(hta) - v["fork_offset"]) / math.sin(hta)) < 0.3


def test_bcad_round_trip_all_modes():
    import tempfile
    import os
    keys = ("stack", "reach", "head_tube_angle", "seat_tube_angle", "chainstay_length", "seat_tube_cc", "bb_drop")
    for fv in ("ht_length", "stack", "bar_y"):
        for fh in ("reach", "front_center", "ett", "wheelbase"):
            for stm in ("cc", "ct"):
                d = Design()
                d.update({"front_v_mode": fv, "front_h_mode": fh, "st_length_mode": stm})
                g0 = solve(d)
                p = tempfile.mktemp(suffix=".bcad")
                save_bcad(d, p)
                g1 = solve(load_bcad(p))
                os.remove(p)
                for k in keys:
                    assert abs(g0.v[k] - g1.v[k]) < 1.0, (fv, fh, stm, k, g0.v[k], g1.v[k])


def test_mitre_holesaw_angle_identity():
    g = solve(Design())
    for c in compute_mitres(g, samples=120):
        assert abs(c.holesaw_angle - (90 - c.angle)) < 0.6, (c.tube, c.end)
        # round tubes: unrolled perimeter == pi * od
        if abs(c.width - c.od) < 1e-6:
            assert abs((c.points[-1][0] - c.points[0][0]) - math.pi * c.od) < 0.05 * math.pi * c.od


def _axis_dist(P, p0, t):
    w = P - p0
    return np.linalg.norm(w - np.outer(w @ t, t), axis=1)


def test_cope_points_lie_on_receiver_surface():
    # a round tube coped onto a cylinder: every cut point must sit on the receiver surface
    r, R = 15.0, 40.0
    rec = Receiver.cylinder([0, -R, 0], [0, 0, 1], R, length=400)
    cp = cope_profile([0, 0, 0.0], [0, -1, 0], [1, 0, 0], [0, 0, 1], r, r, [rec], samples=240)
    d = _axis_dist(cp.points3, np.array([0, -R, 0.0]), np.array([0, 0, 1.0]))
    assert float(np.max(np.abs(d - R))) < 0.05


@pytest.mark.parametrize("theta", [90, 60, 45, 30])
def test_cope_plane_cut_depth(theta):
    # tube cut by a plane at angle theta between axis and plane: depth == od / tan(theta)
    r = 15.0
    th = math.radians(theta)
    axis = [math.cos(th), -math.sin(th), 0.0]
    e1 = [math.sin(th), math.cos(th), 0.0]
    Rbig = 1e5
    rec = Receiver.cylinder([0, -Rbig, 0], [0, 0, 1], Rbig, length=4e5)
    cp = cope_profile([0, 0, 0.0], axis, e1, [0, 0, 1], r, r, [rec], samples=400)
    depth = float(cp.v.max() - cp.v.min())
    expected = 0.0 if theta == 90 else 2 * r / math.tan(th)
    assert abs(depth - expected) < 0.1
