"""Build / cut sheet export."""
from bikebox.export import buildsheet
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_build_html_has_all_sections():
    g = solve(Design())
    html = buildsheet.build_html(g)
    for section in ("build sheet", "Key geometry", "Cut list", "Bill of materials", "Fixture setup"):
        assert section in html
    # key geometry values present
    assert "Head angle" in html and "Wheelbase" in html


def test_save_pdf_writes_valid_pdf(tmp_path, qapp):
    g = solve(Design())
    p = tmp_path / "sheet.pdf"
    buildsheet.save_pdf(g, p)
    data = p.read_bytes()
    assert data[:5] == b"%PDF-" and len(data) > 2000
