"""'What's New' and the update check (checks GitHub releases, opens the download
page -- a frozen bundle can't safely replace itself)."""
from __future__ import annotations

import threading

from .. import __version__, update as U
from ..qt import QtCore, QtGui, QtWidgets, Signal

Qt = QtCore.Qt


class WhatsNewDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, only_current: bool = False):
        super().__init__(parent)
        self.setWindowTitle("What's New")
        self.resize(560, 560)
        lay = QtWidgets.QVBoxLayout(self)
        view = QtWidgets.QTextBrowser()
        view.setOpenExternalLinks(True)
        text = U.latest_notes() if only_current else U.changelog_text()
        try:
            view.setMarkdown(text or "No changelog available.")
        except AttributeError:                      # very old Qt
            view.setPlainText(text)
        lay.addWidget(view, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


class _Checker(QtCore.QObject):
    """Runs the (blocking) release check off the GUI thread; `done` is delivered
    back on the GUI thread via Qt's queued signal."""
    done = Signal(object)                            # dict or None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.done.emit(U.check_latest())


def _notify(window, info: dict) -> None:
    box = QtWidgets.QMessageBox(window)
    box.setIcon(QtWidgets.QMessageBox.Icon.Information)
    box.setWindowTitle("Update available")
    box.setText(f"<b>Bike Box {info['version']}</b> is available (you have {__version__}).")
    notes = info.get("notes") or ""
    if notes:
        box.setDetailedText(notes)
    dl = box.addButton("Open download page", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Later", QtWidgets.QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is dl:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(info.get("url") or U.RELEASES_URL))


def check_now(window) -> None:
    """Manual 'Check for updates…': always tells the user the outcome."""
    chk = _Checker(window)

    def handle(info):
        if info is None:
            QtWidgets.QMessageBox.warning(window, "Check for updates",
                                          "Couldn't reach the update server. Please try again later.")
        elif info["newer"]:
            _notify(window, info)
        else:
            QtWidgets.QMessageBox.information(window, "Check for updates",
                                              f"You're up to date (Bike Box {__version__}).")
    chk.done.connect(handle)
    window._update_checker = chk                     # keep a reference alive
    chk.start()


def check_on_startup(window) -> None:
    """Silent background check; only speaks up if a newer version exists."""
    if not U.update_check_enabled():
        return
    chk = _Checker(window)

    def handle(info):
        if info and info.get("newer"):
            _notify(window, info)
    chk.done.connect(handle)
    window._update_checker = chk
    chk.start()


def maybe_show_whats_new(window) -> None:
    """Show the current version's notes once, the first run after an update."""
    if U.whats_new_unseen():
        U.mark_whats_new_seen()
        WhatsNewDialog(window, only_current=True).show()


def show_whats_new(window) -> None:
    WhatsNewDialog(window).exec()
