"""Minimum Curvature gridding (Briggs, 1974) with optional tension (Smith & Wessel, 1990).

The grid surface z minimises

    E(z) = (1 - T) * sum[ z_xx² + 2 z_xy² + z_yy² ]          (total squared curvature)
         +      T  * sum[ z_x² + z_y² ]                      (tension / membrane term)
         +      W  * sum_k [ B_k z - d_k ]²                  (fit to the data)

on the regular grid, using finite differences in grid-index units (as in
Smith & Wessel, so T is independent of the coordinate units; rectangular
cells are handled through the aspect ratio dy/dx). ``B_k z`` is the bilinear
interpolation of the grid at data point k, so data need not lie on nodes.

The stationarity condition in the interior is the tensioned biharmonic
equation ``(1 - T) ∇⁴z - T ∇²z = 0`` away from the data. Grid edges are free
(natural boundary conditions of the energy above): no values are imposed at
the edges. ``T = 0`` gives the pure minimum-curvature (thin-plate) surface;
``T`` near 1 approaches a membrane that avoids overshoot.

A least-squares plane is first removed from the data and added back to the
result (as in GMT ``surface``); planes are therefore reproduced exactly and,
with tension, the surface relaxes towards that trend away from the data.

``W`` is set to ``fit_weight`` times the mean diagonal of the curvature
operator, which makes the surface honour isolated data closely. When
several data points fall in one cell they are fitted in the least-squares
sense. Residuals at the data are reported, never hidden.

Difference from Briggs's original algorithm: Briggs solved the equations by
iterative relaxation with special edge stencils; this implementation
assembles the same variational problem as a sparse linear system and solves
it directly, so there are no iteration or convergence settings.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from ..errors import GriddingError
from .base import Interpolator

MAX_DIRECT_NODES = 1_000_000


def _second_diff(n):
    """(n-2) x n second-difference operator."""
    if n < 3:
        return sp.csr_matrix((0, n))
    e = np.ones(n - 2)
    return sp.diags([e, -2 * e, e], [0, 1, 2], shape=(n - 2, n), format="csr")


def _first_diff(n):
    e = np.ones(n - 1)
    return sp.diags([-e, e], [0, 1], shape=(n - 1, n), format="csr")


class MinimumCurvature(Interpolator):
    key = "min_curvature"
    title = "Minimum Curvature"
    min_points_required = 3

    def __init__(self, tension: float = 0.0, fit_weight: float = 1e4):
        super().__init__()
        if not (0 <= tension < 1):
            raise GriddingError("Tension must be in [0, 1).")
        if not fit_weight > 0:
            raise GriddingError("Fit weight must be positive.")
        self.tension = float(tension)
        self.fit_weight = float(fit_weight)
        self.residuals = None

    def _predict(self, xq, yq):  # pragma: no cover - grid-only method
        raise GriddingError(
            "Minimum Curvature computes a whole grid; use grid() rather than predict()."
        )

    # Minimum curvature is defined on a grid, so it exposes grid() and the
    # generic gridding routine calls it instead of predict().
    def grid(self, geometry) -> np.ndarray:
        g = geometry
        nx, ny = g.nx, g.ny
        if nx * ny > MAX_DIRECT_NODES:
            raise GriddingError(
                f"Minimum Curvature is limited to {MAX_DIRECT_NODES:,} nodes in this version "
                f"(requested {nx * ny:,}). Increase the grid spacing."
            )
        self._report(0.0)
        r = g.dy / g.dx  # aspect ratio; work in units of dx
        Ix, Iy = sp.identity(nx, format="csr"), sp.identity(ny, format="csr")
        Dxx = sp.kron(Iy, _second_diff(nx))
        Dyy = sp.kron(_second_diff(ny), Ix) / r**2
        Dxy = sp.kron(_first_diff(ny), _first_diff(nx)) / r
        H = (Dxx.T @ Dxx + Dyy.T @ Dyy + 2 * Dxy.T @ Dxy) * (1 - self.tension)
        if self.tension > 0:
            Dx = sp.kron(Iy, _first_diff(nx))
            Dy = sp.kron(_first_diff(ny), Ix) / r
            H = H + self.tension * (Dx.T @ Dx + Dy.T @ Dy)
        self._report(0.2)

        # Bilinear observation operator
        fx = (self.x - g.x_min) / g.dx
        fy = (self.y - g.y_min) / g.dy
        inside = (fx >= 0) & (fx <= nx - 1) & (fy >= 0) & (fy <= ny - 1)
        n_out = int((~inside).sum())
        fx, fy, d = fx[inside], fy[inside], self.z[inside]
        if d.size < 3:
            raise GriddingError("Fewer than three data points fall inside the grid limits.")
        i0 = np.minimum(np.floor(fx).astype(int), nx - 2)
        j0 = np.minimum(np.floor(fy).astype(int), ny - 2)
        tx, ty = fx - i0, fy - j0
        rows = np.repeat(np.arange(d.size), 4)
        cols = np.column_stack([j0 * nx + i0, j0 * nx + i0 + 1,
                                (j0 + 1) * nx + i0, (j0 + 1) * nx + i0 + 1]).ravel()
        vals = np.column_stack([(1 - tx) * (1 - ty), tx * (1 - ty),
                                (1 - tx) * ty, tx * ty]).ravel()
        B = sp.csr_matrix((vals, (rows, cols)), shape=(d.size, nx * ny))

        # Remove a least-squares planar trend (as GMT 'surface' does) and grid
        # the residual field; the plane is added back afterwards.
        G = np.column_stack([np.ones(d.size), fx, fy])
        coef, *_ = np.linalg.lstsq(G, d, rcond=None)
        trend = (coef[0] + coef[1] * np.arange(nx)[None, :] + coef[2] * np.arange(ny)[:, None])
        dd = d - G @ coef
        hmean = float(H.diagonal().mean())
        w = self.fit_weight * hmean
        # A tiny ridge keeps the system well conditioned far from the data
        # (it pulls the residual field towards the trend plane, i.e. zero).
        A = (H + w * (B.T @ B) + sp.identity(nx * ny, format="csr") * (1e-9 * hmean)).tocsc()
        rhs = w * (B.T @ dd)
        self._report(0.3)
        try:
            z = spsolve(A, rhs)
        except Exception as exc:  # SuperLU errors are RuntimeError / MemoryError
            raise GriddingError(f"Minimum Curvature system could not be solved: {exc}") from exc
        if not np.all(np.isfinite(z)):
            raise GriddingError("Minimum Curvature solution is not finite (ill-conditioned).")
        self._report(0.95)
        res = dd - B @ z
        z = z.reshape(ny, nx) + trend
        self.residuals = {
            "points_used": int(d.size),
            "points_outside_grid": n_out,
            "max_abs_residual": float(np.max(np.abs(res))),
            "rms_residual": float(np.sqrt(np.mean(res**2))),
        }
        self._report(1.0)
        return z

    def parameters(self) -> dict:
        return {"tension": self.tension, "fit_weight": self.fit_weight}
