"""Ordinary and Universal Kriging (point kriging).

Both are solved in variogram form, which also admits unbounded models
(linear, power). For a target x0 with neighbours x_1..x_k:

Ordinary Kriging (unknown constant mean)::

    | Γ   1 | |λ|   |γ0|          z*(x0) = Σ λ_i z_i
    | 1ᵀ  0 | |μ| = | 1|          σ²(x0) = Σ λ_i γ(x_i - x0) + μ

Universal Kriging (mean is a polynomial drift m(x) = Σ a_l f_l(x))::

    | Γ   F | |λ|   |γ0|          z*(x0) = Σ λ_i z_i
    | Fᵀ  0 | |μ| = |f0|          σ²(x0) = λᵀγ0 + μᵀf0

with Γ_ij = γ(x_i - x_j), γ0_i = γ(x_i - x0), F_il = f_l(x_i) and
f0_l = f_l(x0). Drift: ``linear`` (1, x, y) or ``quadratic``
(1, x, y, x², xy, y²), evaluated in coordinates centred on the target and
scaled by the neighbourhood size (this changes conditioning, not results).

σ² is the kriging (estimation) variance under the chosen variogram model.
It depends on the model and the data configuration, not on the data
values, and is only as meaningful as the variogram model.

Kriging honours the data exactly (γ(0) = 0 at data locations, also with a
nugget). Local neighbourhoods use the search parameters, with distances in
the anisotropic frame of the variogram model.
"""

from __future__ import annotations

import numpy as np

from ..errors import GriddingError
from .base import Interpolator, NeighbourSearch, SearchParams
from .variogram import VariogramModel

DRIFTS = {"linear": 3, "quadratic": 6}
MAX_GLOBAL_POINTS = 1500


class _KrigingBase(Interpolator):
    exact = True
    provides_variance = True
    drift = None

    def __init__(self, variogram: VariogramModel, search: SearchParams | None = None):
        super().__init__()
        if isinstance(variogram, dict):
            variogram = VariogramModel.from_dict(variogram)
        self.variogram = variogram
        self.search = search or SearchParams(max_points=32, min_points=1)

    @property
    def n_drift(self) -> int:
        return 1 if self.drift is None else DRIFTS[self.drift]

    def _fit(self):
        if self.search.max_points is None and self.x.size > MAX_GLOBAL_POINTS:
            raise GriddingError(
                f"Kriging with all {self.x.size} points per node is too slow. Set a maximum "
                f"number of neighbours (at most {MAX_GLOBAL_POINTS} for a global search)."
            )
        need = self.n_drift + (0 if self.drift is None else 1)
        if self.x.size < max(need, 2):
            raise GriddingError(f"{self.title} needs at least {max(need, 2)} points.")
        self._ns = NeighbourSearch(self.x, self.y, self.search, self.variogram.anisotropy)
        tx, ty = self.variogram.anisotropy.transform(self.x, self.y, self._ns.x0, self._ns.y0)
        self._tp = np.column_stack([tx, ty])
        self.warnings = []
        self.n_singular = 0
        if self.variogram.model == "gaussian" and self.variogram.nugget == 0:
            self.warnings.append(
                "Gaussian variogram without nugget: kriging systems are often "
                "ill-conditioned; consider a small nugget."
            )

    def _drift_matrix(self, dx, dy):
        """Drift functions at offsets (dx, dy) from the target, shape (..., L)."""
        ones = np.ones_like(dx)
        if self.drift == "linear":
            return np.stack([ones, dx, dy], axis=-1)
        if self.drift == "quadratic":
            return np.stack([ones, dx, dy, dx * dx, dx * dy, dy * dy], axis=-1)
        return ones[..., None]

    def _predict(self, xq, yq):
        out = np.full(xq.size, np.nan)
        var = np.full(xq.size, np.nan)
        k = self._ns.n if self.search.max_points is None else min(self.search.max_points,
                                                                     self._ns.n)
        L = self.n_drift
        chunk = int(max(32, min(4096, 3_000_000 // ((k + L) ** 2))))
        g = self.variogram
        min_needed = max(self.search.min_points, L + (0 if self.drift is None else 1))
        for s in self._chunks(xq.size, chunk):
            d0, idx, valid = self._ns.query(xq[s], yq[s])
            m = idx.shape[0]
            nvalid = valid.sum(1)
            P = self._tp[idx]  # (m, k, 2) in anisotropic frame
            dij = np.linalg.norm(P[:, :, None, :] - P[:, None, :, :], axis=-1)
            G = g(dij)
            g0 = g(np.where(valid, d0, 0.0))
            # Drift in real coordinates, centred on target, scaled
            ox = self.x[idx] - xq[s][:, None]
            oy = self.y[idx] - yq[s][:, None]
            sc = np.maximum(np.max(np.where(valid, np.hypot(ox, oy), 0.0), axis=1), 1e-300)
            F = self._drift_matrix(ox / sc[:, None], oy / sc[:, None])  # (m, k, L)
            f0 = self._drift_matrix(np.zeros(m), np.zeros(m))  # (m, L)
            # Mask invalid neighbours: identity rows, zero coupling
            vm = valid[:, :, None] & valid[:, None, :]
            G = np.where(vm, G, 0.0)
            eye = np.eye(k, dtype=bool)[None]
            G = np.where(eye & ~valid[:, :, None], 1.0, G)
            F = np.where(valid[:, :, None], F, 0.0)
            g0 = np.where(valid, g0, 0.0)
            A = np.zeros((m, k + L, k + L))
            A[:, :k, :k] = G
            A[:, :k, k:] = F
            A[:, k:, :k] = np.transpose(F, (0, 2, 1))
            b = np.concatenate([g0, f0], axis=1)
            sol = self._solve(A, b)
            lam, mu = sol[:, :k], sol[:, k:]
            est = np.einsum("mk,mk->m", lam, np.where(valid, self.z[idx], 0.0))
            v = np.einsum("mk,mk->m", lam, g0) + np.einsum("ml,ml->m", mu, f0)
            bad = (nvalid < min_needed) | ~np.isfinite(est)
            # exact hit: a data point at distance 0
            hit = valid & (d0 == 0)
            anyhit = hit.any(1)
            est = np.where(anyhit, np.where(hit, self.z[idx], 0.0).sum(1), est)
            v = np.where(anyhit, 0.0, v)
            est[bad] = np.nan
            v[bad] = np.nan
            out[s] = est
            # round-off can make a zero variance slightly negative
            scale = float(np.max(np.abs(g0))) if g0.size else 1.0
            var[s] = np.where((v < 0) & (v > -1e-8 * max(scale, 1e-300)), 0.0, v)
        self.last_variance = var
        if self.n_singular:
            msg = (f"{self.n_singular} node(s) had a singular kriging system (for example "
                   "coincident or collinear neighbours with this drift) and were left blank.")
            self.warnings = [w for w in self.warnings if "singular kriging system" not in w]
            self.warnings.append(msg)
        return out

    def _solve(self, A, b):
        try:
            return np.linalg.solve(A, b[..., None])[..., 0]
        except np.linalg.LinAlgError:
            out = np.full(b.shape, np.nan)
            for i in range(A.shape[0]):
                try:
                    out[i] = np.linalg.solve(A[i], b[i])
                except np.linalg.LinAlgError:
                    self.n_singular += 1  # singular configuration -> blank node
            return out

    def parameters(self) -> dict:
        p = {"variogram": self.variogram.to_dict(),
             "search": {"radius": self.search.radius, "max_points": self.search.max_points,
                        "min_points": self.search.min_points}}
        if self.drift:
            p["drift"] = self.drift
        return p


class OrdinaryKriging(_KrigingBase):
    key = "ordinary_kriging"
    title = "Ordinary Kriging"


class UniversalKriging(_KrigingBase):
    key = "universal_kriging"
    title = "Universal Kriging"

    def __init__(self, variogram: VariogramModel, drift: str = "linear",
                 search: SearchParams | None = None):
        if drift not in DRIFTS:
            raise GriddingError(f"Unknown drift '{drift}' (use 'linear' or 'quadratic').")
        self.drift = drift
        super().__init__(variogram, search)
