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


def run(argv: list[str]) -> int:
    QtCore.QCoreApplication.setOrganizationName("FrameWright")
    QtCore.QCoreApplication.setApplicationName(APP_NAME)
    QtCore.QCoreApplication.setApplicationVersion(__version__)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]] + argv)
    app.setApplicationDisplayName(APP_NAME)
    _load_plugins()
    from .main_window import MainWindow
    win = MainWindow()
    files = [a for a in argv if not a.startswith("-")]
    for f in files:
        win.open_path(f)
    if not files:
        win.new_doc()
    win.show()
    return app.exec()
