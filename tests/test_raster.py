"""Raster engine: GeoTIFF/GDAL grids, display images, conventions and limits."""

import shutil
import subprocess

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.transform import from_origin

from geohydro.engine.errors import GridFileError, RasterError
from geohydro.engine.gridding.grid import Grid, GridGeometry
from geohydro.engine.gridding.io import read_grid, write_grid
from geohydro.engine.raster import RasterImage
from geohydro.engine.raster.image import reproject_image
from geohydro.engine.raster.io import (raster_info, read_raster, read_raster_grid,
                                       read_raster_image, write_geotiff)

UTM = "EPSG:32639"


def _tif(path, data, transform=None, crs=UTM, nodata=None, **kw):
    data = np.asarray(data)
    if data.ndim == 2:
        data = data[None]
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[2], height=data.shape[1],
                       count=data.shape[0], dtype=data.dtype, crs=crs, nodata=nodata,
                       transform=transform or from_origin(500000, 2900050, 10, 10), **kw) as d:
        d.write(data)
    return path


def _grid():
    z = np.arange(50.0).reshape(5, 10)
    z[0, 0] = np.nan
    return Grid(GridGeometry(500005, 500095, 2900005, 2900045, 10, 5), z, crs=UTM,
                z_units="m", z_label="Head")


def test_cell_centres_become_nodes_and_rows_flip(tmp_path):
    data = np.arange(12, dtype="float32").reshape(3, 4)  # file row 0 = north
    g = read_raster_grid(_tif(tmp_path / "a.tif", data))
    assert (g.geometry.x_min, g.geometry.y_max) == (500005.0, 2900045.0)
    assert (g.geometry.dx, g.geometry.dy) == (10.0, 10.0)
    assert np.array_equal(g.z, data[::-1])           # grid row 0 = south
    assert g.value_at(500005, 2900045) == 0.0        # NW cell centre
    assert g.crs == UTM and g.xy_units == "m"


def test_geotiff_round_trip_exact(tmp_path):
    g = _grid()
    back = read_grid(write_grid(g, tmp_path / "g.tif"))
    assert back.geometry == g.geometry
    assert np.array_equal(back.z, g.z, equal_nan=True)
    assert back.crs == UTM and back.z_units == "m" and back.z_label == "Head"
    with rasterio.open(tmp_path / "g.tif") as src:
        assert src.dtypes[0] == "float64" and np.isnan(src.nodata)
        assert src.transform == from_origin(500000, 2900050, 10, 10)


def test_geotiff_float32_option(tmp_path):
    g = _grid().copy(z=np.full((5, 10), 1 / 3))
    back = read_raster_grid(write_geotiff(g, tmp_path / "f.tif", dtype="float32"))
    assert np.allclose(back.z, 1 / 3, rtol=1e-7) and not np.array_equal(back.z, g.z)


@pytest.mark.skipif(shutil.which("gdal_translate") is None, reason="GDAL command line tools")
def test_matches_gdal_conversion_of_esri_ascii(tmp_path):
    """Our ASC writer + GDAL's own ASC→GeoTIFF conversion + our reader = original grid."""
    g = _grid()
    write_grid(g, tmp_path / "g.asc")
    subprocess.run(["gdal_translate", "-q", "-of", "GTiff", str(tmp_path / "g.asc"),
                    str(tmp_path / "gdal.tif")], check=True)
    back = read_raster_grid(tmp_path / "gdal.tif")
    assert back.geometry == g.geometry
    assert np.array_equal(back.z, g.z, equal_nan=True)


def test_nodata_and_mask(tmp_path):
    data = np.array([[1, -9999], [3, 4]], dtype="int16")
    g = read_raster_grid(_tif(tmp_path / "n.tif", data, nodata=-9999))
    assert np.isnan(g.z[1, 1]) and g.n_blank == 1   # north-east cell, grid row 1
    assert g.metadata["source"]["nodata"] == -9999


def test_scale_offset_applied(tmp_path):
    p = _tif(tmp_path / "s.tif", np.array([[100, 200], [300, 400]], dtype="uint16"))
    with rasterio.open(p, "r+") as d:
        d.scales = (0.01,)
        d.offsets = (-1.0,)
    g = read_raster_grid(p)
    assert np.allclose(g.z[::-1], [[0.0, 1.0], [2.0, 3.0]])
    assert g.metadata["processing"][-1]["operation"] == "scale_offset"


def test_south_up_raster(tmp_path):
    data = np.arange(6, dtype="float32").reshape(2, 3)  # file row 0 = south
    tr = Affine(10, 0, 500000, 0, 10, 2900000)
    g = read_raster_grid(_tif(tmp_path / "su.tif", data, transform=tr))
    assert g.geometry.y_min == 2900005.0
    assert np.array_equal(g.z, data)


def test_rotated_raster_is_warped_with_warning(tmp_path):
    tr = Affine.translation(500000, 2900100) * Affine.rotation(10) * Affine.scale(10, -10)
    g = read_raster_grid(_tif(tmp_path / "r.tif", np.ones((10, 10), "float32"), transform=tr))
    assert any("warped" in w for w in g.metadata["warnings"])
    v = g.z[np.isfinite(g.z)]
    assert v.size > 50 and np.allclose(v, 1.0)


def test_reprojection_on_import(tmp_path):
    p = _tif(tmp_path / "u.tif", np.full((20, 20), 5.0, "float32"))
    g = read_raster_grid(p, target_crs="EPSG:4326")
    assert g.crs == "EPSG:4326" and g.xy_units == "deg"
    assert 50.9 < g.geometry.x_min < 51.1 and 26.1 < g.geometry.y_min < 26.3
    assert np.allclose(g.z[np.isfinite(g.z)], 5.0)
    assert g.metadata["processing"][0]["operation"] == "warp"


def test_decimation_block_average(tmp_path):
    data = np.arange(64, dtype="float64").reshape(8, 8)
    g = read_raster_grid(_tif(tmp_path / "big.tif", data), max_nodes=16)
    assert g.geometry.shape == (4, 4) and g.geometry.dx == 20.0
    expected = data.reshape(4, 2, 4, 2).mean(axis=(1, 3))[::-1]
    assert np.allclose(g.z, expected)
    assert g.geometry.x_min == 500010.0          # centre of the first 2×2 block
    assert any("averaged" in w for w in g.metadata["warnings"])


def test_band_selection_and_errors(tmp_path):
    p = _tif(tmp_path / "m.tif", np.stack([np.zeros((3, 3)), np.ones((3, 3))]).astype("f4"))
    assert read_raster_grid(p, band=2).z.mean() == 1.0
    with pytest.raises(RasterError, match="band 3"):
        read_raster_grid(p, band=3)
    with pytest.raises(RasterError, match="not found"):
        read_raster_grid(tmp_path / "missing.tif")
    with pytest.raises(RasterError, match="2 × 2"):
        read_raster_grid(_tif(tmp_path / "one.tif", np.ones((1, 5), "f4")))
    bad = tmp_path / "bad.tif"
    bad.write_bytes(b"not a tiff")
    with pytest.raises(GridFileError):
        read_grid(bad)


def test_no_crs_and_no_georeferencing_warn(tmp_path):
    p = _tif(tmp_path / "plain.tif", np.ones((3, 3), "f4"), transform=Affine.identity(), crs=None)
    g = read_raster_grid(p)
    w = " ".join(g.metadata["warnings"])
    assert "no coordinate reference system" in w and "pixel coordinates" in w
    assert g.crs is None and g.geometry.x_min == 0.5


def test_classify_and_rgb_image(tmp_path):
    rgb = np.zeros((3, 4, 5), np.uint8)
    rgb[0], rgb[1], rgb[2] = 200, 100, 50
    p = _tif(tmp_path / "rgb.tif", rgb, photometric="RGB")
    info = raster_info(p)
    assert info["kind"] == "image" and info["count"] == 3
    img = read_raster(p)
    assert isinstance(img, RasterImage)
    assert img.extent == (500000.0, 500050.0, 2900010.0, 2900050.0)
    assert tuple(img.rgba[0, 0]) == (200, 100, 50, 255)
    assert raster_info(_tif(tmp_path / "dem.tif", np.ones((3, 3), "f4")))["kind"] == "grid"


def test_palette_image_and_transparency(tmp_path):
    p = _tif(tmp_path / "pal.tif", np.array([[0, 1], [2, 1]], np.uint8), nodata=0)
    with rasterio.open(p, "r+") as d:
        d.write_colormap(1, {0: (0, 0, 0, 255), 1: (255, 0, 0, 255), 2: (0, 0, 255, 255)})
    img = read_raster_image(p)
    assert img.metadata["palette"]
    assert tuple(img.rgba[0, 1]) == (255, 0, 0, 255)
    assert img.rgba[0, 0, 3] == 0                    # NoData → transparent


def test_uint16_image_is_stretched(tmp_path):
    data = np.stack([np.linspace(0, 4000, 100).reshape(10, 10).astype("uint16")] * 3)
    img = read_raster_image(_tif(tmp_path / "u16.tif", data, photometric="RGB"))
    assert img.rgba[..., 0].min() == 0 and img.rgba[..., 0].max() == 255
    assert any("stretched" in w for w in img.metadata["warnings"])


def test_image_downsampled_for_display(tmp_path):
    data = np.full((3, 300, 200), 128, np.uint8)
    img = read_raster_image(_tif(tmp_path / "large.tif", data, photometric="RGB"), max_size=100)
    assert img.shape == (100, 66)
    assert img.extent[0] == 500000.0 and np.isclose(img.extent[1], 502000.0, atol=31)


def test_reproject_image():
    rgba = np.full((50, 50, 4), 255, np.uint8)
    img = RasterImage("i", rgba, (500000, 505000, 2900000, 2905000), crs=UTM)
    out = reproject_image(img, "EPSG:4326")
    assert out.crs == "EPSG:4326"
    x0, x1, y0, y1 = out.extent
    assert 50.99 < x0 < 51.0 and 51.04 < x1 < 51.06 and 26.18 < y0 < 26.23
    assert out.rgba[..., 3].max() == 255
    with pytest.raises(RasterError):
        RasterImage("bad", np.zeros((2, 2, 3), np.uint8), (0, 1, 0, 1))
