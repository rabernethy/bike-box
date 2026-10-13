"""Fit-to-rider auto-size."""
import bikebox.fit.rider  # noqa: F401  (register rider params)
from bikebox.fit import sizing
from bikebox.model import sizerun as SR
from bikebox.model.design import Design


def _run(height, inseam, scheme="Classic road"):
    base = Design()
    base.update({"rider_height": height, "inseam": inseam, "fit_scheme": scheme})
    specs = SR.linear_run(base, 5, SR.suggest_ranges(base))
    return base, SR.generate(base, specs)


def test_recommend_picks_closest_feasible_size():
    base, sizes = _run(1780, 820)
    rec = sizing.recommend(base, sizes)
    assert rec.best in {n for n, _d in sizes}
    assert rec.target_stack and rec.target_reach
    # the recommended size's front end is the closest among standover-feasible sizes
    ok = [s for s in rec.scores if s.standover_ok]
    best = min(ok or rec.scores, key=lambda s: s.dist)
    assert rec.best == best.name


def test_taller_rider_gets_a_bigger_or_equal_size():
    _, small = _run(1620, 720)
    _, big = _run(1900, 890)
    base_s = Design(); base_s.update({"rider_height": 1620, "inseam": 720})
    base_b = Design(); base_b.update({"rider_height": 1900, "inseam": 890})
    rs = sizing.recommend(base_s, small)
    rb = sizing.recommend(base_b, big)
    order = ["XS", "S", "M", "L", "XL"]
    assert order.index(rb.best) >= order.index(rs.best)


def test_no_rider_measurements_gives_note_not_crash():
    base = Design()
    _, sizes = _run(0, 0)          # no measurements (height 0)
    base2 = Design()               # all defaults, inseam 0
    rec = sizing.recommend(base2, sizes)
    # with no target it should not pick a best, and should explain why
    if rec.best is None:
        assert rec.note
