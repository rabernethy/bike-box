"""GUI smoke tests (offscreen)."""
import pytest

from framewright.geometry.solver import solve
from framewright.geometry.vec import V


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from framewright.gui.app import _load_plugins
    _load_plugins()
    from framewright.gui.main_window import MainWindow
    w = MainWindow()
    w.settings.clear()
    w.resize(1400, 900)
    w.new_doc()
    w.show()
    qapp.processEvents()
    yield w
    for d in w.docs():
        d.undo.setClean()
    w.close()


def test_window_renders(window, qapp):
    img = window.grab()
    assert not img.isNull()
    c = window.view().canvas
    c.repaint()
    assert c.scene().prims


def test_param_edit_and_undo(window):
    doc = window.doc()
    before = doc.geometry.v["stack"]
    doc.set_param("head_tube_length", 180)
    assert doc.geometry.v["stack"] > before
    doc.undo.undo()
    assert abs(doc.geometry.v["stack"] - before) < 1e-9
    doc.undo.redo()
    assert doc.design["head_tube_length"] == 180


def test_param_pages_build_for_every_group(window):
    from framewright.gui.param_panel import ordered_groups
    panel = window.params
    for g in ordered_groups():
        panel.show_group(g)
    assert len(panel.pages) == len(ordered_groups())


def test_drag_changes(window):
    from framewright.gui.canvas import drag_point_changes
    doc = window.doc()
    d0, g0 = doc.design.copy(), doc.geometry
    ch, _ = drag_point_changes("saddle", g0.p["saddle"] + g0.s * 20, d0, g0, False)
    assert abs(ch["saddle_height"] - (d0.f("saddle_height") + 20)) < 1e-6
    ch, _ = drag_point_changes("ht_top", g0.p["ht_top"] + V(10, 5), d0, g0, False)
    d1 = d0.copy()
    d1.update(ch)
    g1 = solve(d1)
    assert abs(g1.v["reach"] - (g0.v["reach"] + 10)) < 1e-6
    assert abs(g1.v["stack"] - (g0.v["stack"] + 5)) < 1e-6
    ch, _ = drag_point_changes("bar", g0.p["bar"] + V(15, 8), d0, g0, False)
    d1 = d0.copy()
    d1.update(ch)
    g1 = solve(d1)
    assert g1.p["bar"].dist(g0.p["bar"] + V(15, 8)) < 1e-6


def test_dimension_drag_offset(window):
    doc = window.doc()
    doc.set_extra("dimension_offsets", {"stack": 120.0}, "x")
    sc = window.view().canvas.scene()
    dims = [p for p in sc.prims if getattr(p, "dim_id", "") == "stack"]
    assert dims and dims[0].offset == 120.0


def test_save_and_reopen(window, tmp_path):
    doc = window.doc()
    doc.set_param("reach", 401)
    p = tmp_path / "bike.fwd"
    doc.save(p)
    assert not doc.dirty
    d2 = window.open_path(p)
    assert d2 is doc            # already open -> same tab
    window.close_tab(window.tabs.currentIndex())
    d3 = window.open_path(p)
    assert d3.design["reach"] == 401


def test_dialogs_construct(window, qapp):
    from framewright.gui import dialogs as D
    doc = window.doc()
    for cls in (D.DimensionsDialog, D.SnapshotsDialog, D.TitleBlockDialog, D.ExtraTubesDialog):
        dlg = cls(doc, window)
        dlg.show()
        qapp.processEvents()
        dlg.reject()
    D.CompareDialog(doc, window.docs(), window).reject()
    D.PhotoDialog(doc, None, window).reject()
