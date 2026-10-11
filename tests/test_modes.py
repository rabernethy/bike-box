"""Switching between equivalent measurement modes must not change the geometry."""
import pytest

from framewright.geometry.modes import RULES, mode_switch_values
from framewright.geometry.solver import solve
from framewright.model import params as P
from framewright.model.design import Design
from framewright.model.templates import load_template

POINTS = ("rear_axle", "front_axle", "ht_top", "ht_bottom", "tt_st", "tt_ht", "st_top", "saddle", "bar", "hoods",
          "stem_clamp", "ss_top")
DESIGNS = ["default", "road_race", "xc_hardtail_29", "road_tandem", "city_step_through"]
# seat_angle_source -> seat_tube really changes the saddle angle (it adopts the seat tube's): only its height is kept
CHANGES_GEOMETRY = {("seat_angle_source", "seat_tube")}


def _design(name):
    return Design() if name == "default" else load_template(name)


def _cases():
    for key, rules in RULES.items():
        for value, _ in P.get(key).choices:
            if value in rules:
                yield key, value


@pytest.mark.parametrize("name", DESIGNS)
@pytest.mark.parametrize("key,value", list(_cases()))
def test_mode_switch_preserves_geometry(name, key, value):
    d = _design(name)
    # start from a design that is *not* in the target mode
    others = [c for c, _ in P.get(key).choices if c != value and c in RULES[key]]
    if d[key] == value:
        if not others:
            pytest.skip("single mode")
        d.update(mode_switch_values(d, key, others[0]))
    g0 = solve(d)
    d2 = d.copy()
    d2.update(mode_switch_values(d, key, value))
    assert d2[key] == value
    g1 = solve(d2)
    if (key, value) in CHANGES_GEOMETRY:
        assert abs(g1.p["saddle"].y - g0.p["saddle"].y) < 1e-6
        return
    for pt in POINTS:
        if pt in g0.p:
            assert g1.p[pt].dist(g0.p[pt]) < 1e-6, (pt, g0.p[pt], g1.p[pt])


def test_round_trip_through_every_front_end_mode():
    d = Design()
    g0 = solve(d)
    for v in ("stack", "bar_y", "ht_length"):
        d.update(mode_switch_values(d, "front_v_mode", v))
        for h in ("front_center", "ett", "wheelbase", "bar_x", "reach"):
            d.update(mode_switch_values(d, "front_h_mode", h))
            g = solve(d)
            assert g.p["ht_top"].dist(g0.p["ht_top"]) < 1e-6
            assert g.p["front_axle"].dist(g0.p["front_axle"]) < 1e-6


def test_document_mode_switch_is_one_undo_step(qapp):
    from framewright.gui.document import Document
    doc = Document(Design())
    bb0 = doc.geometry.v["bb_height"]
    doc.set_param("bb_mode", "height")
    assert doc.design["bb_mode"] == "height"
    assert abs(doc.design.f("bb_height") - bb0) < 1e-9
    assert abs(doc.geometry.v["bb_height"] - bb0) < 1e-9
    doc.set_param("bb_height", bb0 + 10)
    assert abs(doc.geometry.v["bb_drop"] - (Design().f("bb_drop") - 10)) < 1e-9
    doc.undo.undo()
    doc.undo.undo()
    assert doc.design["bb_mode"] == "drop"
