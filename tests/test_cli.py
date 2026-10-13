"""Headless CLI subcommands."""
from bikebox.__main__ import main


def test_cli_bom(tmp_path):
    src = "bikebox/data/templates/road_race.bikebox"
    out = tmp_path / "bom.csv"
    assert main(["bom", src, str(out)]) == 0
    text = out.read_text()
    assert "Component,Part,Spec,Brand,Weight (g)" in text


def test_cli_sizes(tmp_path):
    out = tmp_path / "sizes.csv"
    assert main(["sizes", "bikebox/data/templates/road_race.bikebox", str(out), "4"]) == 0
    assert len(out.read_text().strip().splitlines()) == 5      # header + 4 sizes


def test_cli_buildsheet(tmp_path, qapp):
    out = tmp_path / "sheet.pdf"
    assert main(["buildsheet", "bikebox/data/templates/road_race.bikebox", str(out)]) == 0
    assert out.read_bytes()[:5] == b"%PDF-"
