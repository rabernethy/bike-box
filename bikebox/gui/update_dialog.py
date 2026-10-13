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


class _Downloader(QtCore.QObject):
    progress = Signal(float)
    done = Signal(object)                             # Path on success, None on failure

    def __init__(self, url: str, dest):
        super().__init__()
        self.url, self.dest = url, dest

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            path = U.download(self.url, self.dest, progress=lambda f: self.progress.emit(f))
        except Exception:
            path = None
        self.done.emit(path)


class SettingsDialog(QtWidgets.QDialog):
    """Preferences, including manual update check and download/install."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._latest: dict | None = None
        lay = QtWidgets.QVBoxLayout(self)

        box = QtWidgets.QGroupBox("Updates")
        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(QtWidgets.QLabel(f"You have <b>Bike Box {__version__}</b>."))
        self.status = QtWidgets.QLabel("Use the buttons below to check for and install updates.")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setVisible(False)
        v.addWidget(self.bar)

        row = QtWidgets.QHBoxLayout()
        self.check_btn = QtWidgets.QPushButton("Check for updates")
        self.check_btn.clicked.connect(self._check)
        row.addWidget(self.check_btn)
        self.install_btn = QtWidgets.QPushButton("Download && install update")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._install)
        row.addWidget(self.install_btn)
        row.addStretch(1)
        v.addLayout(row)

        self.startup = QtWidgets.QCheckBox("Check for updates when Bike Box starts")
        self.startup.setChecked(U.update_check_enabled())
        self.startup.toggled.connect(lambda on: U.save_settings(update_check=bool(on)))
        v.addWidget(self.startup)

        wn = QtWidgets.QPushButton("What's New…")
        wn.clicked.connect(lambda: WhatsNewDialog(self).exec())
        v.addWidget(wn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(box)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def _check(self):
        self.check_btn.setEnabled(False)
        self.status.setText("Checking…")
        chk = _Checker(self)

        def handle(info):
            self.check_btn.setEnabled(True)
            self._latest = info
            if info is None:
                self.status.setText("Couldn't reach the update server. Please try again later.")
            elif info["newer"]:
                self.status.setText(f"<b>Bike Box {info['version']}</b> is available.")
                self.install_btn.setEnabled(bool(U.asset_for_platform(info.get("assets", []))))
                if not self.install_btn.isEnabled():
                    self.status.setText(self.status.text() + " No installer for this platform — "
                                        "<a href='%s'>open the downloads page</a>." % info["url"])
                    self.status.setOpenExternalLinks(True)
            else:
                self.status.setText(f"You're up to date (Bike Box {__version__}).")
        chk.done.connect(handle)
        self._checker = chk
        chk.start()

    def _install(self):
        info = self._latest or {}
        asset = U.asset_for_platform(info.get("assets", []))
        if not asset:
            return
        import tempfile
        dest = __import__("pathlib").Path(tempfile.gettempdir()) / asset["name"]
        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 100)
        self.status.setText(f"Downloading {asset['name']}…")
        dl = _Downloader(asset["url"], dest)
        dl.progress.connect(lambda f: self.bar.setValue(int(f * 100)))

        def done(path):
            self.bar.setVisible(False)
            self.check_btn.setEnabled(True)
            if path is None:
                self.status.setText("Download failed. Please try again or download manually.")
                self.install_btn.setEnabled(True)
                return
            self.status.setText("Downloaded. Opening the installer — close Bike Box to finish updating.")
            try:
                U.launch_installer(path)
            except Exception:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        dl.done.connect(done)
        self._downloader = dl
        dl.start()


def show_settings(window) -> None:
    SettingsDialog(window).exec()
