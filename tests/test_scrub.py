"""The scrub spin boxes: click-drag changes the value, a plain click doesn't."""
import pytest

pytest.importorskip("PyQt6")
from bikebox.qt import QtCore, QtGui, QtWidgets  # noqa: E402
from bikebox.gui.scrub import ScrubDoubleSpinBox  # noqa: E402

Qt = QtCore.Qt


@pytest.fixture(scope="module")
def app():
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return a


def _mouse(kind, gx, buttons=Qt.MouseButton.LeftButton):
    pos = QtCore.QPointF(5.0, 5.0)
    glob = QtCore.QPointF(float(gx), 5.0)
    return QtGui.QMouseEvent(kind, pos, glob, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)


def _drag(sb, gx0, gx1):
    le = sb.lineEdit()
    sb.eventFilter(le, _mouse(QtCore.QEvent.Type.MouseButtonPress, gx0))
    sb.eventFilter(le, _mouse(QtCore.QEvent.Type.MouseMove, gx1))
    sb.eventFilter(le, _mouse(QtCore.QEvent.Type.MouseButtonRelease, gx1, Qt.MouseButton.NoButton))


def test_drag_right_increases_value(app):
    sb = ScrubDoubleSpinBox()
    sb.setRange(0, 1000)
    sb.setSingleStep(1.0)
    sb.setValue(50)
    _drag(sb, 100, 140)                      # +40 px / 4 px-per-step = +10 steps
    assert sb.value() == pytest.approx(60, abs=1e-6)


def test_drag_left_decreases_value(app):
    sb = ScrubDoubleSpinBox()
    sb.setRange(0, 1000)
    sb.setSingleStep(0.5)
    sb.setValue(50)
    _drag(sb, 200, 160)                      # -40 px -> -10 steps of 0.5
    assert sb.value() == pytest.approx(45, abs=1e-6)


def test_small_move_is_not_a_scrub(app):
    sb = ScrubDoubleSpinBox()
    sb.setRange(0, 1000)
    sb.setSingleStep(1.0)
    sb.setValue(50)
    _drag(sb, 100, 102)                      # 2 px < threshold -> treated as a click
    assert sb.value() == pytest.approx(50, abs=1e-6)


def test_scrub_respects_range(app):
    sb = ScrubDoubleSpinBox()
    sb.setRange(0, 55)
    sb.setSingleStep(1.0)
    sb.setValue(50)
    _drag(sb, 100, 200)                      # +25 steps but clamped at 55
    assert sb.value() == pytest.approx(55, abs=1e-6)
