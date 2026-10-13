"""Bike Box main window."""
from __future__ import annotations

import importlib
import traceback
from pathlib import Path

from .. import APP_NAME, __version__
from ..geometry.solver import solve
from ..model.design import FILE_SUFFIX, Design
from ..qt import QtCore, QtGui, QtWidgets, QtPrintSupport
from . import dialogs as D
from .canvas import BikeCanvas
from .document import Document
from .param_panel import ParamPanel
from .results_panel import ResultsPanel

Qt = QtCore.Qt
FILE_FILTER = f"Bike Box designs (*{FILE_SUFFIX});;BikeCAD designs (*.bcad);;All files (*)"


def _optional(module: str):
    """Import an optional feature module; None if it isn't available."""
    try:
        return importlib.import_module(module, __package__)
    except ImportError:
        return None
    except Exception:              # a broken optional module must not stop the app
        traceback.print_exc()
        return None


class DocumentView(QtWidgets.QWidget):
    def __init__(self, doc: Document, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = BikeCanvas(doc)
        self.canvas.ui_scale = float(settings.value("ui/line_scale", 1.0))
        self.canvas.reverse_wheel = settings.value("ui/reverse_wheel", "false") in (True, "true")
        self.canvas.show_handles = settings.value("ui/handles", "true") in (True, "true")
        lay.addWidget(self.canvas)

    def update_ghosts(self) -> None:
        self.canvas.set_ghosts([(solve(gh["design"]), gh["color"]) for gh in self.doc.ghosts])


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings("Bike Box", "Bike Box")
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 950)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab)
        self.setCentralWidget(self.tabs)
        self.setAcceptDrops(True)

        self.params = ParamPanel()
        self.results = ResultsPanel()
        self.dock_params = self._dock("Parameters", self.params, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.dock_results = self._dock("Results", self.results, Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock_params.setMinimumWidth(360)
        self.dock_results.setMinimumWidth(250)
        self.aux_dock = None
        self.view3d_dock = None

        self.undo_group = QtGui.QUndoGroup(self)
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self.status = self.statusBar()
        self.coord_label = QtWidgets.QLabel()
        self.status.addPermanentWidget(self.coord_label)
        self._autosave = QtCore.QTimer(self)
        self._autosave.timeout.connect(self._do_autosave)
        self.apply_settings()
        geom = self.settings.value("window/geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)

    # -- helpers ------------------------------------------------------------------
    def _dock(self, title, widget, area):
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def view(self) -> DocumentView | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentView) else None

    def doc(self) -> Document | None:
        v = self.view()
        return v.doc if v else None

    def docs(self) -> list[Document]:
        return [self.tabs.widget(i).doc for i in range(self.tabs.count())]

    def _act(self, text, slot=None, shortcut=None, tip=None, checkable=False, icon=None):
        a = QtGui.QAction(text, self)
        if shortcut:
            a.setShortcut(QtGui.QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(tip)
        if checkable:
            a.setCheckable(True)
        if icon:
            ic = QtGui.QIcon.fromTheme(icon)
            if not ic.isNull():
                a.setIcon(ic)
        if slot:
            a.triggered.connect(slot)
        return a

    # -- actions & menus -------------------------------------------------------------
    def _build_actions(self):
        A = self._act
        SK = QtGui.QKeySequence.StandardKey
        self.a_new = A("&New", self.new_doc, SK.New, "New design from defaults", icon="document-new")
        self.a_new_tpl = A("New from &template…", self.new_from_template, "Ctrl+Shift+N", icon="document-new")
        self.a_open = A("&Open…", self.open_dialog, SK.Open, icon="document-open")
        self.a_save = A("&Save", self.save, SK.Save, icon="document-save")
        self.a_save_as = A("Save &as…", self.save_as, SK.SaveAs, icon="document-save-as")
        self.a_save_tpl = A("Save as template…", self.save_as_template)
        self.a_close = A("&Close", lambda: self.close_tab(self.tabs.currentIndex()), SK.Close)
        self.a_quit = A("&Quit", self.close, SK.Quit)
        self.a_undo = self.undo_group.createUndoAction(self, "&Undo")
        self.a_undo.setShortcut(SK.Undo)
        self.a_redo = self.undo_group.createRedoAction(self, "&Redo")
        self.a_redo.setShortcut(SK.Redo)
        self.a_fit = A("&Fit to window", lambda: self.view() and self.view().canvas.fit(), "F", icon="zoom-fit-best")
        self.a_zoom_in = A("Zoom &in", lambda: self.view() and self.view().canvas.zoom_by(1.25), SK.ZoomIn, icon="zoom-in")
        self.a_zoom_out = A("Zoom &out", lambda: self.view() and self.view().canvas.zoom_by(0.8), SK.ZoomOut, icon="zoom-out")
        self.tool_group = QtGui.QActionGroup(self)
        self.tool_actions = {}
        for key, text, sc in (("select", "Select / drag", "Esc"), ("measure", "Measure", "M"),
                              ("add_tube", "Add tube", "T"),
                              ("user_dim", "Add user dimension", "D"), ("user_angle", "Add angle dimension", "Shift+D"),
                              ("note", "Add note", "N"), ("calibrate", "Calibrate photo", None)):
            a = A(text, lambda _c=False, k=key: self.set_tool(k), sc, checkable=True)
            self.tool_group.addAction(a)
            self.tool_actions[key] = a
        self.tool_actions["select"].setChecked(True)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_new_tpl, self.a_open):
            m.addAction(a)
        self.recent_menu = m.addMenu("Open &recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for a in (self.a_save, self.a_save_as, self.a_save_tpl):
            m.addAction(a)
        m.addSeparator()
        ex = m.addMenu("&Export")
        ex.addAction("Drawing (PDF)…", "Ctrl+E", lambda: self.export_drawing("pdf"))
        ex.addAction("Drawing (SVG)…", lambda: self.export_drawing("svg"))
        ex.addAction("Drawing (PNG)…", lambda: self.export_drawing("png"))
        ex.addAction("Bike only (SVG, full detail)…", self.export_svg_plain)
        ex.addAction("DXF…", self.export_dxf)
        ex.addSeparator()
        ex.addAction("Miter templates…", self.mitre_dialog)
        ex.addAction("Spec sheet CSV (this design)…", self.export_csv)
        ex.addAction("Spec sheet CSV (folder of designs)…", self.export_csv_folder)
        ex.addAction("Bill of materials CSV…", self.export_bom)
        ex.addAction("Build / cut sheet (PDF)…", self.export_buildsheet)
        ex.addAction("Multi-model PDF…", self.export_multi_pdf)
        ex.addAction("Bulk export folder…", self.bulk_export)
        ex.addSeparator()
        ex.addAction("FreeCAD macro (3-D)…", self.export_freecad)
        ex.addAction("STL mesh (3-D)…", self.export_stl)
        ex.addAction("Animated GIF morph…", self.export_gif)
        m.addAction("&Print…", QtGui.QKeySequence.StandardKey.Print, self.print_drawing)
        m.addSeparator()
        m.addAction(self.a_close)
        m.addAction(self.a_quit)

        m = mb.addMenu("&Edit")
        m.addAction(self.a_undo)
        m.addAction(self.a_redo)
        m.addSeparator()
        m.addAction("Snapshots…", "Ctrl+Shift+S", self.snapshots)
        m.addAction("Title block…", self.title_block)
        xt = m.addMenu("Extra tubes")
        xt.addAction(self.tool_actions["add_tube"])
        presets = xt.addMenu("Add preset")
        from .extra_tubes import PRESETS
        for title, tip, tubes in PRESETS:
            a_ = presets.addAction(title, lambda t=tubes, n=title: self.doc() and self._add_preset(t, n))
            a_.setStatusTip(tip)
            a_.setToolTip(tip)
        presets.setToolTipsVisible(True)
        xt.addAction("Edit all extra tubes…", self.extra_tubes)
        m.addAction("Decals & logos…", self.decals)
        m.addAction("Parts libraries…", "Ctrl+L", self.library_dialog)
        m.addSeparator()
        m.addAction("Preferences…", self.preferences)

        m = mb.addMenu("&View")
        for a in (self.a_fit, self.a_zoom_in, self.a_zoom_out):
            m.addAction(a)
        m.addSeparator()
        self.layer_actions = {}
        lay = m.addMenu("Layers")
        from ..model import params as P
        for pd in P.by_group("Display"):
            if pd.section == "Layers":
                a = self._act(pd.label, checkable=True)
                a.toggled.connect(lambda v, k=pd.key: self.doc() and self.doc().set_param(k, v, f"Toggle {k}"))
                lay.addAction(a)
                self.layer_actions[pd.key] = a
        lay.aboutToShow.connect(self._sync_layers)
        mode = m.addMenu("Drawing mode")
        for val, label in P.get("display_mode").choices:
            mode.addAction(label, lambda v=val: self.doc() and self.doc().set_param("display_mode", v))
        units = m.addMenu("Units")
        units.addAction("Millimetres", lambda: self.doc() and self.doc().set_param("units", "mm"))
        units.addAction("Inches", lambda: self.doc() and self.doc().set_param("units", "in"))
        self.a_lock = self._act("Lock zoom", self._toggle_lock, checkable=True,
                                tip="Keep the current scale (disables wheel zoom and fit)")
        m.addAction(self.a_lock)
        m.addAction("Find parameter…", "Ctrl+F", lambda: (self.dock_params.show(), self.params.search.setFocus(),
                                                          self.params.search.selectAll()))
        m.addSeparator()
        m.addAction("Dimensions…", "Ctrl+D", self.dimensions_dialog)
        m.addAction("Compare designs…", "Ctrl+K", self.compare)
        m.addAction("Clear comparison", self.clear_compare)
        m.addAction("Photo underlay…", self.photo)
        m.addSeparator()
        m.addAction(self.dock_params.toggleViewAction())
        m.addAction(self.dock_results.toggleViewAction())
        self.view_menu = m

        m = mb.addMenu("&Tools")
        for k in ("select", "measure", "add_tube", "user_dim", "user_angle", "note", "calibrate"):
            m.addAction(self.tool_actions[k])
        m.addSeparator()
        m.addAction("Fit advisor…", "Ctrl+Shift+F", self.fit_advisor)
        m.addAction("Miter templates…", "Ctrl+M", self.mitre_dialog)
        m.addAction("Auxiliary views (stays, crown, toe, lean)", self.show_aux)
        m.addAction("3-D clearance view…", self.show_3d)
        m.addAction("Size run…", self.size_run)
        m.addAction("Resolve issues…", self.fix_clearance)
        m.addAction("Analysis report…", "Ctrl+R", self.report_dialog)
        m.addAction("Gearing & chain/belt…", lambda: self.report_dialog("Gearing"))
        m.addAction("UCI check…", lambda: self.report_dialog("UCI"))
        m.addAction("Frame fixture numbers…", lambda: self.report_dialog("Fixture"))
        m.addAction("Weight & stiffness estimate…", lambda: self.report_dialog("Weight"))

        m = mb.addMenu("&Help")
        m.addAction("Keyboard & mouse", self.help_controls)
        m.addAction(f"About {APP_NAME}", self.about)

    def _build_toolbars(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        for a in (self.a_fit, self.a_zoom_in, self.a_zoom_out):
            tb.addAction(a)
        tb2 = self.addToolBar("Tools")
        tb2.setObjectName("tools_toolbar")
        tb2.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        for k in ("select", "measure", "add_tube", "user_dim", "user_angle", "note"):
            tb2.addAction(self.tool_actions[k])
        tb2.addSeparator()
        for text, slot in (("Dimensions", self.dimensions_dialog), ("Compare", self.compare),
                           ("Fit", self.fit_advisor), ("Miters", self.mitre_dialog), ("Report", self.report_dialog),
                           ("Drawing", lambda: self.export_drawing("pdf"))):
            tb2.addAction(self._act(text, slot))
        self.mode_combo = QtWidgets.QComboBox()
        from ..model import params as P
        for val, label in P.get("display_mode").choices:
            self.mode_combo.addItem(label, val)
        self.mode_combo.currentIndexChanged.connect(
            lambda i: self.doc() and self.doc().set_param("display_mode", self.mode_combo.itemData(i)))
        tb2.addSeparator()
        tb2.addWidget(QtWidgets.QLabel(" Mode "))
        tb2.addWidget(self.mode_combo)
        self.rider_check = QtWidgets.QCheckBox("Rider")
        self.rider_check.toggled.connect(lambda v: self.doc() and self.doc().set_param("show_rider", v))
        self.dims_check = QtWidgets.QCheckBox("Dims")
        self.dims_check.toggled.connect(lambda v: self.doc() and self.doc().set_param("show_dimensions", v))
        tb2.addWidget(self.rider_check)
        tb2.addWidget(self.dims_check)
        self.toolbars = [tb, tb2]

    def apply_settings(self):
        s = self.settings
        fs = int(s.value("ui/font_size", 0) or 0)
        if fs:
            f = QtWidgets.QApplication.font()
            f.setPointSize(fs)
            QtWidgets.QApplication.setFont(f)
        size = int(s.value("ui/icon_size", 22))
        for tb in getattr(self, "toolbars", []):
            tb.setIconSize(QtCore.QSize(size, size))
        theme = str(s.value("ui/theme", "System"))
        app = QtWidgets.QApplication.instance()
        if theme == "Dark":
            app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        elif theme == "Light":
            app.styleHints().setColorScheme(Qt.ColorScheme.Light)
        else:
            app.styleHints().unsetColorScheme()
        for i in range(self.tabs.count()):
            v = self.tabs.widget(i)
            v.canvas.ui_scale = float(s.value("ui/line_scale", 1.0))
            v.canvas.reverse_wheel = s.value("ui/reverse_wheel", "false") in (True, "true")
            v.canvas.show_handles = s.value("ui/handles", "true") in (True, "true")
            v.canvas._on_changed(None)
        minutes = int(s.value("files/autosave_min", 0))
        if minutes > 0:
            self._autosave.start(minutes * 60000)
        else:
            self._autosave.stop()

    # -- documents ------------------------------------------------------------------
    def add_document(self, doc: Document) -> DocumentView:
        view = DocumentView(doc, self.settings)
        idx = self.tabs.addTab(view, doc.display_name)
        self.undo_group.addStack(doc.undo)
        doc.path_changed.connect(lambda v=view: self._update_tab_title(v))
        doc.changed.connect(lambda keys, v=view: self._doc_changed(v, keys))
        view.canvas.status.connect(self.coord_label.setText)
        view.canvas.edit_dimension.connect(lambda did, d=doc: D.edit_dimension_value(d, did, self))
        view.canvas.tool_finished.connect(lambda: self.tool_actions["select"].setChecked(True))
        self.tabs.setCurrentIndex(idx)
        return view

    def _update_tab_title(self, view):
        i = self.tabs.indexOf(view)
        if i >= 0:
            self.tabs.setTabText(i, view.doc.display_name)
            self.tabs.setTabToolTip(i, str(view.doc.path or "unsaved"))
        if view is self.view():
            self._update_title()

    def _update_title(self):
        d = self.doc()
        self.setWindowTitle(f"{d.display_name} — {APP_NAME}" if d else APP_NAME)

    def _doc_changed(self, view, keys):
        if view is self.view():
            self._sync_toolbar()
        if keys and any(isinstance(k, str) and k.startswith("ghost") for k in keys):
            view.update_ghosts()

    def _on_tab(self, idx):
        v = self.view()
        d = v.doc if v else None
        if d is not None:
            self.undo_group.setActiveStack(d.undo)
        self.params.set_document(d)
        self.results.set_document(d)
        if self.aux_dock is not None:
            self.aux_dock.widget().set_document(d)
        if self.view3d_dock is not None:
            self.view3d_dock.widget().set_document(d)
        self._sync_toolbar()
        self._update_title()

    def _sync_toolbar(self):
        d = self.doc()
        if d is None:
            return
        for w, val in ((self.mode_combo, None), (self.rider_check, None), (self.dims_check, None)):
            w.blockSignals(True)
        i = self.mode_combo.findData(d.design["display_mode"])
        self.mode_combo.setCurrentIndex(max(i, 0))
        self.rider_check.setChecked(bool(d.design["show_rider"]))
        self.dims_check.setChecked(bool(d.design["show_dimensions"]))
        for w in (self.mode_combo, self.rider_check, self.dims_check):
            w.blockSignals(False)

    def _sync_layers(self):
        d = self.doc()
        if d is None:
            return
        for k, a in self.layer_actions.items():
            a.blockSignals(True)
            a.setChecked(bool(d.design.get(k)))
            a.blockSignals(False)

    def new_doc(self, design: Design | None = None):
        d = design or Design()
        if design is None:
            d.set("units", str(self.settings.value("defaults/units", "mm")))
        self.add_document(Document(d))

    def new_from_template(self):
        tm = _optional("..model.templates")
        if tm is None:
            QtWidgets.QMessageBox.information(self, "Templates", "Template library not available.")
            return
        dlg = TemplatePicker(tm, self)
        if dlg.exec() and dlg.selected:
            try:
                d = tm.load_template(dlg.selected)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Template", str(exc))
                return
            self.add_document(Document(d))

    def save_as_template(self):
        d = self.doc()
        tm = _optional("..model.templates")
        if d is None or tm is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save as template", "Template name:", text=d.design.title)
        if ok and name.strip():
            p = tm.save_user_template(d.design, name.strip())
            self.status.showMessage(f"Saved template {p}", 5000)

    def open_dialog(self):
        start = str(self.settings.value("files/last_dir", str(Path.home())))
        fns, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Open design", start, FILE_FILTER)
        for fn in fns:
            self.open_path(fn)

    def open_path(self, fn) -> Document | None:
        fn = str(fn)
        for i in range(self.tabs.count()):
            d = self.tabs.widget(i).doc
            if d.path and str(d.path) == str(Path(fn).resolve()):
                self.tabs.setCurrentIndex(i)
                return d
        try:
            doc = Document.open(Path(fn).resolve())
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Open failed", f"Could not open {fn}:\n{exc}")
            return None
        self.add_document(doc)
        self._add_recent(fn)
        self.settings.setValue("files/last_dir", str(Path(fn).parent))
        return doc

    def save(self) -> bool:
        d = self.doc()
        if d is None:
            return False
        if d.path is None:
            return self.save_as()
        try:
            d.save()
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Save failed", str(exc))
            return False
        self.status.showMessage(f"Saved {d.path}", 4000)
        return True

    def save_as(self) -> bool:
        d = self.doc()
        if d is None:
            return False
        start = str(Path(str(self.settings.value("files/last_dir", str(Path.home())))) /
                    (d.design.title.replace("/", "-") + FILE_SUFFIX))
        dlg = QtWidgets.QFileDialog(self, "Save design", start, FILE_FILTER)
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        dlg.setDefaultSuffix(FILE_SUFFIX.lstrip("."))
        # as the format filter changes, default to that format's extension
        dlg.filterSelected.connect(
            lambda f: dlg.setDefaultSuffix("bcad" if "bcad" in f.lower() else FILE_SUFFIX.lstrip(".")))
        if not dlg.exec():
            return False
        fn = (dlg.selectedFiles() or [""])[0]
        if not fn:
            return False
        sel = dlg.selectedNameFilter()
        if "bcad" not in sel.lower() and not fn.lower().endswith((".bcad", FILE_SUFFIX)):
            fn += FILE_SUFFIX
        try:
            d.save(fn)                    # Design.save dispatches .bcad to the BikeCAD writer
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Save failed", str(exc))
            return False
        self._add_recent(fn)
        self.settings.setValue("files/last_dir", str(Path(fn).parent))
        return True

    def close_tab(self, idx) -> bool:
        if idx < 0:
            return True
        view = self.tabs.widget(idx)
        if view.doc.dirty:
            self.tabs.setCurrentIndex(idx)
            r = QtWidgets.QMessageBox.question(
                self, "Unsaved changes", f"Save changes to {view.doc.display_name.rstrip(' *')}?",
                QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard |
                QtWidgets.QMessageBox.StandardButton.Cancel)
            if r == QtWidgets.QMessageBox.StandardButton.Cancel:
                return False
            if r == QtWidgets.QMessageBox.StandardButton.Save and not self.save():
                return False
        self.undo_group.removeStack(view.doc.undo)
        self.tabs.removeTab(idx)
        view.deleteLater()
        return True

    def closeEvent(self, e):
        while self.tabs.count():
            if not self.close_tab(self.tabs.count() - 1):
                e.ignore()
                return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        super().closeEvent(e)

    def _add_recent(self, fn):
        rec = [str(x) for x in (self.settings.value("files/recent") or []) if str(x) != str(fn)]
        rec.insert(0, str(fn))
        self.settings.setValue("files/recent", rec[: int(self.settings.value("ui/recent_count", 12))])

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = self.settings.value("files/recent") or []
        if isinstance(rec, str):
            rec = [rec]
        for fn in rec:
            self.recent_menu.addAction(str(fn), lambda f=fn: self.open_path(f))
        if not rec:
            self.recent_menu.addAction("(none)").setEnabled(False)

    def _do_autosave(self):
        backup = Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.AppDataLocation)) / "autosave"
        for d in self.docs():
            if d.dirty:
                backup.mkdir(parents=True, exist_ok=True)
                name = (d.path.stem if d.path else d.design.title.replace("/", "-")) + ".autosave" + FILE_SUFFIX
                try:
                    d.design.save(backup / name)
                except OSError:
                    pass

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if not p:
                continue
            if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".webp") and self.doc():
                ph = dict(self.doc().design.extras.get("photo") or {})
                ph.update({"path": p, "x": ph.get("x", -950), "y": ph.get("y", 1100),
                           "mm_per_px": ph.get("mm_per_px", 1.0), "opacity": 0.5})
                self.doc().set_extra("photo", ph, "Photo underlay")
                self.photo()
            else:
                self.open_path(p)

    # -- tools & dialogs ------------------------------------------------------------------
    def set_tool(self, key):
        v = self.view()
        if v:
            v.canvas.set_tool(key)

    def _toggle_lock(self, on):
        for d in range(self.tabs.count()):
            self.tabs.widget(d).canvas.zoom_locked = bool(on)

    def dimensions_dialog(self):
        if self.doc():
            D.DimensionsDialog(self.doc(), self).exec()

    def compare(self):
        d = self.doc()
        if d and D.CompareDialog(d, self.docs(), self).exec():
            self.view().update_ghosts()

    def clear_compare(self):
        d = self.doc()
        if d:
            d.ghosts = []
            self.view().update_ghosts()

    def photo(self):
        if self.doc():
            D.PhotoDialog(self.doc(), self.view().canvas, self).exec()

    def snapshots(self):
        d = self.doc()
        if d:
            D.SnapshotsDialog(d, self).exec()
            self.view().update_ghosts()

    def title_block(self):
        if self.doc():
            D.TitleBlockDialog(self.doc(), self).exec()

    def extra_tubes(self):
        if self.doc():
            D.ExtraTubesDialog(self.doc(), self).exec()

    def _add_preset(self, tubes, name):
        from .extra_tubes import add_tubes
        add_tubes(self.doc(), tubes, f"Add {name.lower()}")
        self.status.showMessage(f"Added {name.lower()} — right-click or double-click it to edit", 6000)

    def decals(self):
        if self.doc():
            D.DecalsDialog(self.doc(), self).exec()

    def preferences(self):
        if D.PreferencesDialog(self.settings, self).exec():
            self.apply_settings()

    def _missing(self, what):
        QtWidgets.QMessageBox.information(self, what, f"{what} is not available in this build.")

    def fit_advisor(self):
        mod = _optional(".fit_dialog")
        if mod is None or self.doc() is None:
            return self._missing("Fit advisor")
        mod.FitAdvisorDialog(self.doc(), self).exec()

    def mitre_dialog(self):
        mod = _optional(".mitre_dialog")
        if mod is None or self.doc() is None:
            return self._missing("Miter templates")
        mod.MitreDialog(self.doc(), self).exec()

    def report_dialog(self, focus: str | None = None):
        mod = _optional(".report_dialog")
        if mod is None or self.doc() is None:
            return self._missing("Analysis report")
        mod.ReportDialog(self.doc(), self, focus=focus if isinstance(focus, str) else None).exec()

    def library_dialog(self):
        mod = _optional(".library_dialog")
        if mod is None or self.doc() is None:
            return self._missing("Parts libraries")
        mod.LibraryDialog(self.doc(), self).exec()

    def fix_clearance(self):
        if self.doc():
            from .clearance_dialog import FixClearanceDialog
            FixClearanceDialog(self.doc(), self).exec()

    def show_aux(self):
        mod = _optional(".aux_dock")
        if mod is None:
            return self._missing("Auxiliary views")
        if self.aux_dock is None:
            self.aux_dock = self._dock("Auxiliary views", mod.AuxViewsPanel(), Qt.DockWidgetArea.BottomDockWidgetArea)
            self.view_menu.addAction(self.aux_dock.toggleViewAction())
        self.aux_dock.widget().set_document(self.doc())
        self.aux_dock.show()
        self.aux_dock.raise_()

    def size_run(self):
        if self.doc() is None:
            return
        from .sizerun_dialog import SizeRunDialog
        SizeRunDialog(self.doc(), self).exec()

    def show_3d(self):
        from . import view3d
        if not view3d.available():
            QtWidgets.QMessageBox.information(
                self, "3-D clearance view",
                "The 3-D view needs the 'pyqtgraph' and 'PyOpenGL' packages.\n\nInstall them with:\n"
                "    pip install pyqtgraph PyOpenGL")
            return
        if self.doc() is None:
            return
        if self.view3d_dock is None:
            self.view3d_dock = self._dock("3-D clearance view", view3d.View3DWidget(self.doc()),
                                          Qt.DockWidgetArea.RightDockWidgetArea)
            self.view_menu.addAction(self.view3d_dock.toggleViewAction())
        else:
            self.view3d_dock.widget().set_document(self.doc())
        self.view3d_dock.show()
        self.view3d_dock.raise_()

    # -- export ------------------------------------------------------------------------
    def _save_name(self, title, suffix, filt):
        d = self.doc()
        start = str(Path(str(self.settings.value("files/export_dir", str(Path.home())))) /
                    (d.design.title.replace("/", "-") + suffix))
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, start, filt)
        if fn:
            if not fn.lower().endswith(suffix):
                fn += suffix
            self.settings.setValue("files/export_dir", str(Path(fn).parent))
        return fn

    def _ghost_list(self):
        d = self.doc()
        return [(solve(gh["design"]), gh["color"]) for gh in d.ghosts] if d else []

    def export_drawing(self, fmt="pdf"):
        if self.doc() is None:
            return
        mod = _optional(".drawing_dialog")
        if mod is None:
            return self._missing("Drawing export")
        mod.DrawingDialog(self.doc(), self, fmt=fmt, ghosts=self._ghost_list()).exec()

    def print_drawing(self):
        if self.doc() is None:
            return
        mod = _optional(".drawing_dialog")
        if mod is None:
            return self._missing("Printing")
        mod.DrawingDialog(self.doc(), self, fmt="print", ghosts=self._ghost_list()).exec()

    def export_svg_plain(self):
        if self.doc() is None:
            return
        fn = self._save_name("Export SVG", ".svg", "SVG (*.svg)")
        if fn:
            from ..export.svg import save_svg
            from ..render.bike_scene import build_scene
            save_svg(build_scene(self.doc().geometry, ghosts=self._ghost_list()), fn, 0.2, self.doc().design.title)
            self.status.showMessage(f"Exported {fn}", 5000)

    def export_dxf(self):
        if self.doc() is None:
            return
        fn = self._save_name("Export DXF", ".dxf", "DXF (*.dxf)")
        if fn:
            from ..export.dxf import save_dxf
            from ..render.bike_scene import build_scene
            save_dxf(build_scene(self.doc().geometry), fn)
            self.status.showMessage(f"Exported {fn} (full size, mm)", 5000)

    def export_csv(self):
        mod = _optional("..export.csv_export")
        if mod is None or self.doc() is None:
            return self._missing("CSV export")
        fn = self._save_name("Export CSV", ".csv", "CSV (*.csv)")
        if fn:
            mod.export_csv([(self.doc().design.title, self.doc().design)], fn)
            self.status.showMessage(f"Exported {fn}", 5000)

    def export_bom(self):
        if self.doc() is None:
            return
        from ..analysis import bom
        fn = self._save_name("Export bill of materials", ".csv", "CSV (*.csv)")
        if fn:
            with open(fn, "w", encoding="utf-8", newline="") as fh:
                fh.write(bom.to_csv(self.doc().design, self.doc().geometry))
            self.status.showMessage(f"Exported {fn}", 5000)

    def export_buildsheet(self):
        if self.doc() is None:
            return
        from ..export import buildsheet
        fn = self._save_name("Export build / cut sheet", ".pdf", "PDF (*.pdf)")
        if fn:
            try:
                buildsheet.save_pdf(self.doc().geometry, fn)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Build sheet", str(exc))
                return
            self.status.showMessage(f"Exported {fn}", 5000)

    def export_csv_folder(self):
        mod = _optional("..export.csv_export")
        if mod is None:
            return self._missing("CSV export")
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder of designs", str(Path.home()))
        if not folder:
            return
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save CSV", str(Path(folder) / "designs.csv"), "CSV (*.csv)")
        if fn:
            n = mod.export_folder_csv(folder, fn)
            self.status.showMessage(f"Exported {fn}" + (f" ({n} designs)" if isinstance(n, int) else ""), 5000)

    def export_multi_pdf(self):
        mod = _optional("..export.multi_pdf")
        if mod is None:
            return self._missing("Multi-model PDF")
        docs = self.docs()
        if len(docs) < 1:
            return
        fn = self._save_name("Multi-model PDF", ".pdf", "PDF (*.pdf)")
        if fn:
            mod.save_multi_pdf([d.design for d in docs], fn)
            self.status.showMessage(f"Exported {fn} ({len(docs)} designs)", 5000)

    def bulk_export(self):
        mod = _optional("..export.bulk")
        if mod is None:
            return self._missing("Bulk export")
        src = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder of designs", str(Path.home()))
        if not src:
            return
        out = QtWidgets.QFileDialog.getExistingDirectory(self, "Output folder", src)
        if not out:
            return
        paths = sorted(Path(src).glob("*" + FILE_SUFFIX))
        files = mod.bulk_export(paths, out)
        self.status.showMessage(f"Wrote {len(files)} files to {out}", 6000)

    def export_freecad(self):
        mod = _optional("..export.freecad")
        if mod is None or self.doc() is None:
            return self._missing("FreeCAD export")
        fn = self._save_name("FreeCAD macro", ".FCMacro", "FreeCAD macro (*.FCMacro *.py)")
        if fn:
            mod.save_freecad_macro(self.doc().geometry, fn)
            QtWidgets.QMessageBox.information(self, "FreeCAD", f"Wrote {fn}.\nOpen FreeCAD and run it via "
                                                               "Macro ▸ Macros… to build the 3-D frame.")

    def export_stl(self):
        mod = _optional("..export.stl")
        if mod is None or self.doc() is None:
            return self._missing("STL export")
        fn = self._save_name("STL mesh", ".stl", "STL (*.stl)")
        if fn:
            mod.save_stl(self.doc().geometry, fn)
            self.status.showMessage(f"Exported {fn}", 5000)

    def export_gif(self):
        mod = _optional("..export.gif")
        d = self.doc()
        if mod is None or d is None:
            return self._missing("GIF export")
        others = [x for x in self.docs() if x is not d]
        snaps = d.design.extras.get("snapshots") or []
        choices = [f"Open: {x.display_name}" for x in others] + [f"Snapshot: {s['name']}" for s in snaps]
        if not choices:
            QtWidgets.QMessageBox.information(self, "Morph GIF", "Open a second design or take a snapshot first; the "
                                                                 "animation morphs from it to this design.")
            return
        choice, ok = QtWidgets.QInputDialog.getItem(self, "Morph GIF", "Morph from:", choices, 0, False)
        if not ok:
            return
        i = choices.index(choice)
        src = others[i].design if i < len(others) else d.design.snapshot_design(snaps[i - len(others)]["name"])
        fn = self._save_name("Animated GIF", ".gif", "GIF (*.gif)")
        if fn:
            QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                mod.save_morph_gif(src, d.design, fn)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self.status.showMessage(f"Exported {fn}", 5000)

    # -- help --------------------------------------------------------------------------
    def help_controls(self):
        QtWidgets.QMessageBox.information(self, "Keyboard & mouse", (
            "Mouse wheel: zoom at cursor\nMiddle-drag, right-drag, Space+drag or drag on empty space: pan\n"
            "Drag blue handles: saddle, handlebar, head tube top, rear axle, seat tube top, front axle, pedal\n"
            "  (Shift with saddle: free move / custom seat angle; Shift with rear axle: chainstay length only)\n"
            "Drag a dimension to move it; double-click a dimension to edit its value\n"
            "Right-click: context menu (notes, user dimensions, hide/reset dimensions)\n"
            "F fit · +/- zoom · M measure · D user dimension · N note · Esc select\n"
            "Ctrl+Z / Ctrl+Shift+Z undo/redo · Ctrl+E drawing PDF · Ctrl+M miter templates · Ctrl+R report"))

    def about(self):
        from ..qt import API
        QtWidgets.QMessageBox.about(self, f"About {APP_NAME}", (
            f"<h3>{APP_NAME} {__version__}</h3><p>Open-source bicycle frame design.</p>"
            f"<p>Licensed under the GNU GPL v3 or later.</p><p>Qt binding: {API}</p>"))


class TemplatePicker(QtWidgets.QDialog):
    def __init__(self, tm, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New from template")
        self.resize(640, 420)
        self.selected = None
        lay = QtWidgets.QHBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        lay.addWidget(self.list, 1)
        right = QtWidgets.QVBoxLayout()
        self.preview = QtWidgets.QLabel()
        self.preview.setMinimumSize(360, 230)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc = QtWidgets.QLabel()
        self.desc.setWordWrap(True)
        right.addWidget(self.preview)
        right.addWidget(self.desc, 1)
        bb = D._buttons(self)
        right.addWidget(bb)
        lay.addLayout(right, 1)
        self.infos = tm.list_templates()
        self.tm = tm
        for info in self.infos:
            self.list.addItem(info.name + ("" if info.builtin else "  (user)"))
        self.list.currentRowChanged.connect(self._preview)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        if self.infos:
            self.list.setCurrentRow(0)

    def _preview(self, row):
        if not (0 <= row < len(self.infos)):
            return
        info = self.infos[row]
        self.desc.setText(info.description or "")
        try:
            from ..render.bike_scene import build_scene
            from ..render.qt_render import render_image
            d = self.tm.load_template(info.path)
            d.set("show_dimensions", False)
            img = render_image(build_scene(solve(d)), 720, 460)
            self.preview.setPixmap(QtGui.QPixmap.fromImage(img).scaled(
                360, 230, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception as exc:
            self.preview.setText(str(exc))

    def accept(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.infos):
            self.selected = self.infos[row].path
        super().accept()
