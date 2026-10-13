"""Full-size 1:1 tiled PDF."""
from bikebox.export import fullsize
from bikebox.geometry.solver import solve
from bikebox.model.design import Design


def test_tiling_grid():
    T = fullsize.tiling((-300, -300, 300, 300), page="A4", landscape=True)
    assert T["cols"] >= 1 and T["rows"] >= 1 and T["pw"] == 297.0 and T["ph"] == 210.0


def test_frame_only_uses_fewer_pages_than_with_wheels(tmp_path, qapp):
    g = solve(Design())
    frame = tmp_path / "frame.pdf"
    full = tmp_path / "full.pdf"
    fullsize.save_fullsize_pdf(g, frame, page="A4", include_wheels=False)
    fullsize.save_fullsize_pdf(g, full, page="A4", include_wheels=True)
    def pages(p):
        d = p.read_bytes()
        return d.count(b"/Type /Page") - d.count(b"/Type /Pages")
    assert frame.read_bytes()[:5] == b"%PDF-"
    assert pages(frame) >= 1 and pages(frame) < pages(full)
