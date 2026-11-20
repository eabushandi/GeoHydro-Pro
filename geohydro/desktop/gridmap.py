"""Phase 2 desktop features: gridding, grid files, variograms, maps and map export.

Implemented as a mixin of :class:`~geohydro.desktop.main_window.MainWindow` so
that the main window stays focused on the shell, project and data handling.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog

from geohydro.engine.data.dataset import utc_now
from geohydro.engine.errors import GeoHydroError, MapError
from geohydro.engine.gridding.gridder import GriddingRequest, grid_data
from geohydro.engine.gridding.io import GRID_FORMATS, read_grid, write_grid
from geohydro.engine.mapping.levels import LevelSpec
from geohydro.engine.mapping.model import (LAYER_TITLES, ColourReliefLayer, ContourLayer,
                                           FilledContourLayer, ImageLayer, MapDocument, PostLayer,
                                           VectorLayer)
from geohydro.engine.mapping.render import EXPORT_FORMATS, export_map

from . import icons
from .dialogs.grid_dialog import GridDataDialog
from .dialogs.variogram_dialog import VariogramDialog
from .documents.gis_documents import ImageDocument, VectorDocument
from .documents.grid_document import GridDocument
from .documents.map_document import MapView, apply_edit, layer_props, map_props
from .widgets.properties_panel import Prop

METHOD_FOR_ACTION = {"grid.idw": "idw", "grid.ok": "ordinary_kriging",
                     "grid.uk": "universal_kriging", "grid.mincurv": "min_curvature",
                     "grid.natnb": "natural_neighbour", "grid.nearest": "nearest",
                     "grid.tin": "tin", "grid.rbf": "rbf"}
MAP_FOR_ACTION = {"map.contour": "contour", "map.filled": "filled_contour",
                  "map.relief": "colour_relief", "map.post": "post"}
GRID_FILTER = ";;".join(f"{label}" for label, _ in GRID_FORMATS.values())
MAP_FILTER = ("PNG image (*.png);;TIFF image (*.tif);;JPEG image (*.jpg);;"
              "SVG vector graphic (*.svg);;PDF document (*.pdf)")


class GridMapMixin:
    # ================================================================ wiring
    def _wire_phase2(self):
        a = self.actions
        for key, method in METHOD_FOR_ACTION.items():
            a[key].triggered.connect(lambda _=False, m=method: self.grid_data_dialog(m))
        a["grid.variogram"].triggered.connect(lambda: self.show_variogram())
        a["grid.crossval"].triggered.connect(lambda: self.grid_data_dialog(None, cross_validate=True))
        for key, kind in MAP_FOR_ACTION.items():
            a[key].triggered.connect(lambda _=False, k=kind: self.new_map(k))
        a["map.layout"].triggered.connect(self.open_map_layout)
        a["map.export"].triggered.connect(lambda: self.export_map())
        self.explorer.itemActivated.connect(self._activate_item)

    def _phase2_actions(self):
        A = self._act
        A("grid_data", "Grid Data…", lambda: self.grid_data_dialog(None), "grid", "Ctrl+G",
          tip="Interpolate a point dataset onto a regular grid")
        A("grid_open", "Open Grid File…", lambda: self.open_grid_file(), "open",
          tip="Add a Surfer GRD (DSAA/DSBB/DSRB) or ESRI ASCII grid to the project")
        A("grid_export", "Export Grid File…", lambda: self.export_grid(), "export",
          tip="Write the selected grid as Surfer GRD, ESRI ASCII or an XYZ table")
        A("grid_rename", "Rename Grid…", lambda: self.rename_grid())
        A("grid_remove", "Remove Grid…", lambda: self.remove_grid(), "delete")
        A("map_rename", "Rename Map…", lambda: self.rename_map())
        A("map_remove", "Remove Map…", lambda: self.remove_map(), "delete")

    # ================================================================ selection
    def selected_item(self, kind: str) -> str | None:
        sub = self.mdi.activeSubWindow()
        w = sub.widget() if sub else None
        if kind == "grid" and isinstance(w, GridDocument):
            return w.grid_id
        if kind == "map" and isinstance(w, MapView):
            return w.map_id
        if kind in ("vector", "image") and isinstance(w, (VectorDocument, ImageDocument)):
            store = self.project.vectors if kind == "vector" else self.project.images
            if w.item_id in store:
                return w.item_id
        it = self.explorer.currentItem()
        if it is not None and it.data(0, Qt.ItemDataRole.UserRole) == kind:
            return it.data(0, Qt.ItemDataRole.UserRole + 1)
        return None

    def _activate_item(self, kind, ident):
        if kind == "grid":
            self.open_grid(ident)
        elif kind == "map":
            self.open_map(ident)
        elif kind == "vector":
            self.open_vector(ident)
        elif kind == "image":
            self.open_image(ident)

    def _phase2_context(self, name, ident) -> bool:
        handlers = {
            "grid": lambda: self.grid_data_dialog(None, dataset_id=ident),
            "post": lambda: self.new_map("post", ident),
            "grid.open": lambda: self.open_grid(ident),
            "grid.contour": lambda: self.new_map("contour", ident),
            "grid.filled": lambda: self.new_map("filled_contour", ident),
            "grid.relief": lambda: self.new_map("colour_relief", ident),
            "grid.rename": lambda: self.rename_grid(ident),
            "grid.export": lambda: self.export_grid(ident),
            "grid.remove": lambda: self.remove_grid(ident),
            "map.open": lambda: self.open_map(ident),
            "map.export": lambda: self.export_map(ident),
            "map.rename": lambda: self.rename_map(ident),
            "map.remove": lambda: self.remove_map(ident),
        }
        fn = handlers.get(name)
        if fn is None:
            return False
        fn()
        return True

    # ================================================================ gridding
    def grid_data_dialog(self, method=None, dataset_id=None, cross_validate=False):
        if not any(d.has_z for d in self.project.datasets.values()):
            self._error("Grid Data", GeoHydroError(
                "The project has no point dataset with Z values. Import data first."))
            return None
        did = dataset_id or self.selected_dataset_id()
        if method is None:
            method = self.settings.value("grid/last_method", "idw")
        dlg = GridDataDialog(self.project, self, did, method, runner=self.tasks)
        if cross_validate:
            dlg.setWindowTitle("Grid Data — Cross-Validation")
            dlg.btn_cv.setFocus()
        self._last_grid_dialog = dlg
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        self.settings.setValue("grid/last_method", dlg.method)
        cv = dlg.cv_result.to_dict() if dlg.cv_result is not None and \
            dlg.cv_result.method == dlg.method else None
        return self.run_gridding(dlg.dataset.id, dlg.request(), dlg.out_name.text().strip(),
                                 cv=cv)

    def run_gridding(self, dataset_id: str, request: GriddingRequest, name: str,
                     cv: dict | None = None, synchronous: bool = False):
        ds = self.project.datasets[dataset_id]
        d = ds.data
        x, y, z = (d["X"].to_numpy(float), d["Y"].to_numpy(float), d["Z"].to_numpy(float))
        source = {"dataset_id": ds.id, "dataset_name": ds.name, "z_column": ds.z_label}
        kw = dict(name=name, crs=ds.crs, xy_units=ds.xy_units, z_units=ds.z_units,
                  z_label=ds.z_label, source=source)
        self.console.info(f"Gridding '{ds.name}' with {request.method} on "
                          f"{request.geometry.nx}×{request.geometry.ny} nodes…")
        self.status.busy(True, "Gridding…")

        def done(res):
            self.status.busy(False, "Ready")
            self._gridding_done(res, cv)

        def failed(exc, tb=""):
            self.status.busy(False, "Gridding failed")
            self._error("Gridding failed", exc)

        if synchronous:
            try:
                res = grid_data(x, y, z, request, **kw)
            except GeoHydroError as exc:
                failed(exc)
                return None
            done(res)
            return res
        self.tasks.start(lambda: grid_data(x, y, z, request, **kw), done, failed)
        return None

    def _gridding_done(self, res, cv=None):
        g = res.grid
        if cv:
            g.metadata["cross_validation"] = cv
        self.project.add_grid(g)
        for w in res.warnings:
            self.console.warning(f"{g.name}: {w}")
        r = res.residuals
        self.console.success(
            f"Grid '{g.name}' created: {g.geometry.nx}×{g.geometry.ny} nodes, "
            f"{g.n_blank:,} blank, {g.metadata.get('elapsed_seconds', 0):.2f} s. "
            + (f"Residual RMSE at data {r['rmse']:.4g}." if r.get("rmse") is not None else ""))
        if cv:
            self.console.info(f"Cross-validation RMSE {cv['metrics'].get('rmse', float('nan')):.4g}, "
                              f"R² {cv['metrics'].get('r_squared', float('nan')):.4f} "
                              "(stored with the grid).")
        if res.variance is not None:
            self.project.add_grid(res.variance)
            self.console.info(f"Kriging variance grid '{res.variance.name}' created.")
        self._mark_dirty()
        self._refresh_all()
        self.open_grid(g.id)

    def show_variogram(self, dataset_id=None):
        did = dataset_id or self.selected_dataset_id() or next(
            (d.id for d in self.project.datasets.values() if d.has_z), None)
        if not did:
            self._error("Variogram", GeoHydroError("Import a point dataset with Z values first."))
            return None
        dlg = VariogramDialog(self.project.datasets[did], self)
        dlg.buttons.button(dlg.buttons.StandardButton.Ok).setText("Use for Kriging…")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        model = dlg.current_model()
        self.console.info(f"Variogram model chosen: {model.describe()}")
        g = GridDataDialog(self.project, self, did, "ordinary_kriging", runner=self.tasks)
        g.set_variogram(model)
        if g.exec() == QDialog.DialogCode.Accepted:
            return self.run_gridding(did, g.request(), g.out_name.text().strip())
        return None

    # ================================================================ grid docs & files
    def open_grid(self, grid_id: str):
        g = self.project.grids.get(grid_id)
        if g is None:
            return None
        sub = self.documents.get(grid_id)
        if sub is None:
            src = (g.metadata or {}).get("source", {}).get("dataset_id")
            doc = GridDocument(g, self.project.datasets.get(src))
            doc.cursorMoved.connect(self.status.set_cursor)
            sub = self.mdi.addSubWindow(doc)
            sub.setWindowIcon(icons.icon("grid"))
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            sub.destroyed.connect(lambda _=None, i=grid_id: self.documents.pop(i, None))
            self.documents[grid_id] = sub
            sub.showMaximized()
        self.mdi.setActiveSubWindow(sub)
        sub.setWindowTitle(g.name)
        return sub.widget()

    def open_grid_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open grid file", self._last_dir(),
                "Grid files (*.grd *.asc *.tif *.tiff);;All files (*)")
            if not path:
                return None
        try:
            g = read_grid(path)
        except GeoHydroError as exc:
            self._error("Cannot read grid", exc)
            return None
        if not g.crs:  # Surfer / ESRI ASCII grids carry no CRS; GeoTIFF does
            g.crs = self.project.default_crs
            g.metadata.setdefault("warnings", []).append(
                "Imported grid: the CRS was set to the project default (grid files carry no "
                "CRS)." if g.crs else "Imported grid: no CRS assigned (grid files carry no CRS).")
        self.project.add_grid(g)
        self.console.success(f"Grid '{g.name}' read from {Path(path).name}: "
                             f"{g.geometry.nx}×{g.geometry.ny} nodes, {g.n_blank:,} blank.")
        self._mark_dirty()
        self._refresh_all()
        self.open_grid(g.id)
        return g

    def export_grid(self, grid_id=None, path=None, fmt=None):
        gid = grid_id or self.selected_item("grid")
        if not gid:
            self._error("Export grid", GeoHydroError("Select a grid first."))
            return None
        g = self.project.grids[gid]
        if path is None:
            path, flt = QFileDialog.getSaveFileName(self, "Export grid",
                                                    str(Path(self._last_dir()) / f"{g.name}.grd"),
                                                    GRID_FILTER)
            if not path:
                return None
            fmt = next((k for k, (label, _e) in GRID_FORMATS.items() if label == flt), None)
            overwrite = True  # the native dialog asked
        else:
            overwrite = False
        try:
            out = write_grid(g, path, fmt, overwrite=overwrite)
        except GeoHydroError as exc:
            self._error("Export grid", exc)
            return None
        self.project.outputs.append({"path": str(out), "kind": "grid_file", "grid_id": gid,
                                     "format": fmt, "created": utc_now()})
        self.project.log("grid.export", grid_id=gid, name=g.name, path=str(out), format=fmt)
        self._mark_dirty()
        self.console.success(f"Grid '{g.name}' written to {out}")
        return out

    def rename_grid(self, grid_id=None, new_name=None):
        gid = grid_id or self.selected_item("grid")
        if not gid:
            return
        g = self.project.grids[gid]
        if new_name is None:
            new_name, ok = QInputDialog.getText(self, "Rename grid", "New name:", text=g.name)
            if not ok:
                return
        try:
            self.project.rename_grid(gid, new_name)
        except ValueError as exc:
            self._error("Rename", exc)
            return
        self._mark_dirty()
        sub = self.documents.get(gid)
        if sub:
            sub.setWindowTitle(g.name)
        self._refresh_all()

    def remove_grid(self, grid_id=None):
        gid = grid_id or self.selected_item("grid")
        if not gid:
            return
        g = self.project.grids[gid]
        users = self.project.maps_using(gid)
        msg = f"Remove grid '{g.name}' from the project?"
        if users:
            msg += ("\n\nIt is used by: " + ", ".join(m.name for m in users)
                    + ". Those map layers will show a missing-source warning.")
        if not self.confirm("Remove grid", msg):
            return
        sub = self.documents.pop(gid, None)
        if sub:
            sub.close()
        self.project.remove_grid(gid)
        self._mark_dirty()
        self.console.info(f"Removed grid '{g.name}'.")
        self._refresh_maps()
        self._refresh_all()

    # ================================================================ maps
    def new_map(self, kind: str, source_id: str | None = None):
        if kind == "post":
            sid = source_id or self.selected_dataset_id() or next(iter(self.project.datasets), None)
            src = self.project.datasets.get(sid) if sid else None
            if src is None:
                self._error("New map", GeoHydroError("Import a point dataset first."))
                return None
        else:
            sid = source_id or self.selected_item("grid") or next(iter(self.project.grids), None)
            src = self.project.grids.get(sid) if sid else None
            if src is None:
                self._error("New map", GeoHydroError(
                    "Create a grid first (Grid ▸ Grid Data…) or open a grid file."))
                return None
        layers = []
        if kind == "colour_relief":
            layers = [ColourReliefLayer(grid_id=src.id, name="Colour relief"),
                      ContourLayer(grid_id=src.id, name="Contours", line_width=0.4,
                                   major_width=0.9)]
        elif kind == "filled_contour":
            layers = [FilledContourLayer(grid_id=src.id, name="Filled contours"),
                      ContourLayer(grid_id=src.id, name="Contour lines", line_width=0.4,
                                   major_every=0, labels=True)]
        elif kind == "contour":
            layers = [ContourLayer(grid_id=src.id, name="Contours")]
        elif kind == "post":
            layers = [PostLayer(dataset_id=src.id, name="Data points", color_by_z=src.has_z)]
        else:
            raise MapError(f"Unknown map type {kind}")
        if kind != "post":
            ds_id = (src.metadata or {}).get("source", {}).get("dataset_id")
            if ds_id in self.project.datasets:
                layers.append(PostLayer(dataset_id=ds_id, name="Data points", size=6,
                                        face_color="#111111", visible=False))
        doc = MapDocument(name=f"{src.name} – {LAYER_TITLES[kind]}", title=src.name,
                          subtitle=self._map_subtitle(src), crs=src.crs, xy_units=src.xy_units,
                          layers=layers)
        self.project.add_map(doc)
        self._mark_dirty()
        self.console.success(f"Map '{doc.name}' created.")
        self._refresh_all()
        self.open_map(doc.id)
        return doc

    def _map_subtitle(self, src):
        md = getattr(src, "metadata", None) or {}
        parts = []
        if md.get("method_title"):
            parts.append(md["method_title"])
        if src.crs:
            parts.append(self._crs_short(src.crs) or src.crs)
        return " · ".join(parts)

    def open_map(self, map_id: str):
        doc = self.project.maps.get(map_id)
        if doc is None:
            return None
        sub = self.documents.get(map_id)
        if sub is None:
            view = MapView(doc, self.project)
            view.changed.connect(self._map_changed)
            view.layerSelected.connect(self._show_map_item_properties)
            view.cursorMoved.connect(self.status.set_cursor)
            view.exportRequested.connect(lambda mid: self.export_map(mid))
            view.addLayerRequested.connect(self.add_map_layer)
            view.logoRequested.connect(lambda mid: self.set_map_logo(mid))
            view.textRequested.connect(lambda mid: self.add_map_text(mid))
            sub = self.mdi.addSubWindow(view)
            sub.setWindowIcon(icons.icon("map"))
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            sub.destroyed.connect(lambda _=None, i=map_id: self.documents.pop(i, None))
            self.documents[map_id] = sub
            sub.showMaximized()
        self.mdi.setActiveSubWindow(sub)
        sub.setWindowTitle(doc.name)
        return sub.widget()

    def open_map_layout(self):
        mid = self.selected_item("map") or next(iter(self.project.maps), None)
        if mid:
            return self.open_map(mid)
        return self.new_map("colour_relief")

    def add_map_layer(self, map_id: str, kind: str, source_id: str | None = None):
        doc = self.project.maps[map_id]
        pool = {"post": self.project.datasets, "vector": self.project.vectors,
                "image": self.project.images}.get(kind, self.project.grids)
        if not pool:
            self._error("Add layer", GeoHydroError("No suitable data source in the project."))
            return None
        if source_id is None:
            names = [o.name for o in pool.values()]
            name, ok = QInputDialog.getItem(self, "Add layer", "Data source:", names, 0, False)
            if not ok:
                return None
            source_id = next(o.id for o in pool.values() if o.name == name)
        cls = {"contour": ContourLayer, "filled_contour": FilledContourLayer,
               "colour_relief": ColourReliefLayer, "post": PostLayer, "vector": VectorLayer,
               "image": ImageLayer}[kind]
        key = {"post": "dataset_id", "vector": "vector_id", "image": "image_id"}.get(kind,
                                                                                  "grid_id")
        name = pool[source_id].name if kind in ("vector", "image") else \
            f"{pool[source_id].name} – {LAYER_TITLES[kind]}"
        lyr = cls(name=name, **{key: source_id})
        if kind == "vector":
            fam = pool[source_id].family
            lyr.fill = fam == "polygon"
        if kind == "image":  # base maps go to the bottom
            doc.layers.insert(0, lyr)
        if kind == "contour":
            lyr.levels = LevelSpec("auto", 10)
        if kind != "image":
            doc.layers.append(lyr)
        self._map_changed(map_id)
        self._refresh_all()
        view = self.documents.get(map_id)
        if view is None and kind in ("vector", "image"):
            self.open_map(map_id)
            view = self.documents.get(map_id)
        if view:
            view.widget().refresh()
            view.widget().select_layer(lyr.id)
        return lyr

    def _map_changed(self, map_id):
        self._mark_dirty()
        doc = self.project.maps.get(map_id)
        if doc is not None:
            sub = self.documents.get(map_id)
            if sub:
                sub.setWindowTitle(doc.name)

    def _refresh_maps(self):
        for mid in self.project.maps:
            sub = self.documents.get(mid)
            if sub:
                sub.widget().refresh()

    def export_map(self, map_id=None, path=None, dpi=None):
        mid = map_id or self.selected_item("map")
        if not mid:
            self._error("Export map", GeoHydroError("Open or select a map first."))
            return None
        doc = self.project.maps[mid]
        overwrite = False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export map",
                                                  str(Path(self._last_dir()) / f"{doc.name}.png"),
                                                  MAP_FILTER)
            if not path:
                return None
            overwrite = True
            ext = Path(path).suffix.lower().lstrip(".")
            if ext in ("png", "jpg", "jpeg") and dpi is None:
                dpi, ok = QInputDialog.getInt(self, "Export resolution", "Resolution (dpi):",
                                              300, 72, 1200, 50)
                if not ok:
                    return None
        dpi = dpi or 300
        try:
            out, info = export_map(doc, self.project.item, path, dpi=dpi, overwrite=overwrite)
        except GeoHydroError as exc:
            self._error("Export map", exc)
            return None
        for w in info.warnings:
            self.console.warning(f"{doc.name}: {w}")
        fmt = EXPORT_FORMATS[Path(out).suffix.lower().lstrip('.')]
        self.project.outputs.append({"path": str(out), "kind": "map", "map_id": mid,
                                     "format": fmt, "dpi": dpi, "created": utc_now()})
        self.project.log("map.export", map_id=mid, name=doc.name, path=str(out), dpi=dpi)
        self._mark_dirty()
        self.console.success(f"Map '{doc.name}' exported to {out} ({fmt}, {dpi} dpi).")
        return out

    def rename_map(self, map_id=None, new_name=None):
        mid = map_id or self.selected_item("map")
        if not mid:
            return
        doc = self.project.maps[mid]
        if new_name is None:
            new_name, ok = QInputDialog.getText(self, "Rename map", "New name:", text=doc.name)
            if not ok:
                return
        try:
            self.project.rename_map(mid, new_name)
        except ValueError as exc:
            self._error("Rename", exc)
            return
        self._map_changed(mid)
        self._refresh_all()

    def remove_map(self, map_id=None):
        mid = map_id or self.selected_item("map")
        if not mid:
            return
        doc = self.project.maps[mid]
        if not self.confirm("Remove map", f"Remove map '{doc.name}' from the project?"):
            return
        sub = self.documents.pop(mid, None)
        if sub:
            sub.close()
        self.project.remove_map(mid)
        self._mark_dirty()
        self.console.info(f"Removed map '{doc.name}'.")
        self._refresh_all()

    # ================================================================ properties
    def _show_grid_properties(self, gid):
        g = self.project.grids.get(gid)
        if g is None:
            return
        s = g.statistics()
        md = g.metadata or {}
        res = md.get("residuals") or {}
        cv = (md.get("cross_validation") or {}).get("metrics") or {}

        def f(v):
            return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:,.6g}"

        props = [
            Prop("Grid", "Name", g.name, "text", "grid.name"),
            Prop("Grid", "Method", md.get("method_title", "imported file")),
            Prop("Grid", "Source", (md.get("source") or {}).get("dataset_name")
                 or (md.get("source") or {}).get("path", "—")),
            Prop("Geometry", "Columns × rows", f"{s['nx']} × {s['ny']}"),
            Prop("Geometry", "Spacing X / Y", f"{f(s['dx'])} / {f(s['dy'])}"),
            Prop("Geometry", "X min / max", f"{f(s['x_min'])} / {f(s['x_max'])}"),
            Prop("Geometry", "Y min / max", f"{f(s['y_min'])} / {f(s['y_max'])}"),
            Prop("Geometry", "Blank nodes", f"{s['blank_nodes']:,}"),
            Prop("Coordinate system", "CRS", self._crs_display(g.crs)),
            Prop("Z", "Label", g.z_label),
            Prop("Z", "Units", g.z_units),
            Prop("Z", "Min / Max", f"{f(s.get('z_min'))} / {f(s.get('z_max'))}"),
            Prop("Z", "Mean", f(s.get("z_mean"))),
            Prop("Quality", "Residual RMSE at data", f(res.get("rmse"))),
            Prop("Quality", "Cross-validation RMSE", f(cv.get("rmse")) if cv else "not run"),
            Prop("Quality", "Cross-validation R²", f(cv.get("r_squared")) if cv else "not run"),
        ]
        self.properties.show_properties(f"Grid — {g.name}", props)
        self.status.set_crs(self._crs_short(g.crs))
        self.status.set_grid(f"{s['dx']:,.4g} × {s['dy']:,.4g} ({s['nx']}×{s['ny']})")

    def _show_map_item_properties(self, map_id, layer_id=""):
        doc = self.project.maps.get(map_id)
        if doc is None:
            return
        self._map_prop_target = (map_id, layer_id or None)
        if layer_id:
            lyr = doc.layer(layer_id)
            self.properties.show_properties(f"Layer — {lyr.name}", layer_props(lyr, self.project))
        else:
            self.properties.show_properties(f"Map — {doc.name}", map_props(doc))

    def _phase2_property_edited(self, key, value) -> bool:
        if key.startswith("grid."):
            gid = self.selected_item("grid")
            if gid and key == "grid.name":
                self.rename_grid(gid, value)
            return True
        if key.startswith(("map.", "layer.")):
            map_id, layer_id = getattr(self, "_map_prop_target", (None, None))
            doc = self.project.maps.get(map_id) if map_id else None
            if doc is None:
                return True
            try:
                if key == "map.name":
                    self.project.rename_map(map_id, value)
                else:
                    apply_edit(doc, layer_id, key, value)
            except (MapError, ValueError) as exc:
                self._error("Invalid value", exc)
            self._map_changed(map_id)
            sub = self.documents.get(map_id)
            if sub:
                sub.widget().refresh()
            self._show_map_item_properties(map_id, layer_id or "")
            if key in ("map.name", "layer.name"):
                self.explorer.populate(self.project)
            return True
        return False
