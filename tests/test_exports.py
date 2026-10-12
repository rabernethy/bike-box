"""Tests for the drawing-sheet / CSV / 3-D / animation exporters.

Run: ``QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest -q tests/test_exports.py``
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bikebox.model.design import Design
from bikebox.geometry.solver import solve


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _design(**vals) -> Design:
    d = Design()
    for k, v in vals.items():
        d[k] = v
    return d


# --------------------------------------------------------------------------
# drawing sheets: PDF / SVG / PNG / scale
# --------------------------------------------------------------------------
def test_pdf_starts_with_magic_and_one_page(qapp, tmp_path):
    from bikebox.export import drawing as D
    d = _design(title="Road", designer="RD")
    path = D.save_pdf(d, tmp_path / "sheet.pdf")
    raw = Path(path).read_bytes()
    assert raw[:5] == b"%PDF-"
    pages = raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    assert pages == 1


def test_multi_pdf_page_count(qapp, tmp_path):
    from bikebox.export.multi_pdf import save_multi_pdf
    designs = [_design(title=f"D{i}", reach=380 + 10 * i) for i in range(3)]
    path = save_multi_pdf(designs, tmp_path / "multi.pdf", overlay_page=True)
    raw = Path(path).read_bytes()
    assert raw[:5] == b"%PDF-"
    pages = raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    assert pages == 4                       # 3 designs + overlay comparison

    path2 = save_multi_pdf(designs, tmp_path / "multi2.pdf", overlay_page=False)
    raw2 = Path(path2).read_bytes()
    assert raw2.count(b"/Type /Page") - raw2.count(b"/Type /Pages") == 3


def test_sheet_svg_parses(qapp, tmp_path):
    import defusedxml.ElementTree as ET
    from bikebox.export import drawing as D
    path = D.save_sheet_svg(_design(title="SVG"), tmp_path / "sheet.svg")
    root = ET.parse(str(path)).getroot()
    assert root.tag.endswith("svg")
    assert root.attrib["width"].endswith("mm")


def test_sheet_png_dimensions(qapp, tmp_path):
    from bikebox.export import drawing as D
    from bikebox.qt import QtGui
    opts = D.SheetOptions(page="A4", dpi=100)
    path = D.save_sheet_png(_design(), tmp_path / "sheet.png", opts, dpi=100)
    img = QtGui.QImage(str(path))
    assert not img.isNull()
    w, h = D.page_size(opts)
    assert abs(img.width() - round(w * 100 / 25.4)) <= 2


def test_scale_auto_selection_fits(qapp):
    from bikebox.export import drawing as D
    d = _design()
    for page in ("A4", "A3", "A2", "Letter"):
        opts = D.SheetOptions(page=page)
        sheet = D.build_sheet(d, opts=opts)
        # the chosen scale must be one of the standard ratios
        assert any(abs(sheet.scale - v) < 1e-9 for v, _ in D.STANDARD_SCALES)
        bx0, by0, bx1, by1 = sheet.bike.bounds()
        bw = (bx1 - bx0) * sheet.scale
        bh = (by1 - by0) * sheet.scale
        avail_w = sheet.page_w - 2 * opts.margin
        avail_h = sheet.page_h - 2 * opts.margin
        assert bw <= avail_w and bh <= avail_h


def test_scale_explicit_and_label():
    from bikebox.export import drawing as D
    assert D.scale_label(0.1) == "1:10"
    assert D.scale_label(0.4) == "1:2.5"
    assert D.scale_label(1.0) == "1:1"


def test_explicit_scale_honoured(qapp):
    from bikebox.export import drawing as D
    sheet = D.build_sheet(_design(), opts=D.SheetOptions(page="A0", scale=0.2))
    assert abs(sheet.scale - 0.2) < 1e-9


def test_geometry_and_tube_tables(qapp):
    from bikebox.export import drawing as D
    g = solve(_design())
    gt = D.geometry_table(g, "mm")
    assert gt[0][0] == "Dimension"
    labels = [r[0] for r in gt]
    assert "Stack" in labels and "Head tube angle" in labels and "Trail" in labels
    tt = D.tube_table(g, "mm")
    assert tt[0] == ["Tube", "OD x wall", "Material", "Length (c-c)", "Mass"]
    assert any(row[0].startswith("Top tube") for row in tt[1:])
    # mass column ends with grams
    assert all(row[-1].endswith("g") for row in tt[1:])


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def test_csv_record_driving_vs_driven():
    d = _design(title="Rec", reach=395)
    rec = __import__("bikebox.export.csv_export", fromlist=["design_record"]).design_record(d)
    assert rec["title"] == "Rec"
    assert "reach" in rec                        # driving (input) column
    assert "calc:stack" in rec                   # driven (computed) column, prefixed
    assert rec["reach"] == "395"


def test_csv_roundtrip_and_union_columns(tmp_path):
    from bikebox.export import csv_export as C
    a = _design(title="A")
    b = _design(title="B")
    b.set("some_future_param", "xyz")            # unknown key -> not a column
    path = C.export_csv([("a", a), ("b", b)], tmp_path / "designs.csv")
    rows = C.read_csv_table(path)
    header = rows[0]
    assert header[0] == "source" and header[1] == "title"
    # calc columns come after all parameter columns
    calc_idx = [i for i, c in enumerate(header) if c.startswith("calc:")]
    param_idx = [i for i, c in enumerate(header) if i and not c.startswith("calc:")]
    assert min(calc_idx) > max(param_idx)
    assert len(rows) == 3                          # header + 2 designs
    # round-trip a value
    ti = header.index("title")
    assert {rows[1][0], rows[2][0]} == {"a", "b"}
    assert {rows[1][ti], rows[2][ti]} == {"A", "B"}


def test_csv_union_across_differing_columns(tmp_path):
    from bikebox.export import csv_export as C
    a = _design(title="A")
    b = _design(title="B")
    path = C.export_csv([("a", a), ("b", b)], tmp_path / "u.csv")
    rows = C.read_csv_table(path)
    # every data row has exactly as many fields as the header (ragged rows filled)
    assert all(len(r) == len(rows[0]) for r in rows)


def test_export_folder_csv(tmp_path):
    from bikebox.export import csv_export as C
    (tmp_path / "x").mkdir()
    _design(title="One").save(tmp_path / "x" / "one.bikebox")
    _design(title="Two").save(tmp_path / "x" / "two.bikebox")
    path = C.export_folder_csv(tmp_path / "x", tmp_path / "folder.csv")
    rows = C.read_csv_table(path)
    assert len(rows) == 3
    titles = {r[1] for r in rows[1:]}
    assert titles == {"One", "Two"}


# --------------------------------------------------------------------------
# FreeCAD macro (stub execution)
# --------------------------------------------------------------------------
def test_freecad_macro_compiles_and_runs_against_stubs(qapp):
    from bikebox.export import freecad as F
    g = solve(_design())
    macro = F.freecad_macro(g, mitre=True)
    code = compile(macro, "<macro>", "exec")    # must be valid Python

    freecad = MagicMock(name="FreeCAD")
    part = MagicMock(name="Part")
    gui = MagicMock(name="FreeCADGui")
    stubs = {"FreeCAD": freecad, "Part": part, "FreeCADGui": gui}
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        exec(code, {})
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    assert freecad.newDocument.called
    assert part.makeCone.called or part.makeCylinder.called
    # one object per tube + bb shell at least
    assert freecad.newDocument.return_value.addObject.call_count >= len(g.tubes) + 1


def test_freecad_macro_saved(qapp, tmp_path):
    from bikebox.export import freecad as F
    path = F.save_freecad_macro(solve(_design()), tmp_path / "frame.FCMacro")
    text = Path(path).read_text()
    assert "import FreeCAD" in text and "Part" in text
    assert "Z=y" in text                         # documents the coordinate mapping


# --------------------------------------------------------------------------
# STL
# --------------------------------------------------------------------------
def test_stl_binary_format(tmp_path):
    from bikebox.export import stl as S
    g = solve(_design())
    tris = S.frame_mesh(g, segments=16)
    assert len(tris) > 0
    path = S.save_stl(g, tmp_path / "frame.stl", binary=True, segments=16)
    raw = Path(path).read_bytes()
    count = struct.unpack("<I", raw[80:84])[0]
    assert count == len(tris)
    assert len(raw) == 84 + 50 * count           # 80 header + 4 count + 50/triangle


def test_stl_mesh_bounds_match_frame(tmp_path):
    from bikebox.export import stl as S
    g = solve(_design())
    tris = S.frame_mesh(g, segments=24)
    (minx, miny, minz), (maxx, maxy, maxz) = S.mesh_bounds(tris)
    # x spans at least from the rear axle to the head tube top region
    assert minx <= g.p["rear_axle"].x + 1
    assert maxx >= g.p["ht_top"].x - 1
    # z extent reflects the stays' lateral spread and BB shell width
    half_bb = g.design.f("bb_shell_width") / 2.0
    assert maxz >= half_bb - 1 and minz <= -half_bb + 1
    # mesh straddles the BB origin vertically
    assert miny < 0 < maxy


def test_stl_ascii(tmp_path):
    from bikebox.export import stl as S
    g = solve(_design())
    path = S.save_stl(g, tmp_path / "frame_ascii.stl", binary=False, segments=8)
    text = Path(path).read_text()
    assert text.startswith("solid ") and text.strip().endswith("endsolid bikebox")
    assert "facet normal" in text and "vertex" in text


# --------------------------------------------------------------------------
# GIF morph
# --------------------------------------------------------------------------
def test_morph_frames_endpoints():
    from bikebox.export.gif import morph_frames
    a = _design(reach=370)
    b = _design(reach=410)
    frames = morph_frames(a, b, 5)
    assert len(frames) == 5
    assert abs(frames[0].f("reach") - 370) < 1e-6
    assert abs(frames[-1].f("reach") - 410) < 1e-6
    assert 370 < frames[2].f("reach") < 410


def test_gif_frame_count(qapp, tmp_path):
    from PIL import Image
    from bikebox.export.gif import save_morph_gif
    a = _design(title="S", reach=370, front_v_mode="stack", stack=560)
    b = _design(title="B", reach=410, front_v_mode="stack", stack=600)
    n = save_morph_gif(a, b, tmp_path / "m.gif", frames=6, size=(240, 160), pingpong=False)
    assert n == 6
    assert Image.open(str(tmp_path / "m.gif")).n_frames == 6


def test_gif_pingpong_frame_count(qapp, tmp_path):
    from PIL import Image
    from bikebox.export.gif import save_morph_gif
    a = _design(reach=370, front_v_mode="stack", stack=560)
    b = _design(reach=410, front_v_mode="stack", stack=600)
    n = save_morph_gif(a, b, tmp_path / "pp.gif", frames=6, size=(240, 160), pingpong=True)
    assert n == 10                               # 6 + (6-2) reversed interior frames
    assert Image.open(str(tmp_path / "pp.gif")).n_frames == 10


# --------------------------------------------------------------------------
# bulk
# --------------------------------------------------------------------------
def test_bulk_export(qapp, tmp_path):
    from bikebox.export.bulk import bulk_export
    src = tmp_path / "src"
    src.mkdir()
    _design(title="One").save(src / "one.bikebox")
    _design(title="Two", reach=405).save(src / "two.bikebox")
    out = tmp_path / "out"
    written = bulk_export(sorted(src.glob("*.bikebox")), out, formats=("pdf", "svg", "dxf", "csv"))
    exts = {Path(w).suffix for w in written}
    assert {".pdf", ".svg", ".dxf", ".csv"} <= exts
    # one combined CSV, one of each per-design format
    assert sum(1 for w in written if Path(w).suffix == ".csv") == 1
    assert sum(1 for w in written if Path(w).suffix == ".pdf") == 2
    assert all(Path(w).exists() for w in written)


def _mediaboxes(path):
    import re
    data = open(path, "rb").read().decode("latin-1")
    return [tuple(float(x) for x in m.groups()) for m in
            re.finditer(r"/MediaBox \[\s*0 0 ([0-9.]+) ([0-9.]+)\s*\]", data)]


@pytest.mark.parametrize("page,landscape", [("A3", True), ("A4", False), ("Letter", True)])
def test_pdf_page_orientation(qapp, tmp_path, page, landscape):
    """Regression: landscape sheets must not be rotated twice onto a portrait page."""
    from bikebox.export.drawing import PAGE_SIZES, SheetOptions, save_pdf
    from bikebox.model.design import Design
    p = tmp_path / "o.pdf"
    save_pdf(Design(), p, SheetOptions(page=page, landscape=landscape))
    (w, h), = _mediaboxes(p)
    assert (w > h) == landscape
    long_mm = max(PAGE_SIZES[page]) / 25.4 * 72
    assert abs(max(w, h) - long_mm) < 2
