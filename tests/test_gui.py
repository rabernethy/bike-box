"""GUI smoke tests (offscreen)."""
import pytest

from bikebox.geometry.solver import solve
from bikebox.geometry.vec import V


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from bikebox.gui.app import _load_plugins
    _load_plugins()
    from bikebox.gui.main_window import MainWindow
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
    from bikebox.gui.param_panel import ordered_groups
    panel = window.params
    for g in ordered_groups():
        panel.show_group(g)
    assert len(panel.pages) == len(ordered_groups())


def test_joints_page_not_empty_with_default_joint_style(window):
    # the Joints page must show at least the joint-style selector even for the
    # default TIG joint (regression: it was empty because every lug option is
    # hidden and the selector lived on another page)
    panel = window.params
    panel.show_group("Joints")
    page = panel.pages["Joints"]
    assert window.doc().design["joint_style"] == "tig"
    assert "joint_style" in page.rows
    label, ed, _box = page.rows["joint_style"]
    assert ed.isVisibleTo(page) and label.isVisibleTo(page)


def test_extra_tube_paint_and_in_phase(window):
    from bikebox.gui import extra_tubes as XT
    doc = window.doc()
    XT.add_tubes(doc, [{"name": "lat", "a": {"tube": "st", "pos": 0.4}, "b": {"tube": "ht", "pos": 0.6},
                        "od": 19, "wall": 0.9, "paint": "#2277cc", "parallel_to": "tt", "phase_anchor": "a"}])
    g = doc.geometry
    tt, x = g.tubes["tt"], g.tubes["x0_lat"]
    td, xd = (tt.b - tt.a).norm(), (x.b - x.a).norm()
    assert abs(td.x * xd.y - td.y * xd.x) < 1e-6          # parallel to the top tube
    from bikebox.render.bike_scene import build_scene
    fills = [getattr(p.style, "fill", None) for p in build_scene(g).prims if getattr(p, "tag", "") == "tube:x0_lat"]
    assert "#2277cc" in fills


def test_drag_changes(window):
    from bikebox.gui.canvas import drag_point_changes
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
    p = tmp_path / "bike.bikebox"
    doc.save(p)
    assert not doc.dirty
    d2 = window.open_path(p)
    assert d2 is doc            # already open -> same tab
    window.close_tab(window.tabs.currentIndex())
    d3 = window.open_path(p)
    assert d3.design["reach"] == 401


def test_dialogs_construct(window, qapp):
    from bikebox.gui import dialogs as D
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
    from bikebox.gui.dialogs import DecalsDialog
    from bikebox.gui.drawing_dialog import DrawingDialog
    from bikebox.gui.fit_dialog import FitAdvisorDialog
    from bikebox.gui.library_dialog import LibraryDialog
    from bikebox.gui.main_window import TemplatePicker
    from bikebox.gui.mitre_dialog import MitreDialog
    from bikebox.gui.report_dialog import ReportDialog
    from bikebox.model import templates
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
    lib.items.setCurrentItem(lib.items.topLevelItem(0))
    lib.apply()                                   # tube set applies through undo
    assert doc.undo.canUndo()
    # the sourced catalog shows specs and source links
    lib.search.setText("SID SL")
    lib.sourced.setChecked(True)
    assert lib.items.topLevelItemCount() > 0
    lib.items.setCurrentItem(lib.items.topLevelItem(0))
    assert "Sources" in lib.info.toHtml() and "sram.com" in lib.info.toHtml()
    for dlg in dlgs:
        dlg.reject()


def test_extra_tube_tool_and_presets(window, qapp):
    from bikebox.gui import extra_tubes as XT
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


def test_dimension_tool_snaps_to_tubes(window):
    # the measure/dimension tools snap to positions along tubes (incl. extra
    # tubes), storing a {"tube","pos"} spec, not just named frame points
    from bikebox.gui import extra_tubes as XT
    doc = window.doc()
    XT.add_tubes(doc, [{"name": "lat", "a": "st_top", "b": "ht_top", "od": 19, "wall": 0.9}])
    c = window.view().canvas
    c.zoom = 3.0                                              # zoomed in: a realistic snap radius
    g = doc.geometry
    mid = (g.tubes["tt"].a + g.tubes["tt"].b) * 0.5          # a point on the top tube, not a named point
    q, spec, _ = c._snap_spec(mid)
    assert isinstance(spec, dict) and spec.get("tube") == "tt"
    xmid = (g.tubes["x0_lat"].a + g.tubes["x0_lat"].b) * 0.5  # a point on the extra tube
    _, xspec, _ = c._snap_spec(xmid)
    assert isinstance(xspec, dict) and xspec.get("tube") == "x0_lat"
    # a user dimension built from those specs resolves and follows the geometry
    from bikebox.geometry import dimensions as DIM
    assert DIM.build_user(g, {"id": "u1", "kind": "aligned", "points": [spec, xspec], "offset": 30}) is not None


def test_catalog_pickers_apply_parts(window):
    from bikebox.gui.catalog_picker import CatalogPicker
    from bikebox.model import library as L
    doc = window.doc()
    # per-tube picker changes only that tube position
    pk = CatalogPicker(doc, "tubing", "dt", window)
    assert pk._items and all("dt" in L.item_tube_positions(i) for i in pk._items)
    tt0 = doc.design.f("tt_od")
    pk.list.setCurrentRow(0)
    chosen = pk._items[0]
    pk.use()
    assert abs(doc.design.f("dt_od") - float(chosen.values["tubes"]["dt"]["od"])) < 1e-6
    assert doc.design.f("tt_od") == tt0                       # other tubes untouched
    assert doc.undo.canUndo()                                 # applied as one undo step
    # a component picker (fork) applies its values
    fk = CatalogPicker(doc, "forks", None, window)
    fk.list.setCurrentRow(0)
    chosen_fork = fk._items[0]
    fk.use()
    assert abs(doc.design.f("fork_length") - float(chosen_fork.values["fork_length"])) < 1e-6


def test_param_panel_has_catalog_buttons(window):
    from bikebox.gui.param_panel import SECTION_CATALOG, ordered_groups
    from bikebox.qt import QtWidgets
    panel = window.params
    for g in ordered_groups():
        panel.show_group(g)
    found = sum(len([b for b in page.findChildren(QtWidgets.QPushButton) if b.text().endswith("…")])
                for page in panel.pages.values())
    assert found >= sum(len(v) for v in SECTION_CATALOG.values())


def test_junction_handles_are_exact(window):
    from bikebox.gui.canvas import drag_point_changes
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
