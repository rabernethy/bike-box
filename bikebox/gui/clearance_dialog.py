"""'Resolve issues' dialog: for every geometry or clearance issue in the design
it offers several ways to address it, each measured and previewed, and lets you
pick one (or leave the issue alone) and apply them together."""
from __future__ import annotations

from ..geometry import clearance as C
from ..geometry.remedies import Issue, Option, apply_choices, find_issues
from ..geometry.solver import solve
from ..qt import QtCore, QtGui, QtWidgets
from .document import Document

Qt = QtCore.Qt


class FixClearanceDialog(QtWidgets.QDialog):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Resolve issues")
        self.resize(760, 620)
        lay = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel("Checking the design…")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QtWidgets.QWidget()
        self.vbox = QtWidgets.QVBoxLayout(self.body)
        self.vbox.addStretch(1)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

        self.preview = QtWidgets.QLabel()
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)

        bb = QtWidgets.QDialogButtonBox()
        self.apply_btn = bb.addButton("Apply selected", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QtWidgets.QDialogButtonBox.StandardButton.Close)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.issues: list[Issue] = []
        self._groups: list[QtWidgets.QButtonGroup] = []     # one per issue; buttons carry the Option (or None)
        QtCore.QTimer.singleShot(0, self.compute)

    # -- building ----------------------------------------------------------------
    def compute(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.issues = find_issues(self.doc.design)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        units = self.doc.design["units"]
        from ..model.units import fmt_len            # noqa: F401 (imported for parity/formatting use)
        if not self.issues:
            self.summary.setText("<b>No issues.</b> Every clearance and geometry check passes.")
            self.apply_btn.setEnabled(False)
            self._refresh_preview()
            return
        self.summary.setText(f"<b>{len(self.issues)} issue(s).</b> Pick how to address each one — the recommended "
                             "option is selected. Choose “Leave unchanged” to skip. The effect on the rest of the "
                             "geometry, and any new problem a change would cause, is shown under each option.")
        for iss in self.issues:
            self._add_issue(iss)
        self._refresh_preview()

    def _add_issue(self, iss: Issue) -> None:
        box = QtWidgets.QGroupBox(f"{iss.label} — {iss.message}")
        box.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 8px; }")
        v = QtWidgets.QVBoxLayout(box)
        group = QtWidgets.QButtonGroup(box)
        group.setExclusive(True)
        if iss.options:
            for i, opt in enumerate(iss.options):
                rb = QtWidgets.QRadioButton(self._option_text(opt))
                rb.setProperty("option_index", i)
                rb.toggled.connect(self._refresh_preview)
                group.addButton(rb)
                v.addWidget(rb)
                if i == 0:
                    rb.setChecked(True)
            leave = QtWidgets.QRadioButton("Leave unchanged")
            leave.setProperty("option_index", -1)
            leave.toggled.connect(self._refresh_preview)
            group.addButton(leave)
            v.addWidget(leave)
        else:
            lbl = QtWidgets.QLabel("No automatic option. " + iss.advice)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: gray; font-weight: normal;")
            v.addWidget(lbl)
        self._groups.append(group)
        self.vbox.insertWidget(self.vbox.count() - 1, box)

    def _option_text(self, opt: Option) -> str:
        parts = [f"<b>{opt.label}</b> → {opt.after_text}"]
        if opt.detail:
            parts.append(f"<span style='color:#444'>{opt.detail}</span>")
        if opt.side_effects:
            parts.append(f"<span style='color:#7a5000'>changes: {'; '.join(opt.side_effects)}</span>")
        if opt.new_problems:
            parts.append(f"<span style='color:#c62828'>introduces: {', '.join(opt.new_problems)}</span>")
        return "<br>".join(parts).replace("font-weight: bold", "")

    # -- selection / preview ------------------------------------------------------
    def _chosen(self) -> list[Option]:
        out = []
        for iss, group in zip(self.issues, self._groups):
            btn = group.checkedButton()
            if btn is None:
                continue
            idx = btn.property("option_index")
            if idx is not None and idx >= 0 and idx < len(iss.options):
                out.append(iss.options[idx])
        return out

    def _refresh_preview(self, *_):
        chosen = self._chosen()
        self.apply_btn.setEnabled(bool(chosen))
        if not self.issues:
            self.preview.setText("")
            return
        changes = apply_choices(self.doc.design, chosen)
        if not changes:
            self.preview.setText("<i>Nothing selected.</i>")
            return
        d2 = self.doc.design.copy()
        d2.update(changes)
        g2 = solve(d2)
        from ..geometry.remedies import active_keys
        remaining = len(active_keys(g2))
        base = len(active_keys(self.doc.geometry))
        msg = f"<b>Preview:</b> {len(chosen)} change(s) selected. "
        if remaining == 0:
            msg += "<span style='color:#1d8a3a'>All issues resolved.</span>"
        else:
            msg += f"<span style='color:#c77700'>{remaining} issue(s) would remain</span> (was {base})."
        conflicts = self._conflicts(chosen)
        if conflicts:
            msg += f"<br><span style='color:#c62828'>Overlapping changes to {', '.join(conflicts)}; " \
                   "the later option wins.</span>"
        self.preview.setText(msg)

    def _conflicts(self, chosen: list[Option]) -> list[str]:
        from ..model import params as P
        seen, dup = {}, []
        for o in chosen:
            for k in o.changes:
                if k in seen and k not in dup:
                    dup.append(P.get(k).label if P.has(k) else k)
                seen[k] = True
        return dup

    def apply(self) -> None:
        chosen = self._chosen()
        if chosen:
            self.doc.set_params(apply_choices(self.doc.design, chosen), "Resolve issues")
        self.accept()
