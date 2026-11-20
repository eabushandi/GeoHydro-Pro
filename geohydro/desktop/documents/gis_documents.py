"""Documents for vector layers (preview, attribute table, information) and
raster images (preview, information)."""

from __future__ import annotations

import html
import json

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QTableView, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from geohydro.engine.errors import GeoHydroError
from geohydro.engine.mapping.model import ElementPos, ImageLayer, MapDocument, VectorLayer
from geohydro.engine.mapping.render import render_map

from ..widgets.pandas_model import DataFrameModel


def _preview_doc(item, layer) -> MapDocument:
    return MapDocument(name=item.name, title=item.name, crs=item.crs,
                       xy_units=getattr(item, "xy_units", "m"), layers=[layer],
                       scale_bar=ElementPos(True, "lower left"),
                       north_arrow=ElementPos(False), colorbar={"visible": False, "label": ""},
                       margins_mm=6.0)


class _PreviewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(7, 5), facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        tb = NavigationToolbar2QT(self.canvas, self)
        tb.setStyleSheet("QToolBar{border:none;background:white;}")
        lay.addWidget(tb)
        lay.addWidget(self.canvas, 1)
        self.warnings: list[str] = []

    def draw(self, item, layer):
        self.fig.clear()
        try:
            _, info = render_map(_preview_doc(item, layer), {item.id: item}.get, self.fig)
            self.warnings = info.warnings
        except GeoHydroError as exc:
            self.fig.text(0.5, 0.5, f"Cannot draw: {exc}", ha="center")
            self.warnings = [str(exc)]
        self.canvas.draw_idle()


def _info_html(item, rows: list[tuple[str, str]]) -> str:
    md = item.metadata or {}
    out = [f"<h3>{html.escape(item.name)}</h3><table cellpadding='3'>"]
    for k, v in rows:
        out.append(f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(str(v))}</td></tr>")
    out.append("</table>")
    warns = md.get("warnings") or []
    if warns:
        out.append("<h4>Warnings</h4><ul>" + "".join(f"<li>{html.escape(w)}</li>" for w in warns)
                   + "</ul>")
    rest = {k: v for k, v in md.items() if k != "warnings"}
    if rest:
        out.append("<h4>Metadata</h4><pre>" + html.escape(json.dumps(rest, indent=2, default=str))
                   + "</pre>")
    return "".join(out)


class VectorDocument(QWidget):
    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tabs)
        self.preview = _PreviewTab()
        self.tabs.addTab(self.preview, "Preview")
        self.table = QTableView()
        self.model = DataFrameModel()
        self.table.setModel(self.model)
        self.tabs.addTab(self.table, "Attributes")
        self.info = QTextBrowser()
        self.tabs.addTab(self.info, "Information")
        self.refresh(ds)

    @property
    def item_id(self):
        return self.ds.id

    def refresh(self, ds):
        self.ds = ds
        self.preview.draw(ds, VectorLayer(vector_id=ds.id, name=ds.name, show_in_legend=False))
        self.model.set_frame(ds.attributes)
        b = ds.bounds()
        src = ds.source
        rows = [("Features", f"{ds.n_features:,}"),
                ("Geometry", ", ".join(f"{k} × {v:,}" for k, v in ds.geom_types().items())),
                ("Fields", ", ".join(ds.attributes.columns) or "—"),
                ("CRS", ds.crs or "undefined"),
                ("Extent", "—" if b is None else
                 f"X {b[0]:,.6g} … {b[1]:,.6g}, Y {b[2]:,.6g} … {b[3]:,.6g}"),
                ("Source", src.path if src else "created in the project"),
                ("Format", src.format if src else "—")]
        self.info.setHtml(_info_html(ds, rows))


class ImageDocument(QWidget):
    def __init__(self, img, parent=None):
        super().__init__(parent)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tabs)
        self.preview = _PreviewTab()
        self.tabs.addTab(self.preview, "Preview")
        self.info = QTextBrowser()
        self.tabs.addTab(self.info, "Information")
        self.refresh(img)

    @property
    def item_id(self):
        return self.img.id

    def refresh(self, img):
        self.img = img
        self.preview.draw(img, ImageLayer(image_id=img.id, name=img.name))
        x0, x1, y0, y1 = img.extent
        px, py = img.pixel_size
        rows = [("Size", f"{img.shape[1]:,} × {img.shape[0]:,} pixels"),
                ("Pixel size", f"{px:.6g} × {py:.6g}"),
                ("Extent", f"X {x0:,.6g} … {x1:,.6g}, Y {y0:,.6g} … {y1:,.6g}"),
                ("CRS", img.crs or "undefined"),
                ("Source", img.source.path if img.source else "—")]
        self.info.setHtml(_info_html(img, rows))
