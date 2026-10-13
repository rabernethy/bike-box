"""User-placed braze-ons / mounts."""
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_brazeons_resolve_on_tubes():
    d = Design()
    d.extras["brazeons"] = [
        {"type": "bottle", "tube": "dt", "s": 180, "spacing": 64, "label": "DT bottle"},
        {"type": "rack_eyelet", "tube": "ss", "s": 15, "label": "rack"},
        {"type": "disc_mount", "tube": "cs", "s": 40, "label": "flat mount"},
    ]
    g = solve(d)
    assert len(g.brazeons) == 3
    for b in g.brazeons:
        assert b["point"] is not None and b["type"]
    # position near the down tube for the DT bottle
    dt = g.tubes["dt"]
    bottle = next(b for b in g.brazeons if b["type"] == "bottle")
    from bikebox.geometry.vec import point_segment_distance
    pts = dt.points()
    dist = min(point_segment_distance(bottle["point"], pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    assert dist < dt.od_b          # sits on/near the tube surface


def test_brazeon_unresolved_warns_not_crashes():
    d = Design()
    d.extras["brazeons"] = [{"type": "boss", "tube": "nonexistent", "s": 50}]
    g = solve(d)                   # must not raise
    assert any("Braze-on" in w for w in g.warnings)
    assert g.brazeons == []


def test_brazeons_render_prims():
    from bikebox.render.bike_scene import build_scene
    d = Design()
    d.extras["brazeons"] = [{"type": "bottle", "tube": "dt", "s": 180, "spacing": 64}]
    sc = build_scene(solve(d))
    prims = [p for p in sc.prims if getattr(p, "tag", "").startswith("brazeon:user")]
    assert len(prims) == 2         # a pair of bosses
