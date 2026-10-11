"""Application bootstrap."""
from __future__ import annotations

import sys

from .. import APP_NAME, __version__
from ..qt import QtCore, QtGui, QtWidgets


def _load_plugins() -> None:
    """Import optional modules that register parameters or scene builders."""
    import importlib
    for mod in ("framewright.fit.rider", "framewright.fit.com", "framewright.fit.advisor",
                "framewright.geometry.clearance", "framewright.geometry.mitre", "framewright.analysis.gearing",
                "framewright.analysis.weight", "framewright.analysis.structure", "framewright.analysis.uci",
                "framewright.analysis.jig", "framewright.export.drawing"):
        try:
            importlib.import_module(mod)
        except ImportError:
            pass
        except Exception as exc:            # report, but keep the app usable
            print(f"[{APP_NAME}] failed to load {mod}: {exc}", file=sys.stderr)


def app_icon(size: int = 256) -> QtGui.QIcon:
    """The application icon, painted (no SVG module needed)."""
    icon = QtGui.QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        pm = QtGui.QPixmap(sz, sz)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        k = sz / 64.0
        p.setBrush(QtGui.QColor("#1f2a38"))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(QtCore.QRectF(1 * k, 1 * k, 62 * k, 62 * k), 12 * k, 12 * k)
        wheel = QtGui.QPen(QtGui.QColor("#e8edf3"), max(1.0, 3.2 * k))
        p.setPen(wheel)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(QtCore.QPointF(17 * k, 41 * k), 11 * k, 11 * k)
        p.drawEllipse(QtCore.QPointF(47 * k, 41 * k), 11 * k, 11 * k)
        frame = QtGui.QPen(QtGui.QColor("#e5383b"), max(1.2, 3.6 * k))
        frame.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        frame.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(frame)
        pts = [QtCore.QPointF(x * k, y * k) for x, y in ((17, 41), (31, 41), (25, 22), (17, 41))]
        p.drawPolyline(pts)
        p.drawPolyline([QtCore.QPointF(x * k, y * k) for x, y in ((25, 22), (43, 22), (31, 41))])
        p.drawLine(QtCore.QPointF(43 * k, 22 * k), QtCore.QPointF(47 * k, 41 * k))
        p.end()
        icon.addPixmap(pm)
    return icon


def run(argv: list[str]) -> int:
    QtCore.QCoreApplication.setOrganizationName("FrameWright")
    QtCore.QCoreApplication.setApplicationName(APP_NAME)
    QtCore.QCoreApplication.setApplicationVersion(__version__)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]] + argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setDesktopFileName("framewright")
    splash = None
    path = str(QtCore.QSettings("FrameWright", "FrameWright").value("ui/splash", "") or "")
    if path:
        pm = QtGui.QPixmap(path)
        if not pm.isNull():
            splash = QtWidgets.QSplashScreen(pm.scaled(640, 400, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                       QtCore.Qt.TransformationMode.SmoothTransformation))
            splash.show()
            app.processEvents()
    _load_plugins()
    from .main_window import MainWindow
    win = MainWindow()
    files = [a for a in argv if not a.startswith("-")]
    for f in files:
        win.open_path(f)
    if not files:
        win.new_doc()
    win.show()
    if splash is not None:
        QtCore.QTimer.singleShot(900, lambda: splash.finish(win))
    return app.exec()
