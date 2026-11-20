"""Grid document: preview (colour relief + contours), statistics and provenance."""

from __future__ import annotations

import html
import json
import math

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHeaderView, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from geohydro.engine.gridding.grid import Grid
from geohydro.engine.mapping.levels import LevelSpec
from geohydro.engine.mapping.model import (ColourReliefLayer, ContourLayer, ElementPos,
                                           MapDocument, PostLayer)
from geohydro.engine.mapping.render import render_map

from .. import theme


def _f(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return "—" if not math.isfinite(v) else f"{v:,.6g}"
    return str(v)


class GridDocument(QWidget):
    cursorMoved = Signal(object, object, object)  # x, y, grid z

    def __init__(self, grid: Grid, dataset=None, parent=None):
        super().__init__(parent)
        self.grid = grid
        self.dataset = dataset
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tabs)

        prev = QWidget()
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(7, 5), facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setStyleSheet("QToolBar{border:none;background:white;}")
        pl.addWidget(self.toolbar)
        pl.addWidget(self.canvas, 1)
        self.tabs.addTab(prev, "Preview")

        self.stats = QTableWidget(0, 2)
        self.stats.setHorizontalHeaderLabels(["Statistic", "Value"])
        self.stats.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats.horizontalHeader().setStretchLastSection(True)
        self.stats.verticalHeader().setVisible(False)
        self.tabs.addTab(self.stats, "Statistics")
        self.prov = QTextBrowser()
        self.tabs.addTab(self.prov, "Method && Provenance")
        self.canvas.mpl_connect("motion_notify_event", self._on_move)
        self.refresh(grid, dataset)

    @property
    def grid_id(self) -> str:
        return self.grid.id

    def preview_document(self) -> MapDocument:
        g = self.grid
        layers = [ColourReliefLayer(grid_id=g.id, name="Colour relief"),
                  ContourLayer(grid_id=g.id, name="Contours", levels=LevelSpec("auto", 12),
                               line_width=0.5, major_every=0, labels=True)]
        if self.dataset is not None:
            layers.append(PostLayer(dataset_id=self.dataset.id, name="Data points", size=5,
                                    face_color="#111111", edge_color="#ffffff"))
        return MapDocument(name=g.name, crs=g.crs, xy_units=g.xy_units, layers=layers,
                           margins_mm=4, scale_bar=ElementPos(True, "lower left"),
                           north_arrow=ElementPos(False))

    def refresh(self, grid: Grid, dataset=None):
        self.grid = grid
        if dataset is not None:
            self.dataset = dataset
        objs = {grid.id: grid}
        if self.dataset is not None:
            objs[self.dataset.id] = self.dataset
        self._objs = objs
        self._draw()
        s = grid.statistics()
        md = grid.metadata or {}
        rows = [("Columns × rows", f"{s['nx']} × {s['ny']}"), ("Nodes", f"{s['nodes']:,}"),
                ("Spacing X / Y", f"{_f(s['dx'])} / {_f(s['dy'])} {grid.xy_units}"),
                ("X min / max", f"{_f(s['x_min'])} / {_f(s['x_max'])}"),
                ("Y min / max", f"{_f(s['y_min'])} / {_f(s['y_max'])}"),
                ("Valid / blank nodes", f"{s['valid_nodes']:,} / {s['blank_nodes']:,}")]
        if s.get("valid_nodes"):
            u = grid.z_units
            rows += [("Z minimum", f"{_f(s['z_min'])} {u}"), ("Z maximum", f"{_f(s['z_max'])} {u}"),
                     ("Z mean", f"{_f(s['z_mean'])} {u}"), ("Z median", f"{_f(s['z_median'])} {u}"),
                     ("Z std. dev. (n−1)", f"{_f(s['z_std'])} {u}"),
                     ("Z quartiles Q1 / Q3", f"{_f(s['z_q1'])} / {_f(s['z_q3'])} {u}")]
        res = md.get("residuals") or {}
        if res.get("compared"):
            rows += [("Residuals compared", f"{res['compared']:,} of {res['points']:,} points"),
                     ("Residual mean (obs − grid)", _f(res.get("mean_error"))),
                     ("Residual RMSE", _f(res.get("rmse"))),
                     ("Residual max |r|", _f(res.get("max_abs_error")))]
        cv = (md.get("cross_validation") or {}).get("metrics")
        if cv:
            rows += [("Cross-validation RMSE", _f(cv.get("rmse"))),
                     ("Cross-validation MAE", _f(cv.get("mean_abs_error"))),
                     ("Cross-validation ME", _f(cv.get("mean_error"))),
                     ("Cross-validation R²", _f(cv.get("r_squared")))]
        self.stats.setRowCount(len(rows))
        for i, (a, b) in enumerate(rows):
            self.stats.setItem(i, 0, QTableWidgetItem(a))
            self.stats.setItem(i, 1, QTableWidgetItem(b))
        self.prov.setHtml(provenance_html(grid))

    def _draw(self):
        render_map(self.preview_document(), self._objs.get, self.fig, fit_figure=True)
        self.canvas.draw_idle()

    def resizeEvent(self, ev):  # re-layout margins for the new window size
        super().resizeEvent(ev)
        if hasattr(self, "_objs") and self.isVisible():
            self._draw()

    def _on_move(self, ev):
        if ev.inaxes is None or ev.xdata is None:
            self.cursorMoved.emit(None, None, None)
            return
        z = self.grid.value_at(ev.xdata, ev.ydata)
        self.cursorMoved.emit(ev.xdata, ev.ydata, None if not math.isfinite(z) else z)


def provenance_html(grid: Grid) -> str:
    md = grid.metadata or {}
    out = [f"<h3 style='color:{theme.NAVY}'>{html.escape(grid.name)}</h3>"]
    if md.get("method_title"):
        out.append(f"<p><b>Method:</b> {html.escape(md['method_title'])}</p>")
    elif md.get("source", {}).get("path"):
        out.append(f"<p><b>Imported from:</b> {html.escape(md['source']['path'])}</p>")
    for w in md.get("warnings", []) or []:
        out.append(f"<p style='color:{theme.WARNING}'>⚠ {html.escape(str(w))}</p>")
    out.append("<p style='color:#6A7686'>Results are computed estimates and are not certified "
               "engineering results. See docs/GRIDDING.md for each method's assumptions and "
               "limitations.</p>")
    for key, title in (("parameters", "Parameters (as used)"), ("data_preparation", "Data"),
                       ("blanking", "Blanking"), ("residuals", "Residuals at data points"),
                       ("solver", "Solver"), ("cross_validation", "Cross-validation"),
                       ("source", "Source")):
        if md.get(key):
            out.append(f"<h4>{title}</h4><pre>{html.escape(json.dumps(md[key], indent=2, default=str))}</pre>")
    tail = {k: md[k] for k in ("software", "created", "elapsed_seconds") if k in md}
    if tail:
        out.append(f"<h4>Run</h4><pre>{html.escape(json.dumps(tail, indent=2))}</pre>")
    return "".join(out)
