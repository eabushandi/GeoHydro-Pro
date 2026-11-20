"""Terrain derivatives of an elevation grid: slope, aspect, hillshade, curvature,
and profiles along a line.

Notation (grid row index increases to the north)::

    nw  n  ne
    w   c  e        Δx, Δy: node spacing in metres (see common.metric_spacing)
    sw  s  se

First derivatives (Horn 1981, the default of GDAL ``gdaldem`` and ArcGIS)::

    p = ∂z/∂x = [(ne + 2e + se) − (nw + 2w + sw)] / (8 Δx)
    q = ∂z/∂y = [(nw + 2n + ne) − (sw + 2s + se)] / (8 Δy)

    slope  S = arctan √(p² + q²)                      degrees (or percent = 100·tan S)
    aspect A = atan2(−p, −q), mapped to [0°, 360°)    direction of steepest descent,
                                                      clockwise from grid north; flat
                                                      nodes (p = q = 0) are blank
    hillshade H = 255 · max(0, cos Z cos S + sin Z sin S cos(Az − A))
               with Z the sun zenith (90° − altitude) and Az the sun azimuth;
               the Z factor exaggerates elevations before S and A are computed.

Second derivatives (Zevenbergen & Thorne 1987, 3×3 central differences)::

    zx = (e − w)/(2Δx)        zy = (n − s)/(2Δy)
    zxx = (e − 2c + w)/Δx²    zyy = (n − 2c + s)/Δy²
    zxy = (ne − nw − se + sw)/(4 Δx Δy)

    total (Laplacian)  K = zxx + zyy
    profile  Kp = (zxx zx² + 2 zxy zx zy + zyy zy²) / (zx² + zy²)
    plan     Kc = (zxx zy² − 2 zxy zx zy + zyy zx²) / (zx² + zy²)

    All in 1/m. Kp > 0: concave profile (slope flattens downhill);
    Kp < 0: convex. Kc > 0: concave contours (converging flow, hollows);
    Kc < 0: convex contours (diverging flow, spurs). Kp and Kc are the second
    derivatives of elevation along and across the gradient direction; they are
    undefined (blank) where the surface is flat. They equal the normal-section
    curvatures multiplied by (1 + tan²S)^{3/2} (Kp) or approximately so (Kc):
    below 10° slope the difference is under 5 %.

Assumptions and limits
----------------------
* Nodes on the grid edge, and nodes with a blank neighbour, are blank (the
  3×3 window must be complete), as in ``gdaldem`` without ``-compute_edges``.
* X/Y and Z are converted to metres from the grid's units; a grid whose Z unit
  is not a length is refused (a slope of mg/L has no meaning).
* For geographic (degree) grids the cell size is converted to metres row by
  row on the WGS 84 ellipsoid (more accurate than ``gdaldem``'s single scale
  factor). Aspect is then relative to true north.
* For projected grids aspect is relative to *grid* north; it differs from
  true north by the meridian convergence (within ±3° in a UTM zone).
"""

from __future__ import annotations

import numpy as np

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid

from .common import derived, metric_spacing, neighbours, pad_interior, z_to_metres


def _prep(grid: Grid, z_factor: float = 1.0):
    if grid.geometry.nx < 3 or grid.geometry.ny < 3:
        raise GridMathError("Terrain derivatives need a grid of at least 3 × 3 nodes.")
    if not z_factor > 0:
        raise GridMathError("The Z factor must be positive.")
    zf, w1 = z_to_metres(grid)
    dx, dy, w2 = metric_spacing(grid)
    z = grid.z * zf * z_factor
    if dx.shape[0] > 1:  # geographic: one spacing per row; interior rows
        dx, dy = dx[1:-1], dy[1:-1]
    return z, dx, dy, w1 + w2


def gradient_horn(grid: Grid, z_factor: float = 1.0):
    z, dx, dy, notes = _prep(grid, z_factor)
    k = neighbours(z)
    p = ((k["ne"] + 2 * k["e"] + k["se"]) - (k["nw"] + 2 * k["w"] + k["sw"])) / (8 * dx)
    q = ((k["nw"] + 2 * k["n"] + k["ne"]) - (k["sw"] + 2 * k["s"] + k["se"])) / (8 * dy)
    return p, q, notes


def slope(grid: Grid, units: str = "degrees", name: str | None = None) -> Grid:
    if units not in ("degrees", "percent"):
        raise GridMathError("Slope units must be 'degrees' or 'percent'.")
    p, q, notes = gradient_horn(grid)
    g = np.sqrt(p * p + q * q)
    inner = np.degrees(np.arctan(g)) if units == "degrees" else 100.0 * g
    out = derived(grid, pad_interior(inner, grid.geometry.shape),
                  name or f"{grid.name} slope", "terrain.slope",
                  {"algorithm": "Horn (1981)", "units": units}, notes,
                  z_units="deg" if units == "degrees" else "%",
                  z_label="Slope (°)" if units == "degrees" else "Slope (%)")
    out.metadata["method_title"] = f"Slope ({units}, Horn)"
    return out


def aspect(grid: Grid, name: str | None = None) -> Grid:
    p, q, notes = gradient_horn(grid)
    a = np.degrees(np.arctan2(-p, -q)) % 360.0
    flat = (p == 0) & (q == 0)
    a[flat] = np.nan
    n_flat = int(flat.sum())
    if n_flat:
        notes = notes + [f"{n_flat:,} flat node(s) have no aspect and are blank."]
    if grid.xy_units != "deg":
        notes = notes + ["Aspect is measured from grid north (not corrected for meridian "
                         "convergence)."]
    out = derived(grid, pad_interior(a, grid.geometry.shape), name or f"{grid.name} aspect",
                  "terrain.aspect", {"algorithm": "Horn (1981)",
                                     "convention": "downslope azimuth, clockwise from north"},
                  notes, z_units="deg", z_label="Aspect (°)")
    out.metadata["method_title"] = "Aspect (Horn)"
    return out


def hillshade(grid: Grid, azimuth: float = 315.0, altitude: float = 45.0,
              z_factor: float = 1.0, name: str | None = None) -> Grid:
    if not 0 <= altitude <= 90:
        raise GridMathError("Sun altitude must be between 0° and 90°.")
    p, q, notes = gradient_horn(grid, z_factor)
    s = np.arctan(np.sqrt(p * p + q * q))
    a = np.arctan2(-p, -q)  # downslope azimuth (radians), any value for flat nodes
    zen = np.radians(90.0 - altitude)
    az = np.radians(azimuth % 360.0)
    cosi = np.cos(zen) * np.cos(s) + np.sin(zen) * np.sin(s) * np.cos(az - a)
    inner = 255.0 * np.clip(cosi, 0.0, None)
    out = derived(grid, pad_interior(inner, grid.geometry.shape),
                  name or f"{grid.name} hillshade", "terrain.hillshade",
                  {"algorithm": "Horn (1981) gradient, Lambertian illumination",
                   "azimuth": azimuth, "altitude": altitude, "z_factor": z_factor},
                  notes, z_units="", z_label="Hillshade (0–255)")
    out.metadata["method_title"] = f"Hillshade (az {azimuth:g}°, alt {altitude:g}°)"
    return out


def curvature(grid: Grid, kind: str = "total", name: str | None = None) -> Grid:
    if kind not in ("total", "profile", "plan"):
        raise GridMathError("Curvature type must be total, profile or plan.")
    z, dx, dy, notes = _prep(grid)
    k = neighbours(z)
    zx = (k["e"] - k["w"]) / (2 * dx)
    zy = (k["n"] - k["s"]) / (2 * dy)
    zxx = (k["e"] - 2 * k["c"] + k["w"]) / dx ** 2
    zyy = (k["n"] - 2 * k["c"] + k["s"]) / dy ** 2
    zxy = (k["ne"] - k["nw"] - k["se"] + k["sw"]) / (4 * dx * dy)
    if kind == "total":
        inner = zxx + zyy
    else:
        g2 = zx * zx + zy * zy
        with np.errstate(all="ignore"):
            if kind == "profile":
                inner = (zxx * zx * zx + 2 * zxy * zx * zy + zyy * zy * zy) / g2
            else:
                inner = (zxx * zy * zy - 2 * zxy * zx * zy + zyy * zx * zx) / g2
        flat = g2 == 0
        inner[flat] = np.nan
        if flat.any():
            notes = notes + [f"{int(flat.sum()):,} flat node(s) have no {kind} curvature "
                             "and are blank."]
    out = derived(grid, pad_interior(inner, grid.geometry.shape),
                  name or f"{grid.name} {kind} curvature", f"terrain.curvature.{kind}",
                  {"algorithm": "Zevenbergen & Thorne (1987)", "kind": kind}, notes,
                  z_units="1/m", z_label=f"{kind.capitalize()} curvature (1/m)")
    out.metadata["method_title"] = f"{kind.capitalize()} curvature (Zevenbergen & Thorne)"
    return out


def profile(grid: Grid, vertices, spacing: float | None = None) -> dict:
    """Sample a grid along a polyline (bilinear).

    ``vertices`` is a sequence of (x, y) in the grid CRS. ``spacing`` is the
    distance between samples in XY units (default: half the smaller node
    spacing). Distances are planar for projected grids and geodesic (WGS 84)
    for geographic grids. Returns arrays ``distance``, ``x``, ``y``, ``z``;
    ``z`` is NaN where the line is outside the grid or crosses blank nodes.
    """
    v = np.asarray(vertices, float)
    if v.ndim != 2 or v.shape[0] < 2 or v.shape[1] != 2:
        raise GridMathError("A profile needs at least two (x, y) vertices.")
    g = grid.geometry
    step = spacing or 0.5 * min(g.dx, g.dy)
    if not step > 0:
        raise GridMathError("Sample spacing must be positive.")
    xs, ys = [v[0, 0]], [v[0, 1]]
    for (x0, y0), (x1, y1) in zip(v[:-1], v[1:]):
        L = float(np.hypot(x1 - x0, y1 - y0))
        n = max(int(np.ceil(L / step)), 1)
        t = np.arange(1, n + 1) / n
        xs.extend(x0 + t * (x1 - x0))
        ys.extend(y0 + t * (y1 - y0))
    x, y = np.array(xs), np.array(ys)
    if grid.xy_units == "deg":
        from pyproj import Geod
        _, _, d = Geod(ellps="WGS84").inv(x[:-1], y[:-1], x[1:], y[1:])
        dist = np.concatenate([[0.0], np.cumsum(d)])
        dunit = "m"
    else:
        dist = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
        dunit = grid.xy_units
    return {"distance": dist, "x": x, "y": y, "z": grid.sample(x, y), "distance_units": dunit,
            "z_units": grid.z_units, "method": "bilinear"}
