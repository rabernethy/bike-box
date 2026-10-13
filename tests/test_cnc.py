"""CNC notcher + bender outputs."""
import math

from bikebox.export import cnc
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_bend_spec_math():
    s = cnc.bend_spec(400.0, 10.0)
    # radius from chord+sagitta, checked against the circle relation R = (c^2/4 + s^2)/(2s)
    assert abs(s["radius"] - (400**2 / 4 + 100) / 20) < 1e-6
    assert s["arc"] >= s["chord"] and 0 < s["angle"] < 30
    assert cnc.bend_spec(400, 0) == {}


def test_notcher_rows_match_mitre_count():
    from bikebox.geometry.mitre import compute_mitres
    g = solve(Design())
    rows = cnc.notcher_rows(g)
    assert rows[0][0] == "Tube end"
    assert len(rows) - 1 == len(compute_mitres(g, samples=120))
    # each data row carries a hole-saw size
    assert all("mm" in r[2] or "in" in r[2] for r in rows[1:])


def test_bender_rows_only_bent_tubes():
    d = Design()
    assert len(cnc.bender_rows(solve(d))) >= 1          # header only (chainstay may be straight)
    d.update({"cs_bend": -6, "ss_bend": 8})
    rows = cnc.bender_rows(solve(d))
    tubes = {r[0] for r in rows[1:]}
    assert "Chainstay" in tubes and "Seat stay" in tubes


def test_cli_cnc(tmp_path):
    from bikebox.__main__ import main
    out = tmp_path / "cnc.csv"
    assert main(["cnc", "bikebox/data/templates/road_race.bikebox", str(out)]) == 0
    assert "notcher" in out.read_text().lower()
