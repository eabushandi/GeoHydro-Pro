"""Grid Data dialog: choose data, method, parameters, grid geometry, search,
anisotropy, blanking and duplicate handling; optionally cross-validate."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from geohydro.engine.errors import GeoHydroError, GriddingError
from geohydro.engine.gridding.crossval import leave_one_out
from geohydro.engine.gridding.grid import MAX_NODES, GridGeometry
from geohydro.engine.gridding.gridder import BlankingOptions, GriddingRequest
from geohydro.engine.gridding.methods import METHODS
from geohydro.engine.interpolation.kriging import DRIFTS
from geohydro.engine.interpolation.min_curvature import MAX_DIRECT_NODES
from geohydro.engine.interpolation.simple import RBF_KERNELS
from geohydro.engine.interpolation.variogram import VariogramModel

from .. import theme
from .variogram_dialog import VariogramDialog, dspin

KRIGING = ("ordinary_kriging", "universal_kriging")


def _fmt(v):
    return "—" if v is None or not math.isfinite(v) else f"{v:,.6g}"


class GridDataDialog(QDialog):
    def __init__(self, project, parent=None, dataset_id: str | None = None,
                 method: str = "idw", runner=None):
        super().__init__(parent)
        self.setWindowTitle("Grid Data")
        self.resize(1120, 820)
        self.project = project
        self.runner = runner  # TaskRunner for cross-validation (None = synchronous)
        self.variogram: VariogramModel | None = None
        self.cv_result = None
        self._cv_busy = False

        self.datasets = [d for d in project.datasets.values() if d.has_z]
        self.ds_combo = QComboBox()
        for d in self.datasets:
            self.ds_combo.addItem(f"{d.name}  ({d.n_points:,} points, Z = {d.z_label})", d.id)
        if dataset_id:
            i = self.ds_combo.findData(dataset_id)
            if i >= 0:
                self.ds_combo.setCurrentIndex(i)
        self.method_combo = QComboBox()
        for k, m in METHODS.items():
            self.method_combo.addItem(m.title, k)
        self.method_combo.setCurrentIndex(max(self.method_combo.findData(method), 0))
        self.method_info = QLabel()
        self.method_info.setWordWrap(True)
        self.method_info.setStyleSheet(f"color:{theme.MUTED}")

        # ---- method parameter pages
        self.pages = QStackedWidget()
        self.page_index = {}
        self.p = {}
        self._add_page("idw", self._page_idw())
        self._add_page("kriging", self._page_kriging())
        self._add_page("min_curvature", self._page_mincurv())
        self._add_page("rbf", self._page_rbf())
        self._add_page("none", QLabel("This method has no parameters."))

        # ---- search & anisotropy
        self.search_box = QGroupBox("Search neighbourhood")
        fs = QFormLayout(self.search_box)
        self.radius = dspin(0, 0, 1e12, 3)
        self.radius.setToolTip("0 = unlimited")
        self.max_pts = QSpinBox()
        self.max_pts.setRange(0, 100000)
        self.max_pts.setToolTip("0 = all points")
        self.min_pts = QSpinBox()
        self.min_pts.setRange(1, 1000)
        fs.addRow("Search radius (0 = unlimited)", self.radius)
        fs.addRow("Maximum neighbours (0 = all)", self.max_pts)
        fs.addRow("Minimum neighbours", self.min_pts)
        self.anis_box = QGroupBox("Anisotropy")
        fa = QFormLayout(self.anis_box)
        self.anis_ratio = dspin(1.0, 0.01, 1.0, 3, 0.05)
        self.anis_angle = dspin(0.0, -180, 180, 1, 5)
        fa.addRow("Ratio (minor / major)", self.anis_ratio)
        fa.addRow("Major-axis angle (° CCW from east)", self.anis_angle)
        self.anis_note = QLabel("For Kriging, anisotropy is part of the variogram model.")
        self.anis_note.setStyleSheet(f"color:{theme.MUTED}")
        fa.addRow(self.anis_note)

        # ---- geometry
        self.geo_box = QGroupBox("Grid geometry (node registered)")
        gl = QGridLayout(self.geo_box)
        self.xmin, self.xmax = dspin(0, -1e12, 1e12, 4), dspin(1, -1e12, 1e12, 4)
        self.ymin, self.ymax = dspin(0, -1e12, 1e12, 4), dspin(1, -1e12, 1e12, 4)
        self.dx, self.dy = dspin(1, 1e-9, 1e12, 6), dspin(1, 1e-9, 1e12, 6)
        self.square = QCheckBox("Square cells")
        self.square.setChecked(True)
        self.nodes_label = QLabel()
        self.btn_extent = QPushButton("Reset to data extent")
        for r, (lab, a, b) in enumerate((("X min / max", self.xmin, self.xmax),
                                         ("Y min / max", self.ymin, self.ymax),
                                         ("Spacing X / Y", self.dx, self.dy))):
            gl.addWidget(QLabel(lab), r, 0)
            gl.addWidget(a, r, 1)
            gl.addWidget(b, r, 2)
        gl.addWidget(self.square, 3, 1)
        gl.addWidget(self.btn_extent, 3, 2)
        gl.addWidget(self.nodes_label, 4, 0, 1, 3)

        # ---- blanking, duplicates, output
        self.blank_box = QGroupBox("Blanking and duplicates")
        fb = QFormLayout(self.blank_box)
        self.blank_hull = QCheckBox("Blank nodes outside the convex hull of the data")
        self.blank_dist = dspin(0, 0, 1e12, 3)
        self.dup_tol = dspin(0, 0, 1e9, 6)
        self.dup_policy = QComboBox()
        self.dup_policy.addItems(["mean", "median", "first", "min", "max"])
        fb.addRow(self.blank_hull)
        fb.addRow("Blank beyond distance from data (0 = off)", self.blank_dist)
        fb.addRow("Coincident-point tolerance (0 = exact)", self.dup_tol)
        fb.addRow("Z of merged points", self.dup_policy)
        self.out_box = QGroupBox("Output")
        fo = QFormLayout(self.out_box)
        self.out_name = QLineEdit()
        self.variance_cb = QCheckBox("Also create the kriging variance grid")
        fo.addRow("Grid name", self.out_name)
        fo.addRow(self.variance_cb)

        # ---- cross-validation
        self.btn_cv = QPushButton("Cross-validate (leave-one-out)")
        self.cv_max = QSpinBox()
        self.cv_max.setRange(10, 100000)
        self.cv_max.setValue(500)
        self.cv_text = QTextBrowser()
        self.cv_text.setMinimumHeight(120)
        self.cv_text.setPlaceholderText("Cross-validation results appear here.")

        # ---- layout
        form = QFormLayout()
        form.addRow("Point dataset", self.ds_combo)
        form.addRow("Gridding method", self.method_combo)
        form.addRow("", self.method_info)
        params_box = QGroupBox("Method parameters")
        pl = QVBoxLayout(params_box)
        pl.addWidget(self.pages)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addLayout(form)
        ll.addWidget(params_box)
        ll.addWidget(self.search_box)
        ll.addWidget(self.anis_box)
        ll.addStretch(1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self.geo_box)
        rl.addWidget(self.blank_box)
        rl.addWidget(self.out_box)
        cvrow = QHBoxLayout()
        cvrow.addWidget(self.btn_cv)
        cvrow.addWidget(QLabel("max. validation points"))
        cvrow.addWidget(self.cv_max)
        rl.addLayout(cvrow)
        rl.addWidget(self.cv_text, 1)
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.addWidget(left, 1)
        bl.addWidget(right, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Grid")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setStyleSheet(f"color:{theme.ERROR}")
        self.error.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(scroll, 1)
        lay.addWidget(self.error)
        lay.addWidget(self.buttons)

        # ---- signals
        self.ds_combo.currentIndexChanged.connect(self._dataset_changed)
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        self.btn_extent.clicked.connect(self.reset_extent)
        for w in (self.xmin, self.xmax, self.ymin, self.ymax, self.dx, self.dy):
            w.valueChanged.connect(self._update_nodes)
        self.dx.valueChanged.connect(lambda v: self.square.isChecked() and self.dy.setValue(v))
        self.square.toggled.connect(lambda on: on and self.dy.setValue(self.dx.value()))
        self.btn_cv.clicked.connect(self.cross_validate)

        if not self.datasets:
            self.error.setText("The project has no point dataset with Z values. Import data first.")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            self.btn_cv.setEnabled(False)
        else:
            self._dataset_changed()
        self._method_changed()

    # ------------------------------------------------------------ pages
    def _add_page(self, key, w):
        self.page_index[key] = self.pages.addWidget(w)

    def _page_idw(self):
        w = QWidget()
        f = QFormLayout(w)
        self.p["power"] = dspin(2.0, 0.1, 20, 2, 0.5)
        self.p["smoothing"] = dspin(0.0, 0, 1e9, 4)
        f.addRow("Power", self.p["power"])
        f.addRow("Smoothing distance (0 = exact)", self.p["smoothing"])
        return w

    def _page_kriging(self):
        w = QWidget()
        f = QFormLayout(w)
        self.vg_label = QLabel("No variogram model yet.")
        self.vg_label.setWordWrap(True)
        self.btn_vg = QPushButton("Variogram…")
        self.btn_vg.clicked.connect(self.edit_variogram)
        self.drift = QComboBox()
        for k in DRIFTS:
            self.drift.addItem(k.capitalize(), k)
        f.addRow(self.btn_vg, self.vg_label)
        self.drift_label = QLabel("Drift (Universal Kriging)")
        f.addRow(self.drift_label, self.drift)
        return w

    def _page_mincurv(self):
        w = QWidget()
        f = QFormLayout(w)
        self.p["tension"] = dspin(0.0, 0, 0.99, 2, 0.05)
        self.p["fit_weight"] = dspin(1e4, 1, 1e8, 0, 1000)
        f.addRow("Tension (0 = pure minimum curvature)", self.p["tension"])
        f.addRow("Data fit weight", self.p["fit_weight"])
        return w

    def _page_rbf(self):
        w = QWidget()
        f = QFormLayout(w)
        self.p["kernel"] = QComboBox()
        for k, v in RBF_KERNELS.items():
            self.p["kernel"].addItem(v, k)
        self.p["epsilon"] = QLineEdit()
        self.p["epsilon"].setPlaceholderText("automatic")
        self.p["rbf_smoothing"] = dspin(0.0, 0, 1e12, 4)
        self.p["neighbours"] = QSpinBox()
        self.p["neighbours"].setRange(0, 100000)
        f.addRow("Kernel", self.p["kernel"])
        f.addRow("Shape parameter ε", self.p["epsilon"])
        f.addRow("Smoothing (0 = exact)", self.p["rbf_smoothing"])
        f.addRow("Neighbours (0 = all, global)", self.p["neighbours"])
        return w

    # ------------------------------------------------------------ state
    @property
    def dataset(self):
        did = self.ds_combo.currentData()
        return self.project.datasets.get(did) if did else None

    @property
    def method(self) -> str:
        return self.method_combo.currentData()

    def _dataset_changed(self, *_):
        ds = self.dataset
        if ds is None:
            return
        self.variogram = None
        self.vg_label.setText("No variogram model yet.")
        self.reset_extent()
        self._update_name()

    def _update_name(self):
        ds = self.dataset
        if ds is not None:
            self.out_name.setText(f"{ds.name} – {METHODS[self.method].title}")

    def _method_changed(self, *_):
        m = self.method
        info = METHODS[m]
        self.method_info.setText(info.summary)
        page = {"idw": "idw", "min_curvature": "min_curvature", "rbf": "rbf"}.get(
            m, "kriging" if m in KRIGING else "none")
        self.pages.setCurrentIndex(self.page_index[page])
        self.drift.setVisible(m == "universal_kriging")
        self.drift_label.setVisible(m == "universal_kriging")
        self.search_box.setEnabled(info.uses_search)
        self.anis_box.setEnabled(info.uses_anisotropy)
        self.anis_ratio.setEnabled(m not in KRIGING)
        self.anis_angle.setEnabled(m not in KRIGING)
        self.anis_note.setVisible(m in KRIGING)
        self.variance_cb.setEnabled(info.provides_variance)
        defaults = {"idw": (0, 64, 1), "nearest": (0, 1, 1), "ordinary_kriging": (0, 32, 1),
                    "universal_kriging": (0, 32, 4)}
        if m in defaults:
            r, mx, mn = defaults[m]
            self.radius.setValue(r)
            self.max_pts.setValue(mx)
            self.min_pts.setValue(mn)
        if m in KRIGING and self.variogram is None and self.dataset is not None:
            self.vg_label.setText("Open the variogram to choose a model (required).")
        self._update_name()
        self._update_nodes()
        self.cv_text.clear()

    def reset_extent(self):
        ds = self.dataset
        if ds is None:
            return
        try:
            g = GridGeometry.from_points(ds.data["X"], ds.data["Y"])
        except GriddingError as exc:
            self.error.setText(str(exc))
            return
        for w, v in ((self.xmin, g.x_min), (self.xmax, g.x_max), (self.ymin, g.y_min),
                     (self.ymax, g.y_max), (self.dx, g.dx), (self.dy, g.dy)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self._update_nodes()

    def geometry(self) -> GridGeometry:
        return GridGeometry.from_spacing(self.xmin.value(), self.xmax.value(), self.ymin.value(),
                                         self.ymax.value(), self.dx.value(), self.dy.value())

    def _update_nodes(self, *_):
        try:
            g = self.geometry()
            txt = f"{g.nx} × {g.ny} = {g.n_nodes:,} nodes; X max {g.x_max:,.6g}, Y max {g.y_max:,.6g}"
            warn = ""
            if self.method == "min_curvature" and g.n_nodes > MAX_DIRECT_NODES:
                warn = " — too many nodes for Minimum Curvature"
            elif self.method == "natural_neighbour" and g.n_nodes > 250_000:
                warn = " — Natural Neighbour will be slow at this size"
            self.nodes_label.setText(txt + warn)
            self.nodes_label.setStyleSheet(f"color:{theme.WARNING if warn else theme.TEXT}")
        except GriddingError as exc:
            self.nodes_label.setText(str(exc))
            self.nodes_label.setStyleSheet(f"color:{theme.ERROR}")

    def edit_variogram(self):
        ds = self.dataset
        if ds is None:
            return
        dlg = VariogramDialog(ds, self, self.variogram)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_variogram(dlg.current_model())

    def set_variogram(self, model: VariogramModel):
        self.variogram = model
        self.vg_label.setText(model.describe())

    def params(self) -> dict:
        m = self.method
        p: dict = {}
        if m == "idw":
            p = {"power": self.p["power"].value(), "smoothing": self.p["smoothing"].value()}
        elif m in KRIGING:
            if self.variogram is None:
                raise GriddingError("Choose a variogram model first (Variogram… button).")
            p = {"variogram": self.variogram.to_dict()}
            if m == "universal_kriging":
                p["drift"] = self.drift.currentData()
        elif m == "min_curvature":
            p = {"tension": self.p["tension"].value(), "fit_weight": self.p["fit_weight"].value()}
        elif m == "rbf":
            eps = self.p["epsilon"].text().strip()
            try:
                epsv = float(eps) if eps else None
            except ValueError as exc:
                raise GriddingError("Shape parameter ε must be a number or blank.") from exc
            p = {"kernel": self.p["kernel"].currentData(), "epsilon": epsv,
                 "smoothing": self.p["rbf_smoothing"].value(),
                 "neighbours": self.p["neighbours"].value() or None}
        info = METHODS[m]
        if info.uses_search:
            p["search"] = {"radius": self.radius.value() or None,
                           "max_points": self.max_pts.value() or None,
                           "min_points": self.min_pts.value()}
        if info.uses_anisotropy and m not in KRIGING:
            p["anisotropy"] = {"ratio": self.anis_ratio.value(), "angle": self.anis_angle.value()}
        return p

    def request(self) -> GriddingRequest:
        return GriddingRequest(
            method=self.method, params=self.params(), geometry=self.geometry(),
            blanking=BlankingOptions(self.blank_hull.isChecked(), self.blank_dist.value() or None),
            duplicate_tolerance=self.dup_tol.value(), duplicate_policy=self.dup_policy.currentText(),
            variance_grid=self.variance_cb.isChecked() and self.variance_cb.isEnabled())

    def _accept(self):
        try:
            req = self.request()
            if req.geometry.n_nodes > MAX_NODES:
                raise GriddingError("Too many grid nodes.")
            if self.method == "min_curvature" and req.geometry.n_nodes > MAX_DIRECT_NODES:
                raise GriddingError(f"Minimum Curvature is limited to {MAX_DIRECT_NODES:,} nodes.")
        except GeoHydroError as exc:
            self.error.setText(str(exc))
            return
        if not self.out_name.text().strip():
            self.error.setText("Enter a grid name.")
            return
        self.accept()

    # ------------------------------------------------------------ cross-validation
    def cross_validate(self):
        if self._cv_busy:
            return
        ds = self.dataset
        try:
            req = self.request()
        except GeoHydroError as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        d = ds.data
        args = (d["X"].to_numpy(float), d["Y"].to_numpy(float), d["Z"].to_numpy(float),
                req.method, req.params)
        kw = dict(geometry=req.geometry if METHODS[req.method].grid_only else None,
                  max_validation_points=self.cv_max.value(),
                  duplicate_tolerance=req.duplicate_tolerance,
                  duplicate_policy=req.duplicate_policy)
        self.cv_text.setHtml("<i>Cross-validating…</i>")
        self._cv_busy = True
        self.btn_cv.setEnabled(False)
        if self.runner is None:
            try:
                self._cv_done(leave_one_out(*args, **kw))
            except GeoHydroError as exc:
                self._cv_failed(exc, "")
        else:
            self.runner.start(lambda: leave_one_out(*args, **kw), self._cv_done, self._cv_failed)

    def _cv_done(self, res):
        self._cv_busy = False
        self.btn_cv.setEnabled(True)
        self.cv_result = res
        self.cv_text.setHtml(cv_html(res, self.dataset.z_units if self.dataset else ""))

    def _cv_failed(self, exc, _tb):
        self._cv_busy = False
        self.btn_cv.setEnabled(True)
        self.cv_text.setHtml(f"<span style='color:{theme.ERROR}'>Cross-validation failed: {exc}</span>")


def cv_html(res, units: str = "") -> str:
    m = res.metrics
    u = f" {units}" if units else ""
    rows = [("Validation points", f"{res.n_validated:,} of {res.n_points:,}"
             + (" (random subsample, fixed seed)" if res.subsampled else "")),
            ("Mean error (bias)", _fmt(m.get("mean_error")) + u),
            ("Mean absolute error", _fmt(m.get("mean_abs_error")) + u),
            ("RMSE", _fmt(m.get("rmse")) + u),
            ("Max. absolute error", _fmt(m.get("max_abs_error")) + u),
            ("R² (1 − SSE/SST)", _fmt(m.get("r_squared"))),
            ("Pearson r", _fmt(m.get("pearson_r")))]
    if "mean_squared_standardised_error" in m:
        rows += [("Mean standardised error", _fmt(m["mean_standardised_error"])),
                 ("Mean squared standardised error (≈1 ideal)",
                  _fmt(m["mean_squared_standardised_error"]))]
    html = "<table cellspacing=4>" + "".join(
        f"<tr><td><b>{a}</b></td><td>{b}</td></tr>" for a, b in rows) + "</table>"
    for w in res.warnings:
        html += f"<p style='color:{theme.WARNING}'>⚠ {w}</p>"
    html += ("<p style='color:#6A7686'>Error = estimate − observed. Leave-one-out: each point "
             "is removed and re-estimated from the others with the same parameters.</p>")
    return html


_ = (np, Qt)
