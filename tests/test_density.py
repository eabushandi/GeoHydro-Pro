"""Point density (KDE) validated against scikit-learn, and point counts."""

import math

import numpy as np
import pandas as pd
import pytest
import shapely
from sklearn.neighbors import KernelDensity

from geohydro.engine.errors import GridMathError, VectorError
from geohydro.engine.gridding.grid import GridGeometry
from geohydro.engine.gridmath.density import (bandwidth, kernel_density, kernel_value,
                                              point_count)
from geohydro.engine.vector import VectorDataset
from geohydro.engine.vector.ops import to_point_dataset

GEOM = GridGeometry(0, 1000, 0, 800, 101, 81)


@pytest.fixture(scope="module")
def pts():
    rng = np.random.default_rng(3)
    return rng.normal(500, 80, 300), rng.normal(400, 50, 300)


@pytest.mark.parametrize("ours,sk,tol", [("gaussian", "gaussian", 1e-5),
                                         ("epanechnikov", "epanechnikov", 1e-12),
                                         ("uniform", "tophat", 1e-12),
                                         ("triangular", "linear", 1e-12)])
def test_matches_scikit_learn(pts, ours, sk, tol):
    x, y = pts
    g = kernel_density(x, y, GEOM, h=60, kernel=ours)
    X, Y = GEOM.mesh()
    kd = KernelDensity(kernel=sk, bandwidth=60).fit(np.column_stack([x, y]))
    ref = np.exp(kd.score_samples(np.column_stack([X.ravel(), Y.ravel()]))) * len(x)
    assert np.max(np.abs(g.z.ravel() - ref)) / ref.max() < tol


@pytest.mark.parametrize("kernel", ["quartic", "epanechnikov", "triangular", "uniform",
                                    "gaussian"])
def test_kernels_integrate_to_one(kernel):
    r = np.linspace(0, 6, 600_001)
    dr = r[1] - r[0]
    area = np.sum(kernel_value(kernel, r, 1.0) * 2 * np.pi * r) * dr
    assert math.isclose(area, 1.0, rel_tol=1e-4 if kernel == "uniform" else 1e-5)


def test_quartic_peak_and_integral(pts):
    g = kernel_density([500.0], [400.0], GEOM, h=100, kernel="quartic")
    assert math.isclose(g.value_at(500, 400), 3 / (math.pi * 100 ** 2))
    x, y = pts
    g = kernel_density(x, y, GEOM, h=50, kernel="quartic")
    chk = g.metadata["check"]
    assert math.isclose(chk["grid_integral"], 300, rel_tol=2e-3)   # all kernels inside the grid


def test_weights_probability_and_units(pts):
    x, y = pts
    w = np.full(x.size, 2.0)
    a = kernel_density(x, y, GEOM, h=60, weights=w)
    b = kernel_density(x, y, GEOM, h=60)
    assert np.allclose(a.z, 2 * b.z) and a.z_units == "weight per unit area"
    p = kernel_density(x, y, GEOM, h=60, normalize="probability")
    assert np.allclose(p.z, b.z / 300)
    km = kernel_density(x, y, GEOM, h=60, area_unit_factor=1e6)
    assert np.allclose(km.z, b.z * 1e6)
    with pytest.raises(GridMathError, match="negative"):
        kernel_density(x, y, GEOM, h=60, weights=-w)


def test_bandwidth_rules(pts):
    x, y = pts
    s = math.sqrt((np.var(x) + np.var(y)) / 2) * 300 ** (-1 / 6)
    assert math.isclose(bandwidth(x, y, "scott"), s)
    sd = math.sqrt(np.var(x) + np.var(y))
    dm = np.median(np.hypot(x - x.mean(), y - y.mean()))
    assert math.isclose(bandwidth(x, y, "standard_distance"),
                        0.9 * min(sd, math.sqrt(1 / math.log(2)) * dm) * 300 ** -0.2)
    g = kernel_density(x, y, GEOM, h="scott")
    assert g.metadata["parameters"]["bandwidth_rule"] == "scott"
    with pytest.raises(GridMathError):
        bandwidth([1, 1], [2, 2])


def test_geographic_refused_and_bad_points():
    with pytest.raises(GridMathError, match="projected"):
        kernel_density([1, 2], [1, 2], GEOM, h=1, xy_units="deg")
    g = kernel_density([500, np.nan], [400, 1], GEOM, h=100)
    assert any("skipped" in w for w in g.metadata["warnings"])


def test_point_count():
    x = np.array([0, 4.9, 5.0, 10, 10, 2000])
    y = np.array([0, 0, 0, 0, 0, 0])
    g = point_count(x, y, GridGeometry(0, 100, 0, 100, 11, 11))
    assert g.z[0, 0] == 2 and g.z[0, 1] == 3 and g.z.sum() == 5   # 5.0 → north-east cell
    assert any("outside" in w for w in g.metadata["warnings"])
    pa = point_count(x, y, GridGeometry(0, 100, 0, 100, 11, 11), per_area=True)
    assert math.isclose(pa.z[0, 1], 3 / 100)


def test_vector_points_to_point_dataset():
    geoms = np.array([shapely.Point(0, 0), shapely.MultiPoint([(1, 1), (2, 2)]),
                      shapely.Point(3, 3)], dtype=object)
    vds = VectorDataset("wells", geoms, pd.DataFrame({"head": [10.0, 11.0, np.nan],
                                                      "id": ["a", "b", "c"]}),
                        crs="EPSG:32639")
    pd_ = to_point_dataset(vds, "head")
    assert pd_.n_points == 3 and pd_.has_z and list(pd_.data["Z"]) == [10.0, 11.0, 11.0]
    assert pd_.qc_report["excluded_rows"] == 1 and pd_.crs == "EPSG:32639"
    assert list(pd_.data["id"]) == ["a", "b", "b"]
    with pytest.raises(VectorError):
        to_point_dataset(VectorDataset("l", np.array([shapely.LineString([(0, 0), (1, 1)])],
                                                     dtype=object), None))
