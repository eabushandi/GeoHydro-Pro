"""Experimental variograms and variogram models.

Semivariance: γ(h) = 1 / (2 N(h)) Σ [z(x_i) - z(x_i + h)]²   (Matheron's estimator)

Models (``a`` = range, ``c`` = partial sill, ``c0`` = nugget; γ(0) = 0):

=============  =================================================  =================
Model          γ(h) for h > 0                                      ``range`` meaning
=============  =================================================  =================
spherical      c0 + c [1.5 h/a - 0.5 (h/a)³] (h < a), c0 + c       actual range
exponential    c0 + c [1 - exp(-3h/a)]                             practical (95 %)
gaussian       c0 + c [1 - exp(-3h²/a²)]                           practical (95 %)
linear         c0 + s h          (``c`` holds the slope s)         -
power          c0 + s h^ω        (0 < ω < 2)                       -
nugget         c0                                                  -
=============  =================================================  =================

Anisotropy is geometric: distances are measured in the frame of
:class:`~geohydro.engine.interpolation.base.Anisotropy`, so ``range`` is the
range along the major axis and ``ratio * range`` along the minor axis.

Model fitting uses weighted least squares with Cressie's (1985) weights
``N(h) / γ_model(h)²``, iterated from ordinary-least-squares starting values,
with bounds that keep every parameter physically valid.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.distance import pdist

from ..errors import GriddingError
from .base import Anisotropy

MODELS = {
    "spherical": "Spherical",
    "exponential": "Exponential",
    "gaussian": "Gaussian",
    "linear": "Linear",
    "power": "Power",
    "nugget": "Pure nugget",
}
BOUNDED = {"spherical", "exponential", "gaussian", "nugget"}


@dataclass
class VariogramModel:
    model: str = "spherical"
    nugget: float = 0.0
    sill: float = 1.0  # partial sill c (slope s for linear / power)
    range: float = 1.0
    exponent: float = 1.5  # power model only
    anisotropy: Anisotropy = field(default_factory=Anisotropy)

    def __post_init__(self):
        if self.model not in MODELS:
            raise GriddingError(f"Unknown variogram model '{self.model}'.")
        if isinstance(self.anisotropy, dict):
            self.anisotropy = Anisotropy(**self.anisotropy)
        if self.nugget < 0 or self.sill < 0:
            raise GriddingError("Nugget and sill must be zero or positive.")
        if self.model in ("spherical", "exponential", "gaussian") and not self.range > 0:
            raise GriddingError("Variogram range must be positive.")
        if self.model == "power" and not (0 < self.exponent < 2):
            raise GriddingError("Power-model exponent must be in (0, 2).")

    @property
    def bounded(self) -> bool:
        return self.model in BOUNDED

    @property
    def total_sill(self) -> float:
        return self.nugget + (self.sill if self.model != "nugget" else 0.0)

    def __call__(self, h) -> np.ndarray:
        h = np.asarray(h, float)
        c0, c, a = self.nugget, self.sill, self.range
        m = self.model
        if m == "spherical":
            r = np.minimum(h / a, 1.0)
            g = c * (1.5 * r - 0.5 * r**3)
        elif m == "exponential":
            g = c * (1 - np.exp(-3 * h / a))
        elif m == "gaussian":
            g = c * (1 - np.exp(-3 * (h / a) ** 2))
        elif m == "linear":
            g = c * h
        elif m == "power":
            g = c * h**self.exponent
        else:
            g = np.zeros_like(h)
        return np.where(h > 0, c0 + g, 0.0)

    def covariance(self, h) -> np.ndarray:
        """C(h) = total sill - γ(h); only defined for bounded models."""
        if not self.bounded:
            raise GriddingError(f"The {self.model} model has no finite sill / covariance.")
        return self.total_sill - self(h)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["anisotropy"] = asdict(self.anisotropy)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "VariogramModel":
        d = dict(d)
        d["anisotropy"] = Anisotropy(**d.get("anisotropy", {}))
        return cls(**d)

    def describe(self) -> str:
        if self.model == "nugget":
            return f"Pure nugget, C0 = {self.nugget:.4g}"
        if self.model == "linear":
            core = f"Linear, slope = {self.sill:.4g}"
        elif self.model == "power":
            core = f"Power, scale = {self.sill:.4g}, exponent = {self.exponent:.3g}"
        else:
            core = f"{MODELS[self.model]}, sill = {self.sill:.4g}, range = {self.range:.4g}"
        s = f"{core}, nugget = {self.nugget:.4g}"
        if not self.anisotropy.isotropic:
            s += f", anisotropy ratio {self.anisotropy.ratio:.3g} at {self.anisotropy.angle:.1f}°"
        return s


@dataclass
class ExperimentalVariogram:
    lags: np.ndarray  # mean separation distance of each bin
    gamma: np.ndarray  # semivariance
    counts: np.ndarray  # number of pairs
    bin_edges: np.ndarray
    direction: float | None  # degrees CCW from +X, None = omnidirectional
    tolerance: float
    n_points: int
    n_pairs_total: int
    subsampled: bool
    variance: float  # sample variance of Z (ddof=1)

    def to_dict(self) -> dict:
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in vars(self).items()}


MAX_PAIRS_POINTS = 3000


def experimental_variogram(x, y, z, n_lags: int = 15, max_lag: float | None = None,
                           direction: float | None = None, tolerance: float = 22.5,
                           anisotropy: Anisotropy | None = None,
                           seed: int = 20261120) -> ExperimentalVariogram:
    """Compute an experimental semivariogram.

    ``max_lag`` defaults to half of the largest inter-point distance
    (data bounding-box diagonal). ``direction`` / ``tolerance`` (degrees)
    select a directional variogram; pairs whose separation azimuth lies
    within ±tolerance of the direction (modulo 180°) are used. With more
    than 3000 points a reproducible random subsample (fixed seed) is used,
    and the result says so.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    z = np.asarray(z, float)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[ok], y[ok], z[ok]
    n = x.size
    if n < 4:
        raise GriddingError("At least four points are needed for a variogram.")
    if n_lags < 2:
        raise GriddingError("At least two lag classes are needed.")
    subsampled = False
    if n > MAX_PAIRS_POINTS:
        idx = np.random.default_rng(seed).choice(n, MAX_PAIRS_POINTS, replace=False)
        x, y, z = x[idx], y[idx], z[idx]
        subsampled = True
    anis = anisotropy or Anisotropy()
    tx, ty = anis.transform(x, y, float(x.mean()), float(y.mean()))
    pts = np.column_stack([tx, ty])
    d = pdist(pts)
    sq = pdist(z[:, None], "sqeuclidean")
    if direction is not None:
        ii, jj = np.triu_indices(tx.size, 1)  # same pair order as pdist
        dxp = tx[jj] - tx[ii]
        dyp = ty[jj] - ty[ii]
        del ii, jj
        az = np.degrees(np.arctan2(dyp, dxp)) % 180.0
        diff = np.abs(az - (direction % 180.0))
        diff = np.minimum(diff, 180.0 - diff)
        keep = diff <= tolerance
        d, sq = d[keep], sq[keep]
    if max_lag is None:
        bw = max(np.ptp(tx), np.ptp(ty), 1e-300)
        max_lag = 0.5 * math.hypot(np.ptp(tx), np.ptp(ty)) or bw
    edges = np.linspace(0.0, max_lag, n_lags + 1)
    which = np.digitize(d, edges) - 1
    inb = (which >= 0) & (which < n_lags) & (d > 0)
    counts = np.bincount(which[inb], minlength=n_lags)
    sums = np.bincount(which[inb], weights=sq[inb], minlength=n_lags)
    dsum = np.bincount(which[inb], weights=d[inb], minlength=n_lags)
    with np.errstate(invalid="ignore", divide="ignore"):
        gamma = 0.5 * sums / counts
        lags = dsum / counts
    keep = counts > 0
    return ExperimentalVariogram(
        lags=lags[keep], gamma=gamma[keep], counts=counts[keep], bin_edges=edges,
        direction=direction, tolerance=tolerance, n_points=int(n),
        n_pairs_total=int(inb.sum()), subsampled=subsampled,
        variance=float(np.var(z, ddof=1)),
    )


def fit_variogram(ev: ExperimentalVariogram, model: str = "spherical",
                  nugget: bool = True, exponent: float | None = None,
                  anisotropy: Anisotropy | None = None) -> tuple[VariogramModel, dict]:
    """Fit a model to an experimental variogram (weighted least squares).

    Returns the model and a report with the weighted RSS and the bins used.
    Fitting is a convenience; the variogram should always be inspected.
    """
    if model not in MODELS:
        raise GriddingError(f"Unknown variogram model '{model}'.")
    h, g, nn = ev.lags, ev.gamma, ev.counts.astype(float)
    if h.size < 3:
        raise GriddingError("Too few non-empty lag classes to fit a model.")
    gmax = float(max(g.max(), ev.variance, 1e-300))
    hmax = float(h.max())
    anis = anisotropy or Anisotropy()

    def make(p):
        if model == "nugget":
            return VariogramModel("nugget", nugget=p[0], sill=0.0, range=1.0, anisotropy=anis)
        if model == "linear":
            return VariogramModel("linear", nugget=p[1] if nugget else 0.0, sill=p[0],
                                  anisotropy=anis)
        if model == "power":
            return VariogramModel("power", nugget=p[2] if nugget else 0.0, sill=p[0],
                                  exponent=p[1], anisotropy=anis)
        return VariogramModel(model, nugget=p[2] if nugget else 0.0, sill=p[0], range=p[1],
                              anisotropy=anis)

    if model == "nugget":
        p0, lo, hi = [float(np.average(g, weights=nn))], [0.0], [np.inf]
    elif model == "linear":
        p0, lo, hi = [gmax / hmax], [0.0], [np.inf]
    elif model == "power":
        p0, lo, hi = [gmax / hmax**1.5, 1.5 if exponent is None else exponent], [0.0, 0.01], \
            [np.inf, 1.99]
        if exponent is not None:
            lo[1] = max(exponent - 1e-9, 0.01)
            hi[1] = min(exponent + 1e-9, 1.99)
            p0[1] = exponent
    else:
        p0, lo, hi = [0.9 * gmax, 0.5 * hmax], [0.0, hmax * 1e-3], [10 * gmax, 10 * hmax]
    if nugget and model != "nugget":
        p0.append(0.1 * float(g.min()))
        lo.append(0.0)
        hi.append(gmax)

    def resid(p, weights):
        return np.sqrt(weights) * (make(p)(h) - g)

    w = nn.copy()
    res = least_squares(resid, p0, bounds=(lo, hi), args=(w,))
    for _ in range(5):  # Cressie weights, refreshed from the current fit
        gm = np.maximum(make(res.x)(h), 1e-12 * gmax)
        w = nn / gm**2
        res = least_squares(resid, res.x, bounds=(lo, hi), args=(w / w.max(),))
    m = make(res.x)
    warnings = []
    names = {"nugget": ["nugget"], "linear": ["slope", "nugget"],
             "power": ["scale", "exponent", "nugget"]}.get(model, ["sill", "range", "nugget"])
    for name, val, a, b in zip(names, res.x, lo, hi):
        if name == "nugget" or (model == "power" and exponent is not None and name == "exponent"):
            continue
        if np.isfinite(b) and val >= b * (1 - 1e-6):
            warnings.append(
                f"Fitted {name} reached its upper bound ({b:.4g}); the experimental variogram "
                "may not level off (trend or too short a lag range). Check the model visually."
            )
        if a > 0 and val <= a * (1 + 1e-6):
            warnings.append(f"Fitted {name} reached its lower bound ({a:.4g}).")
    if nugget and model != "nugget" and res.x[-1] < 1e-9 * gmax:
        m.nugget = 0.0
    report = {
        "warnings": warnings,
        "method": "Weighted least squares (Cressie weights N(h)/γ(h)²)",
        "weighted_rss": float(np.sum(w / w.max() * (m(h) - g) ** 2)),
        "bins_used": int(h.size),
        "converged": bool(res.success),
    }
    return m, report
