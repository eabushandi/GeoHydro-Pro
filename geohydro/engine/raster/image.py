"""RGBA raster image for base maps.

The image is stored as an ``(ny, nx, 4)`` uint8 array with **row 0 at the
north** (image order, as drawn by ``imshow(origin="upper")``) and an extent
``(x0, x1, y0, y1)`` giving the outer *cell edges* in the image CRS. Pixel
values are display colours, not measurements; images are never used in
calculations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

from geohydro.engine.data.dataset import SourceInfo, utc_now
from geohydro.engine.errors import RasterError


@dataclass
class RasterImage:
    name: str
    rgba: np.ndarray
    extent: tuple[float, float, float, float]  # x0, x1, y0, y1 (cell edges)
    crs: str | None = None
    source: SourceInfo | None = None
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = "image"
    created: str = field(default_factory=utc_now)
    notes: str = ""

    def __post_init__(self):
        a = np.asarray(self.rgba)
        if a.ndim != 3 or a.shape[2] != 4 or a.dtype != np.uint8:
            raise RasterError("An image must be an (ny, nx, 4) uint8 RGBA array.")
        x0, x1, y0, y1 = (float(v) for v in self.extent)
        if not (x1 > x0 and y1 > y0):
            raise RasterError("Image extent must have x1 > x0 and y1 > y0.")
        self.rgba = a
        self.extent = (x0, x1, y0, y1)

    @property
    def shape(self) -> tuple[int, int]:
        return self.rgba.shape[0], self.rgba.shape[1]

    @property
    def pixel_size(self) -> tuple[float, float]:
        x0, x1, y0, y1 = self.extent
        return (x1 - x0) / self.shape[1], (y1 - y0) / self.shape[0]

    def bounds(self):
        return self.extent

    def transform(self):
        """Affine transform (GDAL convention, north-up)."""
        from rasterio.transform import from_bounds
        x0, x1, y0, y1 = self.extent
        return from_bounds(x0, y0, x1, y1, self.shape[1], self.shape[0])

    def copy(self, **changes) -> "RasterImage":
        kw = dict(name=self.name, rgba=self.rgba.copy(), extent=self.extent, crs=self.crs,
                  source=self.source, metadata=dict(self.metadata), notes=self.notes)
        kw.update(changes)
        return RasterImage(**kw)


def reproject_image(img: RasterImage, dst_crs: str, max_size: int = 4096) -> RasterImage:
    """Warp an image to another CRS (nearest neighbour, so colours are not blended).

    Areas outside the source become transparent. The output keeps about the
    source resolution, capped at ``max_size`` pixels on the long side.
    """
    if not img.crs:
        raise RasterError(f"'{img.name}' has no CRS; it cannot be reprojected.")
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, calculate_default_transform, reproject
    src_crs = CRS.from_user_input(img.crs)
    dst = CRS.from_user_input(dst_crs)
    ny, nx = img.shape
    x0, x1, y0, y1 = img.extent
    tr, w, h = calculate_default_transform(src_crs, dst, nx, ny, left=x0, bottom=y0,
                                           right=x1, top=y1)
    scale = max(w, h) / max_size
    if scale > 1:
        w, h = max(int(w / scale), 1), max(int(h / scale), 1)
        tr, w, h = calculate_default_transform(src_crs, dst, nx, ny, left=x0, bottom=y0,
                                               right=x1, top=y1, dst_width=w, dst_height=h)
    out = np.zeros((4, h, w), np.uint8)
    reproject(np.moveaxis(img.rgba, 2, 0), out, src_transform=img.transform(),
              src_crs=src_crs, dst_transform=tr, dst_crs=dst, resampling=Resampling.nearest,
              src_nodata=None, dst_nodata=0)
    left, top = tr.c, tr.f
    ext = (left, left + tr.a * w, top + tr.e * h, top)
    md = dict(img.metadata)
    md["processing"] = list(md.get("processing", [])) + [
        {"operation": "reproject", "from": img.crs, "to": str(dst_crs),
         "resampling": "nearest"}]
    return RasterImage(name=img.name, rgba=np.moveaxis(out, 0, 2).copy(), extent=ext,
                       crs=str(dst_crs), source=img.source, metadata=md, notes=img.notes)
