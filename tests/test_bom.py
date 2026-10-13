"""Bill of materials."""
from bikebox.analysis import bom
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_bom_lists_tubes_and_fork_by_default():
    d = Design()
    rows = {r.component: r for r in bom.build(d, solve(d))}
    for c in ("Top tube", "Down tube", "Seat tube", "Head tube", "Chainstays", "Seat stays", "Fork"):
        assert c in rows and rows[c].spec           # specs computed from the design
    assert all(not rows[c].sourced for c in ("Top tube", "Fork"))   # nothing assigned yet


def test_assigned_part_appears_sourced():
    d = Design()
    d.extras["bom"] = {"dt": {"name": "Columbus Zona down tube", "brand": "Columbus",
                              "source": "https://example.com", "category": "tubing"},
                       "forks": {"name": "ACME Fork", "brand": "ACME", "category": "forks"}}
    rows = {r.component: r for r in bom.build(d, solve(d))}
    assert rows["Down tube"].part == "Columbus Zona down tube" and rows["Down tube"].sourced
    assert rows["Down tube"].brand == "Columbus"
    assert rows["Fork"].part == "ACME Fork" and rows["Fork"].sourced
    # a tube spec still comes from the design, not the catalog name
    assert rows["Down tube"].spec and "Ø" in rows["Down tube"].spec


def test_bom_csv_round_structure():
    d = Design()
    csv = bom.to_csv(d, solve(d))
    lines = csv.strip().splitlines()
    assert lines[0] == "Component,Part,Spec,Brand,Weight (g),Sourced,Source"
    assert any(line.startswith("Fork,") for line in lines)


def test_component_only_listed_when_assigned():
    d = Design()
    rows = {r.component for r in bom.build(d, solve(d))}
    assert "Crankset" not in rows                    # no crank assigned
    d.extras["bom"] = {"cranks": {"name": "Dura-Ace", "category": "cranks"}}
    rows = {r.component for r in bom.build(d, solve(d))}
    assert "Crankset" in rows


def test_bom_weights_and_total():
    d = Design()
    d.extras["bom"] = {"forks": {"name": "ACME Fork", "weight_g": 480, "category": "forks"},
                       "saddles": {"name": "Flite", "weight_g": 220, "category": "saddles"}}
    rows = {r.component: r for r in bom.build(d, solve(d))}
    assert rows["Fork"].weight_g == 480 and not rows["Fork"].weight_est
    assert rows["Top tube"].weight_g and rows["Top tube"].weight_est      # tube estimated
    total, est = bom.total_weight(list(rows.values()))
    assert total > 480 + 220 and est
    csv = bom.to_csv(d, solve(d))
    assert "Weight (g)" in csv and "Total" in csv
