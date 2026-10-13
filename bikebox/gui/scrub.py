"""Spin boxes you can scrub: click and drag left/right to change the value in
real time, instead of clicking the little arrows one step at a time.

A plain click still places the text cursor for typing; scrubbing only begins
once the pointer has moved past a few pixels, so editing is unaffected.
"""
from __future__ import annotations

from ..qt import QtCore, QtWidgets

Qt = QtCore.Qt
_PX_PER_STEP = 4.0          # horizontal pixels of drag per single-step change
_START = 3                  # pixels of movement before a drag counts as a scrub


class _ScrubBehavior:
    """Mixin: horizontal drag over the field scrubs the value. Mix in *before*
    the concrete QAbstractSpinBox subclass so super() resolves to it."""

    def _scrub_init(self) -> None:
        self._scrub_anchor: float | None = None
        self._scrub_value: float = 0.0
        self._scrubbed = False
        le = self.lineEdit()
        if le is not None:
            le.installEventFilter(self)
            le.setCursor(Qt.CursorShape.SizeHorCursor)

    @staticmethod
    def _gx(e) -> float:
        try:
            return e.globalPosition().x()
        except AttributeError:                      # older event API
            return float(e.globalX())

    def eventFilter(self, obj, e):                  # noqa: N802 (Qt name)
        if obj is self.lineEdit():
            t = e.type()
            if t == QtCore.QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                self._scrub_anchor = self._gx(e)
                self._scrub_value = self.value()
                self._scrubbed = False
            elif (t == QtCore.QEvent.Type.MouseMove and self._scrub_anchor is not None
                  and (e.buttons() & Qt.MouseButton.LeftButton)):
                dx = self._gx(e) - self._scrub_anchor
                if self._scrubbed or abs(dx) > _START:
                    self._scrubbed = True
                    steps = round(dx / _PX_PER_STEP)
                    self.setValue(self._scrub_value + steps * self.singleStep())
                    return True                     # consume: don't select text while scrubbing
            elif t == QtCore.QEvent.Type.MouseButtonRelease:
                scrubbed = self._scrubbed
                self._scrub_anchor = None
                self._scrubbed = False
                if scrubbed:
                    return True                     # consume so the click doesn't move the caret
        return super().eventFilter(obj, e)


class ScrubDoubleSpinBox(_ScrubBehavior, QtWidgets.QDoubleSpinBox):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._scrub_init()


class ScrubSpinBox(_ScrubBehavior, QtWidgets.QSpinBox):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._scrub_init()
