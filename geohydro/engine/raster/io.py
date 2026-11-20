"""Reading and writing raster files through GDAL (rasterio).

Grids from rasters
------------------
A raster stores values for *cells*; a GeoHydro grid stores values at *nodes*
(see docs/GRIDDING.md). A single raster band is converted by placing one grid
node at the centre of every cell:

    x_i = x_left + (i + ½)·Δx,   y_j = y_top − (j + ½)·|Δy|

so no value is interpolated or shifted. Rows are reordered so that row 0 is
the southern row. NoData cells (and cells masked by GDAL) become NaN. Band
scale and offset, if defined, are applied: ``z = raw·scale + offset``.

Exceptions, each recorded in the grid metadata and shown as a warning:

* A rotated or sheared raster, or one georeferenced only by ground control
  points, is warped to a north-up grid with the chosen resampling.
* A reprojection requested by the user (``target_crs``) is a warp with the
  chosen resampling (default bilinear).
* A raster with more cells than the grid limit is read decimated by an
  integer factor using block averaging of valid cells (GDAL ``average``).

Images from rasters
-------------------
RGB(A) and paletted rasters are read as display images (:class:`RasterImage`).
Bands that are not 8-bit are linearly stretched to 0-255 between their 2nd
and 98th percentiles for display only.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from geohydro.engine.data.dataset import SourceInfo
from geohydro.engine.data.importer import file_sha256
from geohydro.engine.errors import RasterError
from geohydro.engine.gridding.grid import MAX_NODES, Grid, GridGeometry

from .image import RasterImage

READ_FORMATS = {
    ".tif": "GeoTIFF", ".tiff": "GeoTIFF", ".img": "ERDAS Imagine", ".vrt": "GDAL VRT",
    ".asc": "ESRI ASCII grid", ".bil": "ESRI BIL", ".hgt": "SRTM HGT", ".dem": "USGS DEM",
    ".dt0": "DTED", ".dt1": "DTED", ".dt2": "DTED", ".jp2": "JPEG 2000",
    ".png": "PNG (with world file)", ".jpg": "JPEG (with world file)",
    ".jpeg": "JPEG (with world file)", ".sdat": "SAGA grid", ".rst": "Idrisi raster",
    ".nc": "NetCDF (single variable)", ".grd": "GDAL-readable grid",
}
RASTER_FILTER = ("Raster files (" + " ".join(f"*{e}" for e in READ_FORMATS) + ");;"
                 "GeoTIFF (*.tif *.tiff);;All files (*)")
RESAMPLING = ("nearest", "bilinear", "cubic", "average")
IMAGE_MAX_SIZE = 4096


def _resampling(name: str):
    from rasterio.enums import Resampling
    if name not in RESAMPLING:
        raise RasterError(f"Unknown resampling '{name}'. Use one of {', '.join(RESAMPLING)}.")
    return getattr(Resampling, name)


def _open(path: Path):
    import rasterio
    if not path.exists():
        raise RasterError(f"File not found: {path}")
    try:
        return rasterio.open(path)
    except Exception as exc:  # RasterioIOError and friends
        raise RasterError(f"{path.name} cannot be read as a raster: {exc}") from exc


def _crs_text(crs) -> str | None:
    if crs is None:
        return None
    epsg = crs.to_epsg(confidence_threshold=90) if hasattr(crs, "to_epsg") else None
    return f"EPSG:{epsg}" if epsg else crs.to_wkt()


def _xy_units(crs_text: str | None) -> str:
    if not crs_text:
        return "m"
    from pyproj import CRS
    c = CRS.from_user_input(crs_text)
    if c.is_geographic:
        return "deg"
    unit = (c.axis_info[0].unit_name if c.axis_info else "metre").lower()
    if "us survey" in unit:
        return "us-ft"
    if "foot" in unit:
        return "ft"
    return "m"


def _source(path: Path, driver: str, **opts) -> SourceInfo:
    st = path.stat()
    return SourceInfo(
        path=str(path.resolve()), format=f"{driver} ({READ_FORMATS.get(path.suffix.lower(), '')})"
        .replace(" ()", ""), sha256=file_sha256(path), size_bytes=st.st_size,
        modified=datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0)
        .isoformat(), read_options=opts)


def raster_info(path) -> dict:
    """Summary of a raster file: size, bands, data types, CRS, NoData, colours."""
    path = Path(path)
    with _open(path) as src:
        ci = [c.name for c in src.colorinterp]
        has_palette = False
        try:
            src.colormap(1)
            has_palette = True
        except ValueError:
            pass
        return {
            "driver": src.driver, "width": src.width, "height": src.height,
            "count": src.count, "dtypes": list(src.dtypes), "crs": _crs_text(src.crs),
            "transform": tuple(src.transform)[:6], "nodata": src.nodata,
            "colorinterp": ci, "palette": has_palette,
            "rotated": not _north_up(src.transform),
            "gcps": bool(src.gcps[0]), "units": list(src.units),
            "descriptions": list(src.descriptions), "scales": list(src.scales),
            "offsets": list(src.offsets), "bounds": tuple(src.bounds),
            "kind": _classify(src, ci, has_palette),
        }


def _north_up(tr) -> bool:
    return tr.b == 0 and tr.d == 0 and tr.a > 0


def _classify(src, ci, has_palette) -> str:
    if has_palette and src.count == 1:
        return "image"
    if src.count >= 3 and ci[:3] == ["red", "green", "blue"]:
        return "image"
    return "grid"


def read_raster_grid(path, band: int = 1, name: str | None = None,
                     target_crs: str | None = None, resampling: str = "bilinear",
                     max_nodes: int = MAX_NODES) -> Grid:
    """Read one band of a raster as a node-registered grid (cell centres → nodes)."""
    from affine import Affine
    from rasterio.vrt import WarpedVRT
    path = Path(path)
    warnings: list[str] = []
    processing: list[dict] = []
    with _open(path) as src:
        if not 1 <= band <= src.count:
            raise RasterError(f"{path.name} has {src.count} band(s); band {band} does not exist.")
        identity = src.transform == Affine.identity() and not src.gcps[0]
        src_crs = src.crs or (src.gcps[1] if src.gcps[0] else None)
        if src_crs is None:
            warnings.append("The raster has no coordinate reference system. Assign one before "
                            "combining it with other data.")
        if identity:
            warnings.append("The raster has no georeferencing; X and Y are pixel coordinates "
                            "(cell centres at 0.5, 1.5, ...).")
        need_warp = bool(target_crs) or (not identity and not _north_up(src.transform))
        rs = _resampling(resampling)
        scale = src.scales[band - 1] if src.scales else 1.0
        offset = src.offsets[band - 1] if src.offsets else 0.0
        units = src.units[band - 1] if src.units else None
        desc = src.descriptions[band - 1] if src.descriptions else None
        nodata = src.nodata
        driver = src.driver
        dtype = src.dtypes[band - 1]
        ds = src
        vrt = None
        if need_warp:
            if src_crs is None and target_crs:
                raise RasterError("A raster without a CRS cannot be reprojected.")
            dst_crs = target_crs or src_crs
            # float64 + NaN destination NoData: cells outside the source become blank, not 0
            vrt = WarpedVRT(src, crs=dst_crs, resampling=rs, src_crs=src_crs,
                            src_nodata=src.nodata, nodata=float("nan"), dtype="float64")
            ds = vrt
            why = (f"reprojected to {target_crs}" if target_crs
                   else "warped from a rotated/GCP georeferencing to north-up")
            warnings.append(f"The raster was {why} with {resampling} resampling; values are "
                            "interpolated, not original cell values.")
            processing.append({"operation": "warp", "to": str(dst_crs), "resampling": resampling,
                               "reason": "reproject" if target_crs else "rotation/gcps"})
        try:
            w, h = ds.width, ds.height
            factor = 1
            if w * h > max_nodes:
                factor = math.ceil(math.sqrt(w * h / max_nodes))
                while (w // factor) * (h // factor) > max_nodes:
                    factor += 1
            out_shape = (max(h // factor, 1), max(w // factor, 1))
            from rasterio.enums import Resampling
            data = ds.read(band, masked=True, out_shape=out_shape if factor > 1 else None,
                           resampling=Resampling.average if factor > 1 else Resampling.nearest)
            tr = ds.transform
            crs_out = _crs_text(ds.crs) if ds.crs else _crs_text(src_crs)
        finally:
            if vrt is not None:
                vrt.close()
    if factor > 1:
        tr = tr * Affine.scale(w / out_shape[1], h / out_shape[0])
        warnings.append(f"The raster has {w:,} × {h:,} cells, more than the grid limit; it was "
                        f"read with every {factor} × {factor} block averaged "
                        f"({out_shape[1]:,} × {out_shape[0]:,} nodes).")
        processing.append({"operation": "decimate", "factor": factor, "method": "block average"})
    z = np.ma.filled(data.astype("float64"), np.nan)
    if scale not in (None, 1.0) or offset not in (None, 0.0):
        z = z * (scale if scale is not None else 1.0) + (offset or 0.0)
        processing.append({"operation": "scale_offset", "scale": scale, "offset": offset})
    ny, nx = z.shape
    if nx < 2 or ny < 2:
        raise RasterError(f"{path.name}: a grid needs at least 2 × 2 cells (found {nx} × {ny}).")
    dx = tr.a
    if tr.e < 0:
        dy = -tr.e
        y_top_centre = tr.f + tr.e / 2
        y_min = y_top_centre - (ny - 1) * dy
        z = z[::-1].copy()
    else:  # south-up raster: row 0 is already the southern row
        dy = tr.e
        y_min = tr.f + dy / 2
    x_min = tr.c + dx / 2
    geom = GridGeometry(x_min, x_min + (nx - 1) * dx, y_min, y_min + (ny - 1) * dy, nx, ny)
    if not np.isfinite(z).any():
        warnings.append("Every cell is NoData.")
    z_units = units or "m"
    if not units:
        warnings.append("The band has no unit; Z units were set to metres. Change them in the "
                        "grid properties if needed.")
    grid = Grid(geom, z, name=name or (path.stem if band == 1 else f"{path.stem} band {band}"),
                crs=crs_out, xy_units=_xy_units(crs_out), z_units=z_units,
                z_label=desc or "Z",
                metadata={
                    "method": "raster import",
                    "source": {"path": str(path.resolve()), "format": driver, "band": band,
                               "sha256": file_sha256(path), "dtype": dtype, "nodata": nodata},
                    "registration": "cell centres mapped to grid nodes",
                    "processing": processing, "warnings": warnings})
    return grid


def _stretch(band: np.ndarray, valid: np.ndarray) -> np.ndarray:
    v = band[valid]
    if v.size == 0:
        return np.zeros(band.shape, np.uint8)
    lo, hi = np.percentile(v, [2, 98])
    if hi <= lo:
        hi = lo + 1
    return (np.clip((band.astype(float) - lo) / (hi - lo), 0, 1) * 255).round().astype(np.uint8)


def read_raster_image(path, name: str | None = None, max_size: int = IMAGE_MAX_SIZE,
                      bands: tuple[int, ...] | None = None) -> RasterImage:
    """Read an RGB(A), paletted or single-band raster as a display image."""
    from affine import Affine
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.vrt import WarpedVRT
    path = Path(path)
    warnings: list[str] = []
    with _open(path) as src:
        driver = src.driver
        src_crs = src.crs or (src.gcps[1] if src.gcps[0] else None)
        identity = src.transform == Affine.identity() and not src.gcps[0]
        if identity:
            warnings.append("The image has no georeferencing (no world file or GeoTIFF tags); "
                            "it is placed in pixel coordinates.")
        if src_crs is None:
            warnings.append("The image has no coordinate reference system.")
        palette = None
        try:
            palette = src.colormap(1)
        except ValueError:
            pass
        ci = list(src.colorinterp)
        if bands is None:
            if palette is not None and src.count == 1:
                bands = (1,)
            elif src.count >= 3:
                bands = (1, 2, 3)
            else:
                bands = (1,)
        alpha_band = next((i + 1 for i, c in enumerate(ci) if c == ColorInterp.alpha), None)
        ds = src
        vrt = None
        if not identity and not _north_up(src.transform):
            vrt = WarpedVRT(src, crs=src_crs, src_crs=src_crs, resampling=Resampling.nearest)
            ds = vrt
            warnings.append("The image was warped from a rotated/GCP georeferencing to north-up "
                            "(nearest neighbour).")
        try:
            w, h = ds.width, ds.height
            f = max(w, h) / max_size
            shape = None
            if f > 1:
                shape = (max(int(h / f), 1), max(int(w / f), 1))
                warnings.append(f"The image ({w:,} × {h:,} pixels) was reduced to "
                                f"{shape[1]:,} × {shape[0]:,} for display.")
            rs = Resampling.nearest if palette is not None else Resampling.average
            data = ds.read(list(bands), out_shape=(len(bands),) + shape if shape else None,
                           resampling=rs)
            mask = ds.dataset_mask(out_shape=shape, resampling=Resampling.nearest) \
                if shape else ds.dataset_mask()
            if alpha_band and alpha_band not in bands:
                a = ds.read(alpha_band, out_shape=shape, resampling=Resampling.nearest) \
                    if shape else ds.read(alpha_band)
                mask = np.minimum(mask, a)
            tr = ds.transform
            if shape:
                tr = tr * Affine.scale(w / shape[1], h / shape[0])
            crs_out = _crs_text(ds.crs) if ds.crs else _crs_text(src_crs)
            dtypes = [ds.dtypes[b - 1] for b in bands]
        finally:
            if vrt is not None:
                vrt.close()
    ny, nx = data.shape[1:]
    rgba = np.zeros((ny, nx, 4), np.uint8)
    valid = mask > 0
    if palette is not None and len(bands) == 1:
        lut = np.zeros((256, 4), np.uint8)
        for k, col in palette.items():
            if 0 <= k < 256:
                lut[k] = col
        idx = np.clip(data[0], 0, 255).astype(np.uint8)
        rgba[:] = lut[idx]
        valid &= rgba[..., 3] > 0
    else:
        chans = []
        for b, dt in zip(data, dtypes):
            if dt == "uint8":
                chans.append(b.astype(np.uint8))
            else:
                chans.append(_stretch(b, valid))
        if any(dt != "uint8" for dt in dtypes):
            warnings.append("Bands that are not 8-bit were stretched between their 2nd and 98th "
                            "percentiles for display.")
        if len(chans) == 1:
            chans = chans * 3
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = chans[:3]
    rgba[..., 3] = np.where(valid, 255, 0)
    if tr.e > 0:  # south-up file: flip to image order (north first)
        rgba = rgba[::-1].copy()
        top = tr.f + tr.e * ny
        bottom = tr.f
    else:
        top = tr.f
        bottom = tr.f + tr.e * ny
    ext = (tr.c, tr.c + tr.a * nx, bottom, top)
    return RasterImage(name=name or path.stem, rgba=rgba, extent=ext, crs=crs_out,
                       source=_source(path, driver, bands=list(bands)),
                       metadata={"warnings": warnings, "bands": list(bands),
                                 "palette": palette is not None})


def read_raster(path, kind: str | None = None, **kw):
    """Read a raster as a grid or an image; ``kind`` None decides from the file."""
    path = Path(path)
    kind = kind or raster_info(path)["kind"]
    return read_raster_image(path, **kw) if kind == "image" else read_raster_grid(path, **kw)


def write_geotiff(grid: Grid, path, dtype: str = "float64", overwrite: bool = False) -> Path:
    """Write a grid as a single-band GeoTIFF (each node becomes the centre of a cell).

    ``float64`` (default) stores values exactly; ``float32`` halves the file
    size and rounds values to about 7 significant digits. Blank nodes are
    stored as NaN (the band NoData value). DEFLATE compression with the
    floating-point predictor is lossless.
    """
    import rasterio
    from rasterio.transform import from_origin
    path = Path(path)
    if dtype not in ("float32", "float64"):
        raise RasterError("GeoTIFF data type must be float32 or float64.")
    if path.exists() and not overwrite:
        raise RasterError(f"{path} already exists.")
    g = grid.geometry
    tr = from_origin(g.x_min - g.dx / 2, g.y_max + g.dy / 2, g.dx, g.dy)
    tiled = g.nx >= 256 and g.ny >= 256
    profile = dict(driver="GTiff", width=g.nx, height=g.ny, count=1, dtype=dtype,
                   crs=grid.crs, transform=tr, nodata=float("nan"), compress="deflate",
                   predictor=3, tiled=tiled)
    if tiled:
        profile.update(blockxsize=256, blockysize=256)
    tmp = path.with_name(f".{path.name}.tmp.tif")
    try:
        with rasterio.open(tmp, "w", **profile) as dst:
            dst.write(grid.z[::-1].astype(dtype), 1)
            dst.set_band_unit(1, grid.z_units or "")
            dst.set_band_description(1, grid.z_label or grid.name)
            dst.update_tags(AREA_OR_POINT="Area", SOFTWARE="GeoHydro Pro",
                            GEOHYDRO_GRID=grid.name)
        tmp.replace(path)
    except Exception as exc:
        raise RasterError(f"Could not write {path}: {exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink()
    return path
