"""Descriptive statistics for point datasets.

Definitions (documented in docs/DATA_IMPORT.md):
  * std / variance use the sample estimator (ddof = 1).
  * skewness is the adjusted Fisher-Pearson coefficient (scipy, bias=False).
  * nearest-neighbour distance is the Euclidean distance in the coordinate
    units of the dataset; it is only meaningful for projected coordinates.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats as _st
from scipy.spatial import cKDTree


def describe(values) -> dict:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = int(v.size)
    out = {"count": n}
    if n == 0:
        return out
    out.update(
        minimum=float(v.min()),
        maximum=float(v.max()),
        range=float(v.max() - v.min()),
        mean=float(v.mean()),
        median=float(np.median(v)),
        q1=float(np.percentile(v, 25)),
        q3=float(np.percentile(v, 75)),
    )
    if n >= 2:
        out["std"] = float(v.std(ddof=1))
        out["variance"] = float(v.var(ddof=1))
        out["coefficient_of_variation"] = (
            float(out["std"] / out["mean"]) if out["mean"] != 0 else math.nan
        )
    if n >= 3 and np.ptp(v) > 0:
        out["skewness"] = float(_st.skew(v, bias=False))
    return out


def spatial_summary(x, y) -> dict:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = int(x.size)
    out = {"count": n}
    if n == 0:
        return out
    out.update(
        x_min=float(x.min()), x_max=float(x.max()),
        y_min=float(y.min()), y_max=float(y.max()),
        width=float(np.ptp(x)), height=float(np.ptp(y)),
    )
    area = out["width"] * out["height"]
    out["bbox_area"] = float(area)
    out["density_per_unit_area"] = float(n / area) if area > 0 else math.nan
    if n >= 2:
        tree = cKDTree(np.column_stack([x, y]))
        d, _ = tree.query(np.column_stack([x, y]), k=2)
        nn = d[:, 1]
        out["nn_mean"] = float(nn.mean())
        out["nn_min"] = float(nn.min())
        out["nn_max"] = float(nn.max())
    return out
