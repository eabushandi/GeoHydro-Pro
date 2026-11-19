"""Supported and planned input formats."""

from __future__ import annotations

from pathlib import Path

# format code -> (description, extensions)
TABULAR_FORMATS: dict[str, tuple[str, tuple[str, ...]]] = {
    "csv": ("Comma/semicolon separated values", (".csv",)),
    "xlsx": ("Excel workbook", (".xlsx", ".xlsm")),
    "xyz": ("XYZ point file (whitespace delimited)", (".xyz",)),
    "txt": ("Delimited text", (".txt",)),
    "dat": ("Delimited data file", (".dat",)),
}

# Planned formats are listed so the UI can name them honestly.
PLANNED_FORMATS: dict[str, tuple[str, tuple[str, ...], int]] = {
    "geotiff": ("GeoTIFF raster", (".tif", ".tiff"), 3),
    "asc": ("ESRI ASCII grid", (".asc",), 3),
    "dem": ("USGS DEM", (".dem",), 3),
    "img": ("ERDAS Imagine", (".img",), 3),
    "shp": ("ESRI Shapefile", (".shp",), 2),
    "gpkg": ("GeoPackage", (".gpkg",), 2),
    "geojson": ("GeoJSON", (".geojson", ".json"), 2),
    "dxf": ("AutoCAD DXF", (".dxf",), 2),
    "netcdf": ("NetCDF", (".nc", ".nc4"), 6),
    "las": ("LAS / LAZ point cloud", (".las", ".laz"), 3),
}


def detect_format(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    for code, (_desc, exts) in TABULAR_FORMATS.items():
        if ext in exts:
            return code
    return None


def planned_format_for(path: str | Path):
    ext = Path(path).suffix.lower()
    for code, (desc, exts, phase) in PLANNED_FORMATS.items():
        if ext in exts:
            return code, desc, phase
    return None


def file_dialog_filter() -> str:
    """Qt-style filter string (also useful for documentation)."""
    all_exts = " ".join(f"*{e}" for _d, exts in TABULAR_FORMATS.values() for e in exts)
    parts = [f"Supported tabular data ({all_exts})"]
    for _code, (desc, exts) in TABULAR_FORMATS.items():
        parts.append(f"{desc} ({' '.join('*' + e for e in exts)})")
    parts.append("All files (*)")
    return ";;".join(parts)
