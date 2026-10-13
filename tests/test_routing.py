"""Cable / hose routing."""
from bikebox.geometry.solver import solve
from bikebox.gui.routing_dialog import PRESETS
from bikebox.model.design import Design


def test_route_resolves_to_polyline_and_ports():
    d = Design()
    d.extras["routing"] = [dict(PRESETS["Rear shift (internal, DT→CS)"])]
    g = solve(d)
    assert len(g.routes) == 1
    r = g.routes[0]
    assert len(r["pts"]) >= 3 and r["internal"] and len(r["ports"]) == 2
    assert r["ports"][0] is r["pts"][0] and r["ports"][-1] is r["pts"][-1]


def test_external_route_has_no_ports():
    d = Design()
    d.extras["routing"] = [{"type": "brake", "internal": False,
                            "points": [{"tube": "tt", "s": 60}, {"tube": "tt", "s": 40, "from": "b"}]}]
    g = solve(d)
    assert g.routes[0]["ports"] == []


def test_bad_route_warns_not_crashes():
    d = Design()
    d.extras["routing"] = [{"type": "shift", "points": [{"tube": "nope", "s": 10}, "ht_top"]}]
    g = solve(d)                       # must not raise
    assert g.routes == [] and any("Route" in w for w in g.warnings)


def test_routes_render_and_build_sheet(qapp):
    from bikebox.render.bike_scene import build_scene
    from bikebox.export import buildsheet
    d = Design()
    d.extras["routing"] = [dict(PRESETS["Dropper (internal, DT→ST)"])]
    g = solve(d)
    sc = build_scene(g)
    assert any(getattr(p, "tag", "").startswith("route:") for p in sc.prims)
    assert "Cable/hose ports" in buildsheet.build_html(g)
