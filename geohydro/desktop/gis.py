"""Phase 3 desktop features: vector and raster import, vector/image documents,
grid mathematics, terrain analysis, volumes, profiles, point density, GIS map
layers and undo / redo.

A mixin of :class:`~geohydro.desktop.main_window.MainWindow`, like
:mod:`geohydro.desktop.gridmap`. Every command accepts its parameters as a
``values`` dict, so it can run without a dialog (tests, scripting); when
``values`` is None the parameter dialog is shown.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog

from geohydro.engine.data.dataset import utc_now
from geohydro.engine.errors import GeoHydroError
from geohydro.engine.gridding.grid import GridGeometry
from geohydro.engine.mapping.model import ColourReliefLayer, ImageLayer, MapDocument, VectorLayer
from geohydro.project.undo import UndoStack

from . import icons
from .dialogs.gis_dialogs import Field, ParamDialog, ProfileDialog, TextReportDialog
from .documents.gis_documents import ImageDocument, VectorDocument
from .widgets.properties_panel import Prop

NONE = "(none)"
TERRAIN_ACTIONS = ("terrain.slope", "terrain.aspect", "terrain.hillshade", "terrain.curvature")


class GISMixin:
    # ================================================================ wiring
    def _gis_actions(self):
        A = self._act
        A("grid_filter", "Filter Grid…", lambda: self.grid_filter(), "grid",
          tip="Moving-window filters: mean, median, min, max, range, std, high-pass, Gaussian")
        A("grid_blank", "Blank Grid with Polygons…", lambda: self.grid_blank(), "grid",
          tip="Blank grid nodes inside or outside the polygons of a vector layer")
        A("grid_clip", "Clip Grid to Rectangle…", lambda: self.grid_clip(), "grid")
        A("vector_rename", "Rename Vector Layer…", lambda: self.rename_vector())
        A("vector_remove", "Remove Vector Layer…", lambda: self.remove_vector(), "delete")
        A("vector_export", "Export Vector Layer…", lambda: self.export_vector(), "export")
        A("vector_to_points", "Vector Points to Point Dataset…", lambda: self.vector_to_points(),
          "points", tip="Use a point layer (e.g. boreholes) for gridding, post maps and statistics")
        A("image_rename", "Rename Image…", lambda: self.rename_image())
        A("image_remove", "Remove Image…", lambda: self.remove_image(), "delete")
        A("edit.redo", "Redo", lambda: self.redo(), None, "Ctrl+Y", tip="Redo the undone action")

    def _wire_gis(self):
        a = self.actions
        a["edit.undo"].setText("Undo")
        a["edit.undo"].setShortcut("Ctrl+Z")
        a["edit.undo"].triggered.connect(lambda: self.undo())
        a["data.import.vector"].triggered.connect(lambda: self.import_vector())
        a["data.import.raster"].triggered.connect(lambda: self.import_raster())
        a["grid.math"].setText("Grid Calculator…")
        a["grid.math"].triggered.connect(lambda: self.grid_calculator())
        a["map.vector"].setText("Add Vector / Image Layer…")
        a["map.vector"].triggered.connect(lambda: self.add_gis_layer())
        a["map.density"].setText("Point Density…")
        a["map.density"].triggered.connect(lambda: self.point_density())
        for key in TERRAIN_ACTIONS:
            a[key].triggered.connect(lambda _=False, k=key.split(".")[1]: self.terrain(k))
        a["terrain.volume"].triggered.connect(lambda: self.grid_volume())
        a["terrain.profile"].triggered.connect(lambda: self.grid_profile())
        self.undo_stack = UndoStack(self.project)
        self._undo_busy = False
        self._update_undo_actions()

    # ================================================================ undo / redo
    def _checkpoint(self):
        if getattr(self, "_undo_busy", True) or not hasattr(self, "undo_stack"):
            return
        if self.undo_stack.project is not self.project:
            self.undo_stack.reset(self.project)
            return
        self.undo_stack.checkpoint()
        self._update_undo_actions()

    def _reset_undo(self):
        if hasattr(self, "undo_stack"):
            self.undo_stack.reset(self.project)
            self._update_undo_actions()

    def _update_undo_actions(self):
        st = self.undo_stack
        u, r = self.actions["edit.undo"], self.actions["edit.redo"]
        u.setEnabled(st.can_undo)
        r.setEnabled(st.can_redo)
        u.setText(f"Undo {st.undo_label}" if st.can_undo else "Undo")
        r.setText(f"Redo {st.redo_label}" if st.can_redo else "Redo")
        u.setIconText("Undo")
        r.setIconText("Redo")

    def undo(self):
        return self._undo_redo(self.undo_stack.undo, "Undone")

    def redo(self):
        return self._undo_redo(self.undo_stack.redo, "Redone")

    def _undo_redo(self, fn, verb):
        open_ids = list(self.documents)
        active = self.mdi.activeSubWindow()
        active_id = next((k for k, s in self.documents.items() if s is active), None)
        self._undo_busy = True
        try:
            label = fn()
        finally:
            self._undo_busy = False
        if label is None:
            return None
        # documents hold references to the replaced objects: reopen them
        for sub in list(self.documents.values()):
            sub.close()
        self.documents.clear()
        self._map_prop_target = (None, None)
        self.project.dirty = True
        self._refresh_all()
        for ident in open_ids:
            self.open_item(ident)
        if active_id in self.documents:
            self.mdi.setActiveSubWindow(self.documents[active_id])
        self.setWindowModified(True)
        self.console.info(f"{verb}: {label}.")
        self._update_undo_actions()
        return label

    def open_item(self, ident):
        p = self.project
        if ident in p.datasets:
            return self.open_dataset(ident)
        if ident in p.grids:
            return self.open_grid(ident)
        if ident in p.maps:
            return self.open_map(ident)
        if ident in p.vectors:
            return self.open_vector(ident)
        if ident in p.images:
            return self.open_image(ident)
        return None

    # ================================================================ helpers
    def _ask(self, title, fields, values, intro="", note=""):
        """Parameter values: from ``values`` (no dialog) or from a ParamDialog."""
        if values is not None:
            out = {f.key: f.default for f in fields}
            out.update(values)
            return out
        dlg = ParamDialog(title, fields, self, intro, note)
        self._last_param_dialog = dlg
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.values()

    def _grid_choices(self):
        return [(g.id, g.name) for g in self.project.grids.values()]

    def _need_grid(self, title):
        if not self.project.grids:
            self._error(title, GeoHydroError("The project has no grid. Create one with Grid ▸ "
                                             "Grid Data…, open a grid file or import a raster."))
            return False
        return True

    def _default_grid(self):
        return self.selected_item("grid") or next(iter(self.project.grids), None)

    def _add_result_grid(self, g, open_doc=True):
        self.project.add_grid(g)
        for w in (g.metadata or {}).get("warnings", []):
            self.console.warning(f"{g.name}: {w}")
        self.console.success(f"Grid '{g.name}' created ({g.geometry.nx}×{g.geometry.ny}, "
                             f"{g.n_blank:,} blank).")
        self._mark_dirty()
        self._refresh_all()
        if open_doc:
            self.open_grid(g.id)
        return g

    def _run(self, title, fn):
        try:
            return fn()
        except (GeoHydroError, ValueError) as exc:
            self._error(title, exc)
            return None

    # ================================================================ import
    def import_vector(self, path=None, layer=None):
        from geohydro.engine.vector.io import VECTOR_FILTER, list_layers, read_vector
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import vector layer", self._last_dir(),
                                                  VECTOR_FILTER)
            if not path:
                return None
            try:
                layers = list_layers(path)
            except GeoHydroError as exc:
                self._error("Import vector", exc)
                return None
            if len(layers) > 1:
                labels = [f"{n} ({t})" for n, t in layers]
                choice, ok = QInputDialog.getItem(self, "Import vector", "Layer:", labels, 0, False)
                if not ok:
                    return None
                layer = layers[labels.index(choice)][0]
        ds = self._run("Import vector", lambda: read_vector(path, layer=layer))
        if ds is None:
            return None
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.project.add_vector(ds)
        for w in (ds.metadata or {}).get("warnings", []):
            self.console.warning(f"{ds.name}: {w}")
        if not ds.crs:
            self.console.warning(f"'{ds.name}' has no coordinate reference system. Assign one in "
                                 "the Properties panel before overlaying it with other data.")
        types = ", ".join(f"{k} × {v:,}" for k, v in ds.geom_types().items())
        self.console.success(f"Imported vector layer '{ds.name}' from {Path(path).name}: "
                             f"{ds.n_features:,} features ({types}).")
        self._mark_dirty()
        self._refresh_all()
        self.open_vector(ds.id)
        return ds

    def import_raster(self, path=None, values=None):
        from geohydro.engine.raster.io import RASTER_FILTER, RESAMPLING, raster_info, read_raster
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import raster", self._last_dir(),
                                                  RASTER_FILTER)
            if not path:
                return None
        info = self._run("Import raster", lambda: raster_info(path))
        if info is None:
            return None
        crs_opts = [("", "keep the raster's CRS")]
        if self.project.default_crs and self.project.default_crs != info.get("crs"):
            crs_opts.append((self.project.default_crs,
                             f"reproject to project CRS ({self._crs_short(self.project.default_crs)})"))
        fields = [
            Field("kind", "Import as", "choice", info["kind"],
                  [("grid", "Grid (values: elevation, depth, …)"),
                   ("image", "Image (base map: colours only)")]),
            Field("band", "Band (grid)", "int", 1, minimum=1, maximum=max(info["count"], 1)),
            Field("target_crs", "Coordinate system (grid)", "choice", "", crs_opts),
            Field("resampling", "Resampling (if reprojected)", "choice", "bilinear",
                  [(r, r) for r in RESAMPLING]),
        ]
        intro = (f"{Path(path).name}: {info['width']:,} × {info['height']:,} cells, "
                 f"{info['count']} band(s), {', '.join(info['dtypes'])}, "
                 f"CRS {info.get('crs') or 'undefined'}.")
        v = self._ask("Import raster", fields, values, intro,
                      "Grid: each cell centre becomes a grid node. Large rasters are reduced by "
                      "block averaging (recorded in the grid's metadata).")
        if v is None:
            return None
        if v["kind"] == "image":
            item = self._run("Import raster", lambda: read_raster(path, "image"))
        else:
            item = self._run("Import raster", lambda: read_raster(
                path, "grid", band=int(v["band"]), target_crs=v["target_crs"] or None,
                resampling=v["resampling"]))
        if item is None:
            return None
        self.settings.setValue("last_dir", str(Path(path).parent))
        if v["kind"] == "image":
            self.project.add_image(item)
            for w in item.metadata.get("warnings", []):
                self.console.warning(f"{item.name}: {w}")
            self.console.success(f"Imported image '{item.name}' ({item.shape[1]}×{item.shape[0]} "
                                 "pixels) as a base map.")
            self._mark_dirty()
            self._refresh_all()
            self.open_image(item.id)
        else:
            self._add_result_grid(item)
        return item

    # ================================================================ vector / image docs
    def open_vector(self, vector_id):
        ds = self.project.vectors.get(vector_id)
        return self._open_doc(vector_id, ds, VectorDocument, "vector")

    def open_image(self, image_id):
        img = self.project.images.get(image_id)
        return self._open_doc(image_id, img, ImageDocument, "raster")

    def _open_doc(self, ident, item, cls, icon):
        if item is None:
            return None
        sub = self.documents.get(ident)
        if sub is None:
            sub = self.mdi.addSubWindow(cls(item))
            sub.setWindowIcon(icons.icon(icon))
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            sub.destroyed.connect(lambda _=None, i=ident: self.documents.pop(i, None))
            self.documents[ident] = sub
            sub.showMaximized()
        self.mdi.setActiveSubWindow(sub)
        sub.setWindowTitle(item.name)
        return sub.widget()

    def rename_vector(self, vector_id=None, new_name=None):
        return self._rename("vector", vector_id, new_name, self.project.rename_vector)

    def rename_image(self, image_id=None, new_name=None):
        return self._rename("image", image_id, new_name, self.project.rename_image)

    def _rename(self, kind, ident, new_name, fn):
        ident = ident or self.selected_item(kind)
        if not ident:
            return
        item = self.project.item(ident)
        if new_name is None:
            new_name, ok = QInputDialog.getText(self, f"Rename {kind}", "New name:", text=item.name)
            if not ok:
                return
        try:
            fn(ident, new_name)
        except ValueError as exc:
            self._error("Rename", exc)
            return
        self._mark_dirty()
        sub = self.documents.get(ident)
        if sub:
            sub.setWindowTitle(item.name)
        self._refresh_all()

    def remove_vector(self, vector_id=None):
        return self._remove("vector", vector_id, self.project.remove_vector, "vector layer")

    def remove_image(self, image_id=None):
        return self._remove("image", image_id, self.project.remove_image, "image")

    def _remove(self, kind, ident, fn, noun):
        ident = ident or self.selected_item(kind)
        if not ident:
            return
        item = self.project.item(ident)
        users = self.project.maps_using(ident)
        msg = f"Remove {noun} '{item.name}' from the project?"
        if users:
            msg += ("\n\nIt is used by: " + ", ".join(m.name for m in users)
                    + ". Those map layers will show a missing-source warning.")
        msg += "\n\nYou can undo this with Edit ▸ Undo."
        if not self.confirm(f"Remove {noun}", msg):
            return
        sub = self.documents.pop(ident, None)
        if sub:
            sub.close()
        fn(ident)
        self._mark_dirty()
        self.console.info(f"Removed {noun} '{item.name}'.")
        self._refresh_maps()
        self._refresh_all()

    def export_vector(self, vector_id=None, path=None, fmt=None):
        from geohydro.engine.vector.io import WRITE_FORMATS, write_vector
        vid = vector_id or self.selected_item("vector")
        if not vid:
            self._error("Export vector", GeoHydroError("Select a vector layer first."))
            return None
        ds = self.project.vectors[vid]
        overwrite = False
        if path is None:
            flt = ";;".join(label for label, _e, _d in WRITE_FORMATS.values())
            path, chosen = QFileDialog.getSaveFileName(
                self, "Export vector layer", str(Path(self._last_dir()) / f"{ds.name}.gpkg"), flt)
            if not path:
                return None
            fmt = next((k for k, (label, _e, _d) in WRITE_FORMATS.items() if label == chosen), None)
            overwrite = True
        out = self._run("Export vector", lambda: write_vector(ds, path, fmt, overwrite=overwrite))
        if out is None:
            return None
        self.project.outputs.append({"path": str(out), "kind": "vector_file", "vector_id": vid,
                                     "format": fmt, "created": utc_now()})
        self.project.log("vector.export", vector_id=vid, name=ds.name, path=str(out), format=fmt)
        self._mark_dirty()
        self.console.success(f"Vector layer '{ds.name}' written to {out}")
        return out

    def vector_to_points(self, vector_id=None, values=None):
        from geohydro.engine.vector.ops import to_point_dataset
        pts = [v for v in self.project.vectors.values() if v.family == "point"]
        if not pts:
            self._error("Vector to points", GeoHydroError("The project has no point vector layer."))
            return None
        vid = vector_id if vector_id in self.project.vectors else \
            (self.selected_item("vector") if self.selected_item("vector") in
             {v.id for v in pts} else pts[0].id)
        ds = self.project.vectors[vid]
        numeric = [c for c in ds.attributes.columns
                   if pd.api.types.is_numeric_dtype(ds.attributes[c])]
        fields = [Field("vector_id", "Point layer", "choice", vid, [(v.id, v.name) for v in pts]),
                  Field("z_field", "Z values from", "choice", numeric[0] if numeric else "__geom__",
                        [(c, f"field '{c}'") for c in numeric]
                        + [("__geom__", "Z coordinate of 3-D points (none if 2-D)")]),
                  Field("z_units", "Z units", "text", "m"),
                  Field("name", "Dataset name", "text", f"{ds.name} points")]
        v = self._ask("Vector points to point dataset", fields, values)
        if v is None:
            return None
        src = self.project.vectors[v["vector_id"]]
        zf = None if v["z_field"] in ("__geom__", NONE, None) else v["z_field"]
        new = self._run("Vector to points", lambda: to_point_dataset(src, zf, v["name"],
                                                                     v["z_units"]))
        if new is None:
            return None
        self.project.add_dataset(new)
        self.console.success(f"Point dataset '{new.name}' created from '{src.name}': "
                             f"{new.n_points:,} points.")
        self._mark_dirty()
        self._refresh_all()
        self.open_dataset(new.id)
        return new

    # ================================================================ grid math
    def grid_calculator(self, values=None):
        from geohydro.engine.gridmath.calculator import FUNCTIONS, calculate
        if not self._need_grid("Grid calculator"):
            return None
        gc = self._grid_choices()
        d = self._default_grid()
        fields = [Field("expression", "Expression", "text", "A"),
                  Field("A", "Grid A", "choice", d, gc)]
        for letter in "BCD":
            fields.append(Field(letter, f"Grid {letter}", "choice", NONE, [(NONE, NONE)] + gc))
        fields += [Field("resampling", "Resample other grids", "choice", "bilinear",
                         [("bilinear", "bilinear"), ("nearest", "nearest")]),
                   Field("z_units", "Result Z units", "text", ""),
                   Field("name", "Result name", "text", "Calculated grid")]
        note = ("Operators + − * / ** (power), comparisons < <= > >= == !=, & (and), | (or). "
                "Functions: " + ", ".join(sorted(FUNCTIONS)) + ". A node is blank where any "
                "input is blank (use fillblank() to replace blanks). The result has the geometry "
                "of grid A; other grids are resampled to it.")
        v = self._ask("Grid calculator", fields, values,
                      "Example: (A - B) * 100 or where(A > 0, A, 0)", note)
        if v is None:
            return None
        grids = {k: self.project.grids[v[k]] for k in "ABCD"
                 if v.get(k) not in (None, NONE) and v[k] in self.project.grids}
        g = self._run("Grid calculator", lambda: calculate(
            v["expression"], grids, name=v["name"] or None, resampling=v["resampling"],
            z_units=v["z_units"] or None))
        return self._add_result_grid(g) if g is not None else None

    def grid_filter(self, values=None):
        from geohydro.engine.gridmath.filters import FILTERS, apply_filter
        if not self._need_grid("Filter grid"):
            return None
        g0 = self.project.grids.get(self._default_grid())
        fields = [Field("grid_id", "Grid", "choice", g0.id, self._grid_choices()),
                  Field("kind", "Filter", "choice", "mean", [(k, k) for k in FILTERS]),
                  Field("size", "Window (nodes, odd)", "int", 3, minimum=3, maximum=99),
                  Field("sigma", "Gaussian σ (XY units)", "float", 2 * g0.geometry.dx,
                        minimum=0, decimals=6),
                  Field("passes", "Passes", "int", 1, minimum=1, maximum=20),
                  Field("min_valid", "Minimum valid nodes in window", "int", 1, minimum=1,
                        maximum=9801)]
        v = self._ask("Filter grid", fields, values, note=(
            "Blank nodes are ignored and stay blank; windows are truncated at the grid edge."))
        if v is None:
            return None
        grid = self.project.grids[v["grid_id"]]
        g = self._run("Filter grid", lambda: apply_filter(
            grid, v["kind"], size=int(v["size"]), sigma=v["sigma"], passes=int(v["passes"]),
            min_valid=int(v["min_valid"])))
        return self._add_result_grid(g) if g is not None else None

    def grid_blank(self, values=None):
        from geohydro.engine.gridmath.blanking import blank_polygon
        if not self._need_grid("Blank grid"):
            return None
        polys = [(x.id, x.name) for x in self.project.vectors.values() if x.family == "polygon"]
        if not polys:
            self._error("Blank grid", GeoHydroError("Import a polygon vector layer first "
                                                    "(Data ▸ Import Vector)."))
            return None
        fields = [Field("grid_id", "Grid", "choice", self._default_grid(), self._grid_choices()),
                  Field("vector_id", "Polygon layer", "choice", polys[0][0], polys),
                  Field("mode", "Blank nodes", "choice", "outside",
                        [("outside", "outside the polygons (keep the inside)"),
                         ("inside", "inside the polygons")])]
        v = self._ask("Blank grid with polygons", fields, values, note=(
            "Nodes on a polygon boundary count as inside. The layer is reprojected to the grid "
            "CRS when the two differ."))
        if v is None:
            return None
        grid, layer = self.project.grids[v["grid_id"]], self.project.vectors[v["vector_id"]]
        g = self._run("Blank grid", lambda: blank_polygon(grid, layer,
                                                          outside=v["mode"] == "outside"))
        return self._add_result_grid(g) if g is not None else None

    def grid_clip(self, values=None):
        from geohydro.engine.gridmath.blanking import clip_extent
        if not self._need_grid("Clip grid"):
            return None
        g0 = self.project.grids[self._default_grid()]
        geo = g0.geometry
        fields = [Field("grid_id", "Grid", "choice", g0.id, self._grid_choices())]
        for k, val in (("x0", geo.x_min), ("x1", geo.x_max), ("y0", geo.y_min), ("y1", geo.y_max)):
            fields.append(Field(k, {"x0": "X min", "x1": "X max", "y0": "Y min",
                                    "y1": "Y max"}[k], "float", val, decimals=4))
        v = self._ask("Clip grid to rectangle", fields, values)
        if v is None:
            return None
        grid = self.project.grids[v["grid_id"]]
        g = self._run("Clip grid", lambda: clip_extent(grid, v["x0"], v["x1"], v["y0"], v["y1"]))
        return self._add_result_grid(g) if g is not None else None

    # ================================================================ terrain
    def terrain(self, kind, values=None):
        from geohydro.engine.gridmath import terrain as T
        title = kind.capitalize()
        if not self._need_grid(title):
            return None
        fields = [Field("grid_id", "Elevation grid", "choice", self._default_grid(),
                        self._grid_choices())]
        if kind == "slope":
            fields.append(Field("units", "Units", "choice", "degrees",
                                [("degrees", "degrees"), ("percent", "percent rise")]))
        elif kind == "hillshade":
            fields += [Field("azimuth", "Sun azimuth (°)", "float", 315.0, minimum=0,
                             maximum=360, decimals=1),
                       Field("altitude", "Sun altitude (°)", "float", 45.0, minimum=0, maximum=90,
                             decimals=1),
                       Field("z_factor", "Vertical exaggeration", "float", 1.0, minimum=0.001,
                             maximum=1000, decimals=3)]
        elif kind == "curvature":
            fields.append(Field("kind", "Curvature", "choice", "total",
                                [("total", "total (Laplacian)"), ("profile", "profile"),
                                 ("plan", "plan")]))
        note = ("Horn (1981) 3×3 gradient, the method of GDAL, ArcGIS and QGIS. Geographic grids "
                "use metric spacing on the WGS 84 ellipsoid. Nodes next to blanks and at the "
                "grid edge are blank.")
        if kind == "curvature":
            note = "Zevenbergen & Thorne (1987) second derivatives on the 3×3 window, in 1/m."
        v = self._ask(title, fields, values, note=note)
        if v is None:
            return None
        grid = self.project.grids[v["grid_id"]]
        if kind == "slope":
            fn = lambda: T.slope(grid, v["units"])  # noqa: E731
        elif kind == "aspect":
            fn = lambda: T.aspect(grid)  # noqa: E731
        elif kind == "hillshade":
            fn = lambda: T.hillshade(grid, v["azimuth"], v["altitude"], v["z_factor"])  # noqa: E731
        else:
            fn = lambda: T.curvature(grid, v["kind"])  # noqa: E731
        g = self._run(title, fn)
        return self._add_result_grid(g) if g is not None else None

    def grid_volume(self, values=None, show=True):
        from geohydro.engine.gridmath.volume import METHODS, volume, volume_report
        if not self._need_grid("Volume"):
            return None
        gc = self._grid_choices()
        fields = [Field("upper", "Upper surface", "choice", self._default_grid(), gc),
                  Field("lower", "Lower surface", "choice", "__level__",
                        [("__level__", "constant level (below)")] + gc),
                  Field("level", "Constant level (Z units of the upper grid)", "float", 0.0,
                        decimals=4),
                  Field("method", "Integration", "choice", "trapezoidal",
                        [("trapezoidal", "trapezoidal rule"),
                         ("simpson", "Simpson's rule (1/3)"),
                         ("simpson38", "Simpson's 3/8 rule")])]
        v = self._ask("Cut and fill volume", fields, values, note=(
            "Volumes in m³ (Z converted to metres from the grid's Z units). Positive = upper "
            "above lower (cut), negative = fill. See docs/GRID_MATH.md for the equations."))
        if v is None:
            return None
        assert v["method"] in METHODS
        up = self.project.grids[v["upper"]]
        low = float(v["level"]) if v["lower"] == "__level__" else self.project.grids[v["lower"]]
        res = self._run("Volume", lambda: volume(up, low, v["method"]))
        if res is None:
            return None
        text = volume_report(res)
        self.project.log("grid.volume", upper=res["upper"], lower=res["lower"],
                         method=res["method"], cut=res["cut_volume"], fill=res["fill_volume"],
                         net=res["net_volume"], planar_area=res["planar_area"],
                         warnings=res["warnings"])
        self.project.dirty = True
        self.setWindowModified(True)
        for line in text.splitlines():
            self.console.info(line)
        if show and v is not None and values is None:
            TextReportDialog("Volume report", text, self).exec()
        return res

    def grid_profile(self, values=None, show=True):
        from geohydro.engine.gridmath.terrain import profile
        if not self._need_grid("Profile"):
            return None
        lines = [(x.id, x.name) for x in self.project.vectors.values() if x.family == "line"]
        g0 = self.project.grids[self._default_grid()]
        geo = g0.geometry
        ym = 0.5 * (geo.y_min + geo.y_max)
        fields = [Field("grid_id", "Grid", "choice", g0.id, self._grid_choices()),
                  Field("source", "Profile line", "choice", "__typed__",
                        [("__typed__", "vertices typed below")] + lines),
                  Field("feature", "Feature number (line layer)", "int", 1, minimum=1,
                        maximum=10**7),
                  Field("vertices", "Vertices  x y; x y; …", "text",
                        f"{geo.x_min:.6g} {ym:.6g}; {geo.x_max:.6g} {ym:.6g}"),
                  Field("spacing", "Sample spacing (XY units)", "float", None, optional=True)]
        v = self._ask("Profile", fields, values)
        if v is None:
            return None
        grid = self.project.grids[v["grid_id"]]

        def verts():
            if v["source"] == "__typed__":
                pts = [p.split() for p in str(v["vertices"]).replace(",", " ").split(";")
                       if p.strip()]
                return [(float(a), float(b)) for a, b in pts]
            from geohydro.engine.vector.ops import reproject
            layer = self.project.vectors[v["source"]]
            if layer.crs and grid.crs and layer.crs != grid.crs:
                layer = reproject(layer, grid.crs)
            i = int(v["feature"]) - 1
            if not 0 <= i < layer.n_features:
                raise ValueError(f"The layer has {layer.n_features} features.")
            geom = layer.geometry[i]
            if geom.geom_type == "MultiLineString":
                geom = max(geom.geoms, key=lambda gg: gg.length)
            return list(geom.coords)

        prof = self._run("Profile", lambda: profile(grid, [c[:2] for c in verts()],
                                                    v.get("spacing") or None))
        if prof is None:
            return None
        d = prof["distance"]
        self.project.log("grid.profile", grid_id=grid.id, grid_name=grid.name,
                         source=v["source"], length=float(d[-1]), samples=int(d.size))
        self.project.dirty = True
        self.setWindowModified(True)
        self.console.info(f"Profile on '{grid.name}': {d[-1]:,.6g} {prof['distance_units']}, "
                          f"{d.size} samples, {int(np.isnan(prof['z']).sum())} blank.")
        dlg = ProfileDialog(prof, grid.name, f"{grid.z_label} ({grid.z_units})", grid.xy_units,
                            self)
        self._last_profile_dialog = dlg
        if show and values is None:
            dlg.exec()
        return prof

    # ================================================================ density
    def point_density(self, values=None):
        from geohydro.engine.gridmath.density import BANDWIDTH_RULES, KERNELS, kernel_density, \
            point_count
        p = self.project
        sources = [(d.id, f"{d.name} (point dataset)") for d in p.datasets.values()] + \
            [(v.id, f"{v.name} (point layer)") for v in p.vectors.values() if v.family == "point"]
        if not sources:
            self._error("Point density", GeoHydroError("Import point data first."))
            return None
        sel = self.selected_dataset_id() or self.selected_item("vector")
        default = sel if sel in {s for s, _ in sources} else sources[0][0]
        fields = [Field("source", "Points", "choice", default, sources),
                  Field("method", "Method", "choice", "kde",
                        [("kde", "kernel density"), ("count", "point count per cell")]),
                  Field("kernel", "Kernel", "choice", "quartic", [(k, k) for k in KERNELS]),
                  Field("bandwidth", "Bandwidth (XY units)", "float", None, optional=True,
                        tip="Blank = use the rule below"),
                  Field("rule", "Bandwidth rule", "choice", "scott",
                        [(r, r.replace("_", " ")) for r in BANDWIDTH_RULES]),
                  Field("weight", "Weight field", "choice", NONE, [(NONE, "(none: count points)")]),
                  Field("geometry", "Grid", "choice", "__auto__",
                        [("__auto__", "cover the points (nodes on the long side below)")]
                        + [(g.id, f"same as '{g.name}'") for g in p.grids.values()]),
                  Field("n_long", "Nodes on the long side", "int", 150, minimum=10, maximum=4000),
                  Field("per_km2", "Report per km² (else per XY unit²)", "bool", True),
                  Field("make_map", "Create a density map", "bool", True),
                  Field("name", "Result name", "text", "")]
        src0 = p.item(default)
        cols = self._numeric_columns(src0)
        fields[5].options += [(c, c) for c in cols]
        v = self._ask("Point density", fields, values, note=(
            "Density = Σ wᵢ·K(distance/h): expected number of points (or sum of weights) per "
            "unit area. Kernels integrate to 1. No edge correction: density is underestimated "
            "within one bandwidth of the edge of the study area. Needs projected coordinates."))
        if v is None:
            return None
        src = p.item(v["source"])
        pts = self._run("Point density", lambda: self._points_xyw(src, v.get("weight")))
        if pts is None:
            return None
        x, y, w, crs, xy_units = pts
        if v["geometry"] in p.grids:
            geo = p.grids[v["geometry"]].geometry
        else:
            geo = self._run("Point density", lambda: GridGeometry.from_points(
                x[np.isfinite(x)], y[np.isfinite(y)], n_long=int(v["n_long"]), margin=0.05))
            if geo is None:
                return None
        factor = 1e6 if v["per_km2"] and xy_units == "m" else 1.0
        meta_src = {"item_id": src.id, "item_name": src.name, "weight_field": v.get("weight")
                    if v.get("weight") not in (None, NONE) else None}
        name = v["name"] or f"{src.name} – {'density' if v['method'] == 'kde' else 'count'}"
        if v["method"] == "kde":
            h = v["bandwidth"] if v.get("bandwidth") else v["rule"]
            g = self._run("Point density", lambda: kernel_density(
                x, y, geo, h=h, kernel=v["kernel"], weights=w, area_unit_factor=factor, crs=crs,
                xy_units=xy_units, name=name, source=meta_src))
            if g is not None and factor == 1e6:
                g.z_units = g.z_units.replace("unit area", "km²")
        else:
            g = self._run("Point density", lambda: point_count(
                x, y, geo, weights=w, per_area=False, crs=crs, xy_units=xy_units, name=name,
                source=meta_src))
        if g is None:
            return None
        self._add_result_grid(g, open_doc=not v["make_map"])
        if v["make_map"]:
            zmax = float(np.nanmax(g.z)) if np.isfinite(g.z).any() else 0.0
            doc = MapDocument(name=f"{g.name} map", title=g.name,
                              subtitle=g.metadata.get("method_title", ""), crs=g.crs,
                              xy_units=g.xy_units,
                              layers=[ColourReliefLayer(grid_id=g.id, name="Density",
                                                        palette="viridis",
                                                        clear_below=zmax * 1e-6 if zmax > 0
                                                        else None)])
            doc.colorbar["label"] = f"{g.z_label} ({g.z_units})"
            p.add_map(doc)
            self._mark_dirty()
            self._refresh_all()
            self.open_map(doc.id)
        return g

    @staticmethod
    def _numeric_columns(item):
        from geohydro.engine.vector import VectorDataset
        df = item.attributes if isinstance(item, VectorDataset) else item.data
        skip = {"X", "Y"}
        return [c for c in df.columns if c not in skip and pd.api.types.is_numeric_dtype(df[c])]

    @staticmethod
    def _points_xyw(item, weight):
        from geohydro.engine.vector import VectorDataset
        from geohydro.engine.vector.ops import points_to_table
        if isinstance(item, VectorDataset):
            df = points_to_table(item)
        else:
            df = item.data
        if weight not in (None, NONE) and weight not in df:
            raise GeoHydroError(f"'{item.name}' has no field named '{weight}'.")
        w = None if weight in (None, NONE) else pd.to_numeric(df[weight], errors="coerce") \
            .to_numpy(float)
        return (df["X"].to_numpy(float), df["Y"].to_numpy(float), w, item.crs,
                getattr(item, "xy_units", "m"))

    # ================================================================ maps
    def add_gis_layer(self, map_id=None, source_id=None):
        p = self.project
        pool = list(p.vectors.values()) + list(p.images.values())
        if not pool:
            self._error("Add layer", GeoHydroError("Import a vector layer or a raster image first "
                                                   "(Data ▸ Import Vector / Import Raster)."))
            return None
        if source_id is None:
            sel = self.selected_item("vector") or self.selected_item("image")
            if sel:
                source_id = sel
            else:
                names = [o.name for o in pool]
                name, ok = QInputDialog.getItem(self, "Add layer", "Layer:", names, 0, False)
                if not ok:
                    return None
                source_id = pool[names.index(name)].id
        mid = map_id or self.selected_item("map")
        if mid is None:
            src = p.item(source_id)
            doc = MapDocument(name=src.name, title=src.name, crs=src.crs or p.default_crs,
                              xy_units=getattr(src, "xy_units", "m"))
            doc.legend["visible"] = True
            p.add_map(doc)
            mid = doc.id
            self.console.success(f"Map '{doc.name}' created.")
        kind = "image" if source_id in p.images else "vector"
        return self.add_map_layer(mid, kind, source_id)

    def set_map_logo(self, map_id, path=None):
        from geohydro.engine.mapping.gis_render import encode_logo
        doc = self.project.maps[map_id]
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Logo image", self._last_dir(),
                                                  "Images (*.png *.jpg *.jpeg)")
            if not path:
                return None
        data = self._run("Logo", lambda: encode_logo(path))
        if data is None:
            return None
        doc.logo.update(visible=True, data=data, name=Path(path).name)
        self._map_edited(map_id)
        return doc.logo

    def add_map_text(self, map_id, text=None):
        import uuid
        doc = self.project.maps[map_id]
        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, "Add text", "Text:")
            if not ok or not text.strip():
                return None
        box = {"id": uuid.uuid4().hex[:8], "text": text, "x": 0.02, "y": 0.02, "size": 8.0,
               "color": "#222222", "bold": False, "frame": True, "ha": "left"}
        doc.text_boxes.append(box)
        self._map_edited(map_id)
        return box

    def _map_edited(self, map_id):
        self._map_changed(map_id)
        sub = self.documents.get(map_id)
        if sub:
            sub.widget().refresh()
        self._show_map_item_properties(map_id, "")

    # ================================================================ properties
    def _show_vector_properties(self, vid):
        ds = self.project.vectors.get(vid)
        if ds is None:
            return
        b = ds.bounds()
        props = [Prop("Vector layer", "Name", ds.name, "text", "vector.name"),
                 Prop("Vector layer", "Features", f"{ds.n_features:,}"),
                 Prop("Vector layer", "Geometry", ", ".join(ds.geom_types())),
                 Prop("Vector layer", "Fields", ", ".join(ds.attributes.columns) or "—"),
                 Prop("Coordinate system", "Assigned CRS", self._crs_display(ds.crs),
                      self._crs_choices(), "vector.crs",
                      "Assigning a CRS changes metadata only; coordinates are not transformed."),
                 Prop("Extent", "X min / max", "—" if b is None else f"{b[0]:,.6g} / {b[1]:,.6g}"),
                 Prop("Extent", "Y min / max", "—" if b is None else f"{b[2]:,.6g} / {b[3]:,.6g}"),
                 Prop("Source", "File", ds.source.path if ds.source else "—"),
                 Prop("Source", "Format", ds.source.format if ds.source else "—")]
        self.properties.show_properties(f"Vector layer — {ds.name}", props)
        self.status.set_crs(self._crs_short(ds.crs))

    def _show_image_properties(self, iid):
        img = self.project.images.get(iid)
        if img is None:
            return
        x0, x1, y0, y1 = img.extent
        props = [Prop("Image", "Name", img.name, "text", "image.name"),
                 Prop("Image", "Pixels", f"{img.shape[1]:,} × {img.shape[0]:,}"),
                 Prop("Coordinate system", "CRS", self._crs_display(img.crs)),
                 Prop("Extent", "X min / max", f"{x0:,.6g} / {x1:,.6g}"),
                 Prop("Extent", "Y min / max", f"{y0:,.6g} / {y1:,.6g}"),
                 Prop("Source", "File", img.source.path if img.source else "—")]
        self.properties.show_properties(f"Image — {img.name}", props)
        self.status.set_crs(self._crs_short(img.crs))

    def _gis_property_edited(self, key, value) -> bool:
        from geohydro.engine.crs import crs_storage_string, resolve_crs
        if key.startswith("vector."):
            vid = self.selected_item("vector")
            if not vid:
                return True
            if key == "vector.name":
                self.rename_vector(vid, value)
            elif key == "vector.crs":
                try:
                    info = resolve_crs(value)
                except GeoHydroError as exc:
                    self._error("Invalid value", exc)
                    return True
                ds = self.project.vectors[vid]
                old, ds.crs = ds.crs, crs_storage_string(info)
                ds.xy_units = "deg" if info and info.is_geographic else "m"
                self.project.log("vector.assign_crs", vector_id=vid, old=old, new=ds.crs,
                                 note="metadata only; coordinates not transformed")
                self.console.info(f"CRS of '{ds.name}' set to "
                                  f"{info.display if info else 'undefined'} (metadata only).")
                self._mark_dirty()
                self._refresh_all()
            return True
        if key.startswith("image."):
            iid = self.selected_item("image")
            if iid and key == "image.name":
                self.rename_image(iid, value)
            return True
        return False

    def _gis_context(self, name, ident) -> bool:
        handlers = {
            "vector.open": lambda: self.open_vector(ident),
            "vector.map": lambda: self.add_gis_layer(None, ident),
            "vector.points": lambda: self.vector_to_points(ident),
            "vector.rename": lambda: self.rename_vector(ident),
            "vector.export": lambda: self.export_vector(ident),
            "vector.remove": lambda: self.remove_vector(ident),
            "image.open": lambda: self.open_image(ident),
            "image.map": lambda: self.add_gis_layer(None, ident),
            "image.rename": lambda: self.rename_image(ident),
            "image.remove": lambda: self.remove_image(ident),
            "grid.slope": lambda: self.terrain("slope", {"grid_id": ident}),
            "grid.hillshade": lambda: self.terrain("hillshade", {"grid_id": ident}),
        }
        fn = handlers.get(name)
        if fn is None:
            return False
        fn()
        return True
