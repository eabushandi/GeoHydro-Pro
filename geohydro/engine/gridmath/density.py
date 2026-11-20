"""Point density: kernel density estimation (KDE) and point counts per cell.

Kernel density
--------------
For points x_i with weights w_i (default 1), the density at a grid node x is

    λ(x) = Σ_i w_i · K_h(‖x − x_i‖)

with a radially symmetric 2-D kernel K_h that integrates to 1 over the
plane, so λ is an *intensity*: expected (weighted) number of points per unit
area, and ∬ λ dA = Σ w_i when all kernels lie inside the grid. With
``normalize="probability"`` λ is divided by Σ w_i (a probability density,
integral 1). Kernels (r = distance, h = bandwidth):

    uniform       K = 1/(π h²)                        r < h
    triangular    K = 3/(π h²) · (1 − r/h)            r < h   (cone)
    epanechnikov  K = 2/(π h²) · (1 − r²/h²)          r < h
    quartic       K = 3/(π h²) · (1 − r²/h²)²         r < h   (biweight; as ArcGIS/QGIS)
    gaussian      K = 1/(2π h²) · exp(−r²/(2h²))      h = σ, evaluated to r = 5h

The Gaussian is evaluated out to 5σ; the omitted mass is exp(−12.5) ≈ 3.7·10⁻⁶
of each kernel (documented truncation). Distances are planar in the grid
CRS; a geographic (degree) CRS is refused, because a bandwidth in degrees is
not a distance. No edge correction is applied: near the edge of the study
area density is underestimated because part of each kernel falls outside.

Bandwidth rules of thumb (data-driven starting points, not optimal values):

    scott              h = σ̄ · n^(−1/6), σ̄ = √((σx² + σy²)/2)
                       (Scott 1992; equal to Silverman's rule in 2-D)
    standard_distance  h = 0.9 · min(SD, √(1/ln 2) · Dm) · n^(−0.2)
                       SD = standard distance, Dm = median distance to the
                       mean centre (the rule used by ArcGIS Kernel Density)

Point counts
------------
``point_count`` counts the points in the cell of side Δx × Δy centred on
each node (a point exactly on a cell boundary belongs to the cell to its
north-east), and can divide by the cell area to give points per unit area.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid, GridGeometry

KERNELS = ("quartic", "epanechnikov", "triangular", "uniform", "gaussian")
BANDWIDTH_RULES = ("scott", "standard_distance")
GAUSS_CUTOFF = 5.0


def kernel_value(kind: str, r: np.ndarray, h: float) -> np.ndarray:
    u = r / h
    if kind == "uniform":
        return np.where(u < 1, 1.0 / (math.pi * h * h), 0.0)
    if kind == "triangular":
        return np.where(u < 1, 3.0 / (math.pi * h * h) * (1 - u), 0.0)
    if kind == "epanechnikov":
        return np.where(u < 1, 2.0 / (math.pi * h * h) * (1 - u * u), 0.0)
    if kind == "quartic":
        return np.where(u < 1, 3.0 / (math.pi * h * h) * (1 - u * u) ** 2, 0.0)
    if kind == "gaussian":
        return np.where(u <= GAUSS_CUTOFF, np.exp(-0.5 * u * u) / (2 * math.pi * h * h), 0.0)
    raise GridMathError(f"Unknown kernel '{kind}'. Choose one of {', '.join(KERNELS)}.")


def bandwidth(x, y, rule: str = "scott", weights=None) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = x.size
    if n < 2:
        raise GridMathError("At least two points are needed to estimate a bandwidth.")
    w = np.ones(n) if weights is None else np.asarray(weights, float)
    W = w.sum()
    mx, my = np.sum(w * x) / W, np.sum(w * y) / W
    vx, vy = np.sum(w * (x - mx) ** 2) / W, np.sum(w * (y - my) ** 2) / W
    if rule == "scott":
        h = math.sqrt((vx + vy) / 2) * n ** (-1 / 6)
    elif rule == "standard_distance":
        sd = math.sqrt(vx + vy)
        dm = float(np.median(np.hypot(x - mx, y - my)))
        h = 0.9 * min(sd, math.sqrt(1 / math.log(2)) * dm) * n ** (-0.2)
    else:
        raise GridMathError(f"Unknown bandwidth rule '{rule}'.")
    if not h > 0:
        raise GridMathError("All points coincide; the bandwidth cannot be estimated.")
    return float(h)


def _prepare(x, y, weights, crs_units):
    if crs_units == "deg":
        raise GridMathError("Point density needs projected coordinates (a bandwidth in degrees "
                            "is not a distance). Reproject the points first.")
    x, y = np.asarray(x, float), np.asarray(y, float)
    w = np.ones(x.size) if weights is None else np.asarray(weights, float)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(w)
    if (w[ok] < 0).any():
        raise GridMathError("Weights must not be negative.")
    return x[ok], y[ok], w[ok], int((~ok).sum())


def kernel_density(x, y, geometry: GridGeometry, h: float | str = "scott",
                   kernel: str = "quartic", weights=None, normalize: str = "intensity",
                   area_unit_factor: float = 1.0, crs: str | None = None,
                   xy_units: str = "m", name: str = "Point density",
                   source: dict | None = None) -> Grid:
    """Kernel density on the nodes of ``geometry``. See the module documentation.

    ``area_unit_factor`` rescales the result, e.g. 1e6 to report points per
    km² when coordinates are in metres.
    """
    if kernel not in KERNELS:
        raise GridMathError(f"Unknown kernel '{kernel}'. Choose one of {', '.join(KERNELS)}.")
    if normalize not in ("intensity", "probability"):
        raise GridMathError("normalize must be 'intensity' or 'probability'.")
    x, y, w, n_bad = _prepare(x, y, weights, xy_units)
    if x.size == 0:
        raise GridMathError("No points with valid coordinates.")
    rule = None
    if isinstance(h, str):
        rule = h
        h = bandwidth(x, y, rule, w)
    h = float(h)
    if not h > 0:
        raise GridMathError("The bandwidth must be positive.")
    reach = h * (GAUSS_CUTOFF if kernel == "gaussian" else 1.0)
    X, Y = geometry.mesh()
    nodes = np.column_stack([X.ravel(), Y.ravel()])
    dens = np.zeros(nodes.shape[0])
    tree_nodes = cKDTree(nodes)
    chunk = max(1, int(5_000_000 / max(math.pi * (reach / geometry.dx) * (reach / geometry.dy), 1)))
    for i0 in range(0, x.size, chunk):
        pts = np.column_stack([x[i0:i0 + chunk], y[i0:i0 + chunk]])
        sdm = cKDTree(pts).sparse_distance_matrix(tree_nodes, reach, output_type="coo_matrix")
        # the COO output keeps zero distances (point exactly on a node)
        vals = kernel_value(kernel, sdm.data, h) * w[i0:i0 + chunk][sdm.row]
        np.add.at(dens, sdm.col, vals)
    if normalize == "probability":
        dens /= w.sum()
    dens *= area_unit_factor
    z = dens.reshape(geometry.shape)
    warnings = ["No edge correction: density is underestimated within one bandwidth of the "
                "edge of the study area."]
    if n_bad:
        warnings.append(f"{n_bad:,} point(s) without valid coordinates or weight were skipped.")
    g = geometry
    if h < max(g.dx, g.dy):
        warnings.append(f"The bandwidth ({h:.4g}) is smaller than the grid spacing; the "
                        "surface will be spiky. Use a finer grid or a larger bandwidth.")
    integral = float(z.sum() * g.dx * g.dy / area_unit_factor)
    expected = float(w.sum()) if normalize == "intensity" else 1.0
    units = "probability per unit area" if normalize == "probability" else \
        ("points per unit area" if weights is None else "weight per unit area")
    md = {"method": "kernel_density", "method_title": f"Kernel density ({kernel}, h = {h:.4g})",
          "parameters": {"kernel": kernel, "bandwidth": h, "bandwidth_rule": rule,
                         "normalize": normalize, "weighted": weights is not None,
                         "area_unit_factor": area_unit_factor, "n_points": int(x.size)},
          "source": source or {}, "warnings": warnings,
          "check": {"grid_integral": integral, "expected_integral_if_no_edge_loss": expected}}
    return Grid(geometry, z, name=name, crs=crs, xy_units=xy_units, z_units=units,
                z_label="Density", metadata=md)


def point_count(x, y, geometry: GridGeometry, weights=None, per_area: bool = False,
                crs: str | None = None, xy_units: str = "m", name: str = "Point count",
                source: dict | None = None) -> Grid:
    x, y, w, n_bad = _prepare(x, y, weights, "m" if not per_area else xy_units)
    g = geometry
    i = np.floor((x - g.x_min) / g.dx + 0.5).astype(int)
    j = np.floor((y - g.y_min) / g.dy + 0.5).astype(int)
    ok = (i >= 0) & (i < g.nx) & (j >= 0) & (j < g.ny)
    z = np.zeros(g.shape)
    np.add.at(z, (j[ok], i[ok]), w[ok])
    if per_area:
        z /= g.dx * g.dy
    warnings = []
    if (~ok).sum():
        warnings.append(f"{int((~ok).sum()):,} point(s) fall outside the grid cells.")
    if n_bad:
        warnings.append(f"{n_bad:,} point(s) without valid coordinates were skipped.")
    md = {"method": "point_count", "method_title": "Point count per cell"
          + (" per unit area" if per_area else ""),
          "parameters": {"per_area": per_area, "weighted": weights is not None},
          "source": source or {}, "warnings": warnings}
    return Grid(geometry, z, name=name, crs=crs, xy_units=xy_units,
                z_units="points per unit area" if per_area else "points",
                z_label="Count", metadata=md)
