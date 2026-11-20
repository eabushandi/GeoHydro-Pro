"""Moving-window (neighbourhood) filters.

Each output node is computed from the nodes of a rectangular window of
``size × size`` nodes centred on it (``size`` odd). Blank nodes are ignored:
statistics use only the valid nodes inside the window, and windows at the
grid edge are truncated to the part inside the grid. A node that is blank in
the input stays blank (filters never fill gaps). ``min_valid`` (default 1)
sets how many valid nodes a window needs; nodes with fewer valid nodes in
their window are blanked (raise it to avoid statistics from very few nodes
next to gaps and at corners).

Filters
-------
mean      low-pass, arithmetic mean of the window
median    median of the window (robust to spikes)
minimum, maximum, range
std       standard deviation (n − 1) of the window
highpass  z − mean (local anomaly; residual of the low-pass)
gaussian  normalised Gaussian-weighted mean, σ given in XY units;
          weights are truncated at 4σ
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid

from .common import derived

FILTERS = ("mean", "median", "minimum", "maximum", "range", "std", "highpass", "gaussian")


def _windows(z, size):
    """Sliding windows (ny, nx, size, size) of a NaN-padded copy (view, no copy)."""
    r = size // 2
    pad = np.pad(z, r, constant_values=np.nan)
    return np.lib.stride_tricks.sliding_window_view(pad, (size, size))


def _reduce_chunked(z, size, fn):
    out = np.empty(z.shape)
    win = _windows(z, size)
    step = max(1, 2_000_000 // max(z.shape[1] * size * size, 1))
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows → NaN
            for j0 in range(0, z.shape[0], step):
                w = win[j0:j0 + step].reshape(win[j0:j0 + step].shape[:2] + (-1,))
                out[j0:j0 + step] = fn(w, axis=-1)
    return out


def apply_filter(grid: Grid, kind: str, size: int = 3, sigma: float | None = None,
                 min_valid: int | None = None, passes: int = 1, name: str | None = None) -> Grid:
    if kind not in FILTERS:
        raise GridMathError(f"Unknown filter '{kind}'. Choose one of: {', '.join(FILTERS)}.")
    if kind != "gaussian":
        if size < 3 or size % 2 == 0:
            raise GridMathError("The window size must be an odd number of nodes, 3 or more.")
        if size > min(grid.geometry.nx, grid.geometry.ny):
            raise GridMathError("The window is larger than the grid.")
    passes = int(passes)
    if passes < 1 or passes > 20:
        raise GridMathError("Number of passes must be between 1 and 20.")
    z0 = grid.z
    blank = np.isnan(z0)
    z = z0.copy()
    warnings = []
    g = grid.geometry
    for _ in range(passes):
        valid = np.isfinite(z)
        if kind == "gaussian":
            if sigma is None or not sigma > 0:
                raise GridMathError("Gaussian filter needs a positive σ (in XY units).")
            s = (sigma / g.dy, sigma / g.dx)
            num = ndimage.gaussian_filter(np.where(valid, z, 0.0), s, mode="constant",
                                          truncate=4.0)
            den = ndimage.gaussian_filter(valid.astype(float), s, mode="constant",
                                          truncate=4.0)
            with np.errstate(all="ignore"):
                res = num / den
            res[den < 1e-12] = np.nan
            count = None
        else:
            k = np.ones((size, size))
            count = ndimage.convolve(valid.astype(float), k, mode="constant", cval=0.0)
            if kind in ("mean", "highpass"):
                s1 = ndimage.convolve(np.where(valid, z, 0.0), k, mode="constant", cval=0.0)
                with np.errstate(all="ignore"):
                    mean = s1 / count
                res = mean if kind == "mean" else z - mean
            elif kind == "std":
                res = _reduce_chunked(z, size, lambda w, axis: np.nanstd(w, axis=axis, ddof=1))
            elif kind == "median":
                res = _reduce_chunked(z, size, np.nanmedian)
            elif kind == "minimum":
                res = _reduce_chunked(z, size, np.nanmin)
            elif kind == "maximum":
                res = _reduce_chunked(z, size, np.nanmax)
            else:  # range
                res = _reduce_chunked(z, size, np.nanmax) - _reduce_chunked(z, size, np.nanmin)
            need = 1 if min_valid is None else int(min_valid)
            res = np.where(count >= need, res, np.nan)
        res[blank] = np.nan
        z = res
    n_lost = int((np.isnan(z) & ~blank).sum())
    if n_lost:
        warnings.append(f"{n_lost:,} node(s) had too few valid neighbours and were blanked.")
    params = {"filter": kind, "passes": passes}
    if kind == "gaussian":
        params["sigma"] = sigma
    else:
        params.update(size=size, min_valid=1 if min_valid is None else int(min_valid))
    label = f"{kind} {size}×{size}" if kind != "gaussian" else f"gaussian σ={sigma:g}"
    out = derived(grid, z, name or f"{grid.name} ({label})", f"grid_math.filter.{kind}", params,
                  warnings, z_units=None if kind != "std" else grid.z_units)
    out.metadata["method_title"] = f"Filter: {label}" + (f", {passes} passes" if passes > 1 else "")
    out.z_label = grid.z_label
    return out
