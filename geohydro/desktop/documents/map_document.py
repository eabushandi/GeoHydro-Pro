"""Map layout view: page preview, layer list and draggable map elements.

The page is rendered by the engine (``geohydro.engine.mapping.render``) at
the real page size, so what is shown is what is exported. Map-level and
layer properties are edited in the Properties panel (see
:func:`map_props`, :func:`layer_props`, :func:`apply_edit`).
"""

from __future__ import annotations

import math

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.offsetbox import DraggableOffsetBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout,
                               QWidget)

from geohydro.engine.errors import MapError
from geohydro.engine.mapping.levels import PALETTES, LevelSpec
from geohydro.engine.mapping.model import (LAYER_TITLES, PAGE_SIZES_MM, POSITIONS, ColourReliefLayer,
                                           ContourLayer, FilledContourLayer, ImageLayer,
                                           MapDocument, PostLayer, VectorLayer, layer_source)
from geohydro.engine.mapping.render import render_map

from .. import icons, theme
from ..widgets.properties_panel import Prop

YES_NO = ["Yes", "No"]


class _Drag(DraggableOffsetBox):
    """Mouse dragging for an AnchoredOffsetbox (scale bar, north arrow).

    ``AnchoredOffsetbox`` computes its position from its anchor and ignores
    ``set_offset``, so the stock DraggableOffsetBox cannot move it. While
    dragging, the box is re-anchored by its centre at the pointer position
    (display pixels); on release the owner converts that to axes fractions.
    """

    def __init__(self, ref_artist, offsetbox, on_done):
        super().__init__(ref_artist, offsetbox, use_blit=False)
        self._on_done = on_done
        self._c0 = (0.0, 0.0)

    def save_offset(self):
        fig = self.offsetbox.get_figure(root=True)
        bb = self.offsetbox.get_window_extent(fig._get_renderer())
        self._c0 = ((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)

    def update_offset(self, dx, dy):
        self.offsetbox.loc = 10  # "center"
        self.offsetbox.set_bbox_to_anchor((self._c0[0] + dx, self._c0[1] + dy))

    def finalize_offset(self):
        super().finalize_offset()
        self._on_done(self)


class MapView(QWidget):
    changed = Signal(str)  # map id (document edited in this view)
    layerSelected = Signal(str, str)  # map id, layer id ("" = the map itself)
    cursorMoved = Signal(object, object, object)
    exportRequested = Signal(str)
    addLayerRequested = Signal(str, str)  # map id, layer type
    logoRequested = Signal(str)  # map id
    textRequested = Signal(str)  # map id

    def __init__(self, doc: MapDocument, project, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.project = project
        self.info = None
        self._drags = []
        self.zoom = 0.0  # 0 = fit to window

        self.fig = Figure(facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setStyleSheet("border:1px solid #B8C2CF;")
        self.nav = NavigationToolbar2QT(self.canvas, self)
        self.nav.setStyleSheet("QToolBar{border:none;background:white;}")
        page_host = QWidget()
        page_host.setStyleSheet("background:#8A96A6;")
        ph = QVBoxLayout(page_host)
        ph.setContentsMargins(18, 18, 18, 18)
        ph.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(page_host)

        tb = QHBoxLayout()
        tb.setContentsMargins(4, 2, 4, 2)
        self.btn_page = QPushButton("Page && Map Elements")
        self.btn_page.setIcon(icons.icon("layout"))
        self.btn_add = QToolButton()
        self.btn_add.setText("Add Layer")
        self.btn_add.setIcon(icons.icon("map"))
        self.btn_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self)
        for t, title in LAYER_TITLES.items():
            a = QAction(title, m)
            a.triggered.connect(lambda _=False, t=t: self.addLayerRequested.emit(self.doc.id, t))
            m.addAction(a)
        self.btn_add.setMenu(m)
        self.btn_insert = QToolButton()
        self.btn_insert.setText("Insert")
        self.btn_insert.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        im = QMenu(self)
        for title, slot in (("Text Box…", lambda: self.textRequested.emit(self.doc.id)),
                            ("Logo Image…", lambda: self.logoRequested.emit(self.doc.id))):
            a = QAction(title, im)
            a.triggered.connect(slot)
            im.addAction(a)
        self.btn_insert.setMenu(im)
        self.btn_fit = QPushButton("Fit Page")
        self.btn_100 = QPushButton("100 %")
        self.btn_extent = QPushButton("Keep View Extent")
        self.btn_extent.setToolTip("Use the current zoom / pan of the map frame as the map extent")
        self.btn_reset_extent = QPushButton("Full Extent")
        self.btn_export = QPushButton("Export…")
        self.btn_export.setIcon(icons.icon("export"))
        for w in (self.btn_page, self.btn_add, self.btn_insert, self.btn_fit, self.btn_100, self.btn_extent,
                  self.btn_reset_extent, self.btn_export):
            tb.addWidget(w)
        tb.addStretch(1)
        self.hint = QLabel("Drag the scale bar or north arrow to move them.")
        self.hint.setStyleSheet(f"color:{theme.MUTED}")
        tb.addWidget(self.hint)

        # layers panel
        self.layers = QListWidget()
        self.layers.setToolTip("Top of the list is drawn on top. Tick to show / hide.")
        lb = QHBoxLayout()
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        self.btn_remove = QPushButton("Remove")
        for b in (self.btn_up, self.btn_down, self.btn_remove):
            lb.addWidget(b)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(4, 4, 4, 4)
        title = QLabel("Layers")
        title.setStyleSheet(f"font-weight:600;color:{theme.NAVY}")
        sl.addWidget(title)
        sl.addWidget(self.layers, 1)
        sl.addLayout(lb)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color:{theme.WARNING}")
        sl.addWidget(self.warn)
        side.setMinimumWidth(200)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        ll.addLayout(tb)
        ll.addWidget(self.nav)
        ll.addWidget(self.scroll, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setSizes([900, 220])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)

        self.btn_page.clicked.connect(lambda: self.layerSelected.emit(self.doc.id, ""))
        self.btn_fit.clicked.connect(lambda: self.set_zoom(0.0))
        self.btn_100.clicked.connect(lambda: self.set_zoom(1.0))
        self.btn_extent.clicked.connect(self.keep_extent)
        self.btn_reset_extent.clicked.connect(self.reset_extent)
        self.btn_export.clicked.connect(lambda: self.exportRequested.emit(self.doc.id))
        self.btn_up.clicked.connect(lambda: self._move(+1))
        self.btn_down.clicked.connect(lambda: self._move(-1))
        self.btn_remove.clicked.connect(self._remove)
        self.layers.itemChanged.connect(self._item_changed)
        self.layers.currentItemChanged.connect(self._current_changed)
        self.canvas.mpl_connect("motion_notify_event", self._on_move)
        self.refresh()

    @property
    def map_id(self) -> str:
        return self.doc.id

    # ------------------------------------------------------------ rendering
    def resolve(self, item_id):
        return self.project.item(item_id)

    def _page_dpi(self) -> float:
        w_in, h_in = self.doc.page_size_inches()
        if self.zoom > 0:
            return 96.0 * self.zoom
        vp = self.scroll.viewport().size()
        avail_w, avail_h = max(vp.width() - 40, 200), max(vp.height() - 40, 150)
        return max(min(avail_w / w_in, avail_h / h_in), 20.0)

    def set_zoom(self, z: float):
        self.zoom = z
        self.refresh()

    def refresh(self, *, keep_selection: bool = True):
        sel = self.current_layer_id() if keep_selection else None
        self._fill_layers(sel)
        w_in, h_in = self.doc.page_size_inches()
        dpi = self._page_dpi()
        ratio = self.canvas.devicePixelRatioF() or 1.0
        self.fig.set_dpi(dpi * ratio)
        self.canvas.setFixedSize(int(w_in * dpi), int(h_in * dpi))
        self.fig.set_size_inches(w_in, h_in, forward=False)
        self.info = None
        try:
            _, self.info = render_map(self.doc, self.resolve, self.fig)
        except MapError as exc:
            self.fig.clear()
            self.fig.text(0.5, 0.5, f"Map cannot be drawn: {exc}", ha="center")
        self._make_draggable()
        self.canvas.draw_idle()
        warns = self.info.warnings if self.info else []
        self.warn.setText("\n".join(f"⚠ {w}" for w in warns))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.zoom == 0.0 and self.isVisible():
            self.refresh()

    def _make_draggable(self):
        self._drags = []
        if not self.info:
            return
        for key in ("scale_bar", "north_arrow"):
            box = self.info.artists.get(key)
            if box is not None:
                self._drags.append(_Drag(box, box, lambda d, k=key: self._dropped(k, d)))

    def _dropped(self, key, drag):
        box = drag.offsetbox
        ax = self.info.ax
        bb = box.get_window_extent(self.canvas.get_renderer())
        cx, cy = ax.transAxes.inverted().transform(((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2))
        el = getattr(self.doc, key)
        el.xy = (round(float(cx), 4), round(float(cy), 4))
        self.changed.emit(self.doc.id)
        self.refresh()

    # ------------------------------------------------------------ extent
    def keep_extent(self):
        if not self.info or self.info.ax is None:
            return
        x0, x1 = self.info.ax.get_xlim()
        y0, y1 = self.info.ax.get_ylim()
        self.doc.extent = [float(x0), float(x1), float(y0), float(y1)]
        self.changed.emit(self.doc.id)
        self.refresh()

    def reset_extent(self):
        self.doc.extent = None
        self.changed.emit(self.doc.id)
        self.refresh()

    # ------------------------------------------------------------ layers
    def _fill_layers(self, select_id=None):
        self.layers.blockSignals(True)
        self.layers.clear()
        for lyr in reversed(self.doc.layers):  # top layer first
            src = self.project.item(layer_source(lyr))
            it = QListWidgetItem(f"{lyr.name}  —  {LAYER_TITLES[lyr.type]}")
            it.setData(Qt.ItemDataRole.UserRole, lyr.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if lyr.visible else Qt.CheckState.Unchecked)
            it.setToolTip(f"Source: {src.name if src else 'missing'}")
            it.setIcon(icons.icon({"contour": "contour", "filled_contour": "filled",
                                   "colour_relief": "relief", "post": "points",
                                   "vector": "vector", "image": "raster"}[lyr.type]))
            self.layers.addItem(it)
            if lyr.id == select_id:
                self.layers.setCurrentItem(it)
        self.layers.blockSignals(False)

    def current_layer_id(self) -> str | None:
        it = self.layers.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def select_layer(self, layer_id: str):
        for i in range(self.layers.count()):
            if self.layers.item(i).data(Qt.ItemDataRole.UserRole) == layer_id:
                self.layers.setCurrentRow(i)
                return

    def _current_changed(self, cur, _prev):
        if cur is not None:
            self.layerSelected.emit(self.doc.id, cur.data(Qt.ItemDataRole.UserRole))

    def _item_changed(self, it):
        lyr = self.doc.layer(it.data(Qt.ItemDataRole.UserRole))
        vis = it.checkState() == Qt.CheckState.Checked
        if lyr.visible != vis:
            lyr.visible = vis
            self.changed.emit(self.doc.id)
            self.refresh()

    def _move(self, step):
        lid = self.current_layer_id()
        if lid:
            self.doc.move_layer(lid, step)
            self.changed.emit(self.doc.id)
            self.refresh()

    def _remove(self):
        lid = self.current_layer_id()
        if lid:
            self.doc.layers = [lyr for lyr in self.doc.layers if lyr.id != lid]
            self.changed.emit(self.doc.id)
            self.refresh(keep_selection=False)
            self.layerSelected.emit(self.doc.id, "")

    def _on_move(self, ev):
        if ev.inaxes is None or self.info is None or ev.inaxes is not self.info.ax:
            self.cursorMoved.emit(None, None, None)
            return
        z = None
        for lyr in reversed(self.doc.layers):
            g = self.project.grids.get(getattr(lyr, "grid_id", ""))
            if lyr.visible and g is not None:
                v = g.value_at(ev.xdata, ev.ydata)
                if math.isfinite(v):
                    z = v
                    break
        self.cursorMoved.emit(ev.xdata, ev.ydata, z)


# ---------------------------------------------------------------- properties
def _yn(v):
    return "Yes" if v else "No"


def map_props(doc: MapDocument) -> list[Prop]:
    return [
        Prop("Map", "Name", doc.name, "text", "map.name"),
        Prop("Map", "Title", doc.title, "text", "map.title"),
        Prop("Map", "Subtitle", doc.subtitle, "text", "map.subtitle"),
        Prop("Map", "CRS", doc.crs or "undefined"),
        Prop("Page", "Size", doc.page, list(PAGE_SIZES_MM), "map.page"),
        Prop("Page", "Orientation", doc.orientation, ["landscape", "portrait"], "map.orientation"),
        Prop("Page", "Margins (mm)", doc.margins_mm, "text", "map.margins_mm"),
        Prop("Page", "Extent", "full extent of layers" if not doc.extent else
             ", ".join(f"{v:,.6g}" for v in doc.extent)),
        Prop("Colour scale", "Show", _yn(doc.colorbar.get("visible", True)), YES_NO,
             "map.colorbar.visible"),
        Prop("Colour scale", "Label", doc.colorbar.get("label", ""), "text", "map.colorbar.label",
             "Blank = the grid's Z label and units"),
        Prop("Scale bar", "Show", _yn(doc.scale_bar.visible), YES_NO, "map.scale_bar.visible"),
        Prop("Scale bar", "Position", "dragged" if doc.scale_bar.xy else doc.scale_bar.position,
             POSITIONS, "map.scale_bar.position"),
        Prop("North arrow", "Show", _yn(doc.north_arrow.visible), YES_NO, "map.north_arrow.visible"),
        Prop("North arrow", "Position", "dragged" if doc.north_arrow.xy else
             doc.north_arrow.position, POSITIONS, "map.north_arrow.position",
             "Points to true north, computed from the map CRS (grid north if no CRS)."),
        Prop("Coordinate grid", "Show tick labels", _yn(doc.graticule.get("visible", True)), YES_NO,
             "map.graticule.visible"),
        Prop("Coordinate grid", "Grid lines", _yn(doc.graticule.get("lines", True)), YES_NO,
             "map.graticule.lines"),
        Prop("Coordinate grid", "Latitude / longitude", _yn(doc.graticule.get("geographic")),
             YES_NO, "map.graticule.geographic",
             "Draw a geographic graticule (degrees and minutes) on a projected map"),
        Prop("Coordinate grid", "Lat/lon interval (°)",
             "" if doc.graticule.get("interval_deg") is None else doc.graticule["interval_deg"],
             "text", "map.graticule.interval_deg", "Blank = automatic"),
        Prop("Legend", "Show", _yn(doc.legend.get("visible")), YES_NO, "map.legend.visible"),
        Prop("Legend", "Title", doc.legend.get("title", ""), "text", "map.legend.title"),
        Prop("Legend", "Position", doc.legend.get("position", "lower right"), POSITIONS,
             "map.legend.position"),
        Prop("Legend", "Text size (pt)", doc.legend.get("size", 8.0), "text", "map.legend.size"),
        Prop("Inset (location map)", "Show", _yn(doc.inset.get("visible")), YES_NO,
             "map.inset.visible", "Small overview map with the main map extent outlined"),
        Prop("Inset (location map)", "Position", doc.inset.get("position", "lower right"),
             POSITIONS, "map.inset.position"),
        Prop("Inset (location map)", "Size (fraction of frame)", doc.inset.get("size", 0.28),
             "text", "map.inset.size"),
        Prop("Logo", "Show", _yn(doc.logo.get("visible")) if doc.logo.get("data") else
             "No logo (Insert ▸ Logo Image…)", YES_NO if doc.logo.get("data") else None,
             "map.logo.visible" if doc.logo.get("data") else ""),
        Prop("Logo", "Position", doc.logo.get("position", "upper left"), POSITIONS,
             "map.logo.position"),
        Prop("Logo", "Width (mm)", doc.logo.get("width_mm", 25.0), "text", "map.logo.width_mm"),
    ] + [p for i, tb in enumerate(doc.text_boxes, 1) for p in (
        Prop(f"Text box {i}", "Text", tb.get("text", ""), "text", f"map.text.{tb['id']}.text",
             "Clear the text to delete the box"),
        Prop(f"Text box {i}", "X (0–1 of frame)", tb.get("x", 0.02), "text",
             f"map.text.{tb['id']}.x"),
        Prop(f"Text box {i}", "Y (0–1 of frame)", tb.get("y", 0.02), "text",
             f"map.text.{tb['id']}.y"),
        Prop(f"Text box {i}", "Size (pt)", tb.get("size", 8.0), "text",
             f"map.text.{tb['id']}.size"),
        Prop(f"Text box {i}", "Frame", _yn(tb.get("frame", True)), YES_NO,
             f"map.text.{tb['id']}.frame"))]


def layer_props(lyr, project) -> list[Prop]:
    src = project.item(layer_source(lyr))
    out = [Prop("Layer", "Name", lyr.name, "text", "layer.name"),
           Prop("Layer", "Type", LAYER_TITLES[lyr.type]),
           Prop("Layer", "Source", src.name if src else "missing"),
           Prop("Layer", "Visible", _yn(lyr.visible), YES_NO, "layer.visible"),
           Prop("Layer", "Opacity (0–1)", lyr.opacity, "text", "layer.opacity")]
    pal = list(PALETTES)
    if isinstance(lyr, (ContourLayer, FilledContourLayer)):
        lv = lyr.levels
        out += [Prop("Levels", "Mode", lv.mode, ["auto", "interval", "list"], "layer.levels.mode"),
                Prop("Levels", "Approx. count (auto)", lv.count, "text", "layer.levels.count"),
                Prop("Levels", "Interval", "" if lv.interval is None else lv.interval, "text",
                     "layer.levels.interval"),
                Prop("Levels", "First level", "" if lv.first is None else lv.first, "text",
                     "layer.levels.first", "Blank = automatic"),
                Prop("Levels", "Last level", "" if lv.last is None else lv.last, "text",
                     "layer.levels.last", "Blank = automatic"),
                Prop("Levels", "Level list", ", ".join(f"{v:g}" for v in (lv.values or [])),
                     "text", "layer.levels.values", "Comma-separated values (mode 'list')")]
    if isinstance(lyr, ContourLayer):
        out += [Prop("Lines", "Colour", lyr.line_color, "text", "layer.line_color"),
                Prop("Lines", "Width (pt)", lyr.line_width, "text", "layer.line_width"),
                Prop("Lines", "Major every n-th level (0 = none)", lyr.major_every, "text",
                     "layer.major_every"),
                Prop("Lines", "Major width (pt)", lyr.major_width, "text", "layer.major_width"),
                Prop("Lines", "Colour by level", _yn(lyr.color_by_level), YES_NO,
                     "layer.color_by_level"),
                Prop("Lines", "Palette", lyr.palette, pal, "layer.palette"),
                Prop("Labels", "Label contours", _yn(lyr.labels), YES_NO, "layer.labels"),
                Prop("Labels", "Decimals", "" if lyr.label_decimals is None else lyr.label_decimals,
                     "text", "layer.label_decimals", "Blank = automatic"),
                Prop("Labels", "Size (pt)", lyr.label_size, "text", "layer.label_size")]
    if isinstance(lyr, FilledContourLayer):
        out += [Prop("Colours", "Palette", lyr.palette, pal, "layer.palette"),
                Prop("Colours", "Reverse", _yn(lyr.reverse), YES_NO, "layer.reverse"),
                Prop("Colours", "Colour scale", _yn(lyr.show_colorbar), YES_NO,
                     "layer.show_colorbar")]
    if isinstance(lyr, ColourReliefLayer):
        out += [Prop("Colours", "Palette", lyr.palette, pal, "layer.palette"),
                Prop("Colours", "Reverse", _yn(lyr.reverse), YES_NO, "layer.reverse"),
                Prop("Colours", "Minimum Z", "" if lyr.z_min is None else lyr.z_min, "text",
                     "layer.z_min", "Blank = grid minimum"),
                Prop("Colours", "Maximum Z", "" if lyr.z_max is None else lyr.z_max, "text",
                     "layer.z_max", "Blank = grid maximum"),
                Prop("Colours", "Smooth display", _yn(lyr.smooth), YES_NO, "layer.smooth"),
                Prop("Colours", "Transparent below", "" if lyr.clear_below is None else
                     lyr.clear_below, "text", "layer.clear_below",
                     "Values below this are not drawn (blank = draw all)"),
                Prop("Colours", "Colour scale", _yn(lyr.show_colorbar), YES_NO,
                     "layer.show_colorbar")]
    if isinstance(lyr, PostLayer):
        cols = ["(none)", "Z"] + (list(src.attribute_columns) if src is not None else [])
        out += [Prop("Symbols", "Marker", lyr.marker, ["o", "s", "^", "v", "D", "+", "x", "*"],
                     "layer.marker"),
                Prop("Symbols", "Size (pt²)", lyr.size, "text", "layer.size"),
                Prop("Symbols", "Fill colour", lyr.face_color, "text", "layer.face_color"),
                Prop("Symbols", "Edge colour", lyr.edge_color, "text", "layer.edge_color"),
                Prop("Symbols", "Colour by Z", _yn(lyr.color_by_z), YES_NO, "layer.color_by_z"),
                Prop("Symbols", "Palette", lyr.palette, pal, "layer.palette"),
                Prop("Labels", "Label column", lyr.label_column or "(none)", cols,
                     "layer.label_column"),
                Prop("Labels", "Decimals", lyr.label_decimals, "text", "layer.label_decimals"),
                Prop("Labels", "Size (pt)", lyr.label_size, "text", "layer.label_size")]
    if isinstance(lyr, VectorLayer):
        fields = list(src.attributes.columns) if src is not None else []
        fam = src.family if src is not None else "?"
        out += [Prop("Layer", "Geometry", fam),
                Prop("Symbology", "Style", lyr.symbology, ["single", "categorized", "graduated"],
                     "layer.symbology",
                     "single colour, one colour per category, or classes of a numeric field"),
                Prop("Symbology", "Field", lyr.field or "(none)", ["(none)"] + fields,
                     "layer.field"),
                Prop("Symbology", "Palette", lyr.palette, list(PALETTES) + ["tab10", "Set2",
                                                                            "Paired"],
                     "layer.palette"),
                Prop("Symbology", "Reverse palette", _yn(lyr.reverse), YES_NO, "layer.reverse"),
                Prop("Symbology", "Classes (graduated)", lyr.classes, "text", "layer.classes"),
                Prop("Symbology", "Classification", lyr.classification,
                     ["quantile", "equal_interval"], "layer.classification"),
                Prop("Style", "Fill colour", lyr.face_color, "text", "layer.face_color"),
                Prop("Style", "Outline / line colour", lyr.edge_color, "text", "layer.edge_color"),
                Prop("Style", "Line width (pt)", lyr.line_width, "text", "layer.line_width"),
                Prop("Style", "Fill polygons", _yn(lyr.fill), YES_NO, "layer.fill"),
                Prop("Style", "Marker", lyr.marker, ["o", "s", "^", "v", "D", "+", "x", "*"],
                     "layer.marker"),
                Prop("Style", "Marker size (pt²)", lyr.marker_size, "text", "layer.marker_size"),
                Prop("Labels", "Label field", lyr.label_field or "(none)", ["(none)"] + fields,
                     "layer.label_field"),
                Prop("Labels", "Size (pt)", lyr.label_size, "text", "layer.label_size"),
                Prop("Legend", "Show in legend", _yn(lyr.show_in_legend), YES_NO,
                     "layer.show_in_legend"),
                Prop("Legend", "Show in inset map", _yn(lyr.show_in_inset), YES_NO,
                     "layer.show_in_inset")]
    if isinstance(lyr, ImageLayer):
        out += [Prop("Image", "Pixels", f"{src.shape[1]} × {src.shape[0]}" if src else "—"),
                Prop("Image", "Show in inset map", _yn(lyr.show_in_inset), YES_NO,
                     "layer.show_in_inset")]
    return out


def _num(value, kind=float, allow_blank=False, lo=None, hi=None):
    s = str(value).strip()
    if s == "" and allow_blank:
        return None
    try:
        v = kind(float(s)) if kind is int else kind(s)
    except ValueError as exc:
        raise MapError(f"'{value}' is not a valid number.") from exc
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise MapError(f"{v} is outside the allowed range [{lo}, {hi}].")
    return v


def _colour(value):
    from matplotlib.colors import is_color_like
    v = str(value).strip()
    if not is_color_like(v):
        raise MapError(f"'{value}' is not a colour (use a name such as 'black' or #RRGGBB).")
    return v


def apply_edit(doc: MapDocument, layer_id: str | None, key: str, value: str) -> None:
    """Validate and apply one property edit (raises MapError on bad input)."""
    yes = str(value) == "Yes"
    if key.startswith("map."):
        f = key[4:]
        if f in ("title", "subtitle"):
            setattr(doc, f, value)
        elif f == "name":
            if not value.strip():
                raise MapError("Map name cannot be empty.")
            doc.name = value.strip()
        elif f == "page":
            if value not in PAGE_SIZES_MM:
                raise MapError(f"Unknown page size '{value}'.")
            doc.page = value
        elif f == "orientation":
            if value not in ("landscape", "portrait"):
                raise MapError("Orientation must be landscape or portrait.")
            doc.orientation = value
        elif f == "margins_mm":
            doc.margins_mm = _num(value, float, lo=0, hi=60)
        elif f == "colorbar.visible":
            doc.colorbar["visible"] = yes
        elif f == "colorbar.label":
            doc.colorbar["label"] = value
        elif f in ("scale_bar.visible", "north_arrow.visible"):
            getattr(doc, f.split(".")[0]).visible = yes
        elif f in ("scale_bar.position", "north_arrow.position"):
            if value not in POSITIONS:
                raise MapError(f"Position must be one of: {', '.join(POSITIONS)}.")
            el = getattr(doc, f.split(".")[0])
            el.position, el.xy = value, None
        elif f in ("graticule.visible", "graticule.lines", "graticule.geographic"):
            doc.graticule[f.split(".")[1]] = yes
        elif f == "graticule.interval_deg":
            doc.graticule["interval_deg"] = _num(value, float, allow_blank=True, lo=1 / 3600,
                                                 hi=30)
        elif f in ("legend.visible", "inset.visible", "logo.visible"):
            getattr(doc, f.split(".")[0])["visible"] = yes
        elif f in ("legend.position", "inset.position", "logo.position"):
            if value not in POSITIONS:
                raise MapError(f"Position must be one of: {', '.join(POSITIONS)}.")
            d = getattr(doc, f.split(".")[0])
            d["position"] = value
            if "xy" in d:
                d["xy"] = None
        elif f == "legend.title":
            doc.legend["title"] = value
        elif f == "legend.size":
            doc.legend["size"] = _num(value, float, lo=4, hi=30)
        elif f == "inset.size":
            doc.inset["size"] = _num(value, float, lo=0.1, hi=0.6)
        elif f == "logo.width_mm":
            doc.logo["width_mm"] = _num(value, float, lo=3, hi=200)
        elif f.startswith("text."):
            _, tid, attr = f.split(".", 2)
            tb = next((t for t in doc.text_boxes if t.get("id") == tid), None)
            if tb is None:
                raise MapError("That text box no longer exists.")
            if attr == "text":
                if not str(value).strip():
                    doc.text_boxes.remove(tb)
                else:
                    tb["text"] = value
            elif attr in ("x", "y"):
                tb[attr] = _num(value, float, lo=0, hi=1)
            elif attr == "size":
                tb["size"] = _num(value, float, lo=3, hi=72)
            elif attr == "frame":
                tb["frame"] = yes
            else:
                raise MapError(f"Unknown text box property {attr}.")
        else:
            raise MapError(f"Unknown map property {key}.")
        return
    if not key.startswith("layer.") or not layer_id:
        raise MapError(f"Unknown property {key}.")
    lyr = doc.layer(layer_id)
    f = key[6:]
    if f.startswith("levels."):
        lv: LevelSpec = lyr.levels
        g = f[7:]
        if g == "mode":
            if value not in ("auto", "interval", "list"):
                raise MapError("Level mode must be auto, interval or list.")
            lv.mode = value
            if value == "interval" and not lv.interval:
                lv.interval = None
        elif g == "count":
            lv.count = _num(value, int, lo=2, hi=200)
        elif g == "interval":
            v = _num(value, float, allow_blank=True)
            if v is not None and v <= 0:
                raise MapError("Contour interval must be positive.")
            lv.interval = v
            if v is not None:
                lv.mode = "interval"
        elif g in ("first", "last"):
            setattr(lv, g, _num(value, float, allow_blank=True))
        elif g == "values":
            parts = [p for p in str(value).replace(";", ",").split(",") if p.strip()]
            lv.values = [_num(p, float) for p in parts]
            if lv.values:
                lv.mode = "list"
        return
    bools = {"visible", "labels", "reverse", "show_colorbar", "smooth", "color_by_z",
             "color_by_level", "fill", "show_in_legend", "show_in_inset"}
    if f in bools:
        setattr(lyr, f, yes)
    elif f == "name":
        if not value.strip():
            raise MapError("Layer name cannot be empty.")
        lyr.name = value.strip()
    elif f == "opacity":
        lyr.opacity = _num(value, float, lo=0, hi=1)
    elif f in ("line_width", "major_width", "label_size", "size", "marker_size"):
        setattr(lyr, f, _num(value, float, lo=0, hi=200))
    elif f == "major_every":
        lyr.major_every = _num(value, int, lo=0, hi=100)
    elif f == "label_decimals":
        v = _num(value, int, allow_blank=isinstance(lyr, ContourLayer), lo=0, hi=12)
        lyr.label_decimals = v
    elif f in ("line_color", "face_color", "edge_color"):
        setattr(lyr, f, _colour(value))
    elif f == "palette":
        if value not in PALETTES and not (isinstance(lyr, VectorLayer)
                                          and value in ("tab10", "Set2", "Paired")):
            raise MapError(f"Unknown palette '{value}'.")
        lyr.palette = value
    elif f == "symbology":
        if value not in ("single", "categorized", "graduated"):
            raise MapError("Style must be single, categorized or graduated.")
        if value != "single" and not lyr.field:
            raise MapError("Choose a field first.")
        lyr.symbology = value
    elif f == "field":
        lyr.field = None if value in ("", "(none)") else value
        if lyr.field is None:
            lyr.symbology = "single"
    elif f == "label_field":
        lyr.label_field = None if value in ("", "(none)") else value
    elif f == "classes":
        lyr.classes = _num(value, int, lo=2, hi=12)
    elif f == "classification":
        if value not in ("quantile", "equal_interval"):
            raise MapError("Classification must be quantile or equal_interval.")
        lyr.classification = value
    elif f == "clear_below":
        lyr.clear_below = _num(value, float, allow_blank=True)
    elif f in ("z_min", "z_max"):
        setattr(lyr, f, _num(value, float, allow_blank=True))
    elif f == "marker":
        lyr.marker = value
    elif f == "label_column":
        lyr.label_column = None if value in ("", "(none)") else value
    else:
        raise MapError(f"Unknown layer property {key}.")
