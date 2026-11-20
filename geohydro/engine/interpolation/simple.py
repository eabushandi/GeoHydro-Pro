"""Deterministic interpolators: Nearest Neighbour, IDW, Linear Triangulation, RBF.

Methodology, parameters and limitations are documented in docs/GRIDDING.md.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import LinearNDInterpolator, RBFInterpolator
from scipy.spatial import Delaunay, QhullError

from ..errors import GriddingError
from .base import Anisotropy, Interpolator, NeighbourSearch, SearchParams


class NearestNeighbour(Interpolator):
    """Each node takes the Z of the closest data point (in the anisotropic frame).

    Nodes with no data point within the search radius are blank.
    """

    key = "nearest"
    title = "Nearest Neighbour"
    exact = True

    def __init__(self, search: SearchParams | None = None, anisotropy: Anisotropy | None = None):
        super().__init__()
        self.search = search or SearchParams(max_points=1)
        self.anisotropy = anisotropy or Anisotropy()

    def _fit(self):
        sp = SearchParams(radius=self.search.radius, max_points=1, min_points=1)
        self._ns = NeighbourSearch(self.x, self.y, sp, self.anisotropy)

    def _predict(self, xq, yq):
        out = np.full(xq.size, np.nan)
        for s in self._chunks(xq.size, 65536):
            d, i, v = self._ns.query(xq[s], yq[s])
            out[s] = np.where(v[:, 0], self.z[i[:, 0]], np.nan)
        return out


class InverseDistance(Interpolator):
    """Inverse Distance Weighting (Shepard, 1968).

    ``z* = sum(w_i z_i) / sum(w_i)``, ``w_i = 1 / (d_i^2 + s^2)^(p/2)``
    where ``p`` is the power and ``s`` the smoothing distance (0 gives an
    exact interpolator). Neighbours come from the search neighbourhood.
    A node coinciding with a data point (d = 0, s = 0) takes that value.
    """

    key = "idw"
    title = "Inverse Distance Weighting"

    def __init__(self, power: float = 2.0, smoothing: float = 0.0,
                 search: SearchParams | None = None, anisotropy: Anisotropy | None = None):
        super().__init__()
        if not power > 0:
            raise GriddingError("IDW power must be positive.")
        if smoothing < 0:
            raise GriddingError("IDW smoothing must be zero or positive.")
        self.power = float(power)
        self.smoothing = float(smoothing)
        self.search = search or SearchParams(max_points=64)
        self.anisotropy = anisotropy or Anisotropy()
        self.exact = self.smoothing == 0

    def _fit(self):
        self._ns = NeighbourSearch(self.x, self.y, self.search, self.anisotropy)

    def _predict(self, xq, yq):
        out = np.full(xq.size, np.nan)
        for s in self._chunks(xq.size):
            d, i, v = self._ns.query(xq[s], yq[s])
            enough = v.sum(axis=1) >= self.search.min_points
            d2 = np.where(v, d, 0.0) ** 2 + self.smoothing ** 2
            with np.errstate(divide="ignore"):
                w = np.where(v, d2 ** (-self.power / 2), 0.0)
            hit = v & (d2 == 0)
            res = np.full(d.shape[0], np.nan)
            anyhit = hit.any(axis=1)
            if anyhit.any():
                # mean of coincident points (there is at most one after preparation)
                zz = np.where(hit, self.z[i], 0.0)
                res[anyhit] = zz[anyhit].sum(1) / hit[anyhit].sum(1)
            rest = ~anyhit
            wsum = w[rest].sum(1)
            with np.errstate(invalid="ignore", divide="ignore"):
                res[rest] = (w[rest] * self.z[i[rest]]).sum(1) / wsum
            res[~enough] = np.nan
            out[s] = res
        return out


class LinearTriangulation(Interpolator):
    """Linear interpolation on the Delaunay triangulation of the data.

    Each node inside the convex hull of the data is interpolated linearly
    within its triangle. Nodes outside the convex hull are blank.
    """

    key = "tin"
    title = "Linear Triangulation"
    exact = True
    min_points_required = 3

    def __init__(self, anisotropy: Anisotropy | None = None):
        super().__init__()
        self.anisotropy = anisotropy or Anisotropy()

    def _fit(self):
        self._x0, self._y0 = float(self.x.mean()), float(self.y.mean())
        tx, ty = self.anisotropy.transform(self.x, self.y, self._x0, self._y0)
        try:
            tri = Delaunay(np.column_stack([tx, ty]))
        except QhullError as exc:
            raise GriddingError(
                "Triangulation failed: the points are collinear or too few distinct points."
            ) from exc
        self._interp = LinearNDInterpolator(tri, self.z, fill_value=np.nan)

    def _predict(self, xq, yq):
        out = np.full(xq.size, np.nan)
        for s in self._chunks(xq.size, 65536):
            tx, ty = self.anisotropy.transform(xq[s], yq[s], self._x0, self._y0)
            out[s] = self._interp(tx, ty)
        return out


RBF_KERNELS = {
    "thin_plate_spline": "Thin-plate spline  r² log r",
    "multiquadric": "Multiquadric  -sqrt(1 + (εr)²)",
    "inverse_multiquadric": "Inverse multiquadric  1/sqrt(1 + (εr)²)",
    "inverse_quadratic": "Inverse quadratic  1/(1 + (εr)²)",
    "gaussian": "Gaussian  exp(-(εr)²)",
    "linear": "Linear  -r",
    "cubic": "Cubic  r³",
    "quintic": "Quintic  -r⁵",
}
_SCALE_FREE = {"thin_plate_spline", "linear", "cubic", "quintic"}


class RadialBasis(Interpolator):
    """Radial Basis Function interpolation (SciPy ``RBFInterpolator``).

    Solves for weights so that ``s(x) = sum(w_i φ(||x - x_i||)) + P(x)``
    reproduces the data (``smoothing = 0``) or approximates it in a
    least-squares sense (``smoothing > 0``). ``P`` is a low-degree
    polynomial (degree chosen by SciPy per kernel). For kernels that need a
    shape parameter ε and none is given, ε = 1 / (mean nearest-neighbour
    spacing of the data), recorded in the grid metadata. ``neighbours``
    limits each estimate to the nearest data points (local RBF); ``None``
    uses all points (global, O(n³)).
    """

    key = "rbf"
    title = "Radial Basis Functions"

    def __init__(self, kernel: str = "thin_plate_spline", epsilon: float | None = None,
                 smoothing: float = 0.0, neighbours: int | None = None,
                 anisotropy: Anisotropy | None = None):
        super().__init__()
        if kernel not in RBF_KERNELS:
            raise GriddingError(f"Unknown RBF kernel '{kernel}'.")
        if smoothing < 0:
            raise GriddingError("RBF smoothing must be zero or positive.")
        self.kernel = kernel
        self.epsilon = epsilon
        self.smoothing = float(smoothing)
        self.neighbours = neighbours
        self.anisotropy = anisotropy or Anisotropy()
        self.exact = self.smoothing == 0
        self.min_points_required = 3

    def _fit(self):
        self._x0, self._y0 = float(self.x.mean()), float(self.y.mean())
        tx, ty = self.anisotropy.transform(self.x, self.y, self._x0, self._y0)
        pts = np.column_stack([tx, ty])
        eps = self.epsilon
        if eps is None and self.kernel not in _SCALE_FREE:
            from scipy.spatial import cKDTree
            d, _ = cKDTree(pts).query(pts, k=2)
            spacing = float(np.mean(d[:, 1]))
            eps = 1.0 / spacing if spacing > 0 else 1.0
            self.epsilon = eps
        kw = dict(kernel=self.kernel, smoothing=self.smoothing)
        if eps is not None:
            kw["epsilon"] = eps
        if self.neighbours is not None:
            kw["neighbors"] = int(min(self.neighbours, len(tx)))
        try:
            self._rbf = RBFInterpolator(pts, self.z, **kw)
        except (np.linalg.LinAlgError, ValueError) as exc:
            raise GriddingError(f"RBF system could not be solved: {exc}") from exc

    def _predict(self, xq, yq):
        out = np.empty(xq.size)
        for s in self._chunks(xq.size, 2048):
            tx, ty = self.anisotropy.transform(xq[s], yq[s], self._x0, self._y0)
            out[s] = self._rbf(np.column_stack([tx, ty]))
        return out
