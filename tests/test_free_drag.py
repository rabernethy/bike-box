"""Sliding tubes and moving the BB by dragging on the canvas."""
import math

import pytest

from bikebox.geometry.solver import solve
from bikebox.geometry.vec import V
from bikebox.model.design import Design


# -- BB drag: the BB follows the cursor, head tube stays put ----------------------
def _world_h(g, name):
    return g.p[name].y - g.ground_y


def test_bb_drags_up_past_the_head_tube():
    from bikebox.gui.canvas import drag_point_changes
    d = Design()
    g = solve(d)
    bb0, ht_bottom0 = -g.ground_y, _world_h(g, "ht_bottom")
    assert bb0 < ht_bottom0                                     # BB starts below the head tube
    ch, _ = drag_point_changes("bb", V(0, 500), d, g, False)    # drag the BB way up
    g2 = solve(Design({**d.values, **ch}))
    # the BB rose; the head tube stayed at the same height above the ground
    assert -g2.ground_y == pytest.approx(bb0 + 500, abs=1.0)
    assert _world_h(g2, "ht_bottom") == pytest.approx(ht_bottom0, abs=2.0)
    assert -g2.ground_y > _world_h(g2, "ht_bottom")            # BB now above the head tube start


def test_bb_drag_keeps_rear_wheel_on_the_ground():
    from bikebox.gui.canvas import drag_point_changes
    d = Design()
    g = solve(d)
    ch, _ = drag_point_changes("bb", V(0, 120), d, g, False)
    g2 = solve(Design({**d.values, **ch}))
    # rear wheel stays put in the world (same height off the ground and ~same x)
    assert g2.wheels["rear"].center.y - g2.ground_y == pytest.approx(
        g.wheels["rear"].center.y - g.ground_y, abs=2.0)


def test_seat_tube_drags_in_2d():
    from bikebox.gui.canvas import drag_point_changes
    d = Design()
    g = solve(d)
    st = g.p["st_top"]
    ch, _ = drag_point_changes("st_top", V(st.x - 150, st.y + 80), d, g, False)
    assert "seat_tube_angle" in ch and "seat_tube_length" in ch  # both, not just length
    g2 = solve(Design({**d.values, **ch}))
    assert g2.v["seat_tube_angle"] != pytest.approx(g.v["seat_tube_angle"])


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
