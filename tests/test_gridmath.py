"""Grid mathematics: calculator, filters, terrain (vs gdaldem), volumes, blanking."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import shapely
from scipy import ndimage

from geohydro.engine.errors import GridMathError
from geohydro.engine.gridding.grid import Grid, GridGeometry
from geohydro.engine.gridmath import terrain
from geohydro.engine.gridmath.blanking import blank_polygon, clip_extent
from geohydro.engine.gridmath.calculator import calculate, parse
from geohydro.engine.gridmath.common import resample
from geohydro.engine.gridmath.filters import apply_filter
from geohydro.engine.gridmath.volume import volume, weights_1d
from geohydro.engine.raster.io import read_raster_grid
from geohydro.engine.vector import VectorDataset

GD = Path(__file__).parent / "fixtures" / "gdaldem"


def grid_of(f, x0=0.0, x1=1.0, y0=0.0, y1=1.0, nx=11, ny=11, **kw):
    geom = GridGeometry(x0, x1, y0, y1, nx, ny)
    X, Y = geom.mesh()
    kw.setdefault("crs", "EPSG:32639")
    return Grid(geom, f(X, Y).astype(float), **kw)


# ------------------------------------------------------------------ calculator
def test_calculator_arithmetic_and_provenance():
    a = grid_of(lambda x, y: x + y, name="A grid")
    b = grid_of(lambda x, y: 2 * x, name="B grid")
    out = calculate("(A - B) * 2 + sqrt(abs(A))", {"A": a, "B": b}, name="R")
    assert np.allclose(out.z, (a.z - b.z) * 2 + np.sqrt(np.abs(a.z)))
    md = out.metadata
    assert md["parameters"]["expression"] == "(A - B) * 2 + sqrt(abs(A))"
    assert md["source"]["grid_ids"] == [a.id, b.id] and out.name == "R"
    assert a.z[0, 0] == 0.0  # inputs untouched


def test_calculator_blanks_and_undefined_results_are_reported():
    a = grid_of(lambda x, y: x - 0.5)
    a.z[3, 3] = np.nan
    out = calculate("1 / A", {"A": a})
    assert np.isnan(out.z[3, 3])
    assert np.isnan(out.z[:, 5]).all()                       # x = 0.5 → 1/0 blanked
    assert any("infinite" in w for w in out.metadata["warnings"])
    out = calculate("log(A)", {"A": a})
    assert any("undefined" in w for w in out.metadata["warnings"])
    assert np.isnan(out.z[:, :5]).all() and np.isfinite(out.z[0, 6])


def test_calculator_conditionals_and_functions():
    a = grid_of(lambda x, y: x * 10)
    out = calculate("where(A > 5, A, blank)", {"A": a})
    assert np.isnan(out.z[:, :6]).all() and out.z[0, 10] == 10
    assert np.allclose(calculate("fillblank(where(A > 5, A, nan), -1)", {"A": a}).z[:, 0], -1)
    assert np.allclose(calculate("(A > 2) & (A < 8)", {"A": a}).z[0], [0, 0, 0, 1, 1, 1, 1, 1,
                                                                       0, 0, 0])
    assert np.allclose(calculate("max(A, 5)", {"A": a}).z[0, :3], 5)


@pytest.mark.parametrize("expr", ["__import__('os').system('x')", "A.__class__", "open('f')",
                                  "[A for A in B]", "lambda: 1", "A if B else C", "'text'",
                                  "D[0]", "exec('1')", "abs(x=A)"])
def test_calculator_rejects_unsafe_expressions(expr):
    with pytest.raises(GridMathError):
        parse(expr)


def test_calculator_resamples_and_checks_crs():
    a = grid_of(lambda x, y: x + y)
    b = grid_of(lambda x, y: x + y, nx=21, ny=21)
    out = calculate("A - B", {"A": a, "B": b})
    assert np.allclose(out.z, 0, atol=1e-12)               # bilinear exact for a plane
    assert any("resampled" in w for w in out.metadata["warnings"])
    c = grid_of(lambda x, y: x, crs="EPSG:4326")
    with pytest.raises(GridMathError, match="different coordinate"):
        calculate("A + C", {"A": a, "C": c})
    with pytest.raises(GridMathError, match="No grid assigned"):
        calculate("A + D", {"A": a})
    with pytest.raises(GridMathError, match="uses no grid"):
        calculate("1 + 2", {"A": a})


def test_resample_nearest_and_outside():
    a = grid_of(lambda x, y: x * 10)
    out = resample(a, GridGeometry(0.5, 1.5, 0, 1, 11, 11), "nearest")
    assert np.allclose(out.z[:, :6], np.round(np.linspace(0.5, 1.0, 6), 1) * 10)
    assert np.isnan(out.z[:, 6:]).all()


# ------------------------------------------------------------------ filters
def test_mean_filter_matches_uniform_filter_in_interior():
    rng = np.random.default_rng(1)
    a = grid_of(lambda x, y: rng.normal(size=x.shape), nx=30, ny=20)
    out = apply_filter(a, "mean", 5)
    ref = ndimage.uniform_filter(a.z, 5, mode="constant")
    assert np.allclose(out.z[2:-2, 2:-2], ref[2:-2, 2:-2])
    # edge windows are truncated, not zero-padded: a constant stays constant
    c = apply_filter(grid_of(lambda x, y: 0 * x + 7), "mean", 5)
    assert np.allclose(c.z, 7)


def test_filters_on_plane_spike_and_blanks():
    plane = grid_of(lambda x, y: 3 * x - 2 * y)
    assert np.allclose(apply_filter(plane, "highpass", 3).z[1:-1, 1:-1], 0, atol=1e-12)
    spiky = plane.copy()
    spiky.z[5, 5] = 1000
    med = apply_filter(spiky, "median", 3)
    assert abs(med.z[5, 5] - plane.z[5, 5]) < 0.31
    blank = plane.copy()
    blank.z[4, 4] = np.nan
    for kind in ("mean", "median", "minimum", "maximum", "std", "range"):
        out = apply_filter(blank, kind, 3)
        assert np.isnan(out.z[4, 4]) and np.isfinite(out.z[4, 5])
    assert np.allclose(apply_filter(grid_of(lambda x, y: 0 * x + 2), "std", 3).z, 0)
    sparse = apply_filter(blank, "mean", 3, min_valid=9)
    assert np.isnan(sparse.z[0, 0]) and np.isnan(sparse.z[5, 5]) and np.isfinite(sparse.z[6, 6])
    rng_ = apply_filter(plane, "range", 3).z[5, 5]
    assert math.isclose(rng_, 3 * 0.2 + 2 * 0.2)


def test_gaussian_filter_normalised_and_errors():
    c = grid_of(lambda x, y: 0 * x + 4)
    c.z[0, 0] = np.nan
    g = apply_filter(c, "gaussian", sigma=0.15)
    assert np.allclose(g.z[np.isfinite(g.z)], 4) and np.isnan(g.z[0, 0])
    with pytest.raises(GridMathError):
        apply_filter(c, "mean", 4)
    with pytest.raises(GridMathError):
        apply_filter(c, "gaussian")
    with pytest.raises(GridMathError):
        apply_filter(c, "sharpen")
    two = apply_filter(grid_of(lambda x, y: x), "mean", 3, passes=2)
    assert two.metadata["parameters"]["passes"] == 2


# ------------------------------------------------------------------ terrain vs GDAL
@pytest.fixture(scope="module")
def dem():
    return read_raster_grid(GD / "dem.tif")


def _cmp(mine, ref, circular=False):
    assert np.array_equal(np.isfinite(mine), np.isfinite(ref))  # same blank pattern (edges)
    ok = np.isfinite(ref)
    d = np.abs(mine[ok] - ref[ok])
    if circular:
        d = np.minimum(d, 360 - d)
    return d.max()


def test_slope_matches_gdaldem(dem):
    # gdaldem writes float32: agreement to float32 precision
    assert _cmp(terrain.slope(dem).z, read_raster_grid(GD / "slope.tif").z) < 1e-4


def test_aspect_matches_gdaldem(dem):
    assert _cmp(terrain.aspect(dem).z, read_raster_grid(GD / "aspect.tif").z, True) < 1e-2


@pytest.mark.parametrize("fname,az,alt,zf", [("hillshade_315_45.tif", 315, 45, 1),
                                             ("hillshade_120_30_z2.tif", 120, 30, 2)])
def test_hillshade_matches_gdaldem(dem, fname, az, alt, zf):
    ref = read_raster_grid(GD / fname).z            # bytes 1..255 = 1 + 254·cos(i); 0 = nodata
    ref = np.where(ref == 0, np.nan, (ref - 1) / 254 * 255)
    assert _cmp(terrain.hillshade(dem, az, alt, zf).z, ref) <= 0.51   # byte rounding


@pytest.mark.parametrize("a,b,exp_aspect", [(1, 0, 270), (-1, 0, 90), (0, 1, 180), (0, -1, 0),
                                            (1, 1, 225), (-1, -1, 45)])
def test_plane_slope_aspect_analytic(a, b, exp_aspect):
    g = grid_of(lambda x, y: 0.1 * (a * x + b * y), 0, 100, 0, 100)
    s = terrain.slope(g).z[1:-1, 1:-1]
    assert np.allclose(s, math.degrees(math.atan(0.1 * math.hypot(a, b))))
    asp = terrain.aspect(g).z[1:-1, 1:-1]
    assert np.allclose(asp, exp_aspect)
    pct = terrain.slope(g, "percent").z[1:-1, 1:-1]
    assert np.allclose(pct, 10 * math.hypot(a, b))


def test_flat_aspect_blank_and_units():
    flat = grid_of(lambda x, y: 0 * x + 5, 0, 100, 0, 100)
    out = terrain.aspect(flat)
    assert np.isnan(out.z).all() and any("flat" in w for w in out.metadata["warnings"])
    ft = grid_of(lambda x, y: x / 0.3048, 0, 100, 0, 100, z_units="ft")
    assert np.allclose(terrain.slope(ft).z[1:-1, 1:-1], 45)       # 1 m per m after conversion
    with pytest.raises(GridMathError, match="not a length"):
        terrain.slope(grid_of(lambda x, y: x, z_units="mg/L"))


def test_geographic_slope_uses_ellipsoid():
    from geohydro.engine.gridmath.common import WGS84_A, WGS84_E2
    lat0 = 25.0
    M = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * math.sin(math.radians(lat0)) ** 2) ** 1.5
    # z rises 0.05 m per metre northwards
    g = grid_of(lambda x, y: 0.05 * M * np.radians(y - lat0), 50.0, 50.02, 24.99, 25.01, 21, 21,
                crs="EPSG:4326", xy_units="deg")
    s = terrain.slope(g).z[1:-1, 1:-1]
    assert np.allclose(s, math.degrees(math.atan(0.05)), atol=2e-4)
    assert np.allclose(terrain.aspect(g).z[1:-1, 1:-1], 180)


def test_curvature_paraboloid_exact():
    a, b = 0.002, -0.001
    g = grid_of(lambda x, y: a * x ** 2 + b * y ** 2, -100, 100, -100, 100, 41, 41)
    assert np.allclose(terrain.curvature(g, "total").z[1:-1, 1:-1], 2 * a + 2 * b)
    prof = terrain.curvature(g, "profile").z
    plan = terrain.curvature(g, "plan").z
    j0, i = 20, 30                                    # on the x axis (y = 0), x = 50
    assert math.isclose(prof[j0, i], 2 * a) and math.isclose(plan[j0, i], 2 * b)
    assert np.isnan(prof[20, 20])                     # flat at the vertex


def test_plan_curvature_sign_on_a_peak():
    g = grid_of(lambda x, y: -np.hypot(x, y), -100, 100, -100, 100, 81, 81)
    plan = terrain.curvature(g, "plan").z
    assert plan[40, 60] < 0                           # spur/peak: divergent, negative


def test_profile_along_line():
    g = grid_of(lambda x, y: 2 * x + y, 0, 100, 0, 100)
    p = terrain.profile(g, [(0, 0), (100, 0), (100, 50)], spacing=10)
    assert p["distance"][-1] == 150 and np.allclose(p["z"], 2 * p["x"] + p["y"])
    assert len(p["distance"]) == 16
    out = terrain.profile(g, [(50, 50), (150, 50)], spacing=25)
    assert np.isnan(out["z"][-1]) and np.isfinite(out["z"][0])


# ------------------------------------------------------------------ volumes
def test_weights_sum_and_exactness():
    for m in range(1, 12):
        for method in ("trapezoidal", "simpson", "simpson38"):
            w = weights_1d(m + 1, 0.5, method)
            assert math.isclose(w.sum(), 0.5 * m)
    x = np.linspace(0, 2, 10)                          # 9 intervals: 1/3 + 3/8 end panel
    for method in ("simpson", "simpson38"):
        assert math.isclose(weights_1d(10, x[1] - x[0], method) @ x ** 3, 4.0)


def test_volume_rules_on_paraboloid():
    g = grid_of(lambda x, y: x ** 2 + y ** 2)          # ∫∫ over the unit square = 2/3
    h = 0.1
    trap = volume(g, 0.0, "trapezoidal")
    assert math.isclose(trap["net_volume"], 2 * (1 / 3 + h * h / 6), rel_tol=1e-12)
    assert math.isclose(volume(g, 0.0, "simpson")["net_volume"], 2 / 3, rel_tol=1e-12)
    g10 = grid_of(lambda x, y: x ** 3 * y, 0, 2, 0, 1, 10, 10)   # ∫∫ = 4 · 1/2 = 2
    assert math.isclose(volume(g10, 0.0, "simpson38")["net_volume"], 2.0, rel_tol=1e-12)
    assert math.isclose(volume(g10, 0.0, "simpson")["net_volume"], 2.0, rel_tol=1e-12)


def test_cut_fill_plane_and_lower_grid():
    g = grid_of(lambda x, y: x - 0.5)                  # zero line on a node column
    r = volume(g, 0.0)
    assert math.isclose(r["cut_volume"], 0.125) and math.isclose(r["fill_volume"], 0.125)
    assert abs(r["net_volume"]) < 1e-15 and math.isclose(r["planar_area"], 1.0)
    lower = grid_of(lambda x, y: x - 0.5 + 0 * y - 1.0)
    r2 = volume(g, lower)
    assert math.isclose(r2["net_volume"], 1.0) and r2["fill_volume"] == 0


def test_volume_units_blanks_and_surface_area():
    ft = grid_of(lambda x, y: 0 * x + 10 / 0.3048, 0, 10, 0, 10, z_units="ft")
    assert math.isclose(volume(ft, 0.0)["net_volume"], 1000.0)
    lvl = volume(ft, 5 / 0.3048)
    assert math.isclose(lvl["net_volume"], 500.0)      # level given in the grid's Z unit
    b = grid_of(lambda x, y: 0 * x + 1.0, 0, 10, 0, 10)
    b.z[5, 5] = np.nan
    r = volume(b, 0.0)
    assert r["cells_excluded"] == 4 and math.isclose(r["planar_area"], 96.0)
    with pytest.raises(GridMathError, match="trapezoidal"):
        volume(b, 0.0, "simpson")
    tilt = grid_of(lambda x, y: x * math.tan(math.radians(30)), 0, 10, 0, 10)
    assert math.isclose(volume(tilt, 0.0)["surface_area"], 100 / math.cos(math.radians(30)))


def test_volume_geographic_cell_areas():
    from pyproj import Geod
    g = grid_of(lambda x, y: 0 * x + 1.0, 50.0, 50.1, 25.0, 25.1, 11, 11, crs="EPSG:4326",
                xy_units="deg")
    area = abs(Geod(ellps="WGS84").geometry_area_perimeter(
        shapely.segmentize(shapely.box(50.0, 25.0, 50.1, 25.1), 0.001))[0])
    r = volume(g, 0.0)
    assert math.isclose(r["planar_area"], area, rel_tol=1e-4)
    assert math.isclose(r["net_volume"], area, rel_tol=1e-4)


# ------------------------------------------------------------------ blanking
def test_blank_inside_outside_with_hole_and_vector_layer():
    g = grid_of(lambda x, y: x + y, 0, 10, 0, 10)
    poly = shapely.Polygon([(2, 2), (8, 2), (8, 8), (2, 8)], [[(4, 4), (6, 4), (6, 6), (4, 6)]])
    inside = blank_polygon(g, poly)
    X, Y = g.geometry.mesh()
    in_ring = (X >= 2) & (X <= 8) & (Y >= 2) & (Y <= 8)
    in_hole = (X > 4) & (X < 6) & (Y > 4) & (Y < 6)
    assert np.array_equal(np.isnan(inside.z), in_ring & ~in_hole)
    outside = blank_polygon(g, poly, outside=True)
    assert np.array_equal(np.isnan(outside.z), ~(in_ring & ~in_hole))
    lay = VectorDataset("zone", np.array([shapely.box(0, 0, 5, 5)], dtype=object),
                        pd.DataFrame({"k": [1]}), crs="EPSG:32639")
    out = blank_polygon(g, lay, outside=True)
    assert out.metadata["parameters"]["vector_name"] == "zone"
    assert np.isfinite(out.z[5, 5]) and np.isnan(out.z[6, 6])


def test_blank_reprojects_layer_and_clip_extent():
    from geohydro.engine.vector.ops import reproject
    g = grid_of(lambda x, y: x, 500000, 501000, 2900000, 2901000)
    lay = VectorDataset("z", np.array([shapely.box(499950, 2899950, 500550, 2901050)],
                                      dtype=object), None, crs="EPSG:32639")
    out = blank_polygon(g, reproject(lay, "EPSG:4326"))
    assert np.isnan(out.z[:, :6]).all() and np.isfinite(out.z[:, 6:]).all()
    c = clip_extent(g, 500200, 500600, 2900100, 2900300)
    assert c.geometry.nx == 5 and c.geometry.ny == 3 and c.geometry.x_min == 500200
    assert np.array_equal(c.z, g.z[1:4, 2:7])
    with pytest.raises(GridMathError):
        clip_extent(g, 0, 1, 0, 1)
