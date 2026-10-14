"""Overriding a parameter's min/max — per field (right-click) and globally."""
import pytest

pytest.importorskip("PyQt6")
from bikebox.qt import QtWidgets  # noqa: E402
from bikebox.gui.document import Document  # noqa: E402
from bikebox.gui.param_panel import ParamPanel  # noqa: E402
from bikebox.model import params as P  # noqa: E402
from bikebox.model.design import Design  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def _reset():
    yield
    P.set_unlock_limits(False)
    for k in list(getattr(P, "_UNLOCKED_KEYS", set())):
        P.set_key_unlocked(k, False)


def _panel(doc):
    panel = ParamPanel()
    panel.set_document(doc)
    panel.show_group("Frame")
    return panel


def test_coerce_clamps_by_default():
    assert P.get("head_tube_angle").coerce(200) == P.get("head_tube_angle").max          # clamped to max


def test_per_field_override(app):
    doc = Document(Design())
    panel = _panel(doc)
    page = panel.pages["Frame"]
    doc.set_param("head_tube_angle", 200)
    assert doc.design.get("head_tube_angle") == P.get("head_tube_angle").max             # clamped

    page._set_key_unlocked("head_tube_angle", True)
    doc.set_param("head_tube_angle", 200)
    assert doc.design.get("head_tube_angle") == 200            # this field unclamped
    assert page.editors["head_tube_angle"].maximum() > 1000    # spin widened

    # a different field is unaffected
    doc.set_param("seat_tube_angle", 200)
    assert doc.design.get("seat_tube_angle") == P.get("seat_tube_angle").max

    page._set_key_unlocked("head_tube_angle", False)
    doc.set_param("head_tube_angle", 250)
    assert doc.design.get("head_tube_angle") == P.get("head_tube_angle").max             # re-clamped


def test_global_unlock_affects_all(app):
    doc = Document(Design())
    panel = _panel(doc)
    panel.set_unlock_limits(True)
    doc.set_param("head_tube_angle", 200)
    doc.set_param("seat_tube_angle", 200)
    assert doc.design.get("head_tube_angle") == 200
    assert doc.design.get("seat_tube_angle") == 200
    panel.set_unlock_limits(False)
    doc.set_param("head_tube_angle", 300)
    assert doc.design.get("head_tube_angle") == P.get("head_tube_angle").max
