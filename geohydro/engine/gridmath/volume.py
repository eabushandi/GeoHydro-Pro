"""Volumes and areas between an upper surface and a lower surface.

The upper surface is a grid; the lower surface is a constant level or a
second grid (resampled to the upper grid's geometry if needed). With
d = upper − lower at every node:

    net volume   V = ∬ d dA
    cut  (positive) volume  V⁺ = ∬ max(d, 0) dA   (upper above lower)
    fill (negative) volume  V⁻ = ∬ max(−d, 0) dA  (upper below lower)
    V = V⁺ − V⁻

Integration rules (tensor products of the 1-D rules along X and Y)
------------------------------------------------------------------
trapezoidal   weights h/2·(1, 2, 2, …, 2, 1). Exact for surfaces that are
              bilinear between nodes; error O(h²) for smooth surfaces.
simpson       composite Simpson 1/3, weights h/3·(1, 4, 2, 4, …, 4, 1).
              Exact for polynomials up to cubic in each direction; error
              O(h⁴). With an odd number of intervals, the last three
              intervals use Simpson's 3/8 rule (also exact for cubics).
simpson38     composite Simpson 3/8, weights 3h/8·(1, 3, 3, 2, 3, 3, 2, …, 1),
              with a Simpson 1/3 (or trapezoidal) end panel when the number
              of intervals is not a multiple of three.

V⁺ and V⁻ apply the same rule to max(d, 0) and max(−d, 0), as Surfer does.
Where d changes sign between two nodes, the clipped integrand has a kink, so
V⁺ and V⁻ carry an extra discretisation error of order h² along the zero
line, whatever the rule; V is not affected. Refine the grid if the
difference between rules matters.

Blank nodes
-----------
Simpson rules need a complete grid. The trapezoidal rule is computed cell by
cell (each cell's volume = cell area × mean of its four corner values) over
the cells whose four corners are all valid; on a complete grid this equals
the tensor-product trapezoidal rule exactly. Cells touching a blank node are
excluded and reported.

Areas
-----
planar area   area of the included cells (cells with four valid corners).
surface area  sum over the included cells of the areas of the two triangles
              spanned by the corner nodes (diagonal SW–NE) in 3-D, using the
              upper surface in metres.
cut/fill area area of the included cells, split per cell in proportion to the
              number of corners above/below (an estimate; reported as such).

Units: XY and Z are converted to metres when they are length units, so
volumes are in m³ and areas in m²; for geographic grids the cell areas use
the WGS 84 metric spacing of each row (see common.metric_spacing).
"""

from __future__ import annotations

import numpy as np

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid

from .common import check_crs, metric_spacing, resample, same_geometry, z_to_metres

METHODS = ("trapezoidal", "simpson", "simpson38")


def weights_1d(n: int, h: float, method: str) -> np.ndarray:
    """1-D quadrature weights for ``n`` equally spaced nodes with spacing ``h``."""
    m = n - 1  # intervals
    w = np.zeros(n)
    if m < 1:
        raise GridMathError("At least two nodes are needed in each direction.")

    def trap(i0, i1):
        w[i0] += h / 2
        w[i1] += h / 2

    def simp13(i0, k):  # k intervals (even) from i0
        for s in range(i0, i0 + k, 2):
            w[s] += h / 3
            w[s + 1] += 4 * h / 3
            w[s + 2] += h / 3

    def simp38(i0, k):  # k intervals (multiple of 3) from i0
        for s in range(i0, i0 + k, 3):
            w[s] += 3 * h / 8
            w[s + 1] += 9 * h / 8
            w[s + 2] += 9 * h / 8
            w[s + 3] += 3 * h / 8

    if method == "trapezoidal" or m == 1:
        for i in range(m):
            trap(i, i + 1)
    elif method == "simpson":
        if m % 2 == 0:
            simp13(0, m)
        elif m >= 3:
            simp13(0, m - 3)
            simp38(m - 3, 3)
    elif method == "simpson38":
        r = m % 3
        simp38(0, m - r)
        if r == 2:
            simp13(m - 2, 2)
        elif r == 1:
            trap(m - 1, m)
    else:
        raise GridMathError(f"Unknown integration method '{method}'.")
    return w


def volume(upper: Grid, lower: Grid | float = 0.0, method: str = "trapezoidal",
           resampling: str = "bilinear") -> dict:
    """Cut, fill and net volume between ``upper`` and ``lower``. See module docs."""
    if method not in METHODS:
        raise GridMathError(f"Method must be one of {', '.join(METHODS)}.")
    warnings: list[str] = []
    zf, w = z_to_metres(upper)
    warnings += w
    zu = upper.z * zf
    if isinstance(lower, Grid):
        check_crs([upper, lower])
        lg = lower
        if not same_geometry(lower.geometry, upper.geometry):
            lg = resample(lower, upper.geometry, resampling)
            warnings.append(f"Lower grid '{lower.name}' was resampled ({resampling}) to the "
                            f"geometry of '{upper.name}'.")
        zfl, w = z_to_metres(lower)
        warnings += w
        zl = lg.z * zfl
        lower_desc = {"grid_id": lower.id, "grid_name": lower.name}
    else:
        if not np.isfinite(lower):
            raise GridMathError("The lower level must be a number.")
        zl = np.full(zu.shape, float(lower) * zf)
        lower_desc = {"level": float(lower), "units": upper.z_units}
    d = zu - zl
    dxm, dym, w = metric_spacing(upper)
    warnings += w
    g = upper.geometry
    valid = np.isfinite(d)
    cell_ok = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    # cell areas (rows: dy per row-pair from the mean latitude for geographic grids)
    dx_rows = np.broadcast_to(dxm, (g.ny, 1))[:, 0]
    dy_rows = np.broadcast_to(dym, (g.ny, 1))[:, 0]
    cell_dx = 0.5 * (dx_rows[:-1] + dx_rows[1:])
    cell_dy = 0.5 * (dy_rows[:-1] + dy_rows[1:])
    cell_area = (cell_dx * cell_dy)[:, None] * np.ones((1, g.nx - 1))
    complete = bool(valid.all())
    if method != "trapezoidal" and not complete:
        raise GridMathError(f"The {method} rule needs a grid without blank nodes "
                            f"({int((~valid).sum()):,} blank). Use the trapezoidal rule.")

    def integrate(f):
        if method == "trapezoidal":
            corner = np.where(valid, f, 0.0)
            mean = 0.25 * (corner[:-1, :-1] + corner[1:, :-1] + corner[:-1, 1:] + corner[1:, 1:])
            return float(np.sum(np.where(cell_ok, mean * cell_area, 0.0)))
        if upper.xy_units == "deg":  # rows have different dx: weight per row
            wy = weights_1d(g.ny, 1.0, method)
            wx = weights_1d(g.nx, 1.0, method)
            return float(np.sum(wy[:, None] * wx[None, :] * f * (dx_rows * dy_rows)[:, None]))
        wy = weights_1d(g.ny, float(dym.ravel()[0]), method)
        wx = weights_1d(g.nx, float(dxm.ravel()[0]), method)
        return float(wy @ f @ wx)

    pos = integrate(np.maximum(d, 0.0))
    neg = integrate(np.maximum(-d, 0.0))
    net = integrate(d)
    planar = float(np.sum(np.where(cell_ok, cell_area, 0.0)))
    # 3-D surface area of the upper surface (two triangles per cell)
    zz = np.where(np.isfinite(zu), zu, 0.0)
    z00, z10, z01, z11 = zz[:-1, :-1], zz[:-1, 1:], zz[1:, :-1], zz[1:, 1:]
    cdx, cdy = cell_dx[:, None], cell_dy[:, None]

    def tri(ax, ay, az, bx, by, bz):
        cx = ay * bz - az * by
        cy = az * bx - ax * bz
        cz = ax * by - ay * bx
        return 0.5 * np.sqrt(cx * cx + cy * cy + cz * cz)

    zero = np.zeros_like(z00)
    t1 = tri(cdx + zero, zero, z10 - z00, cdx + zero, cdy + zero, z11 - z00)
    t2 = tri(cdx + zero, cdy + zero, z11 - z00, zero, cdy + zero, z01 - z00)
    surface = float(np.sum(np.where(cell_ok, t1 + t2, 0.0)))
    above = (np.where(valid, d > 0, False)).astype(float)
    frac_above = 0.25 * (above[:-1, :-1] + above[1:, :-1] + above[:-1, 1:] + above[1:, 1:])
    below = (np.where(valid, d < 0, False)).astype(float)
    frac_below = 0.25 * (below[:-1, :-1] + below[1:, :-1] + below[:-1, 1:] + below[1:, 1:])
    n_excluded = int((~cell_ok).sum())
    if n_excluded:
        warnings.append(f"{n_excluded:,} of {cell_ok.size:,} cells touch a blank node and are "
                        "excluded from volumes and areas.")
    crossing = int(np.sum(cell_ok & (frac_above > 0) & (frac_below > 0)))
    if crossing:
        warnings.append(f"{crossing:,} cells contain the zero line (upper = lower); cut and fill "
                        "volumes there carry an additional discretisation error. Net volume "
                        "is unaffected.")
    return {
        "method": method, "upper": {"grid_id": upper.id, "grid_name": upper.name},
        "lower": lower_desc, "cut_volume": pos, "fill_volume": neg, "net_volume": net,
        "check_cut_minus_fill": pos - neg,
        "planar_area": planar, "surface_area": surface,
        "cut_area": float(np.sum(np.where(cell_ok, frac_above * cell_area, 0.0))),
        "fill_area": float(np.sum(np.where(cell_ok, frac_below * cell_area, 0.0))),
        "cells_used": int(cell_ok.sum()), "cells_excluded": n_excluded,
        "volume_units": "m³", "area_units": "m²", "warnings": warnings,
    }


def volume_report(res: dict) -> str:
    def f(v):
        return f"{v:,.3f}"
    lower = res["lower"].get("grid_name") or f"level {res['lower']['level']:g} {res['lower']['units']}"
    lines = [f"Volume of '{res['upper']['grid_name']}' relative to {lower}",
             f"Integration: {res['method']}",
             f"Cut (positive) volume:  {f(res['cut_volume'])} m³",
             f"Fill (negative) volume: {f(res['fill_volume'])} m³",
             f"Net volume (cut − fill): {f(res['net_volume'])} m³",
             f"Planar area: {f(res['planar_area'])} m²   Surface area: {f(res['surface_area'])} m²",
             f"Cut area ≈ {f(res['cut_area'])} m²   Fill area ≈ {f(res['fill_area'])} m² (estimate)",
             f"Cells used: {res['cells_used']:,}, excluded: {res['cells_excluded']:,}"]
    lines += [f"Note: {w}" for w in res["warnings"]]
    return "\n".join(lines)
