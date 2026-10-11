"""An open design in the GUI: Design + undo stack + file path."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..geometry.solver import Geometry, solve
from ..model.design import Design
from ..qt import QtCore, QtGui, Signal

QUndoCommand = QtGui.QUndoCommand
QUndoStack = QtGui.QUndoStack

_MERGE_BASE = 0x4657


class SetParams(QUndoCommand):
    """Change one or more parameters.  Consecutive edits of the same single
    parameter (e.g. spinning a spin box) merge into one undo step."""

    def __init__(self, doc: "Document", changes: dict[str, tuple[Any, Any]], text: str):
        super().__init__(text)
        self.doc = doc
        self.changes = dict(changes)
        self._id = (_MERGE_BASE + (hash(next(iter(changes))) & 0xFFFF)) if len(changes) == 1 else -1

    def id(self) -> int:
        return self._id

    def mergeWith(self, other) -> bool:
        if not isinstance(other, SetParams) or other.id() != self.id() or self.id() < 0:
            return False
        for k, (old, new) in other.changes.items():
            self.changes[k] = (self.changes[k][0] if k in self.changes else old, new)
        return True

    def redo(self) -> None:
        for k, (_, new) in self.changes.items():
            self.doc.design.set(k, new)
        self.doc._touch(set(self.changes))

    def undo(self) -> None:
        for k, (old, _) in self.changes.items():
            self.doc.design.set(k, old)
        self.doc._touch(set(self.changes))


class SetExtra(QUndoCommand):
    def __init__(self, doc: "Document", key: str, new: Any, text: str, merge_id: int = -1):
        super().__init__(text)
        self.doc = doc
        self.key = key
        self.old = copy.deepcopy(doc.design.extras.get(key))
        self.new = copy.deepcopy(new)
        self._id = merge_id

    def id(self) -> int:
        return self._id

    def mergeWith(self, other) -> bool:
        if not isinstance(other, SetExtra) or other.id() != self.id() or other.key != self.key or self._id < 0:
            return False
        self.new = other.new
        return True

    def redo(self) -> None:
        self.doc.design.extras[self.key] = copy.deepcopy(self.new)
        self.doc._touch({"extras:" + self.key})

    def undo(self) -> None:
        self.doc.design.extras[self.key] = copy.deepcopy(self.old)
        self.doc._touch({"extras:" + self.key})


class Document(QtCore.QObject):
    changed = Signal(object)          # set of changed keys
    path_changed = Signal()

    def __init__(self, design: Design | None = None, path: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.design = design or Design()
        self.path: Path | None = Path(path) if path else None
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(lambda _c: self.path_changed.emit())
        self._geometry: Geometry | None = None
        self.ghosts: list[dict] = []        # [{"label", "design", "color"}]

    # -- state ----------------------------------------------------------------
    @property
    def geometry(self) -> Geometry:
        if self._geometry is None:
            self._geometry = solve(self.design)
        return self._geometry

    def _touch(self, keys: set[str]) -> None:
        self._geometry = None
        self.changed.emit(keys)

    def refresh(self) -> None:
        self._touch({"*"})

    @property
    def dirty(self) -> bool:
        return not self.undo.isClean()

    @property
    def display_name(self) -> str:
        name = self.path.name if self.path else self.design.title
        return name + (" *" if self.dirty else "")

    # -- edits ----------------------------------------------------------------
    def set_param(self, key: str, value: Any, text: str | None = None) -> None:
        old = self.design.get(key)
        from ..model import params as P
        new = P.get(key).coerce(value) if P.has(key) else value
        if old == new:
            return
        from ..geometry.modes import MODE_KEYS, mode_switch_values
        if key in MODE_KEYS:
            # switching how a dimension is specified: carry the current value
            # over so the geometry doesn't move (one undo step)
            label = P.get(key).label if P.has(key) else key
            self.set_params(mode_switch_values(self.design, key, new, self.geometry), text or f"Set {label}")
            return
        self.undo.push(SetParams(self, {key: (old, new)}, text or f"Set {key}"))

    def set_params(self, values: dict[str, Any], text: str = "Edit", merge_id: int = -1) -> None:
        """Set several parameters in one undo step.  Pass the same ``merge_id``
        for a stream of updates (e.g. a mouse drag) to collapse them."""
        from ..model import params as P
        changes = {}
        for k, v in values.items():
            old = self.design.get(k)
            new = P.get(k).coerce(v) if P.has(k) else v
            if old != new:
                changes[k] = (old, new)
        if changes:
            cmd = SetParams(self, changes, text)
            cmd._id = merge_id
            self.undo.push(cmd)

    def set_extra(self, key: str, value: Any, text: str = "Edit", merge_id: int = -1) -> None:
        self.undo.push(SetExtra(self, key, value, text, merge_id))

    # -- files ----------------------------------------------------------------
    def save(self, path: str | Path | None = None) -> None:
        if path is not None:
            self.path = Path(path)
        if self.path is None:
            raise ValueError("no path")
        self.design.save(self.path)
        self.undo.setClean()
        self.path_changed.emit()

    @classmethod
    def open(cls, path: str | Path, parent=None) -> "Document":
        return cls(Design.load(path), path if str(path).endswith(".fwd") else None, parent)
