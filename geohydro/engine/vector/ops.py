"""Vector processing: reprojection, measures, clipping, buffering, repair, conversion.

Measures
--------
* In a projected CRS, area and length are planar (Shapely/GEOS) in the CRS
  units. They are *grid* measures: they differ from ground measures by the
  projection's scale distortion (for UTM within about ±0.1 % inside the zone,
  area within about ±0.2 %).
* In a geographic CRS, area and length are computed on the WGS 84 ellipsoid
  with PROJ's geodesic routines (Karney 2013) via ``pyproj.Geod``, in m² and m.
  Planar measures in degrees are never reported as areas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import shapely

from geohydro.engine.errors import VectorError

from .dataset import VectorDataset


def _crs(crs_text):
    from pyproj import CRS
    try:
        return CRS.from_user_input(crs_text)
    except Exception as exc:
        raise VectorError(f"Invalid CRS: {crs_text}") from exc


def transform_coords(geoms: np.ndarray, src: str, dst: str) -> np.ndarray:
    """Reproject an array of geometries (always_xy axis order)."""
    from pyproj import Transformer
    t = Transformer.from_crs(_crs(src), _crs(dst), always_xy=True)

    def f(coords):
        x, y = t.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    out = np.empty(geoms.size, dtype=object)
    ok = ~shapely.is_missing(geoms)
    out[ok] = shapely.transform(geoms[ok], f)  # Z (if any) is preserved unchanged
    out[~ok] = None
    return out


def reproject(ds: VectorDataset, target_crs: str) -> VectorDataset:
    """Return a copy of ``ds`` with coordinates transformed to ``target_crs``.

    Vertices are transformed exactly (PROJ); edges between vertices are not
    densified, so long straight segments stay straight in the target CRS.
    """
    if not ds.crs:
        raise VectorError(f"'{ds.name}' has no CRS; assign one before reprojecting.")
    tgt = _crs(target_crs)
    epsg = tgt.to_epsg(min_confidence=90)
    crs_text = f"EPSG:{epsg}" if epsg else tgt.to_wkt()
    geoms = transform_coords(ds.geometry, ds.crs, crs_text)
    md = dict(ds.metadata)
    md["processing"] = list(md.get("processing", [])) + [
        {"operation": "reproject", "from": ds.crs, "to": crs_text}]
    return ds.copy(geometry=geoms, crs=crs_text, metadata=md,
                   xy_units="deg" if tgt.is_geographic else "m",
                   name=f"{ds.name} ({crs_text})")


def is_geographic(ds: VectorDataset) -> bool:
    return bool(ds.crs) and _crs(ds.crs).is_geographic


def measures(ds: VectorDataset) -> pd.DataFrame:
    """Area, length/perimeter and centroid of each feature.

    Returns columns ``area``, ``length`` (perimeter for polygons),
    ``centroid_x``, ``centroid_y`` and ``method`` (``planar`` or ``geodesic``).
    """
    g = ds.geometry
    n = g.size
    area = np.full(n, np.nan)
    length = np.full(n, np.nan)
    ok = ~shapely.is_missing(g)
    if is_geographic(ds):
        from pyproj import Geod
        geod = Geod(ellps="WGS84")
        tid = shapely.get_type_id(g)
        for i in np.flatnonzero(ok):
            if tid[i] in (1, 2, 5):  # lines: geometry_area_perimeter would close the ring
                area[i] = 0.0
                length[i] = geod.geometry_length(g[i])
            elif tid[i] in (0, 4):
                area[i] = 0.0
                length[i] = 0.0
            else:
                a, p = geod.geometry_area_perimeter(g[i])
                area[i] = abs(a)
                length[i] = p
        method = "geodesic (WGS 84)"
    else:
        area[ok] = shapely.area(g[ok])
        length[ok] = shapely.length(g[ok])
        method = "planar"
    c = np.full((n, 2), np.nan)
    if ok.any():
        cen = shapely.centroid(g[ok])
        c[ok, 0] = shapely.get_x(cen)
        c[ok, 1] = shapely.get_y(cen)
    return pd.DataFrame({"area": area, "length": length, "centroid_x": c[:, 0],
                         "centroid_y": c[:, 1], "method": method})


def add_measures(ds: VectorDataset) -> VectorDataset:
    m = measures(ds)
    attrs = ds.attributes.copy()
    unit = "m" if is_geographic(ds) else (ds.xy_units or "units")
    fam = ds.family
    if fam in ("polygon", "mixed"):
        attrs[f"area_{unit}2"] = m["area"].to_numpy()
    if fam in ("line", "polygon", "mixed"):
        attrs[f"length_{unit}" if fam != "polygon" else f"perim_{unit}"] = m["length"].to_numpy()
    md = dict(ds.metadata)
    md["processing"] = list(md.get("processing", [])) + [
        {"operation": "measures", "method": m["method"].iat[0] if len(m) else "planar"}]
    return ds.copy(attributes=attrs, metadata=md)


def repair(ds: VectorDataset) -> tuple[VectorDataset, int]:
    """Repair invalid geometries with GEOS ``make_valid`` (structure-preserving)."""
    g = ds.geometry.copy()
    ok = ~shapely.is_missing(g)
    bad = np.zeros(g.size, bool)
    bad[ok] = ~shapely.is_valid(g[ok])
    if bad.any():
        g[bad] = shapely.make_valid(g[bad])
    md = dict(ds.metadata)
    md["processing"] = list(md.get("processing", [])) + [
        {"operation": "repair", "repaired": int(bad.sum())}]
    return ds.copy(geometry=g, metadata=md, name=f"{ds.name} (repaired)"), int(bad.sum())


def buffer(ds: VectorDataset, distance: float, quad_segs: int = 16) -> VectorDataset:
    if is_geographic(ds):
        raise VectorError("Buffering needs a projected CRS (distances in degrees are not "
                          "lengths). Reproject the layer first.")
    if not np.isfinite(distance):
        raise VectorError("Buffer distance must be a number.")
    ok = ~shapely.is_missing(ds.geometry)
    g = ds.geometry.copy()
    g[ok] = shapely.buffer(g[ok], distance, quad_segs=quad_segs)
    md = dict(ds.metadata)
    md["processing"] = list(md.get("processing", [])) + [
        {"operation": "buffer", "distance": distance, "quad_segs": quad_segs}]
    return ds.copy(geometry=g, metadata=md, name=f"{ds.name} buffer {distance:g}")


def clip(ds: VectorDataset, mask) -> VectorDataset:
    """Clip features to a polygon (Shapely geometry) or extent (x0, x1, y0, y1).

    Features entirely outside are dropped; attributes are kept unchanged
    (they are not apportioned by area).
    """
    if isinstance(mask, (tuple, list)) and len(mask) == 4:
        x0, x1, y0, y1 = mask
        mask = shapely.box(x0, y0, x1, y1)
    g = ds.geometry
    ok = ~shapely.is_missing(g)
    out = np.empty(g.size, dtype=object)
    out[ok] = shapely.intersection(g[ok], mask)
    keep = ok.copy()
    keep[ok] = ~shapely.is_empty(out[ok])
    md = dict(ds.metadata)
    md["processing"] = list(md.get("processing", [])) + [
        {"operation": "clip", "mask_bounds": [float(v) for v in shapely.bounds(mask)],
         "kept": int(keep.sum()), "dropped": int((~keep).sum())}]
    return ds.copy(geometry=out[keep], attributes=ds.attributes[keep].reset_index(drop=True),
                   metadata=md, name=f"{ds.name} (clipped)")


def dissolve(ds: VectorDataset, by: str | None = None) -> VectorDataset:
    """Union features, optionally grouped by an attribute."""
    g = ds.geometry
    ok = ~shapely.is_missing(g)
    if by is None:
        geoms = np.array([shapely.union_all(g[ok])], dtype=object)
        attrs = pd.DataFrame({"count": [int(ok.sum())]})
    else:
        if by not in ds.attributes:
            raise VectorError(f"No field named '{by}'.")
        keys = ds.attributes[by]
        groups = [(k, np.flatnonzero((keys == k).to_numpy() & ok)) for k in pd.unique(keys)]
        geoms = np.array([shapely.union_all(g[idx]) for _k, idx in groups], dtype=object)
        attrs = pd.DataFrame({by: [k for k, _ in groups], "count": [len(i) for _, i in groups]})
    md = dict(ds.metadata)
    md["processing"] = list(md.get("processing", [])) + [{"operation": "dissolve", "by": by}]
    return ds.copy(geometry=geoms, attributes=attrs, metadata=md,
                   name=f"{ds.name} dissolved" + (f" by {by}" if by else ""))


def polygon_union(ds: VectorDataset):
    """Single (multi)polygon of all polygon features, for masks and blanking."""
    if ds.family not in ("polygon", "mixed"):
        raise VectorError(f"'{ds.name}' contains no polygons.")
    g = ds.geometry[~shapely.is_missing(ds.geometry)]
    polys = g[np.isin(shapely.get_type_id(g), (3, 6))]
    if polys.size == 0:
        raise VectorError(f"'{ds.name}' contains no polygons.")
    return shapely.make_valid(shapely.union_all(polys))


def points_to_table(ds: VectorDataset, z_field: str | None = None) -> pd.DataFrame:
    """X, Y (and Z) of point features; multipoints are exploded.

    The Z value comes from ``z_field`` or, if None and the geometries are 3D,
    from their Z coordinate.
    """
    if ds.family != "point":
        raise VectorError(f"'{ds.name}' is not a point layer.")
    g = ds.geometry
    ok = ~shapely.is_missing(g) & ~shapely.is_empty(g)
    parts, idx = shapely.get_parts(g[ok], return_index=True)
    src = np.flatnonzero(ok)[idx]
    coords = shapely.get_coordinates(parts, include_z=True)
    df = pd.DataFrame({"X": coords[:, 0], "Y": coords[:, 1]})
    if z_field:
        if z_field not in ds.attributes:
            raise VectorError(f"No field named '{z_field}'.")
        df["Z"] = pd.to_numeric(ds.attributes[z_field].to_numpy()[src], errors="coerce")
    elif shapely.has_z(parts).all():
        df["Z"] = coords[:, 2]
    df["source_row"] = src + 1
    for c in ds.attributes.columns:
        if c != z_field and c not in df:
            df[c] = ds.attributes[c].to_numpy()[src]
    return df


def from_points(x, y, attributes: pd.DataFrame | None = None, crs=None, name="points",
                **kw) -> VectorDataset:
    geoms = shapely.points(np.column_stack([np.asarray(x, float), np.asarray(y, float)]))
    return VectorDataset(name=name, geometry=geoms, attributes=attributes, crs=crs, **kw)


def contains_mask(polygon, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """True where (x, y) lies inside or on the boundary of ``polygon``."""
    shapely.prepare(polygon)
    return shapely.intersects_xy(polygon, x, y)
