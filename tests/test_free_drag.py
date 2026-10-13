"""Sliding tubes and moving the BB by dragging on the canvas."""
import math

import pytest

from bikebox.geometry.solver import solve
from bikebox.geometry.vec import V
from bikebox.model.design import Design


# -- BB drag (pure geometry) -----------------------------------------------------
def test_bb_drag_moves_height_and_fore_aft():
    from bikebox.gui.canvas import drag_point_changes
    d = Design()
    g = solve(d)
    ch, _ = drag_point_changes("bb", V(20, 30), d, g, False)   # forward 20, up 30
    g2 = solve(Design({**d.values, **ch}))
    assert g2.v["bb_height"] == pytest.approx(g.v["bb_height"] + 30, abs=0.5)
    assert g2.v["front_center"] < g.v["front_center"]          # BB moved toward the front wheel
    assert g2.wheels["rear"].center.x < g.wheels["rear"].center.x  # rear wheel further back


def test_bb_drag_vertical_only_keeps_fore_aft():
    from bikebox.gui.canvas import drag_point_changes
    d = Design()
    g = solve(d)
    ch, _ = drag_point_changes("bb", V(0, -25), d, g, False)   # straight down 25
    g2 = solve(Design({**d.values, **ch}))
    assert g2.v["bb_height"] == pytest.approx(g.v["bb_height"] - 25, abs=0.5)
    # a vertical-only move keeps the wheels at the same horizontal positions
    assert g2.wheels["front"].center.x == pytest.approx(g.wheels["front"].center.x, abs=2.0)
    assert g2.wheels["rear"].center.x == pytest.approx(g.wheels["rear"].center.x, abs=2.0)


# -- GUI interaction -------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt6")
    from bikebox.qt import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _canvas(app):
    from bikebox.gui.canvas import BikeCanvas
    from bikebox.gui.document import Document
    c = BikeCanvas(Document(Design()))
    c.resize(1000, 700)
    return c


def test_begin_tube_drag_picks_nearest_end(app):
    c = _canvas(app)
    g = c.doc.geometry
    tt = g.tubes["tt"]
    # near the head-tube end of the top tube -> the tt_ht handle
    assert c._begin_tube_drag("tt", tt.b) and c._drag["point"] == "tt_ht"
    c._drag = None
    assert c._begin_tube_drag("tt", tt.a) and c._drag["point"] == "tt_st"
    c._drag = None
    # the seat tube's lower end is the BB handle
    st = g.tubes["st"]
    assert c._begin_tube_drag("st", st.a) and c._drag["point"] == "bb"


def _mouse(app, kind, pos, button, buttons):
    from bikebox.qt import QtCore, QtGui
    Qt = QtCore.Qt
    p = QtCore.QPointF(*pos)
    return QtGui.QMouseEvent(kind, p, p, button, buttons, Qt.KeyboardModifier.NoModifier)


def test_click_selects_but_drag_slides(app):
    from bikebox.qt import QtCore
    Qt = QtCore.Qt
    c = _canvas(app)
    g = c.doc.geometry
    dev = c.to_device(g.tubes["tt"].a.lerp(g.tubes["tt"].b, 0.5))   # a point on the top tube

    # a plain click (press + release, no move) selects the part
    picked = []
    c.select_part.connect(picked.append)
    c.mousePressEvent(_mouse(app, QtCore.QEvent.Type.MouseButtonPress, (dev.x(), dev.y()),
                             Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
    assert c._press is not None and c._press["tube"] == "tt"
    c.mouseReleaseEvent(_mouse(app, QtCore.QEvent.Type.MouseButtonRelease, (dev.x(), dev.y()),
                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    assert picked == ["tube:tt"] and c._press is None

    # press then move past the threshold starts a drag instead of selecting
    c.mousePressEvent(_mouse(app, QtCore.QEvent.Type.MouseButtonPress, (dev.x(), dev.y()),
                             Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
    c.mouseMoveEvent(_mouse(app, QtCore.QEvent.Type.MouseMove, (dev.x() + 40, dev.y() - 25),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    assert c._press is None and c._drag is not None and c._drag["point"] in ("tt_st", "tt_ht")
    c.mouseReleaseEvent(_mouse(app, QtCore.QEvent.Type.MouseButtonRelease, (dev.x() + 40, dev.y() - 25),
                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    assert len(picked) == 1          # the drag did not also fire a selection
