"""Regular grid model.

Conventions (documented in docs/GRIDDING.md):

* Grids are **node registered**: values are defined at the nodes
  ``x_i = x_min + i*dx`` (``i = 0 .. nx-1``) and ``y_j = y_min + j*dy``.
  ``x_max`` and ``y_max`` are themselves nodes. This is the convention used by
  Surfer ASCII/binary grids and by GMT's gridline registration.
* ``z`` has shape ``(ny, nx)``; row 0 is the **southern** (minimum Y) row.
* Missing / blanked nodes are ``NaN`` in memory. File formats translate NaN to
  their own NoData sentinel on write and back to NaN on read.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

import numpy as np

from ..errors import GriddingError

MAX_NODES = 25_000_000  # hard safety limit (about 200 MB of float64)


@dataclass(frozen=True)
class GridGeometry:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    nx: int
    ny: int

    def __post_init__(self):
        for name in ("x_min", "x_max", "y_min", "y_max"):
            if not math.isfinite(getattr(self, name)):
                raise GriddingError(f"Grid limit {name} must be a finite number.")
        if self.nx < 2 or self.ny < 2:
            raise GriddingError("A grid needs at least 2 nodes in each direction.")
        if not (self.x_max > self.x_min and self.y_max > self.y_min):
            raise GriddingError("Grid maximum limits must be greater than the minimum limits.")
        if self.nx * self.ny > MAX_NODES:
            raise GriddingError(
                f"Grid of {self.nx} x {self.ny} nodes exceeds the limit of {MAX_NODES:,} nodes. "
                "Increase the spacing."
            )

    # ---- construction --------------------------------------------------
    @classmethod
    def from_spacing(cls, x_min, x_max, y_min, y_max, dx, dy=None) -> "GridGeometry":
        """Build a geometry from a node spacing.

        The minimum limits are kept; the maximum limits are extended (never
        shrunk) so that they fall exactly on a node.
        """
        dy = dx if dy is None else dy
        if not (dx > 0 and dy > 0):
            raise GriddingError("Grid spacing must be positive.")
        nx = int(math.ceil((x_max - x_min) / dx - 1e-9)) + 1
        ny = int(math.ceil((y_max - y_min) / dy - 1e-9)) + 1
        nx, ny = max(nx, 2), max(ny, 2)
        return cls(float(x_min), float(x_min + (nx - 1) * dx), float(y_min),
                   float(y_min + (ny - 1) * dy), nx, ny)

    @classmethod
    def from_points(cls, x, y, n_long: int = 100, margin: float = 0.0) -> "GridGeometry":
        """Default geometry covering the data extent with ~``n_long`` nodes on the long side.

        The spacing is equal in X and Y (square cells), as most mapping
        packages default to.
        """
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 2:
            raise GriddingError("At least two points with valid coordinates are needed.")
        x0, x1, y0, y1 = x[ok].min(), x[ok].max(), y[ok].min(), y[ok].max()
        w, h = x1 - x0, y1 - y0
        if w <= 0 and h <= 0:
            raise GriddingError("All points have the same location.")
        w = w if w > 0 else h
        h = h if h > 0 else w
        x0 -= margin * w
        x1 = x0 + w * (1 + 2 * margin)
        y0 -= margin * h
        y1 = y0 + h * (1 + 2 * margin)
        d = nice_spacing(max(x1 - x0, y1 - y0) / max(n_long - 1, 1))
        return cls.from_spacing(x0, x1, y0, y1, d, d)

    # ---- derived -------------------------------------------------------
    @property
    def dx(self) -> float:
        return (self.x_max - self.x_min) / (self.nx - 1)

    @property
    def dy(self) -> float:
        return (self.y_max - self.y_min) / (self.ny - 1)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    @property
    def n_nodes(self) -> int:
        return self.nx * self.ny

    def x_nodes(self) -> np.ndarray:
        return self.x_min + np.arange(self.nx) * self.dx

    def y_nodes(self) -> np.ndarray:
        return self.y_min + np.arange(self.ny) * self.dy

    def mesh(self) -> tuple[np.ndarray, np.ndarray]:
        return np.meshgrid(self.x_nodes(), self.y_nodes())

    def to_dict(self) -> dict:
        return dict(x_min=self.x_min, x_max=self.x_max, y_min=self.y_min,
                    y_max=self.y_max, nx=self.nx, ny=self.ny)

    @classmethod
    def from_dict(cls, d: dict) -> "GridGeometry":
        return cls(float(d["x_min"]), float(d["x_max"]), float(d["y_min"]),
                   float(d["y_max"]), int(d["nx"]), int(d["ny"]))


def nice_spacing(d: float) -> float:
    """Largest value of the form 1, 2, 2.5 or 5 x 10^k that does not exceed ``d``."""
    if d <= 0 or not math.isfinite(d):
        return d
    e = math.floor(math.log10(d))
    best = 10 ** e
    for m in (1, 2, 2.5, 5, 10):
        cand = m * 10 ** e
        if cand <= d * (1 + 1e-9):
            best = cand
    return float(best)


@dataclass
class Grid:
    """A regular grid of Z values with provenance metadata."""

    geometry: GridGeometry
    z: np.ndarray
    name: str = "Grid"
    crs: str | None = None
    xy_units: str = "m"
    z_units: str = "m"
    z_label: str = "Z"
    metadata: dict = field(default_factory=dict)  # method, parameters, source, warnings, cv
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = "grid"
    notes: str = ""

    def __post_init__(self):
        self.z = np.asarray(self.z, dtype=float)
        if self.z.shape != self.geometry.shape:
            raise GriddingError(
                f"Z array shape {self.z.shape} does not match grid shape {self.geometry.shape}."
            )

    # ---- queries -------------------------------------------------------
    @property
    def n_blank(self) -> int:
        return int(np.isnan(self.z).sum())

    @property
    def n_valid(self) -> int:
        return int(np.isfinite(self.z).sum())

    def statistics(self) -> dict:
        return grid_statistics(self)

    def value_at(self, x: float, y: float) -> float:
        return float(self.sample(np.array([x]), np.array([y]))[0])

    def sample(self, x, y) -> np.ndarray:
        """Bilinear interpolation of the grid at arbitrary locations.

        Returns NaN outside the grid or where any of the four surrounding
        nodes is blank (no extrapolation, no filling).
        """
        g = self.geometry
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        fx = (x - g.x_min) / g.dx
        fy = (y - g.y_min) / g.dy
        out = np.full(x.shape, np.nan)
        eps = 1e-9
        inside = (fx >= -eps) & (fx <= g.nx - 1 + eps) & (fy >= -eps) & (fy <= g.ny - 1 + eps)
        if not inside.any():
            return out
        fxi = np.clip(fx[inside], 0, g.nx - 1)
        fyi = np.clip(fy[inside], 0, g.ny - 1)
        i0 = np.minimum(np.floor(fxi).astype(int), g.nx - 2)
        j0 = np.minimum(np.floor(fyi).astype(int), g.ny - 2)
        tx = fxi - i0
        ty = fyi - j0
        z = self.z
        z00 = z[j0, i0]
        z10 = z[j0, i0 + 1]
        z01 = z[j0 + 1, i0]
        z11 = z[j0 + 1, i0 + 1]
        # A node with zero weight must not blank the result (e.g. on an edge).
        w00 = (1 - tx) * (1 - ty)
        w10 = tx * (1 - ty)
        w01 = (1 - tx) * ty
        w11 = tx * ty
        vals = np.zeros_like(tx)
        bad = np.zeros(tx.shape, bool)
        for w, zz in ((w00, z00), (w10, z10), (w01, z01), (w11, z11)):
            used = w > 1e-12
            bad |= used & ~np.isfinite(zz)
            vals += np.where(used, w * np.nan_to_num(zz), 0.0)
        vals[bad] = np.nan
        out[inside] = vals
        return out

    def copy(self, **changes) -> "Grid":
        d = dict(geometry=self.geometry, z=self.z.copy(), name=self.name, crs=self.crs,
                 xy_units=self.xy_units, z_units=self.z_units, z_label=self.z_label,
                 metadata=dict(self.metadata), notes=self.notes)
        d.update(changes)
        return Grid(**d)


def grid_statistics(grid: Grid) -> dict:
    """Descriptive statistics of the valid (non-blank) nodes.

    Node statistics are unweighted (each node counts equally), which equals
    an area-weighted statistic for a regular grid.
    """
    g = grid.geometry
    v = grid.z[np.isfinite(grid.z)]
    out = {
        "nx": g.nx, "ny": g.ny, "nodes": g.n_nodes,
        "dx": g.dx, "dy": g.dy,
        "x_min": g.x_min, "x_max": g.x_max, "y_min": g.y_min, "y_max": g.y_max,
        "valid_nodes": int(v.size), "blank_nodes": int(g.n_nodes - v.size),
    }
    if v.size:
        out.update(
            z_min=float(v.min()), z_max=float(v.max()), z_range=float(np.ptp(v)),
            z_mean=float(v.mean()), z_median=float(np.median(v)),
            z_std=float(v.std(ddof=1)) if v.size > 1 else 0.0,
            z_q1=float(np.percentile(v, 25)), z_q3=float(np.percentile(v, 75)),
        )
    return out
