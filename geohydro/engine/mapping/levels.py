"""Contour level selection and colour palettes."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from ..errors import MapError

MAX_LEVELS = 500

# Curated palettes (all are Matplotlib colormaps). Perceptually uniform ones
# first; 'terrain'/'gist_earth' are conventional for elevation but not
# perceptually uniform, which the description says.
PALETTES = {
    "viridis": "Viridis (perceptually uniform)",
    "cividis": "Cividis (uniform, colour-vision-deficiency friendly)",
    "magma": "Magma (perceptually uniform)",
    "plasma": "Plasma (perceptually uniform)",
    "terrain": "Terrain (conventional elevation; not uniform)",
    "gist_earth": "Earth (conventional elevation; not uniform)",
    "Blues": "Blues (depth, water)",
    "YlGnBu": "Yellow-Green-Blue (bathymetry, concentration)",
    "YlOrRd": "Yellow-Orange-Red (concentration, hazard)",
    "RdBu_r": "Red-Blue diverging (change, residuals)",
    "BrBG": "Brown-Blue-Green diverging (erosion / accretion)",
    "Spectral_r": "Spectral (rainbow-like; not uniform)",
    "Greys": "Greys",
}


def get_cmap(name: str, reverse: bool = False):
    import matplotlib

    if name not in PALETTES and name not in matplotlib.colormaps:
        raise MapError(f"Unknown colour palette '{name}'.")
    cmap = matplotlib.colormaps[name]
    return cmap.reversed() if reverse else cmap


def nice_interval(span: float, target: int = 10) -> float:
    """A 1, 2, 2.5 or 5 x 10^k interval giving roughly ``target`` levels over ``span``."""
    if not span > 0 or not math.isfinite(span):
        return 1.0
    raw = span / max(target, 1)
    e = math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10**e >= raw * 0.999999:
            return m * 10**e
    return 10 ** (e + 1)


@dataclass
class LevelSpec:
    """How contour levels are chosen.

    ``mode``: ``auto`` (nice interval, about ``count`` levels over the data
    range), ``interval`` (``first`` + k * ``interval`` up to ``last``; blank
    first/last means data min/max rounded to the interval) or ``list``
    (explicit ``values``).
    """

    mode: str = "auto"
    count: int = 10
    interval: float | None = None
    first: float | None = None
    last: float | None = None
    values: list | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**(d or {}))

    def levels(self, zmin: float, zmax: float) -> np.ndarray:
        if not (math.isfinite(zmin) and math.isfinite(zmax)):
            raise MapError("The grid has no valid values to contour.")
        if self.mode == "list":
            vals = np.unique(np.asarray(self.values or [], float))
            vals = vals[np.isfinite(vals)]
            if vals.size == 0:
                raise MapError("The contour level list is empty.")
            return vals
        if self.mode == "interval":
            step = self.interval
            if not step or step <= 0:
                raise MapError("Contour interval must be positive.")
        elif self.mode == "auto":
            step = nice_interval(zmax - zmin, self.count)
        else:
            raise MapError(f"Unknown level mode '{self.mode}'.")
        first = self.first if self.first is not None else math.floor(zmin / step) * step
        last = self.last if self.last is not None else math.ceil(zmax / step) * step
        if last < first:
            raise MapError("Last contour level is below the first level.")
        n = int(math.floor((last - first) / step + 1e-9)) + 1
        if n > MAX_LEVELS:
            raise MapError(
                f"{n} contour levels requested (limit {MAX_LEVELS}); increase the interval."
            )
        lv = first + step * np.arange(n)
        # tidy floating-point noise (e.g. 0.30000000000000004)
        dec = max(0, -int(math.floor(math.log10(step))) + 6)
        return np.round(lv, dec)
