"""Numerical validation of statistics, CRS handling and unit conversion."""

import math

import numpy as np
import pytest
from scipy import stats as st

from geohydro.engine.crs import crs_storage_string, resolve_crs, transform_points
from geohydro.engine.data.statistics import describe, spatial_summary
from geohydro.engine.errors import CRSError, UnitError
from geohydro.engine.units import convert_length


def test_describe_hand_computed():
    d = describe([2, 4, 4, 4, 5, 5, 7, 9])
    assert d["count"] == 8
    assert d["mean"] == 5.0
    assert d["median"] == 4.5
    assert d["minimum"] == 2 and d["maximum"] == 9 and d["range"] == 7
    # sample variance: sum((x-5)^2)=32 -> 32/7
    assert d["variance"] == pytest.approx(32 / 7, rel=1e-15)
    assert d["std"] == pytest.approx(math.sqrt(32 / 7), rel=1e-15)


def test_describe_matches_scipy_and_ignores_nan():
    rng = np.random.default_rng(1)
    v = rng.gamma(2.0, 3.0, 500)
    d = describe(np.append(v, [np.nan, np.inf]))
    assert d["count"] == 500
    assert d["skewness"] == pytest.approx(st.skew(v, bias=False), rel=1e-12)
    assert d["q1"] == pytest.approx(np.percentile(v, 25))


def test_describe_edge_cases():
    assert describe([]) == {"count": 0}
    d = describe([3.0])
    assert d["mean"] == 3.0 and "std" not in d


def test_spatial_summary_grid():
    xs, ys = np.meshgrid(np.arange(0, 100, 10.0), np.arange(0, 50, 10.0))
    s = spatial_summary(xs.ravel(), ys.ravel())
    assert s["count"] == 50
    assert (s["x_min"], s["x_max"], s["y_min"], s["y_max"]) == (0, 90, 0, 40)
    assert s["nn_mean"] == pytest.approx(10.0) and s["nn_min"] == pytest.approx(10.0)
    assert s["density_per_unit_area"] == pytest.approx(50 / (90 * 40))


def test_resolve_crs_variants():
    a = resolve_crs("EPSG:32639")
    b = resolve_crs("32639")
    c = resolve_crs("EPSG:32639 - WGS 84 / UTM zone 39N")
    assert a.authority == b.authority == c.authority == "EPSG:32639"
    assert a.is_projected and a.is_metric and not a.is_geographic
    g = resolve_crs("EPSG:4326")
    assert g.is_geographic and g.axis_unit == "degree"
    assert resolve_crs("") is None and resolve_crs("Undefined (local)") is None
    assert crs_storage_string(a) == "EPSG:32639"


def test_resolve_crs_invalid():
    with pytest.raises(CRSError):
        resolve_crs("EPSG:99999999")
    with pytest.raises(CRSError):
        resolve_crs("not a crs")


def test_transform_wgs84_to_utm39_reference_point():
    # Central meridian of UTM 39N is 51E: a point on it at the equator maps to
    # E = 500000 m, N = 0 m exactly by definition of the projection.
    x, y = transform_points([51.0], [0.0], "EPSG:4326", "EPSG:32639")
    assert x[0] == pytest.approx(500000.0, abs=1e-6)
    assert y[0] == pytest.approx(0.0, abs=1e-6)
    # round trip
    lon, lat = transform_points([450000.0], [2885000.0], "EPSG:32639", "EPSG:4326")
    x2, y2 = transform_points(lon, lat, "EPSG:4326", "EPSG:32639")
    assert x2[0] == pytest.approx(450000.0, abs=1e-6) and y2[0] == pytest.approx(2885000.0, abs=1e-6)


def test_transform_requires_defined_crs():
    with pytest.raises(CRSError):
        transform_points([0], [0], "", "EPSG:4326")


def test_units():
    assert convert_length(1.0, "ft", "m") == pytest.approx(0.3048, rel=1e-15)
    assert convert_length(1.0, "us-ft", "m") == pytest.approx(1200 / 3937, rel=1e-15)
    assert convert_length(2500.0, "m", "km") == pytest.approx(2.5)
    np.testing.assert_allclose(convert_length([1, 2], "km", "m"), [1000, 2000])
    with pytest.raises(UnitError):
        convert_length(1, "deg", "m")
