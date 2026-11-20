"""Numerical validation of the interpolation methods.

Reference checks used:
* analytic properties (exactness, linear precision, convexity, weights),
* brute-force constructions (Voronoi nearest neighbour, raster Sibson areas),
* independent implementations (PyKrige for Kriging, SciPy thin-plate spline),
* accuracy against the known generating surface of the synthetic sample data.
"""

import math

import numpy as np
import pytest
from scipy.interpolate import RBFInterpolator
from scipy.spatial import cKDTree

from geohydro.engine.errors import GriddingError
from geohydro.engine.gridding.grid import GridGeometry
from geohydro.engine.gridding.gridder import GriddingRequest, grid_data
from geohydro.engine.gridding.methods import METHODS, build_interpolator
from geohydro.engine.interpolation.base import Anisotropy, SearchParams
from geohydro.engine.interpolation.kriging import OrdinaryKriging, UniversalKriging
from geohydro.engine.interpolation.min_curvature import MinimumCurvature
from geohydro.engine.interpolation.natural_neighbour import NaturalNeighbour
from geohydro.engine.interpolation.simple import (InverseDistance, LinearTriangulation,
                                                  NearestNeighbour, RadialBasis)
from geohydro.engine.interpolation.variogram import (VariogramModel, experimental_variogram,
                                                     fit_variogram)


@pytest.fixture
def pts():
    rng = np.random.default_rng(11)
    x = rng.uniform(0, 1000, 120)
    y = rng.uniform(0, 600, 120)
    return x, y


def plane(x, y):
    return 12.5 + 0.03 * x - 0.011 * y


def smooth(x, y):
    return np.sin(x / 180) * np.cos(y / 120) + 0.002 * x


VG = {"model": "spherical", "nugget": 0.0, "sill": 1.0, "range": 500.0}
EXACT_PARAMS = {
    "idw": {}, "nearest": {}, "tin": {}, "natural_neighbour": {}, "rbf": {},
    "ordinary_kriging": {"variogram": VG}, "universal_kriging": {"variogram": VG},
}


# ------------------------------------------------------------------ exactness
@pytest.mark.parametrize("method", sorted(EXACT_PARAMS))
def test_exact_methods_honour_data(pts, method):
    x, y = pts
    z = smooth(x, y)
    it = build_interpolator(method, EXACT_PARAMS[method]).fit(x, y, z)
    np.testing.assert_allclose(it.predict(x, y), z, atol=1e-9)


@pytest.mark.parametrize("method", ["tin", "natural_neighbour", "rbf", "universal_kriging"])
def test_linear_precision(pts, method):
    """These methods reproduce a plane exactly (inside the hull where applicable)."""
    x, y = pts
    it = build_interpolator(method, EXACT_PARAMS[method]).fit(x, y, plane(x, y))
    gx, gy = np.meshgrid(np.linspace(0, 1000, 37), np.linspace(0, 600, 23))
    est = it.predict(gx, gy)
    ok = np.isfinite(est)
    assert ok.sum() > 0.6 * ok.size
    np.testing.assert_allclose(est[ok], plane(gx, gy)[ok], atol=1e-8)


def test_min_curvature_reproduces_planes_with_and_without_tension(pts):
    x, y = pts
    geom = GridGeometry(0, 1000, 0, 600, 51, 31)
    X, Y = geom.mesh()
    for t in (0.0, 0.25, 0.75):
        mc = MinimumCurvature(tension=t).fit(x, y, plane(x, y))
        np.testing.assert_allclose(mc.grid(geom), plane(X, Y), atol=1e-8)


# ------------------------------------------------------------------ nearest / idw
def test_nearest_matches_brute_force_voronoi(pts):
    x, y = pts
    z = np.arange(x.size, dtype=float)
    nn = NearestNeighbour().fit(x, y, z)
    q = np.random.default_rng(1).uniform([0, 0], [1000, 600], (500, 2))
    d = np.hypot(q[:, None, 0] - x[None], q[:, None, 1] - y[None])
    np.testing.assert_array_equal(nn.predict(q[:, 0], q[:, 1]), z[d.argmin(1)])


def test_nearest_radius_blanks():
    nn = NearestNeighbour(SearchParams(radius=1.0)).fit([0, 10], [0, 0], [1, 2])
    assert np.isnan(nn.predict([5.0], [0.0])[0]) and nn.predict([0.5], [0.0])[0] == 1


def test_idw_hand_computed_and_bounded():
    x = np.array([0.0, 1.0, 0.0])
    y = np.array([0.0, 0.0, 2.0])
    z = np.array([1.0, 3.0, 5.0])
    idw = InverseDistance(power=2).fit(x, y, z)
    # at (0,1): distances 1, sqrt2, 1 -> weights 1, 0.5, 1
    assert idw.predict([0.0], [1.0])[0] == pytest.approx((1 + 1.5 + 5) / 2.5)
    q = np.random.default_rng(2).uniform(-5, 5, (200, 2))
    est = idw.predict(q[:, 0], q[:, 1])
    assert est.min() >= 1 - 1e-12 and est.max() <= 5 + 1e-12  # convex combination
    sm = InverseDistance(power=2, smoothing=0.5).fit(x, y, z)
    assert sm.predict([0.0], [0.0])[0] != pytest.approx(1.0)  # smoothing -> not exact


def test_idw_search_min_points_blank():
    idw = InverseDistance(search=SearchParams(radius=2, max_points=8, min_points=2))
    idw.fit([0, 1, 10], [0, 0, 0], [1, 2, 3])
    assert np.isfinite(idw.predict([0.5], [0])[0])
    assert np.isnan(idw.predict([10.5], [0])[0])  # only one neighbour within 2


def test_anisotropy_equivalent_to_rotated_and_scaled_coordinates(pts):
    """IDW with anisotropy equals isotropic IDW on transformed coordinates."""
    x, y = pts
    z = smooth(x, y)
    an = Anisotropy(ratio=0.4, angle=30)
    a = InverseDistance(anisotropy=an).fit(x, y, z)
    tx, ty = an.transform(x, y)
    b = InverseDistance().fit(tx, ty, z)
    q = np.random.default_rng(3).uniform([0, 0], [1000, 600], (100, 2))
    qx, qy = an.transform(q[:, 0], q[:, 1])
    np.testing.assert_allclose(a.predict(q[:, 0], q[:, 1]), b.predict(qx, qy), rtol=1e-12)


def test_anisotropy_validation():
    with pytest.raises(GriddingError):
        Anisotropy(ratio=0)
    with pytest.raises(GriddingError):
        Anisotropy(ratio=1.5)


# ------------------------------------------------------------------ natural neighbour
def test_natural_neighbour_weights_properties_and_brute_force(pts):
    x, y = pts
    nn = NaturalNeighbour().fit(x, y, smooth(x, y))
    tree = cKDTree(np.column_stack([x, y]))
    for qx, qy in [(500, 300), (231.7, 412.9), (777, 99)]:
        w = nn.weights(qx, qy)
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-12)
        assert min(w.values()) >= 0
        # Brute-force Sibson: area of the fine raster stolen from each point
        res = 900
        X, Y = np.meshgrid(np.linspace(qx - 250, qx + 250, res), np.linspace(qy - 250, qy + 250, res))
        P = np.column_stack([X.ravel(), Y.ravel()])
        d, i = tree.query(P)
        stolen = np.hypot(P[:, 0] - qx, P[:, 1] - qy) < d
        ids, counts = np.unique(i[stolen], return_counts=True)
        brute = dict(zip(ids.tolist(), (counts / counts.sum()).tolist()))
        diff = max(abs(w.get(k, 0) - brute.get(k, 0)) for k in set(w) | set(brute))
        assert diff < 0.02  # raster resolution limit


def test_natural_neighbour_outside_hull_blank():
    nn = NaturalNeighbour().fit([0, 1, 0, 1], [0, 0, 1, 1], [1, 2, 3, 4])
    assert np.isnan(nn.predict([2.0], [2.0])[0])
    # on the hull edge: linear along the edge
    assert nn.predict([0.25], [0.0])[0] == pytest.approx(1.25)
    with pytest.raises(GriddingError):
        NaturalNeighbour().fit([0, 1, 2], [0, 1, 2], [1, 2, 3])


def test_tin_hull_and_collinear():
    t = LinearTriangulation().fit([0, 1, 0], [0, 0, 1], [0, 1, 2])
    assert t.predict([0.25], [0.25])[0] == pytest.approx(0.25 + 0.5)
    assert np.isnan(t.predict([1.0], [1.0])[0])
    with pytest.raises(GriddingError):
        LinearTriangulation().fit([0, 1, 2], [0, 1, 2], [1, 2, 3])


# ------------------------------------------------------------------ RBF / min curvature
def test_rbf_matches_scipy_and_smoothing(pts):
    x, y = pts
    z = smooth(x, y)
    r = RadialBasis("thin_plate_spline").fit(x, y, z)
    q = np.random.default_rng(5).uniform([0, 0], [1000, 600], (50, 2))
    ref = RBFInterpolator(np.column_stack([x - x.mean(), y - y.mean()]), z,
                          kernel="thin_plate_spline")(q - [x.mean(), y.mean()])
    np.testing.assert_allclose(r.predict(q[:, 0], q[:, 1]), ref, atol=1e-9)
    s = RadialBasis("thin_plate_spline", smoothing=1000).fit(x, y, z)
    assert np.abs(s.predict(x, y) - z).max() > 1e-2  # smoothing -> approximation
    g = RadialBasis("gaussian").fit(x, y, z)
    assert g.epsilon is not None and g.epsilon > 0  # automatic shape parameter recorded
    with pytest.raises(GriddingError):
        RadialBasis("nope")


def test_min_curvature_close_to_thin_plate_spline(pts):
    """Minimum curvature is the gridded analogue of the thin-plate spline."""
    x, y = pts
    z = smooth(x, y)
    geom = GridGeometry(0, 1000, 0, 600, 201, 121)
    X, Y = geom.mesh()
    mc = MinimumCurvature().fit(x, y, z)
    Z = mc.grid(geom)
    tps = RBFInterpolator(np.column_stack([x, y]), z, kernel="thin_plate_spline")(
        np.column_stack([X.ravel(), Y.ravel()])).reshape(X.shape)
    inner = (X > 100) & (X < 900) & (Y > 100) & (Y < 500)
    assert np.sqrt(np.mean((Z - tps)[inner] ** 2)) < 0.01
    assert mc.residuals["max_abs_residual"] < 1e-4


def test_tension_reduces_overshoot():
    # A step: the curvature-only surface overshoots the data range, tension reduces it.
    g = np.arange(0, 101, 10.0)
    X0, Y0 = np.meshgrid(g, g)
    x, y = X0.ravel(), Y0.ravel()
    z = np.where(x <= 50, 0.0, 1.0)
    geom = GridGeometry(0, 100, 0, 100, 51, 51)
    over = [np.nanmax(MinimumCurvature(tension=t).fit(x, y, z).grid(geom)) - 1 for t in (0, 0.5)]
    assert over[0] > 0.05 and over[1] < 0.5 * over[0]


def test_min_curvature_limits():
    with pytest.raises(GriddingError):
        MinimumCurvature(tension=1.0)
    mc = MinimumCurvature().fit([0, 1, 2], [0, 1, 0], [1, 2, 3])
    with pytest.raises(GriddingError):
        mc.grid(GridGeometry(10, 20, 10, 20, 5, 5))  # no data inside the grid


# ------------------------------------------------------------------ variograms
def test_variogram_model_values():
    for m in ("spherical", "exponential", "gaussian"):
        vm = VariogramModel(m, nugget=0.5, sill=2.0, range=100)
        assert vm(0.0) == 0.0  # γ(0) = 0 even with nugget
        assert vm(1e-9) == pytest.approx(0.5, abs=1e-6)
        expect = 2.5 if m == "spherical" else 0.5 + 2.0 * (1 - math.exp(-3))
        assert vm(100.0) == pytest.approx(expect)
        assert vm.covariance(0.0) == pytest.approx(2.5)
    assert VariogramModel("linear", sill=0.1)(50.0) == pytest.approx(5.0)
    assert VariogramModel("power", sill=2.0, exponent=1.5)(4.0) == pytest.approx(16.0)
    with pytest.raises(GriddingError):
        VariogramModel("linear").covariance(1.0)
    with pytest.raises(GriddingError):
        VariogramModel("spherical", range=0)
    d = VariogramModel("gaussian", 0.1, 1.0, 50, anisotropy=Anisotropy(0.5, 45)).to_dict()
    assert VariogramModel.from_dict(d).anisotropy.ratio == 0.5


def test_experimental_variogram_hand_computed():
    # four points on a line, spacing 1: lags 1 (3 pairs), 2 (2 pairs), 3 (1 pair)
    x = np.array([0.0, 1, 2, 3])
    y = np.zeros(4)
    z = np.array([0.0, 1, 0, 1])
    ev = experimental_variogram(x, y, z, n_lags=3, max_lag=3.5)
    np.testing.assert_allclose(ev.lags, [1, 2, 3])
    np.testing.assert_array_equal(ev.counts, [3, 2, 1])
    np.testing.assert_allclose(ev.gamma, [0.5, 0.0, 0.5])


def test_directional_variogram_detects_anisotropy():
    g = np.arange(0, 400, 10.0)
    X, Y = np.meshgrid(g, g)
    x, y = X.ravel(), Y.ravel()
    z = np.sin(y / 30)  # varies along Y only
    ev_x = experimental_variogram(x, y, z, n_lags=5, max_lag=50, direction=0, tolerance=5)
    ev_y = experimental_variogram(x, y, z, n_lags=5, max_lag=50, direction=90, tolerance=5)
    assert ev_x.gamma.max() < 1e-12 < ev_y.gamma.max()


def test_variogram_fit_recovers_parameters():
    true = VariogramModel("exponential", nugget=0.2, sill=1.5, range=300)
    from geohydro.engine.interpolation.variogram import ExperimentalVariogram
    h = np.linspace(10, 600, 25)
    ev = ExperimentalVariogram(h, true(h), np.full(25, 100), np.linspace(0, 610, 26), None,
                               22.5, 100, 2500, False, 1.7)
    m, rep = fit_variogram(ev, "exponential")
    assert m.sill == pytest.approx(1.5, rel=1e-4)
    assert m.range == pytest.approx(300, rel=1e-4)
    assert m.nugget == pytest.approx(0.2, abs=1e-4)
    assert rep["converged"] and not rep["warnings"]


# ------------------------------------------------------------------ kriging
pykrige = pytest.importorskip("pykrige", reason="PyKrige is the reference implementation")


@pytest.mark.parametrize("model,params,mine", [
    ("spherical", {"sill": 1.05, "range": 400, "nugget": 0.05},
     {"nugget": 0.05, "sill": 1.0, "range": 400}),
    ("exponential", {"sill": 0.9, "range": 300, "nugget": 0.0},
     {"nugget": 0.0, "sill": 0.9, "range": 300}),
    ("linear", {"slope": 0.002, "nugget": 0.01}, {"nugget": 0.01, "sill": 0.002, "range": 1}),
])
def test_kriging_matches_pykrige(pts, model, params, mine):
    from pykrige.ok import OrdinaryKriging as POK
    from pykrige.uk import UniversalKriging as PUK
    x, y = pts
    z = smooth(x, y)
    vm = VariogramModel(model, **mine)
    gx = np.linspace(0, 1000, 21)
    gy = np.linspace(0, 600, 13)
    X, Y = np.meshgrid(gx, gy)
    ok = OrdinaryKriging(vm, SearchParams(max_points=None)).fit(x, y, z)
    pz, pv = POK(x, y, z, variogram_model=model, variogram_parameters=params).execute(
        "grid", gx, gy)
    np.testing.assert_allclose(ok.predict(X, Y), pz, atol=1e-9)
    np.testing.assert_allclose(ok.last_variance, pv, atol=1e-9)
    uk = UniversalKriging(vm, "linear", SearchParams(max_points=None)).fit(x, y, z)
    pz, pv = PUK(x, y, z, variogram_model=model, variogram_parameters=params,
                 drift_terms=["regional_linear"]).execute("grid", gx, gy)
    np.testing.assert_allclose(uk.predict(X, Y), pz, atol=1e-8)
    np.testing.assert_allclose(uk.last_variance, pv, atol=1e-8)


def test_kriging_properties(pts):
    x, y = pts
    z = smooth(x, y)
    vm = VariogramModel("spherical", 0.0, 1.0, 400)
    ok = OrdinaryKriging(vm, SearchParams(max_points=16)).fit(x, y, z)
    est = ok.predict(x, y)
    np.testing.assert_allclose(est, z, atol=1e-10)
    np.testing.assert_allclose(ok.last_variance, 0, atol=1e-10)
    far = ok.predict([5000.0], [5000.0])
    assert np.isfinite(far[0]) and ok.last_variance[0] > 0.9  # approaches sill far away
    # Local neighbourhood equals global solution when the neighbourhood holds all points
    a = OrdinaryKriging(vm, SearchParams(max_points=x.size)).fit(x, y, z).predict([300], [200])
    b = OrdinaryKriging(vm, SearchParams(max_points=None)).fit(x, y, z).predict([300], [200])
    assert a[0] == pytest.approx(b[0], abs=1e-12)
    # Radius with too few neighbours blanks
    r = OrdinaryKriging(vm, SearchParams(radius=5, max_points=8, min_points=3)).fit(x, y, z)
    assert np.isnan(r.predict([5000.0], [5000.0])[0])


def test_kriging_anisotropy_equals_transformed_isotropic(pts):
    x, y = pts
    z = smooth(x, y)
    an = Anisotropy(ratio=0.5, angle=60)
    a = OrdinaryKriging(VariogramModel("spherical", 0, 1, 400, anisotropy=an),
                        SearchParams(max_points=None)).fit(x, y, z)
    tx, ty = an.transform(x, y)
    b = OrdinaryKriging(VariogramModel("spherical", 0, 1, 400),
                        SearchParams(max_points=None)).fit(tx, ty, z)
    q = np.random.default_rng(8).uniform([0, 0], [1000, 600], (40, 2))
    qx, qy = an.transform(q[:, 0], q[:, 1])
    np.testing.assert_allclose(a.predict(q[:, 0], q[:, 1]), b.predict(qx, qy), atol=1e-10)


def test_kriging_input_errors(pts):
    x, y = pts
    with pytest.raises(GriddingError):
        build_interpolator("ordinary_kriging", {})
    with pytest.raises(GriddingError):
        UniversalKriging(VariogramModel(), drift="cubic")
    big = np.random.default_rng(0).uniform(0, 1, (2000, 3))
    with pytest.raises(GriddingError):
        OrdinaryKriging(VariogramModel(), SearchParams(max_points=None)).fit(
            big[:, 0], big[:, 1], big[:, 2])


# ------------------------------------------------------------------ accuracy on sample data
def test_accuracy_against_known_sample_surface(samples):
    """Grid the synthetic terrain survey and compare with its generating function.

    Thresholds are regression guards set from measured values (documented
    in docs/TEST_RESULTS.md), not claims of general accuracy.
    """
    import importlib.util
    import pandas as pd
    spec = importlib.util.spec_from_file_location("gen", samples.parent / "generate_samples.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    df = pd.read_csv(samples / "terrain_survey_utm39n.csv")
    x, y, z = df["Easting_m"].values, df["Northing_m"].values, df["Elevation_m"].values
    geom = GridGeometry.from_spacing(441000, 449000, 2886000, 2894000, 200)  # interior
    X, Y = geom.mesh()
    truth = gen.terrain_surface(X, Y)
    ev = experimental_variogram(x, y, z, n_lags=15, max_lag=5000)
    vm, _ = fit_variogram(ev, "gaussian")
    params = {"idw": {}, "nearest": {}, "tin": {}, "natural_neighbour": {}, "rbf": {},
              "min_curvature": {}, "ordinary_kriging": {"variogram": vm.to_dict()},
              "universal_kriging": {"variogram": vm.to_dict()}}
    limits = {"idw": 1.6, "nearest": 2.2, "tin": 0.9, "natural_neighbour": 0.8, "rbf": 0.5,
              "min_curvature": 0.5, "ordinary_kriging": 0.5, "universal_kriging": 0.5}
    assert set(params) == set(METHODS)
    for m, p in params.items():
        g = grid_data(x, y, z, GriddingRequest(m, p, geom)).grid
        rmse = float(np.sqrt(np.nanmean((g.z - truth) ** 2)))
        assert rmse < limits[m], (m, rmse)


def test_universal_kriging_singular_systems_are_reported():
    """Collinear data on the target's own line make the linear-drift system exactly
    singular: that node is left blank and the count is reported, never silently."""
    x = np.linspace(0, 100, 12)
    y = np.zeros_like(x)
    uk = UniversalKriging(VariogramModel("linear", sill=1.0), "linear", SearchParams(max_points=8))
    uk.fit(x, y, 0.1 * x)
    out = uk.predict(np.array([50.0, 20.0]), np.array([0.0, 0.0]))
    assert np.isnan(out).all()
    assert uk.n_singular == 2 and "2 node(s) had a singular kriging system" in uk.warnings[-1]
