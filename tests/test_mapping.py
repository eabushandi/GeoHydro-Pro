"""2D map engine: levels, model serialisation, rendering, north arrow, export."""

import numpy as np
import pytest

from geohydro.engine.data import ImportSettings, import_point_file
from geohydro.engine.data.importer import apply_crs
from geohydro.engine.errors import MapError
from geohydro.engine.gridding.grid import Grid, GridGeometry
from geohydro.engine.mapping.levels import LevelSpec, get_cmap, nice_interval
from geohydro.engine.mapping.model import (ColourReliefLayer, ContourLayer, FilledContourLayer,
                                           MapDocument, PostLayer, layer_from_dict)
from geohydro.engine.mapping.render import export_map, render_map, true_north_bearing


@pytest.fixture
def grid():
    g = GridGeometry(440000, 450000, 2885000, 2895000, 51, 51)
    X, Y = g.mesh()
    z = 10 + 5 * np.sin((X - 440000) / 2000) * np.cos((Y - 2885000) / 3000)
    z[:3, :3] = np.nan
    return Grid(g, z, name="g", crs="EPSG:32639", z_label="Elevation", z_units="m")


@pytest.fixture
def dataset(samples):
    s = apply_crs(ImportSettings("Easting_m", "Northing_m", "Elevation_m"), "EPSG:32639")
    return import_point_file(samples / "terrain_survey_utm39n.csv", settings=s, name="terrain")


def resolver(*objs):
    d = {o.id: o for o in objs}
    return d.get


# ------------------------------------------------------------------ levels
def test_level_spec_modes():
    assert nice_interval(97, 10) == 10
    assert nice_interval(0.37, 10) == pytest.approx(0.05)
    np.testing.assert_allclose(LevelSpec("auto", 10).levels(3.2, 97.5), np.arange(0, 101, 10))
    lv = LevelSpec("interval", interval=0.1).levels(0.05, 0.42)
    np.testing.assert_allclose(lv, [0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    assert lv[3] == 0.3  # no floating-point noise
    np.testing.assert_allclose(LevelSpec("interval", interval=5, first=2, last=17).levels(0, 100),
                               [2, 7, 12, 17])
    np.testing.assert_allclose(LevelSpec("list", values=[3, 1, 2, 2]).levels(0, 1), [1, 2, 3])
    with pytest.raises(MapError):
        LevelSpec("interval", interval=0).levels(0, 1)
    with pytest.raises(MapError):
        LevelSpec("interval", interval=1e-6).levels(0, 1)  # too many levels
    with pytest.raises(MapError):
        LevelSpec("list", values=[]).levels(0, 1)
    with pytest.raises(MapError):
        get_cmap("not-a-palette")


def test_map_document_roundtrip():
    doc = MapDocument(title="T", layers=[ContourLayer(grid_id="a", levels=LevelSpec("interval", interval=2)),
                                         PostLayer(dataset_id="b", label_column="Z")])
    doc.scale_bar.xy = (0.3, 0.2)
    back = MapDocument.from_dict(doc.to_dict())
    assert back.to_dict() == doc.to_dict()
    assert isinstance(back.layers[0].levels, LevelSpec) and back.scale_bar.xy == (0.3, 0.2)
    assert back.referenced_ids() == {"a", "b"}
    back.move_layer(back.layers[0].id, +1)
    assert back.layers[1].type == "contour"
    with pytest.raises(MapError):
        layer_from_dict({"type": "vector"})
    with pytest.raises(MapError):
        MapDocument(page="B7")


# ------------------------------------------------------------------ rendering
def test_render_all_layer_types(grid, dataset):
    doc = MapDocument(title="All layers", subtitle="s", crs="EPSG:32639", layers=[
        ColourReliefLayer(grid_id=grid.id), FilledContourLayer(grid_id=grid.id, opacity=0.5),
        ContourLayer(grid_id=grid.id, levels=LevelSpec("interval", interval=1)),
        PostLayer(dataset_id=dataset.id, color_by_z=True, label_column="Z")])
    fig, info = render_map(doc, resolver(grid, dataset))
    assert info.warnings == []
    assert info.extent == (440000, 450000, 2885000, 2895000)
    assert {"title", "subtitle", "colorbar", "scale_bar", "north_arrow"} <= set(info.artists)
    assert info.scale_text in ("2 km", "2.5 km")
    assert abs(info.north_convergence) < 2
    w, h = fig.get_size_inches()
    assert (round(w * 25.4), round(h * 25.4)) == (297, 210)  # A4 landscape


def test_render_reports_missing_sources_and_empty_map(grid):
    doc = MapDocument(layers=[ContourLayer(grid_id="missing")])
    _, info = render_map(doc, resolver(grid))
    assert any("missing" in w for w in info.warnings)
    _, info = render_map(MapDocument(), resolver())
    assert info.extent is None


def test_contour_levels_outside_range_warn(grid):
    doc = MapDocument(layers=[ContourLayer(grid_id=grid.id,
                                           levels=LevelSpec("list", values=[500, 600]))])
    _, info = render_map(doc, resolver(grid))
    assert any("no contour level" in w for w in info.warnings)


def test_true_north_sign_and_geographic_scale():
    # UTM 39N: central meridian 51°E at easting 500 000. West of it, true north is
    # clockwise (east) of grid north in the northern hemisphere, east of it anticlockwise.
    west = true_north_bearing("EPSG:32639", 445000, 2890000)
    east = true_north_bearing("EPSG:32639", 600000, 2890000)
    assert west > 0 > east
    assert abs(true_north_bearing("EPSG:32639", 500000, 2890000)) < 1e-6
    assert true_north_bearing("EPSG:4326", 51, 26) is None
    g = GridGeometry(50.0, 52.0, 25.0, 27.0, 21, 21)
    grid = Grid(g, np.ones((21, 21)) + np.arange(21)[None, :], crs="EPSG:4326")
    _, info = render_map(MapDocument(crs="EPSG:4326", layers=[ColourReliefLayer(grid_id=grid.id)]),
                         resolver(grid))
    assert "km" in info.scale_text and "at 26.00°" in info.scale_text


@pytest.mark.parametrize("ext", ["png", "jpg", "svg", "pdf"])
def test_export_formats(tmp_path, grid, ext):
    doc = MapDocument(title="Export", crs="EPSG:32639",
                      layers=[FilledContourLayer(grid_id=grid.id), ContourLayer(grid_id=grid.id)])
    out, _ = export_map(doc, resolver(grid), tmp_path / f"m.{ext}", dpi=100)
    data = out.read_bytes()
    magic = {"png": b"\x89PNG", "jpg": b"\xff\xd8", "svg": b"<?xml", "pdf": b"%PDF"}[ext]
    assert data.startswith(magic) and len(data) > 5000
    with pytest.raises(MapError):
        export_map(doc, resolver(grid), out)  # never overwrite silently


def test_export_resolution_and_format_checks(tmp_path, grid):
    doc = MapDocument(layers=[ColourReliefLayer(grid_id=grid.id)])
    out, _ = export_map(doc, resolver(grid), tmp_path / "a.png", dpi=150)
    from PIL import Image
    with Image.open(out) as im:
        w, h = im.size
        assert abs(w - 297 / 25.4 * 150) <= 1 and abs(h - 210 / 25.4 * 150) <= 1
    with pytest.raises(MapError):
        export_map(doc, resolver(grid), tmp_path / "a.tif")
    with pytest.raises(MapError):
        export_map(doc, resolver(grid), tmp_path / "b.png", dpi=5000)
