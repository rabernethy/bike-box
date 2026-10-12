"""Options for resolving geometry and clearance issues."""
from bikebox.geometry import clearance as C
from bikebox.geometry.remedies import active_keys, apply_choices, find_issues
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def _wide(width, **kw):
    d = Design()
    d.update({"rear_tire_width": width, "rear_tire_height": width * 0.9, "front_tire_width": width,
              "front_tire_height": width * 0.9, **kw})
    return d


def test_clean_design_has_no_issues():
    assert find_issues(Design()) == []


def test_each_option_resolves_its_own_issue():
    for iss in find_issues(_wide(55)):
        assert iss.options, f"no options offered for {iss.key}"
        for opt in iss.options:
            assert opt.resolves and opt.changes
            d2 = Design()
            d2.update({"rear_tire_width": 55, "rear_tire_height": 49.5, "front_tire_width": 55,
                       "front_tire_height": 49.5})
            d2.update(opt.changes)
            # the issue's own keys are no longer problems after this single option
            g2 = solve(d2)
            if iss.key == "rear_end":
                keys = [k for k in ("cs_tire", "cs_chainring", "cs_crank")]
            elif iss.key == "toe":
                keys = ["toe_steer_angle", "toe_clearance_3d"]
            else:
                keys = [iss.key]
            for k in keys:
                if k in C.TIRE_KEYS:
                    assert C.clearances(g2).get(k, -9) >= (C.threshold(g2, k) or 0) + 1 - 1e-6
                elif k in ("seatpost_insertion", "ht_overlap"):
                    pass
                else:
                    assert not C.is_problem(g2, k)


def test_multiple_options_per_tire_issue():
    issues = {i.key: i for i in find_issues(_wide(55))}
    assert "st_tire" in issues
    labels = [o.label for o in issues["st_tire"].options]
    assert any("chainstay" in l.lower() for l in labels)
    assert any("narrower" in l.lower() for l in labels)


def test_toe_overlap_offers_several_fixes():
    d = Design()
    d.update({"front_h_mode": "front_center", "front_center": 560, "front_tire_width": 44,
              "front_tire_height": 43})
    toe = [i for i in find_issues(d) if i.key == "toe"]
    assert toe and len(toe[0].options) >= 1
    # applying the first option clears the overlap
    d2 = d.copy()
    d2.update(toe[0].options[0].changes)
    assert not C.is_problem(solve(d2), "toe_steer_angle")


def test_seatpost_insertion_issue_and_fix():
    d = Design()
    d.update({"seat_tube_length": 300})
    issues = {i.key: i for i in find_issues(d)}
    assert "seatpost_insertion" in issues
    opt = issues["seatpost_insertion"].options[0]
    d2 = d.copy()
    d2.update(opt.changes)
    g2 = solve(d2)
    assert g2.v["seatpost_insertion"] >= d.f("seatpost_min_insertion")


def test_head_tube_overlap_issue_and_fix():
    d = Design()
    d.update({"front_v_mode": "ht_length", "head_tube_length": 70, "tt_ht_offset": 40, "dt_ht_offset": 40})
    issues = {i.key: i for i in find_issues(d)}
    assert "ht_overlap" in issues
    opt = issues["ht_overlap"].options[0]
    d2 = d.copy()
    d2.update(opt.changes)
    assert solve(d2).v["ht_exposed"] >= 0.0


def test_apply_choices_merges_and_reduces_problems():
    d = _wide(50, fenders=True)
    issues = find_issues(d)
    chosen = [i.options[0] for i in issues if i.options]
    changes = apply_choices(d, chosen)
    d2 = d.copy()
    d2.update(changes)
    assert len(active_keys(solve(d2))) < len(active_keys(solve(d)))
