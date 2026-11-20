"""Grid model, grid files, data preparation, gridding orchestration, cross-validation."""

import numpy as np
import pandas as pd
import pytest

from geohydro.engine.errors import CancelledError, GridFileError, GriddingError
from geohydro.engine.gridding.crossval import leave_one_out, metrics
from geohydro.engine.gridding.grid import Grid, GridGeometry, grid_statistics, nice_spacing
from geohydro.engine.gridding.gridder import (BlankingOptions, GriddingRequest, grid_data,
                                              residual_analysis)
from geohydro.engine.gridding.io import GRID_FORMATS, read_grid, write_grid
from geohydro.engine.interpolation.base import prepare_points


# ------------------------------------------------------------------ geometry
def test_geometry_from_spacing_keeps_minimum_and_extends_maximum():
    g = GridGeometry.from_spacing(0, 95, 10, 50, 10)
    assert (g.x_min, g.x_max, g.nx) == (0, 100, 11)
    assert (g.y_min, g.y_max, g.ny) == (10, 50, 5)
    assert g.dx == pytest.approx(10) and g.dy == pytest.approx(10)
    np.testing.assert_allclose(g.x_nodes(), np.arange(0, 101, 10))


def test_geometry_validation():
    with pytest.raises(GriddingError):
        GridGeometry(0, 0, 0, 1, 10, 10)
    with pytest.raises(GriddingError):
        GridGeometry(0, 1, 0, 1, 1, 10)
    with pytest.raises(GriddingError):
        GridGeometry(0, 1, 0, 1, 10_000, 10_000)
    with pytest.raises(GriddingError):
        GridGeometry.from_spacing(0, 1, 0, 1, 0)


def test_geometry_from_points_and_nice_spacing():
    g = GridGeometry.from_points([0, 1000], [0, 400], n_long=100)
    assert g.dx == g.dy == 10.0
    assert g.x_max >= 1000 and g.y_max >= 400
    assert nice_spacing(10.1) == 10
    assert nice_spacing(0.0237) == pytest.approx(0.02)
    assert nice_spacing(7.3) == 5
    assert nice_spacing(2.5) == 2.5


def test_bilinear_sample_reproduces_plane_and_respects_blanks():
    g = GridGeometry(0, 10, 0, 5, 11, 6)
    X, Y = g.mesh()
    grid = Grid(g, 2 * X - 3 * Y + 1)
    xs = np.array([0.0, 3.3, 10.0, 7.25])
    ys = np.array([0.0, 4.1, 5.0, 0.6])
    np.testing.assert_allclose(grid.sample(xs, ys), 2 * xs - 3 * ys + 1, atol=1e-12)
    assert np.isnan(grid.value_at(-0.1, 1))
    grid.z[2, 3] = np.nan
    assert np.isnan(grid.value_at(3.5, 2.5))
    assert np.isfinite(grid.value_at(4.0, 2.0))  # node itself unaffected by neighbour blank
    s = grid_statistics(grid)
    assert s["blank_nodes"] == 1 and s["valid_nodes"] == 65


# ------------------------------------------------------------------ files
@pytest.fixture
def sample_grid():
    g = GridGeometry(440000.0, 440900.0, 2885000.0, 2885500.0, 10, 6)
    X, Y = g.mesh()
    z = 0.001 * (X - 440000) + np.sin(Y / 100) + 0.1234567890123
    z[2, 4] = np.nan
    return Grid(g, z, name="t")


@pytest.mark.parametrize("fmt", ["surfer_ascii", "surfer7_binary", "esri_ascii"])
def test_grid_file_roundtrip_exact(tmp_path, sample_grid, fmt):
    p = write_grid(sample_grid, tmp_path / f"g{GRID_FORMATS[fmt][1]}", fmt)
    back = read_grid(p)
    assert back.geometry.nx == 10 and back.geometry.ny == 6
    assert back.geometry.x_min == pytest.approx(440000.0, abs=1e-6)
    assert back.geometry.y_max == pytest.approx(2885500.0, abs=1e-6)
    np.testing.assert_array_equal(np.isnan(back.z), np.isnan(sample_grid.z))
    ok = np.isfinite(sample_grid.z)
    np.testing.assert_allclose(back.z[ok], sample_grid.z[ok], rtol=0, atol=1e-12)


def test_surfer6_binary_roundtrip_single_precision(tmp_path, sample_grid):
    p = write_grid(sample_grid, tmp_path / "g.grd", "surfer6_binary")
    back = read_grid(p)
    ok = np.isfinite(sample_grid.z)
    np.testing.assert_allclose(back.z[ok], sample_grid.z[ok], rtol=1e-6)
    assert np.isnan(back.z[2, 4])


def test_read_handwritten_dsaa_and_esri_corner(write):
    p = write("a.grd", "DSAA\n3 2\n0 20\n100 110\n1 6\n1 2 3\n4 5 1.70141e38\n")
    g = read_grid(p)
    assert g.z[0].tolist() == [1, 2, 3]  # first row is the southern row
    assert g.z[1, 0] == 4 and np.isnan(g.z[1, 2])
    assert g.geometry.dx == 10 and g.geometry.dy == 10
    p = write("b.asc", "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 10\n"
                       "NODATA_value -9999\n1 2\n3 -9999\n")
    e = read_grid(p)
    assert e.geometry.x_min == 5 and e.geometry.y_min == 5  # cell centres become nodes
    assert e.z[0].tolist()[0] == 3 and np.isnan(e.z[0, 1])  # last file row is the south row
    assert e.z[1].tolist() == [1, 2]


def test_grid_file_errors(tmp_path, write, sample_grid):
    with pytest.raises(GridFileError):
        read_grid(write("bad.grd", "hello"))
    with pytest.raises(GridFileError):
        read_grid(write("short.grd", "DSAA\n3 2\n0 20\n100 110\n1 6\n1 2 3\n"))
    p = write_grid(sample_grid, tmp_path / "x.grd")
    with pytest.raises(GridFileError):
        write_grid(sample_grid, p)  # never overwrite silently
    rect = Grid(GridGeometry(0, 10, 0, 10, 11, 6), np.zeros((6, 11)))
    with pytest.raises(GridFileError):
        write_grid(rect, tmp_path / "r.asc", "esri_ascii")


def test_xyz_export(tmp_path, sample_grid):
    p = write_grid(sample_grid, tmp_path / "n.csv", "xyz")
    df = pd.read_csv(p)
    assert len(df) == 60 and df.iloc[:, 2].isna().sum() == 1


# ------------------------------------------------------------------ preparation
def test_prepare_points_invalid_and_duplicates():
    x = [0, 0, 1, np.nan, 2, 2.0000001]
    y = [0, 0, 1, 1, 2, 2]
    z = [1, 3, 5, 7, 9, 11]
    p = prepare_points(x, y, z)
    assert p.n_invalid == 1 and p.n_merged == 1 and p.x.size == 4
    assert p.z[(p.x == 0) & (p.y == 0)][0] == 2  # mean of 1 and 3
    p2 = prepare_points(x, y, z, duplicate_tolerance=1e-3, duplicate_policy="max")
    assert p2.n_merged == 2 and p2.x.size == 3 and 11 in p2.z
    assert any("merged" in w for w in p2.warnings)
    with pytest.raises(GriddingError):
        prepare_points(x, y, z, 0.1, "bogus")


# ------------------------------------------------------------------ orchestration
@pytest.fixture
def scattered():
    rng = np.random.default_rng(7)
    x = rng.uniform(0, 100, 80)
    y = rng.uniform(0, 60, 80)
    z = 10 + 0.3 * x - 0.2 * y + 2 * np.sin(x / 15)
    return x, y, z


def test_grid_data_records_provenance(scattered):
    x, y, z = scattered
    geom = GridGeometry.from_spacing(0, 100, 0, 60, 5)
    r = grid_data(x, y, z, GriddingRequest("idw", {"power": 3}, geom), name="g",
                  crs="EPSG:32639", source={"dataset_id": "abc"})
    md = r.grid.metadata
    assert md["method"] == "idw" and md["parameters"]["power"] == 3.0
    assert md["data_preparation"]["points_used"] == 80
    assert md["source"]["dataset_id"] == "abc" and r.grid.crs == "EPSG:32639"
    assert "residuals" in md and md["residuals"]["compared"] == 80
    assert r.grid.geometry == geom


def test_blanking_hull_and_distance(scattered):
    x, y, z = scattered
    geom = GridGeometry.from_spacing(-20, 120, -20, 80, 5)
    full = grid_data(x, y, z, GriddingRequest("idw", geometry=geom)).grid
    assert full.n_blank == 0
    hull = grid_data(x, y, z, GriddingRequest("idw", geometry=geom,
                                              blanking=BlankingOptions(outside_hull=True))).grid
    assert hull.n_blank > 0 and np.isnan(hull.value_at(-20, -20))
    dist = grid_data(x, y, z, GriddingRequest("idw", geometry=geom,
                                              blanking=BlankingOptions(max_distance=8))).grid
    assert dist.n_blank > 0 and dist.metadata["blanking"]["nodes_blanked"] == dist.n_blank


def test_all_blank_raises_and_cancel(scattered):
    x, y, z = scattered
    geom = GridGeometry.from_spacing(500, 600, 500, 600, 10)
    with pytest.raises(GriddingError):
        grid_data(x, y, z, GriddingRequest("tin", geometry=geom))
    with pytest.raises(CancelledError):
        grid_data(x, y, z, GriddingRequest("natural_neighbour"), cancel_check=lambda: True)


def test_kriging_variance_grid(scattered):
    x, y, z = scattered
    vg = {"model": "spherical", "nugget": 0.0, "sill": 10.0, "range": 50.0}
    r = grid_data(x, y, z, GriddingRequest("ordinary_kriging", {"variogram": vg},
                                           variance_grid=True))
    assert r.variance is not None
    v = r.variance.z
    assert np.nanmin(v) >= 0
    assert r.variance.geometry == r.grid.geometry


def test_residual_analysis_definition():
    g = GridGeometry(0, 1, 0, 1, 2, 2)
    grid = Grid(g, np.zeros((2, 2)))
    res, r = residual_analysis(grid, [0.5, 5], [0.5, 5], [2.0, 1.0])
    assert res["compared"] == 1 and res["not_compared"] == 1
    assert res["mean_error"] == 2.0 and r[0] == 2.0 and np.isnan(r[1])


# ------------------------------------------------------------------ cross-validation
def test_metrics_hand_computed():
    m = metrics([1, 2, 3, 4], [1.5, 2, 2, 4])
    # errors: 0.5, 0, -1, 0
    assert m["mean_error"] == pytest.approx(-0.125)
    assert m["mean_abs_error"] == pytest.approx(0.375)
    assert m["rmse"] == pytest.approx(np.sqrt(1.25 / 4))
    assert m["r_squared"] == pytest.approx(1 - 1.25 / 5)


def test_loo_nearest_on_a_line_is_hand_checkable():
    # 1-D arrangement: leaving out an interior point picks the closer neighbour.
    x = np.array([0.0, 1.0, 3.0, 6.0, 10.0])
    y = np.zeros(5) + np.array([0, 1e-9, 0, 1e-9, 0])
    z = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    cv = leave_one_out(x, y, z, "nearest")
    est = cv.table.set_index("observed")["estimate"]
    assert est[0.0] == 10 and est[10.0] == 0 and est[20.0] == 10 and est[40.0] == 30


def test_loo_kriging_reports_standardised_errors(scattered):
    x, y, z = scattered
    vg = {"model": "exponential", "nugget": 0.01, "sill": 8.0, "range": 60.0}
    cv = leave_one_out(x, y, z, "ordinary_kriging", {"variogram": vg})
    assert cv.n_validated == 80
    assert "mean_squared_standardised_error" in cv.metrics
    assert cv.metrics["r_squared"] > 0.9
    assert "kriging_std" in cv.table


def test_loo_subsampling_is_reported_and_reproducible(scattered):
    x, y, z = scattered
    a = leave_one_out(x, y, z, "idw", max_validation_points=20)
    b = leave_one_out(x, y, z, "idw", max_validation_points=20)
    assert a.subsampled and a.n_validated == 20
    pd.testing.assert_frame_equal(a.table, b.table)


def test_loo_min_curvature(scattered):
    x, y, z = scattered
    geom = GridGeometry.from_spacing(0, 100, 0, 60, 4)
    cv = leave_one_out(x, y, z, "min_curvature", {}, geometry=geom, max_validation_points=10)
    assert cv.metrics["n"] == 10 and cv.metrics["rmse"] < 2
