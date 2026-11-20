"""Vector (feature) dataset model: geometries plus an attribute table.

Geometries are Shapely 2 objects held in a NumPy object array, attributes in a
pandas DataFrame with one row per feature (same order). Coordinates are in
the dataset's CRS; nothing is reprojected implicitly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import shapely

from geohydro.engine.data.dataset import SourceInfo, utc_now
from geohydro.engine.errors import VectorError

#: Simplified geometry families used for symbology and validation.
FAMILIES = {"Point": "point", "MultiPoint": "point", "LineString": "line",
            "MultiLineString": "line", "LinearRing": "line", "Polygon": "polygon",
            "MultiPolygon": "polygon", "GeometryCollection": "mixed"}


@dataclass
class VectorDataset:
    name: str
    geometry: np.ndarray  # object array of shapely geometries (None = missing geometry)
    attributes: pd.DataFrame
    crs: str | None = None
    source: SourceInfo | None = None
    metadata: dict = field(default_factory=dict)  # driver, layer, read report, processing
    xy_units: str = "m"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = "vector"
    created: str = field(default_factory=utc_now)
    notes: str = ""

    def __post_init__(self):
        self.geometry = np.asarray(self.geometry, dtype=object)
        if self.geometry.ndim != 1:
            raise VectorError("Geometry must be a one-dimensional array.")
        if self.attributes is None:
            self.attributes = pd.DataFrame(index=range(len(self.geometry)))
        if len(self.attributes) != len(self.geometry):
            raise VectorError(
                f"{len(self.geometry)} geometries but {len(self.attributes)} attribute rows.")
        self.attributes = self.attributes.reset_index(drop=True)

    # ---- queries -----------------------------------------------------------
    @property
    def n_features(self) -> int:
        return int(self.geometry.size)

    def geom_types(self) -> dict[str, int]:
        t = shapely.get_type_id(self.geometry)
        names = {0: "Point", 1: "LineString", 2: "LinearRing", 3: "Polygon", 4: "MultiPoint",
                 5: "MultiLineString", 6: "MultiPolygon", 7: "GeometryCollection", -1: "None"}
        vals, counts = np.unique(t, return_counts=True)
        return {names.get(int(v), str(v)): int(c) for v, c in zip(vals, counts)}

    @property
    def family(self) -> str:
        """``point``, ``line``, ``polygon``, ``mixed`` or ``empty``."""
        fams = {FAMILIES.get(t) for t in self.geom_types() if t != "None"}
        fams.discard(None)
        if not fams:
            return "empty"
        return fams.pop() if len(fams) == 1 else "mixed"

    def bounds(self) -> tuple[float, float, float, float] | None:
        g = self.geometry[~shapely.is_missing(self.geometry) & ~shapely.is_empty(self.geometry)] \
            if self.n_features else self.geometry
        if g.size == 0:
            return None
        b = shapely.total_bounds(g)
        if not np.all(np.isfinite(b)):
            return None
        return float(b[0]), float(b[2]), float(b[1]), float(b[3])  # x0, x1, y0, y1

    def extent(self):
        return self.bounds()

    def validity(self) -> dict:
        g = self.geometry
        missing = shapely.is_missing(g)
        empty = np.zeros(g.size, bool)
        empty[~missing] = shapely.is_empty(g[~missing])
        valid = np.ones(g.size, bool)
        ok = ~missing & ~empty
        valid[ok] = shapely.is_valid(g[ok])
        reasons = {}
        for i in np.flatnonzero(~valid)[:20]:
            reasons[int(i)] = shapely.is_valid_reason(g[i])
        return {"features": int(g.size), "missing_geometry": int(missing.sum()),
                "empty_geometry": int(empty.sum()), "invalid_geometry": int((~valid).sum()),
                "invalid_examples": reasons}

    def numeric_fields(self) -> list[str]:
        return [c for c in self.attributes.columns
                if pd.api.types.is_numeric_dtype(self.attributes[c])
                and not pd.api.types.is_bool_dtype(self.attributes[c])]

    def copy(self, **changes) -> "VectorDataset":
        kw = dict(name=self.name, geometry=self.geometry.copy(), attributes=self.attributes.copy(),
                  crs=self.crs, source=self.source, metadata=dict(self.metadata),
                  xy_units=self.xy_units, notes=self.notes)
        kw.update(changes)
        return VectorDataset(**kw)
