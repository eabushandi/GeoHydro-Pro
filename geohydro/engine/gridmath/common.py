"""Shared helpers: result construction, geometry checks and resampling."""

from __future__ import annotations

import math

import numpy as np

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid, GridGeometry

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def derived(src: Grid, z: np.ndarray, name: str, method: str, parameters: dict,
            warnings: list[str] | None = None, z_units: str | None = None,
            z_label: str | None = None, geometry: GridGeometry | None = None,
            sources: list[Grid] | None = None) -> Grid:
    """New grid derived from ``src`` with provenance metadata."""
    sources = sources or [src]
    md = {
        "method": method,
        "method_title": method,
        "parameters": parameters,
        "source": {"grid_ids": [g.id for g in sources], "grid_names": [g.name for g in sources]},
        "warnings": list(warnings or []),
    }
    return Grid(geometry or src.geometry, z, name=name, crs=src.crs, xy_units=src.xy_units,
                z_units=src.z_units if z_units is None else z_units,
                z_label=z_label or name, metadata=md)


def same_geometry(a: GridGeometry, b: GridGeometry, rtol: float = 1e-9) -> bool:
    if (a.nx, a.ny) != (b.nx, b.ny):
        return False
    span = max(a.x_max - a.x_min, a.y_max - a.y_min)
    return all(abs(getattr(a, k) - getattr(b, k)) <= rtol * span
               for k in ("x_min", "x_max", "y_min", "y_max"))


def check_crs(grids: list[Grid]) -> None:
    crs = {g.crs for g in grids if g.crs}
    if len(crs) > 1:
        raise GridMathError("The grids have different coordinate reference systems ("
                            + ", ".join(sorted(crs)) + "). Reproject them to one CRS first.")


def resample(grid: Grid, geometry: GridGeometry, method: str = "bilinear") -> Grid:
    """Values of ``grid`` at the nodes of ``geometry``.

    ``bilinear`` interpolates from the four surrounding nodes (NaN if any
    contributing node is blank); ``nearest`` takes the closest node. Nodes
    outside the source grid are blank; nothing is extrapolated.
    """
    if same_geometry(grid.geometry, geometry):
        return grid
    X, Y = geometry.mesh()
    if method == "bilinear":
        z = grid.sample(X.ravel(), Y.ravel()).reshape(geometry.shape)
    elif method == "nearest":
        g = grid.geometry
        i = np.rint((X - g.x_min) / g.dx).astype(int)
        j = np.rint((Y - g.y_min) / g.dy).astype(int)
        ok = (i >= 0) & (i < g.nx) & (j >= 0) & (j < g.ny)
        z = np.full(geometry.shape, np.nan)
        z[ok] = grid.z[j[ok], i[ok]]
    else:
        raise GridMathError(f"Unknown resampling method '{method}'.")
    out = derived(grid, z, f"{grid.name} (resampled)", "resample",
                  {"method": method, "geometry": geometry.to_dict()}, geometry=geometry)
    out.z_label = grid.z_label
    return out


def metric_spacing(grid: Grid) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Node spacing in metres as arrays broadcastable to ``z`` (rows = Y).

    * Projected grids: dx, dy converted from the XY unit to metres.
    * Geographic grids (degrees): for each row, the WGS 84 ellipsoid gives
      dx = Δλ·N(φ)·cos φ and dy = Δφ·M(φ), with M and N the meridional and
      prime-vertical radii of curvature at that row's latitude. This is
      exact for the local scale of a small cell; it does not account for
      the CRS's own datum if it is not WGS 84 (difference < 0.01 %).
    """
    g = grid.geometry
    notes = []
    if grid.xy_units == "deg":
        phi = np.radians(g.y_nodes())
        s = np.sin(phi)
        w = np.sqrt(1 - WGS84_E2 * s * s)
        N = WGS84_A / w
        M = WGS84_A * (1 - WGS84_E2) / w ** 3
        dx = np.radians(g.dx) * N * np.cos(phi)
        dy = np.radians(g.dy) * M
        notes.append("Geographic grid: cell sizes converted to metres row by row on the "
                     "WGS 84 ellipsoid.")
        if np.any(np.abs(g.y_nodes()) > 85):
            raise GridMathError("Grid extends beyond 85° latitude; reproject it first.")
        return dx[:, None], dy[:, None], notes
    from geohydro.engine.units import LENGTH_UNITS
    if grid.xy_units not in LENGTH_UNITS:
        raise GridMathError(f"XY unit '{grid.xy_units}' is not a length unit.")
    f = LENGTH_UNITS[grid.xy_units][1]
    return np.array([[g.dx * f]]), np.array([[g.dy * f]]), notes


def z_to_metres(grid: Grid, allow_unknown: bool = False) -> tuple[float, list[str]]:
    from geohydro.engine.units import LENGTH_UNITS
    if grid.z_units in LENGTH_UNITS:
        return LENGTH_UNITS[grid.z_units][1], []
    if allow_unknown:
        return 1.0, [f"Z unit '{grid.z_units}' is not a length; Z was treated as metres."]
    raise GridMathError(f"Z unit '{grid.z_units}' is not a length unit, so a slope or "
                        "curvature has no physical meaning. Set the grid's Z unit (for an "
                        "elevation grid: m or ft) in its properties.")


def neighbours(z: np.ndarray):
    """3×3 window values for every interior node, as arrays of shape (ny-2, nx-2).

    Names follow compass positions with grid row index increasing to the
    north: ``nw n ne / w c e / sw s se``.
    """
    return dict(
        sw=z[:-2, :-2], s=z[:-2, 1:-1], se=z[:-2, 2:],
        w=z[1:-1, :-2], c=z[1:-1, 1:-1], e=z[1:-1, 2:],
        nw=z[2:, :-2], n=z[2:, 1:-1], ne=z[2:, 2:],
    )


def pad_interior(inner: np.ndarray, shape) -> np.ndarray:
    out = np.full(shape, np.nan)
    out[1:-1, 1:-1] = inner
    return out


def finite_count_warning(z: np.ndarray, what: str) -> list[str]:
    n = int(np.isinf(z).sum())
    if n:
        z[np.isinf(z)] = np.nan
        return [f"{n:,} node(s) gave an infinite result ({what}) and were blanked."]
    return []


def nice(v: float) -> str:
    return f"{v:.6g}" if math.isfinite(v) else "—"
