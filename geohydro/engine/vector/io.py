"""Reading and writing vector files through GDAL/OGR (pyogrio).

Supported for reading: any format the bundled GDAL can read; the formats below
are the ones tested and offered in the user interface. Writing is limited to
the formats in :data:`WRITE_FORMATS`.

Notes
-----
* Coordinates are read exactly as stored; the CRS comes from the file
  (``.prj`` for shapefiles). A file without a CRS gives a dataset with no CRS
  and a warning, never a guessed one.
* KML/KMZ coordinates are WGS 84 longitude/latitude by definition (OGC KML).
* Z values in 3D geometries are kept; measures (M) are dropped by Shapely.
* A zipped shapefile can be read directly (``.zip``).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from geohydro.engine.data.dataset import SourceInfo
from geohydro.engine.data.importer import file_sha256
from geohydro.engine.errors import VectorError

from .dataset import VectorDataset

READ_FORMATS = {
    ".shp": "ESRI Shapefile", ".zip": "ESRI Shapefile (zipped)", ".geojson": "GeoJSON",
    ".json": "GeoJSON", ".gpkg": "GeoPackage", ".kml": "KML", ".kmz": "KMZ",
    ".gml": "GML", ".fgb": "FlatGeobuf", ".dxf": "AutoCAD DXF", ".gpx": "GPX",
    ".tab": "MapInfo TAB", ".mif": "MapInfo MIF",
}
WRITE_FORMATS = {  # key -> (label, extension, OGR driver)
    "gpkg": ("GeoPackage (*.gpkg)", ".gpkg", "GPKG"),
    "shapefile": ("ESRI Shapefile (*.shp)", ".shp", "ESRI Shapefile"),
    "geojson": ("GeoJSON (*.geojson)", ".geojson", "GeoJSON"),
    "kml": ("KML (*.kml)", ".kml", "KML"),
    "fgb": ("FlatGeobuf (*.fgb)", ".fgb", "FlatGeobuf"),
}
VECTOR_FILTER = ("Vector files (" + " ".join(f"*{e}" for e in READ_FORMATS) + ");;"
                 + ";;".join(f"{v} (*{k})" for k, v in READ_FORMATS.items()) + ";;All files (*)")


def _gdal_path(path: Path) -> str:
    return str(path)


def list_layers(path) -> list[tuple[str, str]]:
    """Layers in a vector file as (name, geometry type)."""
    import pyogrio
    path = Path(path)
    if not path.exists():
        raise VectorError(f"File not found: {path}")
    try:
        return [(str(n), str(t)) for n, t in pyogrio.list_layers(_gdal_path(path))]
    except Exception as exc:  # pyogrio raises DataSourceError and friends
        raise VectorError(f"{path.name} cannot be read as a vector file: {exc}") from exc


def _crs_text(crs) -> str | None:
    if not crs:
        return None
    try:
        from pyproj import CRS
        c = CRS.from_user_input(crs)
        epsg = c.to_epsg(min_confidence=90)
        return f"EPSG:{epsg}" if epsg else c.to_wkt()
    except Exception:
        return str(crs)


def read_vector(path, layer: str | int | None = None, name: str | None = None) -> VectorDataset:
    import pyogrio
    path = Path(path)
    if not path.exists():
        raise VectorError(f"File not found: {path}")
    try:
        meta, _fids, wkb, field_data = pyogrio.raw.read(_gdal_path(path), layer=layer)
    except Exception as exc:
        raise VectorError(f"{path.name} cannot be read as a vector file: {exc}") from exc
    warnings = []
    geoms = np.empty(len(wkb), dtype=object)
    n_bad = 0
    for i, b in enumerate(wkb):
        if b is None:
            geoms[i] = None
            continue
        try:
            geoms[i] = shapely.from_wkb(b)
        except shapely.errors.GEOSException:
            geoms[i] = None
            n_bad += 1
    if n_bad:
        warnings.append(f"{n_bad} feature(s) had unreadable geometry and were kept without one.")
    cols = {}
    for fname, arr in zip(meta["fields"], field_data):
        a = np.asarray(arr)
        if a.dtype.kind == "M":
            cols[str(fname)] = pd.to_datetime(a)
        else:
            cols[str(fname)] = a
    attrs = pd.DataFrame(cols, index=range(len(geoms)))
    try:
        info = pyogrio.read_info(_gdal_path(path), layer=layer)
    except Exception:
        info = {}
    driver = str(info.get("driver") or "")
    if driver.upper() in ("KML", "LIBKML"):
        # LIBKML exposes every KML feature property as a field; drop the empty ones
        kml_std = {"id", "description", "timestamp", "begin", "end", "altitudeMode",
                   "tessellate", "extrude", "visibility", "drawOrder", "icon", "snippet"}
        def _is_default(col):
            v = col.dropna()
            return v.empty or v.astype(str).isin(["", "-1", "0", "-1.0", "0.0"]).all()
        empty = [c for c in attrs.columns if c in kml_std and _is_default(attrs[c])]
        attrs = attrs.drop(columns=empty)
    crs = _crs_text(meta.get("crs"))
    ext = path.suffix.lower()
    if crs is None:
        if ext in (".kml", ".kmz"):
            crs = "EPSG:4326"
        else:
            warnings.append("The file has no coordinate reference system (for a shapefile: no "
                            ".prj). Assign one before combining it with other data.")
    is_geo = False
    if crs:
        try:
            from pyproj import CRS
            is_geo = CRS.from_user_input(crs).is_geographic
        except Exception:
            warnings.append(f"The CRS in the file could not be interpreted: {crs[:80]}")
    st = path.stat()
    layer_name = layer if isinstance(layer, str) else info.get("layer_name")
    source = SourceInfo(
        path=str(path.resolve()), format=READ_FORMATS.get(ext, ext.lstrip(".") or "vector"),
        sha256=file_sha256(path), size_bytes=st.st_size,
        modified=datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        read_options={"layer": layer_name, "driver": driver or None,
                      "encoding": meta.get("encoding")})
    ds = VectorDataset(name=name or (path.stem if layer_name in (None, path.stem)
                                     else f"{path.stem} – {layer_name}"),
                       geometry=geoms, attributes=attrs, crs=crs, source=source,
                       xy_units="deg" if is_geo else "m",
                       metadata={"geometry_type": meta.get("geometry_type"),
                                 "warnings": warnings})
    v = ds.validity()
    if v["invalid_geometry"]:
        warnings.append(f"{v['invalid_geometry']} feature(s) have invalid geometry "
                        "(for example self-intersecting polygons). They are kept as read; "
                        "use Repair Geometry before area calculations or overlays.")
    if v["missing_geometry"]:
        warnings.append(f"{v['missing_geometry']} feature(s) have no geometry.")
    ds.metadata["validity"] = v
    return ds


def _geometry_type_for_write(ds: VectorDataset) -> str:
    types = {t for t in ds.geom_types() if t != "None"}
    if not types:
        return "Unknown"
    if len(types) == 1:
        return types.pop()
    fam = ds.family
    return {"point": "MultiPoint", "line": "MultiLineString", "polygon": "MultiPolygon"}.get(
        fam, "Unknown")


def write_vector(ds: VectorDataset, path, fmt: str | None = None, overwrite: bool = False) -> Path:
    import pyogrio
    path = Path(path)
    if fmt is None:
        fmt = next((k for k, (_l, e, _d) in WRITE_FORMATS.items() if e == path.suffix.lower()), None)
    if fmt not in WRITE_FORMATS:
        raise VectorError(f"Cannot write vector format for '{path.suffix}'.")
    if path.exists() and not overwrite:
        raise VectorError(f"{path} already exists.")
    _label, _ext, driver = WRITE_FORMATS[fmt]
    if fmt == "kml" and ds.crs:
        from .ops import reproject
        if ds.crs.upper() not in ("EPSG:4326", "OGC:CRS84"):
            ds = reproject(ds, "EPSG:4326")  # KML is WGS 84 by definition
    gtype = _geometry_type_for_write(ds)
    fields, data = [], []
    for c in ds.attributes.columns:
        col = ds.attributes[c]
        name = str(c)
        if fmt == "shapefile" and len(name) > 10:
            name = name[:10]  # dBASE limit; GDAL would truncate with a warning
        if pd.api.types.is_datetime64_any_dtype(col):
            arr = col.dt.strftime("%Y-%m-%dT%H:%M:%S").to_numpy(dtype=object)
        elif pd.api.types.is_bool_dtype(col):
            arr = col.astype("int32").to_numpy()
        elif pd.api.types.is_integer_dtype(col) and col.isna().any():
            arr = col.astype("float64").to_numpy()
        elif pd.api.types.is_numeric_dtype(col):
            arr = col.to_numpy()
        else:
            arr = col.astype(object).where(col.notna(), None).to_numpy(dtype=object)
        fields.append(name)
        data.append(arr)
    if len(set(fields)) != len(fields):
        raise VectorError("Field names are not unique after shortening to 10 characters "
                          "(shapefile limit). Rename fields or use GeoPackage.")
    wkb = np.array([None if g is None else shapely.to_wkb(g) for g in ds.geometry], dtype=object)
    crs = None
    if ds.crs:
        from pyproj import CRS
        crs = CRS.from_user_input(ds.crs).to_wkt()
    if path.exists():
        if fmt == "shapefile":
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                p = path.with_suffix(ext)
                if p.exists():
                    os.remove(p)
        else:
            os.remove(path)
    try:
        pyogrio.raw.write(str(path), geometry=wkb, field_data=data, fields=fields,
                          geometry_type=gtype, crs=crs, driver=driver,
                          promote_to_multi=(fmt == "shapefile" and gtype.startswith("Multi")) or None,
                          encoding="UTF-8" if fmt == "shapefile" else None,
                          # FlatGeobuf's packed R-tree reorders features (Hilbert sort) and
                          # cannot hold null geometry; without it, feature order is kept.
                          layer_options={"SPATIAL_INDEX": "NO"} if fmt == "fgb" else None)
    except Exception as exc:
        raise VectorError(f"Writing {path.name} failed: {exc}") from exc
    return path
