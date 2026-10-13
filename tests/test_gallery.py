"""Online design gallery (marketplace)."""
import json
from pathlib import Path

import pytest

from bikebox import gallery as G

GALLERY = Path(__file__).resolve().parents[1] / "gallery"


def test_bundled_index_is_valid_and_files_exist():
    idx = json.loads((GALLERY / "index.json").read_text(encoding="utf-8"))
    designs = idx["designs"]
    assert designs
    for d in designs:
        assert {"name", "file", "author", "description"} <= d.keys()
        assert (GALLERY / d["file"]).exists(), d["file"]


def test_submit_url():
    url = G.submit_url("My bike")
    assert url.startswith("https://github.com/rabernethy/bike-box/issues/new")
    assert "labels=gallery" in url


def test_fetch_design_blocks_path_traversal():
    assert G.fetch_design("../secret.bikebox") is None
    assert G.fetch_design("sub/dir.bikebox") is None


class _Resp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_index_parses(monkeypatch):
    payload = json.dumps({"designs": [
        {"name": "A", "file": "a.bikebox", "author": "x", "description": "d"},
        {"name": "bad", "author": "x"},            # no file -> dropped
    ]}).encode()
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    got = G.fetch_index()
    assert got and len(got) == 1 and got[0]["file"] == "a.bikebox"


def test_fetch_index_handles_no_network(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert G.fetch_index(timeout=0.1) is None


def test_gallery_dialog_downloads_and_opens(monkeypatch, tmp_path):
    pytest.importorskip("PyQt6")
    from bikebox.qt import QtWidgets, QtCore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class FakeWindow(QtWidgets.QWidget):
        opened: list = []

        def designs_dir(self):
            return str(tmp_path)

        def open_path(self, p):
            self.opened.append(p)

    monkeypatch.setattr(G, "fetch_index",
                        lambda timeout=5.0: [{"name": "A", "file": "a.bikebox", "author": "x", "description": "d"}])
    monkeypatch.setattr(G, "fetch_design", lambda f, timeout=15.0: b'{"format":"bikebox-design"}')

    from bikebox.gui.gallery_dialog import GalleryDialog
    win = FakeWindow()
    dlg = GalleryDialog(win)
    # the index worker + download worker deliver via queued signals; spin the loop
    for _ in range(200):
        app.processEvents()
        if dlg._designs:
            break
        QtCore.QThread.msleep(5)
    assert dlg._designs and dlg.list.count() == 1
    dlg._download()
    for _ in range(200):
        app.processEvents()
        if win.opened:
            break
        QtCore.QThread.msleep(5)
    assert win.opened and (tmp_path / "a.bikebox").exists()
