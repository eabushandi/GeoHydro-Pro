"""Raster files (GeoTIFF and every format the bundled GDAL reads).

Single-band rasters become :class:`~geohydro.engine.gridding.grid.Grid`
objects (cell centres become grid nodes); RGB(A) and paletted rasters become
:class:`RasterImage` objects used as base maps.

Phase 3. Methodology and limitations: docs/GIS.md.
"""

STATUS = "implemented"
PHASE = 3

from .image import RasterImage  # noqa: E402,F401
