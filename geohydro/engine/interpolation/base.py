"""Shared infrastructure for interpolation methods.

Every method implements :class:`Interpolator`:

* ``fit(x, y, z)`` stores the data (after :func:`prepare_points`).
* ``predict(xq, yq)`` returns estimates (NaN where the method gives none).
* methods that provide an estimation variance (Kriging) also fill
  ``self.last_variance`` after ``predict``.

Distances in search neighbourhoods and in anisotropic methods are computed
in a transformed coordinate frame (see :class:`Anisotropy`).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from ..errors import CancelledError, GriddingError


@dataclass
class Anisotropy:
    """Geometric anisotropy.

    ``angle`` is the direction of the *major* axis in degrees,
    counter-clockwise from the +X (east) axis. ``ratio`` is
    minor-axis range / major-axis range (0 < ratio <= 1). ``ratio = 1``
    is isotropic.

    Transform: rotate by ``-angle`` so the major axis lies on X', then
    divide Y' by ``ratio``. Distances in the transformed frame are
    "isotropic-equivalent" distances measured along the major axis.
    """

    ratio: float = 1.0
    angle: float = 0.0

    def __post_init__(self):
        if not (0 < self.ratio <= 1):
            raise GriddingError("Anisotropy ratio must be in (0, 1].")

    @property
    def isotropic(self) -> bool:
        return self.ratio == 1.0

    def transform(self, x, y, x0: float = 0.0, y0: float = 0.0):
        x = np.asarray(x, float) - x0
        y = np.asarray(y, float) - y0
        if self.isotropic:
            return x, y
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        xr = c * x + s * y
        yr = (-s * x + c * y) / self.ratio
        return xr, yr


@dataclass
class SearchParams:
    """Neighbourhood used by local methods.

    ``radius``: search radius in data units along the major axis
    (``None`` = unlimited). ``max_points``: maximum neighbours used
    (``None`` = all). ``min_points``: fewer neighbours than this gives a
    blank (NaN) node.
    """

    radius: float | None = None
    max_points: int | None = 64
    min_points: int = 1

    def __post_init__(self):
        if self.radius is not None and not self.radius > 0:
            raise GriddingError("Search radius must be positive.")
        if self.max_points is not None and self.max_points < 1:
            raise GriddingError("Maximum number of neighbours must be at least 1.")
        if self.min_points < 1:
            raise GriddingError("Minimum number of neighbours must be at least 1.")
        if self.max_points is not None and self.min_points > self.max_points:
            raise GriddingError("Minimum neighbours cannot exceed maximum neighbours.")


@dataclass
class PreparedPoints:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    n_input: int
    n_invalid: int  # rows dropped because X, Y or Z is missing / non-finite
    n_merged: int  # rows merged into coincident locations
    warnings: list[str] = field(default_factory=list)


def prepare_points(x, y, z, duplicate_tolerance: float = 0.0,
                   duplicate_policy: str = "mean") -> PreparedPoints:
    """Drop invalid rows and merge coincident points.

    Points closer than ``duplicate_tolerance`` (exact matches when 0) are
    merged into one, located at the first point of the group, with Z taken
    by ``duplicate_policy``: ``mean``, ``median``, ``first``, ``min`` or
    ``max``. Merging is required because coincident points with different Z
    make exact interpolators (triangulation, Kriging, RBF) singular. The
    count is reported - never silent.
    """
    x = np.asarray(x, float).ravel()
    y = np.asarray(y, float).ravel()
    z = np.asarray(z, float).ravel()
    if not (x.size == y.size == z.size):
        raise GriddingError("X, Y and Z must have the same length.")
    n_input = x.size
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[ok], y[ok], z[ok]
    warnings = []
    n_invalid = int(n_input - ok.sum())
    if n_invalid:
        warnings.append(f"{n_invalid} point(s) without valid X, Y and Z were excluded.")
    n_merged = 0
    if x.size > 1:
        pts = np.column_stack([x, y])
        labels = None
        if duplicate_tolerance > 0:
            pairs = cKDTree(pts).query_pairs(duplicate_tolerance, output_type="ndarray")
            if len(pairs):
                from scipy.sparse import coo_matrix
                from scipy.sparse.csgraph import connected_components
                n = x.size
                adj = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])),
                                 shape=(n, n))
                _, labels = connected_components(adj, directed=False)
        else:
            _, inv, counts = np.unique(pts, axis=0, return_inverse=True, return_counts=True)
            if (counts > 1).any():
                labels = inv.ravel()
        if labels is not None:
            x, y, z, n_merged = _merge(x, y, z, labels, duplicate_policy)
            if n_merged:
                warnings.append(
                    f"{n_merged} coincident point(s) merged into existing locations "
                    f"(Z = {duplicate_policy} of each group)."
                )
    return PreparedPoints(x, y, z, n_input, n_invalid, n_merged, warnings)


def _merge(x, y, z, labels, policy):
    func = {"mean": np.mean, "median": np.median, "min": np.min, "max": np.max,
            "first": lambda a: a[0]}.get(policy)
    if func is None:
        raise GriddingError(f"Unknown duplicate policy '{policy}'.")
    order = np.argsort(labels, kind="stable")
    lab = labels[order]
    starts = np.flatnonzero(np.r_[True, lab[1:] != lab[:-1]])
    ends = np.r_[starts[1:], lab.size]
    nx_, ny_, nz_ = [], [], []
    for s, e in zip(starts, ends):
        idx = order[s:e]
        nx_.append(x[idx[0]])
        ny_.append(y[idx[0]])
        nz_.append(float(func(z[idx])))
    n_merged = int(x.size - len(nx_))
    return np.array(nx_), np.array(ny_), np.array(nz_), n_merged


class Interpolator:
    """Base class. Subclasses set ``key``, ``title`` and implement ``_predict``."""

    key = "base"
    title = "Interpolator"
    exact = False  # honours data values at data locations
    provides_variance = False
    min_points_required = 1

    def __init__(self):
        self.x = self.y = self.z = None
        self.last_variance = None
        self.progress = None  # callable(fraction) -> None
        self.cancel_check = None  # callable() -> bool

    # ---- public --------------------------------------------------------
    def fit(self, x, y, z) -> "Interpolator":
        self.x = np.asarray(x, float)
        self.y = np.asarray(y, float)
        self.z = np.asarray(z, float)
        if self.x.size < self.min_points_required:
            raise GriddingError(
                f"{self.title} needs at least {self.min_points_required} points "
                f"({self.x.size} available)."
            )
        self._fit()
        return self

    def predict(self, xq, yq) -> np.ndarray:
        if self.x is None:
            raise GriddingError("Interpolator used before fit().")
        xq = np.asarray(xq, float)
        yq = np.asarray(yq, float)
        shape = xq.shape
        self.last_variance = None
        out = self._predict(xq.ravel(), yq.ravel())
        if self.last_variance is not None:
            self.last_variance = self.last_variance.reshape(shape)
        return out.reshape(shape)

    def parameters(self) -> dict:
        """JSON-serialisable parameters, recorded in grid provenance."""
        out = {}
        for k, v in vars(self).items():
            if k.startswith("_") or k in ("x", "y", "z", "last_variance", "progress",
                                         "cancel_check"):
                continue
            if hasattr(v, "__dataclass_fields__"):
                v = asdict(v)
            elif hasattr(v, "to_dict"):
                v = v.to_dict()
            out[k] = v
        return out

    # ---- hooks ---------------------------------------------------------
    def _fit(self):
        pass

    def _predict(self, xq, yq) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    # ---- helpers -------------------------------------------------------
    def _report(self, fraction: float):
        if self.cancel_check is not None and self.cancel_check():
            raise CancelledError("Gridding cancelled by the user.")
        if self.progress is not None:
            self.progress(min(max(fraction, 0.0), 1.0))

    def _chunks(self, n: int, size: int = 4096):
        for s in range(0, n, size):
            self._report(s / max(n, 1))
            yield slice(s, min(s + size, n))
        self._report(1.0)


class NeighbourSearch:
    """KD-tree neighbourhood search in an (optionally anisotropic) frame."""

    def __init__(self, x, y, search: SearchParams, anisotropy: Anisotropy | None = None):
        self.search = search
        self.anis = anisotropy or Anisotropy()
        self.x0 = float(np.mean(x))
        self.y0 = float(np.mean(y))
        tx, ty = self.anis.transform(x, y, self.x0, self.y0)
        self.tree = cKDTree(np.column_stack([tx, ty]))
        self.n = len(tx)

    def query(self, xq, yq):
        """Return (dist, idx, valid) arrays of shape (m, k).

        ``valid`` is False for neighbours outside the radius or padding
        entries; ``idx`` of invalid entries is 0 (safe for indexing).
        """
        tx, ty = self.anis.transform(xq, yq, self.x0, self.y0)
        k = self.n if self.search.max_points is None else min(self.search.max_points, self.n)
        ub = np.inf if self.search.radius is None else self.search.radius
        d, i = self.tree.query(np.column_stack([tx, ty]), k=k, distance_upper_bound=ub)
        if k == 1:
            d = d[:, None]
            i = i[:, None]
        valid = np.isfinite(d)
        i = np.where(valid, i, 0)
        d = np.where(valid, d, np.inf)
        return d, i, valid
