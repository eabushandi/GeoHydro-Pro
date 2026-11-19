"""Point location preview: scatter of X/Y coloured by Z (matplotlib).

This is a *data preview* used to check an import (locations, extent,
outliers). It is not the Phase 2 Post Map / mapping engine.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.ticker import ScalarFormatter
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from scipy.spatial import cKDTree

from geohydro.engine.units import LENGTH_UNITS

from .. import theme

GEOHYDRO_CMAP = LinearSegmentedColormap.from_list(
    "geohydro", ["#0B1F3A", "#1E4378", "#2F6FED", "#14B8A6", "#9BE15D", "#F4D35E"]
)


class PointPreview(QWidget):
    cursorMoved = Signal(object, object, object)  # x, y, nearest z (or None)
    scaleChanged = Signal(str)

    def __init__(self, parent=None, toolbar: bool = True):
        super().__init__(parent)
        self.fig = Figure(figsize=(5, 4), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        if toolbar:
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            self.toolbar.setStyleSheet("QToolBar{border:none;background:white;}")
            lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)
        self.ax = self.fig.add_subplot(111)
        self._tree = None
        self._z = None
        self._units = "m"
        self.canvas.mpl_connect("motion_notify_event", self._on_move)
        self.canvas.mpl_connect("draw_event", lambda _e: self._emit_scale())
        self.show_message("No data")

    def show_message(self, text: str) -> None:
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self.ax.set_axis_off()
        self.ax.text(0.5, 0.5, text, ha="center", va="center", color=theme.MUTED, fontsize=11,
                     transform=self.ax.transAxes)
        self._tree = None
        self.canvas.draw_idle()

    def plot(self, x, y, z=None, *, title="", x_label="X", y_label="Y", z_label="Z",
             units="m", crs_label="", excluded_xy=None) -> None:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        ok = np.isfinite(x) & np.isfinite(y)
        self.fig.clear()
        self.ax = ax = self.fig.add_subplot(111)
        self._units = units
        if not ok.any():
            self.show_message("No valid coordinates to display")
            return
        if z is not None:
            z = np.asarray(z, dtype=float)
            zc = np.where(np.isfinite(z), z, np.nan)
            sc = ax.scatter(x[ok], y[ok], c=zc[ok], s=16, cmap=GEOHYDRO_CMAP, edgecolors="none")
            cb = self.fig.colorbar(sc, ax=ax, shrink=0.85, pad=0.02)
            cb.set_label(z_label, color=theme.TEXT)
            self._z = zc[ok]
        else:
            ax.scatter(x[ok], y[ok], s=14, color=theme.BLUE, edgecolors="none")
            self._z = None
        if excluded_xy is not None and len(excluded_xy[0]):
            ax.scatter(excluded_xy[0], excluded_xy[1], s=40, marker="x", color=theme.ERROR,
                       label="excluded by QC")
            ax.legend(loc="upper right", fontsize=8, frameon=True)
        geographic = units == "deg"
        if not geographic:
            ax.set_aspect("equal", adjustable="datalim")
        else:
            mid = math.radians(float(np.nanmean(y[ok])))
            ax.set_aspect(1.0 / max(math.cos(mid), 1e-6), adjustable="datalim")
        for axis in (ax.xaxis, ax.yaxis):
            fmt = ScalarFormatter(useOffset=False)
            fmt.set_scientific(False)
            axis.set_major_formatter(fmt)
        ax.set_xlabel(f"{x_label} [{units}]")
        ax.set_ylabel(f"{y_label} [{units}]")
        ax.grid(True, color="#E3E8EF", linewidth=0.7)
        ax.tick_params(labelsize=8, colors=theme.TEXT)
        for s in ax.spines.values():
            s.set_color(theme.BORDER)
        t = title
        if crs_label:
            t = f"{title}\n{crs_label}" if title else crs_label
        ax.set_title(t, fontsize=9.5, color=theme.NAVY, loc="left")
        self.fig.tight_layout()
        self._tree = cKDTree(np.column_stack([x[ok], y[ok]]))
        self.canvas.draw_idle()

    def _on_move(self, event):
        if event.inaxes is not self.ax or event.xdata is None:
            return
        zval = None
        if self._tree is not None and self._z is not None:
            d, i = self._tree.query([event.xdata, event.ydata])
            # report nearest observation only when within ~10 px
            x0, x1 = self.ax.get_xlim()
            px = self.ax.bbox.width or 1
            if d <= 10 * abs(x1 - x0) / px:
                zval = float(self._z[i])
        self.cursorMoved.emit(event.xdata, event.ydata, zval)

    def screen_scale(self) -> float | None:
        """Approximate representative fraction of the current view on screen."""
        if self._units not in LENGTH_UNITS or self._tree is None:
            return None
        x0, x1 = self.ax.get_xlim()
        width_px = self.ax.bbox.width
        if width_px <= 0:
            return None
        metres = abs(x1 - x0) * LENGTH_UNITS[self._units][1]
        screen_m = width_px / self.fig.dpi * 0.0254
        return metres / screen_m

    def _emit_scale(self):
        s = self.screen_scale() if self.isVisible() else None
        self.scaleChanged.emit(f"1:{s:,.0f} (screen)" if s else "—")
