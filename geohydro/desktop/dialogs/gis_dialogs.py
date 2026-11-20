"""Phase 3 dialogs: a generic parameter form used by the grid-math, terrain,
density and import commands, a read-only text report, and the profile plot.

``ParamDialog`` is data driven so every command shows the same layout and so
tests can set values without clicking (``set_value`` / ``values``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from .. import theme


@dataclass
class Field:
    """One input of a :class:`ParamDialog`.

    kind: ``float``, ``int``, ``text``, ``bool`` or ``choice``. For ``choice``,
    ``options`` is a list of (value, label) pairs; the dialog returns the value.
    """

    key: str
    label: str
    kind: str = "float"
    default: object = None
    options: list = field(default_factory=list)
    minimum: float = -1e12
    maximum: float = 1e12
    decimals: int = 4
    tip: str = ""
    optional: bool = False  # float/int: an empty box means None


class ParamDialog(QDialog):
    def __init__(self, title: str, fields: list[Field], parent=None, intro: str = "",
                 note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.fields = {f.key: f for f in fields}
        self.editors: dict[str, object] = {}
        lay = QVBoxLayout(self)
        if intro:
            lab = QLabel(intro)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        form = QFormLayout()
        for f in fields:
            w = self._editor(f)
            if f.tip:
                w.setToolTip(f.tip)
            self.editors[f.key] = w
            form.addRow(f.label, w)
        lay.addLayout(form)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet(f"color:{theme.MUTED};font-size:8.5pt")
            lay.addWidget(n)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def _editor(self, f: Field):
        if f.kind == "choice":
            w = QComboBox()
            for value, label in f.options:
                w.addItem(label, value)
            if f.default is not None:
                i = w.findData(f.default)
                w.setCurrentIndex(max(i, 0))
            return w
        if f.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(f.default))
            return w
        if f.kind == "int" and not f.optional:
            w = QSpinBox()
            w.setRange(int(max(f.minimum, -2**31 + 1)), int(min(f.maximum, 2**31 - 1)))
            w.setValue(int(f.default or 0))
            return w
        if f.kind == "float" and not f.optional:
            w = QDoubleSpinBox()
            w.setDecimals(f.decimals)
            w.setRange(f.minimum, f.maximum)
            w.setValue(float(f.default or 0.0))
            return w
        w = QLineEdit("" if f.default is None else str(f.default))
        if f.optional:
            w.setPlaceholderText("automatic")
        return w

    # ---- values -----------------------------------------------------------------
    def value(self, key):
        f, w = self.fields[key], self.editors[key]
        if f.kind == "choice":
            return w.currentData()
        if f.kind == "bool":
            return w.isChecked()
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            return w.value()
        s = w.text().strip()
        if f.kind in ("float", "int"):
            if s == "":
                return None
            v = float(s)
            return int(v) if f.kind == "int" else v
        return s

    def values(self) -> dict:
        return {k: self.value(k) for k in self.fields}

    def set_value(self, key, value):
        f, w = self.fields[key], self.editors[key]
        if f.kind == "choice":
            i = w.findData(value)
            if i < 0:
                raise KeyError(f"{value!r} is not an option of {key}")
            w.setCurrentIndex(i)
        elif f.kind == "bool":
            w.setChecked(bool(value))
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            w.setValue(value)
        else:
            w.setText("" if value is None else str(value))


class TextReportDialog(QDialog):
    """Read-only report (monospace) with a Save button."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family:Consolas,'DejaVu Sans Mono',monospace;")
        lay.addWidget(self.text)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        save = QPushButton("Save as Text…")
        bb.addButton(save, QDialogButtonBox.ButtonRole.ActionRole)
        save.clicked.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save report", "report.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.text.toPlainText())


class ProfileDialog(QDialog):
    """Plot of a profile (distance vs Z) with CSV export of the sampled values."""

    def __init__(self, prof: dict, grid_name: str, z_label: str, xy_units: str, parent=None):
        super().__init__(parent)
        self.prof = prof
        self.setWindowTitle(f"Profile — {grid_name}")
        self.resize(820, 460)
        lay = QVBoxLayout(self)
        self.fig = Figure(figsize=(8, 4), facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        lay.addWidget(NavigationToolbar2QT(self.canvas, self))
        lay.addWidget(self.canvas, 1)
        ax = self.fig.add_subplot(111)
        d, z = np.asarray(prof["distance"]), np.asarray(prof["z"])
        ax.plot(d, z, color=theme.NAVY, lw=1.2)
        ax.fill_between(d, z, np.nanmin(z) if np.isfinite(z).any() else 0, color=theme.TURQUOISE,
                        alpha=0.15)
        ax.set_xlabel(f"Distance along profile ({prof.get('distance_units', xy_units)})")
        ax.set_ylabel(z_label)
        ax.grid(alpha=0.3)
        ax.set_title(f"{grid_name}: {prof.get('length', d[-1] if d.size else 0):,.6g} "
                     f"{prof.get('distance_units', xy_units)}, {d.size} samples", fontsize=9)
        self.fig.tight_layout()
        self.note = QLabel("Bilinear interpolation between grid nodes. Gaps are blank nodes or "
                           "parts of the line outside the grid.")
        self.note.setStyleSheet(f"color:{theme.MUTED}")
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        save = QPushButton("Export CSV…")
        bb.addButton(save, QDialogButtonBox.ButtonRole.ActionRole)
        save.clicked.connect(lambda: self.export_csv())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def export_csv(self, path=None):
        import pandas as pd
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export profile", "profile.csv",
                                                  "CSV (*.csv)")
            if not path:
                return None
        pd.DataFrame({k: np.asarray(self.prof[k]) for k in ("distance", "x", "y", "z")}).to_csv(
            path, index=False, float_format="%.10g")
        return path


def item_choices(store: dict, kind_filter=None) -> list[tuple[str, str]]:
    """(id, name) pairs for a choice field from a project store."""
    return [(o.id, o.name) for o in store.values() if kind_filter is None or kind_filter(o)]


_ = Qt
