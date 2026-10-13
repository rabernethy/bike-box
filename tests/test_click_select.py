"""Clicking a part on the drawing opens its editing section."""
import pytest

pytest.importorskip("PyQt6")
from bikebox.qt import QtWidgets  # noqa: E402
from bikebox.gui.canvas import BikeCanvas  # noqa: E402
from bikebox.gui.document import Document  # noqa: E402
from bikebox.gui.param_panel import ParamPanel  # noqa: E402
from bikebox.geometry.vec import V  # noqa: E402
from bikebox.model import params as P  # noqa: E402
from bikebox.model.design import Design  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _canvas(doc):
    c = BikeCanvas(doc)
    c.resize(1000, 700)
    return c


def test_click_resolves_many_parts(app):
    doc = Document(Design())
    c = _canvas(doc)
    panel = ParamPanel()
    panel.set_document(doc)
    g = doc.geometry

    def param_at(m):
        tag = c._hit_part(m)
        return tag, panel._param_for_tag(tag) if tag else None

    cases = {
        "tt": g.tubes["tt"].a.lerp(g.tubes["tt"].b, 0.5),
        "dt": g.tubes["dt"].a.lerp(g.tubes["dt"].b, 0.5),
        "fork": g.tubes["fork"].a.lerp(g.tubes["fork"].b, 0.5),
        "front_wheel": g.wheels["front"].center + V(0, g.wheels["front"].outer_r - 20),
        "rear_wheel": g.wheels["rear"].center + V(0, g.wheels["rear"].outer_r - 20),
        "saddle": g.p["saddle"],
        "bb": V(0, 0),
    }
    for name, m in cases.items():
        tag, key = param_at(m)
        assert tag is not None, f"nothing hit at {name}"
        assert key is not None and P.has(key), f"{name}: tag {tag} -> {key}"

    # specific expectations
    assert param_at(cases["tt"])[1] == "tt_od"
    assert param_at(cases["front_wheel"])[1] == "front_bsd"
    assert param_at(cases["rear_wheel"])[1] == "rear_bsd"


def test_empty_space_hits_nothing(app):
    doc = Document(Design())
    c = _canvas(doc)
    assert c._hit_part(V(9000, 9000)) is None


def test_focus_part_switches_group(app):
    doc = Document(Design())
    panel = ParamPanel()
    panel.set_document(doc)
    panel.focus_part("wheel:front")                 # a scene tag
    assert panel.list.currentItem().text() == P.get("front_bsd").group
    panel.focus_part("tube:dt")
    assert panel.list.currentItem().text() == "Tubes"
