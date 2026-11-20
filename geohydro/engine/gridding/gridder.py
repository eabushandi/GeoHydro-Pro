"""Grid point data with any registered method, with blanking and residual analysis."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import Delaunay, QhullError, cKDTree

from ... import __version__
from ..errors import GriddingError
from ..interpolation.base import prepare_points
from .grid import Grid, GridGeometry
from .methods import METHODS, build_interpolator


@dataclass
class BlankingOptions:
    """Which nodes to blank (set to NoData) after interpolation.

    ``outside_hull``: blank nodes outside the convex hull of the data.
    ``max_distance``: blank nodes farther than this from the nearest data
    point (data units; ``None`` = off).
    """

    outside_hull: bool = False
    max_distance: float | None = None

    def to_dict(self):
        return {"outside_hull": self.outside_hull, "max_distance": self.max_distance}


@dataclass
class GriddingRequest:
    method: str
    params: dict = field(default_factory=dict)
    geometry: GridGeometry | None = None
    blanking: BlankingOptions = field(default_factory=BlankingOptions)
    duplicate_tolerance: float = 0.0
    duplicate_policy: str = "mean"
    variance_grid: bool = False  # also return the kriging variance grid


@dataclass
class GriddingResult:
    grid: Grid
    variance: Grid | None
    residuals: dict
    warnings: list[str]


def residual_analysis(grid: Grid, x, y, z) -> dict:
    """Compare the grid (bilinear) with the data it was made from.

    ``residual = observed - grid``. Points outside the grid or on blank
    cells are counted but excluded from the statistics.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    z = np.asarray(z, float)
    est = grid.sample(x, y)
    ok = np.isfinite(est) & np.isfinite(z)
    r = z[ok] - est[ok]
    out = {"points": int(z.size), "compared": int(ok.sum()),
           "not_compared": int(z.size - ok.sum())}
    if r.size:
        out.update(mean_error=float(r.mean()), mean_abs_error=float(np.abs(r).mean()),
                   rmse=float(np.sqrt(np.mean(r**2))), max_abs_error=float(np.abs(r).max()))
    return out, np.where(ok, z - np.where(ok, est, 0.0), np.nan)


def apply_blanking(z: np.ndarray, geometry: GridGeometry, x, y,
                   opts: BlankingOptions) -> tuple[np.ndarray, int]:
    z = z.copy()
    before = int(np.isnan(z).sum())
    X, Y = geometry.mesh()
    q = np.column_stack([X.ravel(), Y.ravel()])
    if opts.outside_hull:
        try:
            tri = Delaunay(np.column_stack([x, y]))
            outside = tri.find_simplex(q) < 0
            z.ravel()[outside] = np.nan
        except QhullError:
            pass
    if opts.max_distance:
        d, _ = cKDTree(np.column_stack([x, y])).query(q)
        z.ravel()[d > opts.max_distance] = np.nan
    return z, int(np.isnan(z).sum()) - before


def grid_data(x, y, z, request: GriddingRequest, *, name: str = "Grid",
              crs: str | None = None, xy_units: str = "m", z_units: str = "m",
              z_label: str = "Z", source: dict | None = None,
              progress=None, cancel_check=None) -> GriddingResult:
    """Interpolate scattered points onto a regular grid.

    The returned grid's ``metadata`` records the method, its full
    parameters (including any value chosen automatically), the data
    preparation, blanking, residuals and software version, so that the
    result is reproducible and auditable.
    """
    t0 = time.perf_counter()
    if request.method not in METHODS:
        raise GriddingError(f"Unknown gridding method '{request.method}'.")
    info = METHODS[request.method]
    prep = prepare_points(x, y, z, request.duplicate_tolerance, request.duplicate_policy)
    warnings = list(prep.warnings)
    if prep.x.size == 0:
        raise GriddingError("No points with valid X, Y and Z.")
    geom = request.geometry or GridGeometry.from_points(prep.x, prep.y)
    interp = build_interpolator(request.method, request.params)

    def prog(f):
        if progress:
            progress(0.05 + 0.85 * f)

    interp.progress = prog
    interp.cancel_check = cancel_check
    interp.fit(prep.x, prep.y, prep.z)
    variance = None
    if info.grid_only:
        zz = interp.grid(geom)
        if getattr(interp, "residuals", None):
            if interp.residuals.get("points_outside_grid"):
                warnings.append(
                    f"{interp.residuals['points_outside_grid']} point(s) lie outside the grid "
                    "limits and were not used by Minimum Curvature."
                )
    else:
        X, Y = geom.mesh()
        zz = interp.predict(X, Y)
        if request.variance_grid and interp.provides_variance:
            variance = interp.last_variance
    warnings += list(getattr(interp, "warnings", []) or [])  # after prediction (counts)
    zz, n_blanked = apply_blanking(zz, geom, prep.x, prep.y, request.blanking)
    if variance is not None:
        variance = np.where(np.isnan(zz), np.nan, variance)
    if progress:
        progress(0.95)
    if np.isnan(zz).all():
        raise GriddingError(
            "Every grid node is blank. Check the grid limits, search radius and blanking."
        )
    meta = {
        "method": request.method,
        "method_title": info.title,
        "parameters": interp.parameters(),
        "requested_parameters": request.params,
        "data_preparation": {
            "points_input": prep.n_input, "points_invalid": prep.n_invalid,
            "points_merged": prep.n_merged, "points_used": int(prep.x.size),
            "duplicate_tolerance": request.duplicate_tolerance,
            "duplicate_policy": request.duplicate_policy,
        },
        "blanking": {**request.blanking.to_dict(), "nodes_blanked": n_blanked},
        "source": source or {},
        "software": f"GeoHydro Pro {__version__}",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "warnings": warnings,
    }
    grid = Grid(geom, zz, name=name, crs=crs, xy_units=xy_units, z_units=z_units,
                z_label=z_label, metadata=meta)
    res, _ = residual_analysis(grid, prep.x, prep.y, prep.z)
    meta["residuals"] = res
    if getattr(interp, "residuals", None):
        meta["solver"] = interp.residuals
    meta["elapsed_seconds"] = round(time.perf_counter() - t0, 3)
    vgrid = None
    if variance is not None:
        vgrid = Grid(geom, variance, name=f"{name} (kriging variance)", crs=crs,
                     xy_units=xy_units, z_units=f"({z_units})²", z_label="Kriging variance",
                     metadata={"method": request.method, "derived_from": grid.id,
                               "quantity": "kriging variance"})
    if progress:
        progress(1.0)
    return GriddingResult(grid, vgrid, res, warnings)
