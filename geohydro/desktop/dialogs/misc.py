"""Smaller dialogs: About, CRS inspector, processing history, project validation."""

from __future__ import annotations

import json
import platform

import numpy as np
from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

from geohydro import APP_NAME, APP_TAGLINE, DEVELOPMENT_PHASE, __version__
from geohydro.engine.crs import COMMON_CRS, resolve_crs, transform_points
from geohydro.engine.errors import CRSError
from geohydro.project import FORMAT_VERSION, Project

from .. import icons, theme


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(72))
        top.addWidget(logo)
        import matplotlib
        import pandas
        import pyproj
        import scipy
        txt = QLabel(
            f"<h2 style='color:{theme.NAVY};margin:0'>{APP_NAME}</h2>"
            f"<p style='color:{theme.TURQUOISE_DARK};margin:2px 0 10px 0'>{APP_TAGLINE}</p>"
            f"<p>Version {__version__} · {DEVELOPMENT_PHASE}<br>Project format version {FORMAT_VERSION}</p>"
            f"<p style='color:{theme.MUTED}'>Python {platform.python_version()} · Qt {qVersion()} · "
            f"PySide6 {PYSIDE_VERSION}<br>NumPy {np.__version__} · pandas {pandas.__version__} · "
            f"SciPy {scipy.__version__} · PyProj {pyproj.__version__} (PROJ {pyproj.proj_version_str}) · "
            f"Matplotlib {matplotlib.__version__}<br>{platform.system()} {platform.release()}</p>"
            "<p style='color:#6A7686;font-size:8.5pt'>Pre-release development build. Results are not certified "
            "engineering results. Licensing and subscriptions are planned for Phase 7.</p>"
        )
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(txt, 1)
        lay.addLayout(top)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.resize(560, 280)


class CRSToolDialog(QDialog):
    """Inspect a CRS definition and transform a single coordinate pair."""

    def __init__(self, parent=None, initial: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("CRS Inspector & Coordinate Transform")
        self.setWindowIcon(icons.icon("crs"))
        self.resize(720, 620)
        lay = QVBoxLayout(self)

        g1 = QGroupBox("Coordinate reference system")
        f1 = QFormLayout(g1)
        self.src = self._crs_combo(initial or "EPSG:4326")
        f1.addRow("CRS:", self.src)
        self.info = QTextBrowser()
        self.info.setMinimumHeight(220)
        f1.addRow(self.info)
        lay.addWidget(g1)

        g2 = QGroupBox("Transform a coordinate")
        f2 = QFormLayout(g2)
        self.dst = self._crs_combo("EPSG:32639")
        f2.addRow("Target CRS:", self.dst)
        self.x = QDoubleSpinBox()
        self.y = QDoubleSpinBox()
        for w, v in ((self.x, 50.55), (self.y, 26.1)):
            w.setDecimals(6)
            w.setRange(-1e12, 1e12)
            w.setValue(v)
        row = QHBoxLayout()
        row.addWidget(QLabel("X / Lon:"))
        row.addWidget(self.x)
        row.addWidget(QLabel("Y / Lat:"))
        row.addWidget(self.y)
        b = QPushButton("Transform")
        b.setObjectName("Primary")
        b.clicked.connect(self.do_transform)
        row.addWidget(b)
        f2.addRow(row)
        self.result = QLabel("")
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f2.addRow("Result:", self.result)
        lay.addWidget(g2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.src.currentTextChanged.connect(self.inspect)
        self.inspect()

    @staticmethod
    def _crs_combo(text):
        c = QComboBox()
        c.setEditable(True)
        for code, name in COMMON_CRS:
            c.addItem(f"{code} - {name}")
        c.setCurrentText(text)
        return c

    def inspect(self, *_):
        try:
            info = resolve_crs(self.src.currentText())
        except CRSError as exc:
            self.info.setHtml(f"<p style='color:{theme.ERROR}'>{exc}</p>")
            return
        if info is None:
            self.info.setHtml("<p>Undefined CRS</p>")
            return
        self.info.setHtml(
            f"<b>{info.display}</b><br>Type: {'geographic' if info.is_geographic else 'projected' if info.is_projected else 'other'}"
            f" · axis unit: {info.axis_unit}<pre style='font-size:8pt'>{info.wkt}</pre>"
        )

    def do_transform(self):
        try:
            xo, yo = transform_points([self.x.value()], [self.y.value()], self.src.currentText(),
                                      self.dst.currentText())
            self.result.setText(f"<b>X = {xo[0]:.4f}   Y = {yo[0]:.4f}</b>")
        except CRSError as exc:
            self.result.setText(f"<span style='color:{theme.ERROR}'>{exc}</span>")


class HistoryDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Processing History — {project.name}")
        self.setWindowIcon(icons.icon("history"))
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(project.history), 3)
        self.table.setHorizontalHeaderLabels(["Time (UTC)", "Action", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        for i, h in enumerate(project.history):
            self.table.setItem(i, 0, QTableWidgetItem(h.timestamp))
            self.table.setItem(i, 1, QTableWidgetItem(h.action))
            short = ", ".join(f"{k}={v}" for k, v in h.details.items()
                              if k in ("name", "old", "new", "changes", "qc", "from_version", "to_version"))
            it = QTableWidgetItem(short[:300])
            it.setToolTip(json.dumps(h.details, indent=2, default=str)[:4000])
            self.table.setItem(i, 2, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(160)
        lay.addWidget(self.detail)
        self.table.currentCellChanged.connect(
            lambda r, *_: self.detail.setPlainText(
                json.dumps(project.history[r].details, indent=2, default=str) if 0 <= r < len(project.history) else ""))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
