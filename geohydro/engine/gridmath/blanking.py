"""Blanking with polygons and clipping to a rectangle.

A node is *inside* a polygon when it lies in its interior or on its boundary
(GEOS ``intersects``). Holes are respected. Polygons come from a vector layer
in the same CRS as the grid (the layer is reprojected first if its CRS
differs), or from any Shapely polygon. Blanked nodes become NaN; no value is
changed otherwise.
"""

from __future__ import annotations

import numpy as np

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid, GridGeometry

from .common import derived


def _polygon(grid: Grid, mask):
    from geohydro.engine.vector import VectorDataset
    from geohydro.engine.vector.ops import polygon_union, reproject
    if isinstance(mask, VectorDataset):
        layer = mask
        if layer.crs and grid.crs and layer.crs != grid.crs:
            layer = reproject(layer, grid.crs)
        elif bool(layer.crs) != bool(grid.crs):
            raise GridMathError("The grid or the polygon layer has no CRS; assign one so that "
                                "they can be overlaid reliably.")
        return polygon_union(layer), {"vector_id": mask.id, "vector_name": mask.name}
    return mask, {"polygon_bounds": [float(v) for v in mask.bounds]}


def blank_polygon(grid: Grid, mask, outside: bool = False, name: str | None = None) -> Grid:
    """Blank nodes inside (default) or outside the polygon(s)."""
    from geohydro.engine.vector.ops import contains_mask
    poly, desc = _polygon(grid, mask)
    X, Y = grid.geometry.mesh()
    inside = contains_mask(poly, X.ravel(), Y.ravel()).reshape(X.shape)
    kill = ~inside if outside else inside
    z = np.where(kill, np.nan, grid.z)
    n = int((kill & np.isfinite(grid.z)).sum())
    where = "outside" if outside else "inside"
    out = derived(grid, z, name or f"{grid.name} (blanked {where})", "grid_math.blank_polygon",
                  {"mode": where, **desc}, [f"{n:,} node(s) blanked {where} the polygon(s)."])
    out.metadata["method_title"] = f"Blanked {where} polygon"
    out.z_label = grid.z_label
    return out


def clip_extent(grid: Grid, x0: float, x1: float, y0: float, y1: float,
                name: str | None = None) -> Grid:
    """Sub-grid of the nodes inside [x0, x1] × [y0, y1] (values unchanged)."""
    g = grid.geometry
    xs, ys = g.x_nodes(), g.y_nodes()
    eps = 1e-9 * max(g.dx, g.dy)
    ix = np.flatnonzero((xs >= x0 - eps) & (xs <= x1 + eps))
    iy = np.flatnonzero((ys >= y0 - eps) & (ys <= y1 + eps))
    if ix.size < 2 or iy.size < 2:
        raise GridMathError("The clip rectangle contains fewer than 2 × 2 grid nodes.")
    geom = GridGeometry(float(xs[ix[0]]), float(xs[ix[-1]]), float(ys[iy[0]]), float(ys[iy[-1]]),
                        ix.size, iy.size)
    z = grid.z[iy[0]:iy[-1] + 1, ix[0]:ix[-1] + 1].copy()
    out = derived(grid, z, name or f"{grid.name} (clipped)", "grid_math.clip_extent",
                  {"extent": [x0, x1, y0, y1]}, geometry=geom)
    out.metadata["method_title"] = "Clipped to extent"
    out.z_label = grid.z_label
    return out
