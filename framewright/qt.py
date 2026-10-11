"""Qt binding shim: PyQt6 preferred, PySide6 supported.

Import Qt modules from here (``from framewright.qt import QtCore, QtGui,
QtWidgets, Signal``) so the rest of the code works with either binding.
"""
from __future__ import annotations

import os

_api = os.environ.get("FRAMEWRIGHT_QT", "").lower()

QtPrintSupport = None
if _api != "pyside6":
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
        try:
            from PyQt6 import QtPrintSupport  # type: ignore
        except ImportError:
            pass
        Signal = QtCore.pyqtSignal
        Slot = QtCore.pyqtSlot
        API = "pyqt6"
    except ImportError:
        _api = "pyside6"
if _api == "pyside6":
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
    try:
        from PySide6 import QtPrintSupport  # type: ignore
    except ImportError:
        pass
    Signal = QtCore.Signal
    Slot = QtCore.Slot
    API = "pyside6"

__all__ = ["QtCore", "QtGui", "QtWidgets", "QtPrintSupport", "Signal", "Slot", "API"]
