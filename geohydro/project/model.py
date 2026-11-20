"""In-memory project model (UI independent)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from geohydro import __version__
from geohydro.engine.data.dataset import PointDataset, utc_now
from geohydro.engine.gridding.grid import Grid
from geohydro.engine.mapping.model import MapDocument
from geohydro.engine.raster.image import RasterImage
from geohydro.engine.vector.dataset import VectorDataset


@dataclass
class HistoryEntry:
    timestamp: str
    action: str
    details: dict = field(default_factory=dict)
    app_version: str = __version__


@dataclass
class Project:
    name: str = "Untitled Project"
    description: str = ""
    author: str = ""
    default_crs: str | None = None
    units: str = "m"  # project default length unit (metric)
    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: str = field(default_factory=utc_now)
    modified: str = field(default_factory=utc_now)
    datasets: dict[str, PointDataset] = field(default_factory=dict)
    grids: dict[str, Grid] = field(default_factory=dict)
    maps: dict[str, MapDocument] = field(default_factory=dict)
    vectors: dict[str, VectorDataset] = field(default_factory=dict)  # format v3
    images: dict[str, RasterImage] = field(default_factory=dict)  # format v3 (base maps)
    history: list[HistoryEntry] = field(default_factory=list)
    settings: dict = field(default_factory=dict)  # visualisation / UI settings
    outputs: list[dict] = field(default_factory=list)  # {path, kind, created, description}

    # runtime-only state (not persisted as such)
    path: str | None = None
    revision: int = 0  # revision number of the file this was loaded from / saved to
    dirty: bool = False

    def log(self, action: str, **details) -> HistoryEntry:
        entry = HistoryEntry(utc_now(), action, details)
        self.history.append(entry)
        self.dirty = True
        return entry

    # ---- datasets ---------------------------------------------------------
    def add_dataset(self, ds: PointDataset) -> PointDataset:
        existing = {d.name for d in self.datasets.values()}
        base, i = ds.name, 2
        while ds.name in existing:
            ds.name = f"{base} ({i})"
            i += 1
        self.datasets[ds.id] = ds
        self.log(
            "dataset.import",
            dataset_id=ds.id,
            name=ds.name,
            source=ds.source.path,
            source_sha256=ds.source.sha256,
            format=ds.source.format,
            read_options=ds.source.read_options,
            import_settings=ds.import_settings,
            qc={k: ds.qc_report.get(k) for k in ("source_rows", "imported_rows", "excluded_rows",
                                                  "duplicate_groups", "duplicates_removed")},
        )
        return ds

    def remove_dataset(self, dataset_id: str) -> PointDataset:
        ds = self.datasets.pop(dataset_id)
        self.log("dataset.remove", dataset_id=dataset_id, name=ds.name)
        return ds

    def rename_dataset(self, dataset_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Dataset name cannot be empty")
        if any(d.name == new_name and d.id != dataset_id for d in self.datasets.values()):
            raise ValueError(f"A dataset named {new_name!r} already exists")
        ds = self.datasets[dataset_id]
        old = ds.name
        if old == new_name:
            return
        ds.name = new_name
        self.log("dataset.rename", dataset_id=dataset_id, old=old, new=new_name)

    def assign_crs(self, dataset_id: str, crs: str | None, is_geographic: bool) -> None:
        ds = self.datasets[dataset_id]
        old = ds.crs
        ds.crs = crs
        ds.xy_units = "deg" if is_geographic else ("m" if ds.xy_units == "deg" else ds.xy_units)
        self.log("dataset.assign_crs", dataset_id=dataset_id, old=old, new=crs,
                 note="CRS assigned as metadata; coordinates were not transformed")

    def set_metadata(self, **fields) -> None:
        changed = {}
        for k, v in fields.items():
            if k not in ("name", "description", "author", "default_crs", "units"):
                raise KeyError(k)
            if getattr(self, k) != v:
                changed[k] = {"old": getattr(self, k), "new": v}
                setattr(self, k, v)
        if changed:
            self.log("project.metadata", changes=changed)

    def dataset_by_name(self, name: str) -> PointDataset | None:
        return next((d for d in self.datasets.values() if d.name == name), None)

    # ---- generic lookup ------------------------------------------------------
    def item(self, item_id: str):
        """Dataset, grid, map, vector layer or image with this id (or None)."""
        for store in (self.datasets, self.grids, self.maps, self.vectors, self.images):
            if item_id in store:
                return store[item_id]
        return None

    def _unique(self, name: str, existing: set) -> str:
        base, i, out = name, 2, name
        while out in existing:
            out = f"{base} ({i})"
            i += 1
        return out

    # ---- grids ---------------------------------------------------------------
    def add_grid(self, grid: Grid) -> Grid:
        grid.name = self._unique(grid.name, {g.name for g in self.grids.values()})
        self.grids[grid.id] = grid
        md = grid.metadata or {}
        self.log("grid.create", grid_id=grid.id, name=grid.name, method=md.get("method"),
                 parameters=md.get("parameters"), source=md.get("source"),
                 geometry=grid.geometry.to_dict(), blanking=md.get("blanking"),
                 residuals=md.get("residuals"))
        return grid

    def maps_using(self, item_id: str) -> list:
        return [m for m in self.maps.values() if item_id in m.referenced_ids()]

    def remove_grid(self, grid_id: str) -> Grid:
        g = self.grids.pop(grid_id)
        self.log("grid.remove", grid_id=grid_id, name=g.name)
        return g

    def rename_grid(self, grid_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Grid name cannot be empty")
        if any(g.name == new_name and g.id != grid_id for g in self.grids.values()):
            raise ValueError(f"A grid named {new_name!r} already exists")
        g = self.grids[grid_id]
        if g.name != new_name:
            old, g.name = g.name, new_name
            self.log("grid.rename", grid_id=grid_id, old=old, new=new_name)

    # ---- maps ----------------------------------------------------------------
    def add_map(self, doc: MapDocument) -> MapDocument:
        doc.name = self._unique(doc.name, {m.name for m in self.maps.values()})
        self.maps[doc.id] = doc
        self.log("map.create", map_id=doc.id, name=doc.name,
                 layers=[lyr.type for lyr in doc.layers])
        return doc

    def remove_map(self, map_id: str) -> MapDocument:
        m = self.maps.pop(map_id)
        self.log("map.remove", map_id=map_id, name=m.name)
        return m

    def rename_map(self, map_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Map name cannot be empty")
        if any(m.name == new_name and m.id != map_id for m in self.maps.values()):
            raise ValueError(f"A map named {new_name!r} already exists")
        m = self.maps[map_id]
        if m.name != new_name:
            old, m.name = m.name, new_name
            self.log("map.rename", map_id=map_id, old=old, new=new_name)

    # ---- vector layers (Phase 3) -----------------------------------------------
    def add_vector(self, ds: VectorDataset, action: str = "vector.import", **details) -> VectorDataset:
        ds.name = self._unique(ds.name, {v.name for v in self.vectors.values()})
        self.vectors[ds.id] = ds
        src = ds.source
        self.log(action, vector_id=ds.id, name=ds.name, features=ds.n_features,
                 geometry=ds.geom_types(), crs=ds.crs,
                 source=src.path if src else None, source_sha256=src.sha256 if src else None,
                 format=src.format if src else None,
                 read_options=src.read_options if src else None,
                 processing=(ds.metadata or {}).get("processing"),
                 warnings=(ds.metadata or {}).get("warnings"), **details)
        return ds

    def remove_vector(self, vector_id: str) -> VectorDataset:
        v = self.vectors.pop(vector_id)
        self.log("vector.remove", vector_id=vector_id, name=v.name)
        return v

    def rename_vector(self, vector_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Layer name cannot be empty")
        if any(v.name == new_name and v.id != vector_id for v in self.vectors.values()):
            raise ValueError(f"A vector layer named {new_name!r} already exists")
        v = self.vectors[vector_id]
        if v.name != new_name:
            old, v.name = v.name, new_name
            self.log("vector.rename", vector_id=vector_id, old=old, new=new_name)

    # ---- raster images (Phase 3) -------------------------------------------------
    def add_image(self, img: RasterImage) -> RasterImage:
        img.name = self._unique(img.name, {i.name for i in self.images.values()})
        self.images[img.id] = img
        src = img.source
        self.log("image.import", image_id=img.id, name=img.name, size=list(img.shape),
                 extent=list(img.extent), crs=img.crs, source=src.path if src else None,
                 source_sha256=src.sha256 if src else None,
                 warnings=(img.metadata or {}).get("warnings"))
        return img

    def remove_image(self, image_id: str) -> RasterImage:
        i = self.images.pop(image_id)
        self.log("image.remove", image_id=image_id, name=i.name)
        return i

    def rename_image(self, image_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Image name cannot be empty")
        if any(i.name == new_name and i.id != image_id for i in self.images.values()):
            raise ValueError(f"An image named {new_name!r} already exists")
        i = self.images[image_id]
        if i.name != new_name:
            old, i.name = i.name, new_name
            self.log("image.rename", image_id=image_id, old=old, new=new_name)
