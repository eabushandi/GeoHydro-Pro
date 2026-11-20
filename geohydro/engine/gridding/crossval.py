"""Leave-one-out cross-validation for any gridding method.

Each validation point is removed in turn, the method is refitted on the
remaining points with identical parameters, and the point is estimated.
Error = estimate - observed (so a positive mean error means
over-estimation).

Metrics
-------
* ME   mean error (bias)
* MAE  mean absolute error
* RMSE root mean square error
* R²   1 - SSE / SST, with SST about the mean of the observed values. It can be
       negative (estimates worse than the mean) and is reported as the
       coefficient of determination of the cross-validated estimates, not of
       a fitted regression.
* r    Pearson correlation between observed and estimated values.
* For Kriging, standardised errors e / σ: their mean (≈ 0) and mean square
  (≈ 1 when the variogram describes the data well).

For grid-only methods (Minimum Curvature) each refit solves a full grid and
the estimate is the bilinear grid value at the removed point.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..errors import GriddingError
from ..interpolation.base import prepare_points
from .grid import Grid, GridGeometry
from .methods import METHODS, build_interpolator

DEFAULT_MAX_VALIDATION = 500


@dataclass
class CrossValidationResult:
    method: str
    table: pd.DataFrame  # X, Y, observed, estimate, error, (std_error)
    metrics: dict
    n_validated: int
    n_points: int
    subsampled: bool
    warnings: list

    def to_dict(self) -> dict:
        return {"method": self.method, "metrics": self.metrics,
                "n_validated": self.n_validated, "n_points": self.n_points,
                "subsampled": self.subsampled, "warnings": self.warnings}


def metrics(observed, estimate, variance=None) -> dict:
    o = np.asarray(observed, float)
    e = np.asarray(estimate, float)
    ok = np.isfinite(o) & np.isfinite(e)
    o, e = o[ok], e[ok]
    out = {"n": int(o.size)}
    if o.size == 0:
        return out
    err = e - o
    out["mean_error"] = float(err.mean())
    out["mean_abs_error"] = float(np.abs(err).mean())
    out["rmse"] = float(np.sqrt(np.mean(err**2)))
    out["max_abs_error"] = float(np.abs(err).max())
    sst = float(np.sum((o - o.mean()) ** 2))
    out["r_squared"] = float(1 - np.sum(err**2) / sst) if sst > 0 else float("nan")
    if o.size > 2 and np.std(o) > 0 and np.std(e) > 0:
        out["pearson_r"] = float(np.corrcoef(o, e)[0, 1])
    if variance is not None:
        v = np.asarray(variance, float)[ok]
        good = np.isfinite(v) & (v > 0)
        if good.any():
            se = err[good] / np.sqrt(v[good])
            out["mean_standardised_error"] = float(se.mean())
            out["mean_squared_standardised_error"] = float(np.mean(se**2))
    return out


def leave_one_out(x, y, z, method: str, params: dict | None = None,
                  geometry: GridGeometry | None = None,
                  max_validation_points: int | None = DEFAULT_MAX_VALIDATION,
                  duplicate_tolerance: float = 0.0, duplicate_policy: str = "mean",
                  seed: int = 20261120, progress=None, cancel_check=None
                  ) -> CrossValidationResult:
    if method not in METHODS:
        raise GriddingError(f"Unknown gridding method '{method}'.")
    info = METHODS[method]
    prep = prepare_points(x, y, z, duplicate_tolerance, duplicate_policy)
    n = prep.x.size
    if n < 4:
        raise GriddingError("Cross-validation needs at least four points.")
    if info.grid_only and geometry is None:
        geometry = GridGeometry.from_points(prep.x, prep.y)
    idx = np.arange(n)
    subsampled = False
    if max_validation_points and n > max_validation_points:
        idx = np.sort(np.random.default_rng(seed).choice(n, max_validation_points, False))
        subsampled = True
    est = np.full(idx.size, np.nan)
    var = np.full(idx.size, np.nan) if info.provides_variance else None
    warnings = list(prep.warnings)
    failures = 0
    mask = np.ones(n, bool)
    for k, i in enumerate(idx):
        if cancel_check and cancel_check():
            from ..errors import CancelledError
            raise CancelledError("Cross-validation cancelled by the user.")
        if progress:
            progress(k / idx.size)
        mask[i] = False
        try:
            it = build_interpolator(method, params)
            it.fit(prep.x[mask], prep.y[mask], prep.z[mask])
            if info.grid_only:
                g = Grid(geometry, it.grid(geometry))
                est[k] = g.sample(prep.x[i:i + 1], prep.y[i:i + 1])[0]
            else:
                est[k] = it.predict(prep.x[i:i + 1], prep.y[i:i + 1])[0]
                if var is not None and it.last_variance is not None:
                    var[k] = it.last_variance[0]
        except GriddingError:
            failures += 1
        mask[i] = True
    if progress:
        progress(1.0)
    if failures:
        warnings.append(f"{failures} validation point(s) could not be estimated.")
    n_blank = int(np.isnan(est).sum()) - failures
    if n_blank > 0:
        warnings.append(
            f"{n_blank} validation point(s) had no estimate (outside the convex hull or "
            "search neighbourhood) and are excluded from the metrics."
        )
    obs = prep.z[idx]
    table = pd.DataFrame({"X": prep.x[idx], "Y": prep.y[idx], "observed": obs,
                          "estimate": est, "error": est - obs})
    if var is not None:
        table["kriging_std"] = np.sqrt(np.where(var >= 0, var, np.nan))
    m = metrics(obs, est, var)
    return CrossValidationResult(method, table, m, int(idx.size), int(n), subsampled, warnings)
