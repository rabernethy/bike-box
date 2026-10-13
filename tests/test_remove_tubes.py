"""The live Remove-tubes checkbox widget."""
import pytest

pytest.importorskip("PyQt6")
from bikebox.qt import QtWidgets  # noqa: E402
from bikebox.gui.document import Document  # noqa: E402
from bikebox.gui.param_panel import ParamPanel, RemoveTubesWidget  # noqa: E402
from bikebox.model.design import Design  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_toggling_updates_remove_tubes_live(app):
    doc = Document(Design())
    panel = ParamPanel()
    panel.set_document(doc)
    panel.show_group("Frame")
    w = panel.pages["Frame"].editors["remove_tubes"]
    assert isinstance(w, RemoveTubesWidget)

    w.boxes["tt"].setChecked(True)
    w.boxes["cs"].setChecked(True)
    assert set(doc.design.get("remove_tubes").split(",")) == {"tt", "cs"}
    # the solved geometry drops exactly those tubes
    g = doc.geometry
    assert "tt" not in g.tubes and "cs" not in g.tubes
    assert "dt" in g.tubes and "st" in g.tubes

    w.boxes["tt"].setChecked(False)
    assert doc.design.get("remove_tubes") == "cs"


def test_set_value_syncs_boxes(app):
    w = RemoveTubesWidget()
    w.set_value("dt, ss")
    assert w.boxes["dt"].isChecked() and w.boxes["ss"].isChecked()
    assert not w.boxes["tt"].isChecked()
    # setting the boxes from a value must not re-emit (avoid feedback loops)
    seen = []
    w.changed.connect(seen.append)
    w.set_value("st")
    assert seen == []
