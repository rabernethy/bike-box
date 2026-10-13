"""Size-run generator."""
from bikebox.geometry.solver import solve
from bikebox.model import sizerun as SR
from bikebox.model.design import Design


def test_linear_run_interpolates_and_names():
    base = Design()
    specs = SR.linear_run(base, 5, {"seat_tube_length": (480, 600), "stack": (540, 630), "reach": (365, 415)})
    assert [s.name for s in specs] == ["XS", "S", "M", "L", "XL"]
    assert specs[0].overrides["seat_tube_length"] == 480
    assert specs[-1].overrides["seat_tube_length"] == 600
    assert specs[2].overrides["reach"] == 390            # midpoint


def test_generate_applies_overrides_and_scales_geometry():
    base = Design()
    specs = SR.linear_run(base, 3, SR.suggest_ranges(base))
    sizes = SR.generate(base, specs)
    assert len(sizes) == 3
    gs = [solve(d) for _n, d in sizes]
    # stack, reach and standover increase monotonically with size
    for key in ("stack", "reach", "standover", "wheelbase"):
        vals = [g.v[key] for g in gs]
        assert vals[0] < vals[1] < vals[2], key
    # seat-tube length is taken from the override
    assert abs(sizes[0][1].f("seat_tube_length") - specs[0].overrides["seat_tube_length"]) < 1e-6


def test_generate_switches_to_stack_reach_mode():
    base = Design()
    sizes = SR.generate(base, [SR.SizeSpec("M", {"stack": 600, "reach": 400})])
    d = sizes[0][1]
    assert d["front_v_mode"] == "stack" and d["front_h_mode"] == "reach"
    g = solve(d)
    assert abs(g.v["stack"] - 600) < 1.0 and abs(g.v["reach"] - 400) < 1.0
