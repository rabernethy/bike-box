"""Update check + What's New."""
import pytest

from bikebox import __version__
from bikebox import update as U


def test_version_compare():
    assert U.is_newer("0.1.18", "0.1.17")
    assert U.is_newer("v0.2.0", "0.1.17")
    assert not U.is_newer("0.1.9", "0.1.17")
    assert not U.is_newer("0.1.17", "0.1.17")


def test_changelog_bundled_and_current_notes():
    assert U.CHANGELOG.exists()
    notes = U.latest_notes()
    assert notes.startswith("## ")
    assert U.__version__ in notes                    # the current version has an entry


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEBOX_CONFIG_DIR", str(tmp_path))
    assert U.update_check_enabled() is False          # opt-in, off by default
    U.save_settings(update_check=True)
    assert U.update_check_enabled() is True
    assert U.whats_new_unseen() is True
    U.mark_whats_new_seen()
    assert U.whats_new_unseen() is False


def test_check_latest_handles_no_network(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert U.check_latest(timeout=0.1) is None       # best-effort, never raises


def test_startup_check_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("BIKEBOX_CONFIG_DIR", str(tmp_path))
    assert U.update_check_enabled() is False          # no silent updater by default


ASSETS = [
    {"name": "BikeBox-Setup-9.9.9.exe", "url": "u1", "size": 1},
    {"name": "BikeBox-windows-portable-9.9.9.zip", "url": "u2", "size": 1},
    {"name": "BikeBox-macos-9.9.9.dmg", "url": "u3", "size": 1},
    {"name": "BikeBox-linux-9.9.9.tar.gz", "url": "u4", "size": 1},
]


@pytest.mark.parametrize("plat,expect", [
    ("win32", "BikeBox-Setup-9.9.9.exe"),             # installer, not the portable zip
    ("darwin", "BikeBox-macos-9.9.9.dmg"),
    ("linux", "BikeBox-linux-9.9.9.tar.gz"),
])
def test_asset_for_platform(plat, expect, monkeypatch):
    monkeypatch.setattr(U, "sys", __import__("types").SimpleNamespace(platform=plat))
    a = U.asset_for_platform(ASSETS)
    assert a and a["name"] == expect


def test_asset_for_platform_none_when_absent(monkeypatch):
    monkeypatch.setattr(U, "sys", __import__("types").SimpleNamespace(platform="win32"))
    assert U.asset_for_platform([{"name": "readme.txt", "url": "x", "size": 1}]) is None


# -- GUI pieces ------------------------------------------------------------------
def test_whats_new_dialog_and_checker(monkeypatch):
    pytest.importorskip("PyQt6")
    from bikebox.qt import QtWidgets, QtCore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from bikebox.gui.update_dialog import WhatsNewDialog, _Checker

    WhatsNewDialog(only_current=True)                # constructs + renders markdown
    WhatsNewDialog(only_current=False)

    monkeypatch.setattr(U, "check_latest",
                        lambda timeout=4.0: {"version": "9.9.9", "url": "x", "notes": "n", "newer": True})
    got = []
    c = _Checker()
    c.done.connect(got.append)
    c.start()
    for _ in range(400):
        app.processEvents()
        if got:
            break
        QtCore.QThread.msleep(5)
    assert got and got[0]["version"] == "9.9.9"


def test_settings_dialog_constructs(monkeypatch):
    pytest.importorskip("PyQt6")
    from bikebox.qt import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # keep a reference alive
    assert app is not None
    from bikebox.gui.update_dialog import SettingsDialog
    d = SettingsDialog()
    assert d.install_btn.isEnabled() is False        # until a check finds an update
