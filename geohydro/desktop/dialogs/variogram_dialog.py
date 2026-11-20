"""Variogram analysis dialog: experimental variogram, model selection and fitting."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from geohydro.engine.errors import GriddingError
from geohydro.engine.interpolation.base import Anisotropy
from geohydro.engine.interpolation.variogram import (MODELS, VariogramModel,
                                                     experimental_variogram, fit_variogram)

from .. import theme


def dspin(value=0.0, lo=0.0, hi=1e12, decimals=6, step=None):
    s = QDoubleSpinBox()
    s.setDecimals(decimals)
    s.setRange(lo, hi)
    s.setValue(value)
    s.setKeyboardTracking(False)
    if step:
        s.setSingleStep(step)
    return s


class VariogramDialog(QDialog):
    """Compute an experimental variogram for a dataset and choose a model."""

    def __init__(self, dataset, parent=None, model: VariogramModel | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Variogram — {dataset.name}")
        self.resize(980, 620)
        d = dataset.data
        self.x = d["X"].to_numpy(float)
        self.y = d["Y"].to_numpy(float)
        self.z = d["Z"].to_numpy(float) if "Z" in d else np.full(len(d), np.nan)
        self.z_units = dataset.z_units
        self.ev = None
        self.fit_report = None

        ok = np.isfinite(self.x) & np.isfinite(self.y) & np.isfinite(self.z)
        diag = float(np.hypot(np.ptp(self.x[ok]), np.ptp(self.y[ok]))) if ok.sum() > 1 else 1.0

        self.fig = Figure(figsize=(6, 4.5), facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)

        # experimental variogram controls
        self.n_lags = QSpinBox()
        self.n_lags.setRange(3, 100)
        self.n_lags.setValue(15)
        self.max_lag = dspin(diag / 2, 0.0, 1e12, 3)
        self.directional = QCheckBox("Directional")
        self.direction = dspin(0, 0, 180, 1, 5)
        self.tolerance = dspin(22.5, 1, 90, 1, 2.5)
        self.direction.setEnabled(False)
        self.tolerance.setEnabled(False)
        self.directional.toggled.connect(self.direction.setEnabled)
        self.directional.toggled.connect(self.tolerance.setEnabled)
        g1 = QGroupBox("Experimental variogram")
        f1 = QFormLayout(g1)
        f1.addRow("Lag classes", self.n_lags)
        f1.addRow("Maximum lag", self.max_lag)
        f1.addRow(self.directional)
        f1.addRow("Direction (° CCW from east)", self.direction)
        f1.addRow("Angular tolerance (±°)", self.tolerance)

        # model controls
        self.model = QComboBox()
        for k, v in MODELS.items():
            self.model.addItem(v, k)
        self.nugget = dspin(0.0, 0, 1e15, 6)
        self.sill = dspin(1.0, 0, 1e15, 6)
        self.range_ = dspin(diag / 3 or 1.0, 1e-9, 1e12, 3)
        self.exponent = dspin(1.5, 0.01, 1.99, 3, 0.05)
        self.ratio = dspin(1.0, 0.01, 1.0, 3, 0.05)
        self.angle = dspin(0.0, -180, 180, 1, 5)
        self.fit_nugget = QCheckBox("Fit nugget")
        self.fit_nugget.setChecked(True)
        self.btn_fit = QPushButton("Auto-fit model")
        g2 = QGroupBox("Variogram model")
        f2 = QFormLayout(g2)
        f2.addRow("Model", self.model)
        f2.addRow("Nugget (C0)", self.nugget)
        self.sill_label = QLabel("Partial sill (C)")
        f2.addRow(self.sill_label, self.sill)
        self.range_label = QLabel("Range (major axis)")
        f2.addRow(self.range_label, self.range_)
        f2.addRow("Exponent (power)", self.exponent)
        f2.addRow("Anisotropy ratio", self.ratio)
        f2.addRow("Anisotropy angle (°)", self.angle)
        row = QHBoxLayout()
        row.addWidget(self.fit_nugget)
        row.addWidget(self.btn_fit)
        f2.addRow(row)
        self.report = QLabel("")
        self.report.setWordWrap(True)
        self.report.setStyleSheet(f"color:{theme.MUTED}")

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(g1)
        sl.addWidget(g2)
        sl.addWidget(self.report)
        sl.addStretch(1)
        side.setFixedWidth(340)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use this model")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(self.canvas, 1)
        top.addWidget(side)
        lay = QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addWidget(self.buttons)

        for w in (self.n_lags, self.max_lag, self.direction, self.tolerance, self.ratio, self.angle):
            w.valueChanged.connect(self.recompute)
        self.directional.toggled.connect(self.recompute)
        for w in (self.nugget, self.sill, self.range_, self.exponent):
            w.valueChanged.connect(self.redraw)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.btn_fit.clicked.connect(self.auto_fit)

        if model is not None:
            self.set_model(model)
        self.recompute()
        if model is None:
            self.auto_fit()
        self._model_changed()

    # ------------------------------------------------------------------
    def anisotropy(self) -> Anisotropy:
        return Anisotropy(ratio=self.ratio.value(), angle=self.angle.value())

    def set_model(self, m: VariogramModel):
        for w in (self.nugget, self.sill, self.range_, self.exponent, self.ratio, self.angle):
            w.blockSignals(True)
        self.model.setCurrentIndex(self.model.findData(m.model))
        self.nugget.setValue(m.nugget)
        self.sill.setValue(m.sill)
        self.range_.setValue(m.range)
        self.exponent.setValue(m.exponent)
        self.ratio.setValue(m.anisotropy.ratio)
        self.angle.setValue(m.anisotropy.angle)
        for w in (self.nugget, self.sill, self.range_, self.exponent, self.ratio, self.angle):
            w.blockSignals(False)

    def current_model(self) -> VariogramModel:
        return VariogramModel(model=self.model.currentData(), nugget=self.nugget.value(),
                              sill=self.sill.value(), range=self.range_.value(),
                              exponent=self.exponent.value(), anisotropy=self.anisotropy())

    def _model_changed(self, *_):
        m = self.model.currentData()
        self.range_.setEnabled(m in ("spherical", "exponential", "gaussian"))
        self.exponent.setEnabled(m == "power")
        self.sill.setEnabled(m != "nugget")
        self.sill_label.setText({"linear": "Slope", "power": "Scale"}.get(m, "Partial sill (C)"))
        self.range_label.setText("Practical range (major)" if m in ("exponential", "gaussian")
                                 else "Range (major axis)")
        self.redraw()

    def recompute(self, *_):
        try:
            self.ev = experimental_variogram(
                self.x, self.y, self.z, n_lags=self.n_lags.value(),
                max_lag=self.max_lag.value() or None,
                direction=self.direction.value() if self.directional.isChecked() else None,
                tolerance=self.tolerance.value(), anisotropy=self.anisotropy())
        except GriddingError as exc:
            self.ev = None
            self.report.setText(str(exc))
        self.redraw()

    def auto_fit(self):
        if self.ev is None:
            return
        try:
            m, rep = fit_variogram(self.ev, self.model.currentData(),
                                   nugget=self.fit_nugget.isChecked(),
                                   anisotropy=self.anisotropy())
        except GriddingError as exc:
            self.report.setText(str(exc))
            return
        self.fit_report = rep
        self.set_model(m)
        self.redraw()

    def redraw(self, *_):
        ax = self.ax
        ax.clear()
        if self.ev is None or self.ev.lags.size == 0:
            ax.text(0.5, 0.5, "No variogram", ha="center", va="center", transform=ax.transAxes)
            self.canvas.draw_idle()
            return
        ev = self.ev
        sizes = 15 + 60 * ev.counts / max(ev.counts.max(), 1)
        ax.scatter(ev.lags, ev.gamma, s=sizes, color=theme.BLUE, edgecolor="white", zorder=3,
                   label="Experimental (size ∝ pairs)")
        hmax = float(ev.bin_edges[-1])
        h = np.linspace(0, hmax, 300)
        try:
            m = self.current_model()
            ax.plot(h[1:], m(h[1:]), color=theme.NAVY, lw=1.8, label=m.describe())
            ax.plot([0], [0], "o", color=theme.NAVY, ms=3)
        except GriddingError as exc:
            self.report.setText(str(exc))
            m = None
        ax.axhline(ev.variance, color="#999999", lw=0.8, ls="--", label="Sample variance")
        ax.set_xlim(0, hmax)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("Lag distance h (map units, major axis)")
        ax.set_ylabel(f"Semivariance γ(h)  ({self.z_units})²")
        title = "Omnidirectional" if ev.direction is None else \
            f"Direction {ev.direction:.1f}° ± {ev.tolerance:.1f}°"
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7, loc="upper left")
        self.fig.tight_layout()
        self.canvas.draw_idle()
        txt = (f"{ev.n_points} points, {ev.n_pairs_total:,} pairs in {ev.lags.size} classes."
               + (" A reproducible random subsample of 3000 points was used."
                  if ev.subsampled else ""))
        if self.fit_report:
            txt += f"<br>Fit: {self.fit_report['method']}."
            for w in self.fit_report.get("warnings", []):
                txt += f"<br><span style='color:{theme.WARNING}'>⚠ {w}</span>"
        self.report.setText(txt)
