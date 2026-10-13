"""Online design gallery: browse, download and open shared designs, or share
your own. Designs come from the project's GitHub ``gallery/`` folder."""
from __future__ import annotations

import threading
from pathlib import Path

from .. import gallery as G
from ..qt import QtCore, QtGui, QtWidgets, Signal

Qt = QtCore.Qt


class _Worker(QtCore.QObject):
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def start(self):
        threading.Thread(target=lambda: self.done.emit(self._fn()), daemon=True).start()


class GalleryDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._designs: list[dict] = []
        self.setWindowTitle("Online designs")
        self.resize(640, 460)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Download a shared design, or share your own."))

        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda _i: self._download())
        self.info = QtWidgets.QTextBrowser()
        split.addWidget(self.list)
        split.addWidget(self.info)
        split.setSizes([230, 400])
        lay.addWidget(split, 1)

        row = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Loading…")
        self.status.setStyleSheet("color: gray")
        row.addWidget(self.status)
        row.addStretch(1)
        self.get_btn = QtWidgets.QPushButton("Download && open")
        self.get_btn.setEnabled(False)
        self.get_btn.clicked.connect(self._download)
        row.addWidget(self.get_btn)
        share = QtWidgets.QPushButton("Share your design…")
        share.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(G.submit_url())))
        row.addWidget(share)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

        self._load()

    def _load(self):
        w = _Worker(G.fetch_index)

        def done(designs):
            if not designs:
                self.status.setText("Couldn't reach the gallery. Please try again later.")
                return
            self._designs = designs
            self.list.clear()
            for d in designs:
                self.list.addItem(f"{d.get('name', d['file'])}")
            self.status.setText(f"{len(designs)} designs")
            if designs:
                self.list.setCurrentRow(0)
        w.done.connect(done)
        self._w = w
        w.start()

    def _show(self, row: int):
        self.get_btn.setEnabled(0 <= row < len(self._designs))
        if not (0 <= row < len(self._designs)):
            self.info.clear()
            return
        d = self._designs[row]
        import html
        e = html.escape
        self.info.setHtml(f"<h3>{e(str(d.get('name', '')))}</h3>"
                          f"<p style='color:gray'>by {e(str(d.get('author', 'unknown')))}</p>"
                          f"<p>{e(str(d.get('description', '')))}</p>")

    def _download(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self._designs)):
            return
        d = self._designs[row]
        self.get_btn.setEnabled(False)
        self.status.setText(f"Downloading {d['file']}…")
        w = _Worker(lambda f=d["file"]: G.fetch_design(f))

        def done(data):
            if not data:
                self.status.setText("Download failed. Please try again.")
                self.get_btn.setEnabled(True)
                return
            dest = Path(self.window.designs_dir()) / d["file"]
            try:
                dest.write_bytes(data)
            except OSError:
                self.status.setText("Couldn't save the downloaded design.")
                self.get_btn.setEnabled(True)
                return
            self.accept()
            self.window.open_path(str(dest))
        w.done.connect(done)
        self._dw = w
        w.start()
