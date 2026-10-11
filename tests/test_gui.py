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


def test_aux_panel_values(window, qapp):
    window.show_aux()
    qapp.processEvents()
    panel = window.aux_dock.widget()
    tree = panel.values
    assert tree.topLevelItemCount() > 10
    labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert "Chainstay to tire" in labels
    for i in range(panel.tabs.count()):
        panel.tabs.setCurrentIndex(i)
        panel.refresh()
        assert panel.viewers[i]._scene is not None


def test_feature_dialogs_construct(window, qapp):
    """Every integration dialog opens against the real feature modules."""
    from framewright.gui.dialogs import DecalsDialog
    from framewright.gui.drawing_dialog import DrawingDialog
    from framewright.gui.fit_dialog import FitAdvisorDialog
    from framewright.gui.library_dialog import LibraryDialog
    from framewright.gui.main_window import TemplatePicker
    from framewright.gui.mitre_dialog import MitreDialog
    from framewright.gui.report_dialog import ReportDialog
    from framewright.model import templates
    doc = window.doc()
    dlgs = [FitAdvisorDialog(doc, window), MitreDialog(doc, window), ReportDialog(doc, window, focus="UCI"),
            LibraryDialog(doc, window), DrawingDialog(doc, window, "pdf"), DecalsDialog(doc, window),
            TemplatePicker(templates, window)]
    for dlg in dlgs:
        dlg.show()
        qapp.processEvents()
    assert dlgs[0].recs and len(dlgs[1].cuts) >= 6 and dlgs[2].tabs.count() >= 5
    assert dlgs[3].cats.count() >= 10 and dlgs[6].infos
    lib = dlgs[3]
    lib.cats.setCurrentRow(0)
    lib.items.setCurrentRow(0)
    lib.apply()                                   # tube set applies through undo
    assert doc.undo.canUndo()
    for dlg in dlgs:
        dlg.reject()


def test_extra_tube_tool_and_presets(window, qapp):
    from framewright.gui import extra_tubes as XT
    doc = window.doc()
    c = window.view().canvas
    g = doc.geometry
    q, spec, _ = c._snap_spec(g.tubes["dt"].point_at(g.tubes["dt"].length * 0.4)[0])
    assert spec == {"tube": "dt", "pos": 0.4}
    assert c._snap_spec(g.p["ht_bottom"])[1] == "ht_bottom"
    for _title, _tip, tubes in XT.PRESETS:
        XT.add_tubes(doc, tubes)
    g = doc.geometry
    extra = [n for n, t in g.tubes.items() if t.kind == "extra"]
    assert len(extra) == len(XT.PRESETS) and not g.warnings
    # extra tubes follow the frame: lengthen the head tube and the step tube end moves with it
    step = next(n for n in extra if n.endswith("_step"))
    a0 = g.tubes[step].a
    doc.set_param("head_tube_length", 170)
    assert doc.geometry.tubes[step].a.dist(a0) > 1
    dlg = XT.ExtraTubeEditor(doc, doc.design.extras["extra_tubes"][0], window)
    dlg.od.setValue(22.2)
    dlg.profile.setCurrentIndex(dlg.profile.findData("oval"))
    dlg.accept()
    assert dlg.tube["od"] == 22.2 and dlg.tube["profile"] == "oval"
    XT.delete_tube(doc, 0)
    assert len([t for t in doc.geometry.tubes.values() if t.kind == "extra"]) == len(XT.PRESETS) - 1


def test_junction_handles_are_exact(window):
    from framewright.gui.canvas import drag_point_changes
    doc = window.doc()
    for mode in ("centerline", "stickout"):
        doc.set_param("ht_junction_mode", mode)
        d0, g0 = doc.design.copy(), doc.geometry
        for name, axis, delta in (("tt_ht", g0.u, -12), ("dt_ht", g0.u, 9), ("tt_st", g0.s, -20),
                                  ("ss_top", g0.s, -15)):
            target = g0.p[name] + axis * delta
            ch, _ = drag_point_changes(name, target, d0, g0, False)
            d1 = d0.copy()
            d1.update(ch)
            assert solve(d1).p[name].dist(target) < 1e-6, (mode, name)
