"""Status bar: cursor coordinates, CRS, map scale, grid resolution, elevation,
processing status."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QStatusBar


class GeoStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self.status = QLabel("Ready")
        self.addWidget(self.status, 1)
        self.coords = QLabel("X: —   Y: —")
        self.elev = QLabel("Z: —")
        self.crs = QLabel("CRS: —")
        self.scale = QLabel("Scale: —")
        self.grid = QLabel("Grid: none")
        self.grid.setToolTip("Grid resolution (gridding is planned for Phase 2)")
        self.elev.setToolTip("Value of the nearest observation under the cursor")
        self.scale.setToolTip("Approximate on-screen scale of the active preview")
        for w in (self.coords, self.elev, self.crs, self.scale, self.grid):
            self.addPermanentWidget(w)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.addPermanentWidget(self.progress)

    def set_cursor(self, x, y, z=None):
        if x is None:
            self.coords.setText("X: —   Y: —")
        else:
            self.coords.setText(f"X: {x:,.3f}   Y: {y:,.3f}")
        self.elev.setText("Z: —" if z is None else f"Z: {z:,.3f}")

    def set_crs(self, text: str | None):
        self.crs.setText(f"CRS: {text or 'undefined'}")

    def set_scale(self, text: str):
        self.scale.setText(f"Scale: {text}")

    def set_status(self, text: str):
        self.status.setText(text)

    def busy(self, on: bool, text: str | None = None):
        self.progress.setVisible(on)
        self.progress.setRange(0, 0 if on else 1)
        if text:
            self.status.setText(text)
