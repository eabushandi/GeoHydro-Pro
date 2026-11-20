"""Registry of gridding methods and construction from JSON-serialisable parameters.

The parameter dictionaries are what the desktop dialog produces and what a
grid's provenance records, so a grid can always be recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import GriddingError
from ..interpolation.base import Anisotropy, SearchParams
from ..interpolation.kriging import OrdinaryKriging, UniversalKriging
from ..interpolation.min_curvature import MinimumCurvature
from ..interpolation.natural_neighbour import NaturalNeighbour
from ..interpolation.simple import (InverseDistance, LinearTriangulation, NearestNeighbour,
                                    RadialBasis)
from ..interpolation.variogram import VariogramModel


@dataclass(frozen=True)
class MethodInfo:
    key: str
    title: str
    summary: str
    exact: str  # "yes", "no", "optional"
    uses_search: bool
    uses_anisotropy: bool
    grid_only: bool = False  # computes the whole grid at once (no point predict)
    provides_variance: bool = False


METHODS: dict[str, MethodInfo] = {
    m.key: m for m in [
        MethodInfo("idw", "Inverse Distance Weighting",
                   "Weighted average of neighbours, weights 1/distance^power. Fast and robust; "
                   "produces 'bull's-eyes' around data points.", "optional", True, True),
        MethodInfo("ordinary_kriging", "Ordinary Kriging",
                   "Geostatistical best linear unbiased estimator with an unknown constant "
                   "mean. Requires a variogram model; also gives the kriging variance.",
                   "yes", True, True, provides_variance=True),
        MethodInfo("universal_kriging", "Universal Kriging",
                   "Kriging with a linear or quadratic polynomial drift (trend) in the mean.",
                   "yes", True, True, provides_variance=True),
        MethodInfo("min_curvature", "Minimum Curvature",
                   "Smoothest surface (least total squared curvature) through the data, with "
                   "optional tension. Extrapolates over the whole grid.", "yes", False, False,
                   grid_only=True),
        MethodInfo("natural_neighbour", "Natural Neighbour",
                   "Sibson area-stealing weights from the Voronoi diagram. Local, exact, no "
                   "parameters; blank outside the convex hull.", "yes", False, True),
        MethodInfo("nearest", "Nearest Neighbour",
                   "Value of the closest data point (Voronoi polygons). For regularly spaced "
                   "data or categorical values.", "yes", True, True),
        MethodInfo("tin", "Linear Triangulation",
                   "Linear interpolation on the Delaunay triangles. Exact; blank outside the "
                   "convex hull.", "yes", False, True),
        MethodInfo("rbf", "Radial Basis Functions",
                   "Weighted sum of radial kernels plus a polynomial, solved exactly or with "
                   "smoothing. Thin-plate spline by default.", "optional", False, True),
    ]
}


def _anis(p: dict) -> Anisotropy:
    a = p.get("anisotropy") or {}
    return Anisotropy(ratio=float(a.get("ratio", 1.0)), angle=float(a.get("angle", 0.0)))


def _search(p: dict, default_max: int | None) -> SearchParams:
    s = p.get("search") or {}
    radius = s.get("radius")
    max_pts = s.get("max_points", default_max)
    return SearchParams(
        radius=float(radius) if radius not in (None, "", 0) else None,
        max_points=int(max_pts) if max_pts not in (None, "", 0) else None,
        min_points=int(s.get("min_points", 1)),
    )


def build_interpolator(method: str, params: dict | None = None):
    """Create an interpolator from a method key and a parameter dict."""
    p = dict(params or {})
    if method == "idw":
        return InverseDistance(power=float(p.get("power", 2.0)),
                               smoothing=float(p.get("smoothing", 0.0)),
                               search=_search(p, 64), anisotropy=_anis(p))
    if method == "nearest":
        return NearestNeighbour(search=_search(p, 1), anisotropy=_anis(p))
    if method == "tin":
        return LinearTriangulation(anisotropy=_anis(p))
    if method == "natural_neighbour":
        return NaturalNeighbour(anisotropy=_anis(p))
    if method == "rbf":
        nb = p.get("neighbours")
        eps = p.get("epsilon")
        return RadialBasis(kernel=p.get("kernel", "thin_plate_spline"),
                           epsilon=float(eps) if eps not in (None, "") else None,
                           smoothing=float(p.get("smoothing", 0.0)),
                           neighbours=int(nb) if nb not in (None, "", 0) else None,
                           anisotropy=_anis(p))
    if method == "min_curvature":
        return MinimumCurvature(tension=float(p.get("tension", 0.0)),
                                fit_weight=float(p.get("fit_weight", 1e4)))
    if method in ("ordinary_kriging", "universal_kriging"):
        vg = p.get("variogram")
        if not vg:
            raise GriddingError("Kriging needs a variogram model.")
        model = VariogramModel.from_dict(vg) if isinstance(vg, dict) else vg
        search = _search(p, 32)
        if method == "ordinary_kriging":
            return OrdinaryKriging(model, search)
        return UniversalKriging(model, p.get("drift", "linear"), search)
    raise GriddingError(f"Unknown gridding method '{method}'.")
