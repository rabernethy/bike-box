"""3-D clearance scene data."""
from bikebox.geometry.solver import solve
from bikebox.model.design import Design
from bikebox.render import scene3d


def test_scene3d_has_mesh_and_clearance_lines():
    sc = scene3d.build(solve(Design()))
    assert len(sc.triangles) > 500                     # frame + wheels mesh
    assert sc.clearances                               # clearance gap lines
    cl = {c.key: c for c in sc.clearances}
    for key in ("cs_tire", "st_tire", "fork_crown_tire"):
        assert key in cl
        c = cl[key]
        assert c.p != c.q and len(c.p) == 3            # two distinct 3-D points
        assert c.text                                  # has a label string
    assert len(sc.bounds) == 2


def test_scene3d_flags_problem_clearances():
    d = Design()
    d.update({"rear_tire_width": 55, "rear_tire_height": 50, "front_tire_width": 55, "front_tire_height": 50})
    sc = scene3d.build(solve(d))
    fails = [c for c in sc.clearances if not c.ok]
    assert fails and any(c.key in ("cs_tire", "ss_tire", "st_tire") for c in fails)


def test_oval_tube_meshes_elliptically():
    from bikebox.export import stl
    d = Design()
    d.update({"ss_od_top": 16, "ss_od2": 30, "ss_profile": "oval"})
    g = solve(d)
    _c, radii = stl._tube_centers(g.tubes["ss"], 8)
    depth, width = radii[-1]            # top end carries the oval section
    assert abs(width - 15.0) < 0.1 and abs(depth - 8.0) < 0.1 and width > depth
    # round tubes stay circular
    dr = Design(); gr = solve(dr)
    rd = stl._tube_centers(gr.tubes["dt"], 4)[1][0]
    assert abs(rd[0] - rd[1]) < 1e-6
