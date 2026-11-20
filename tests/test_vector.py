"""Vector engine: file round trips, CRS handling, measures and processing."""

import math
import zipfile

import numpy as np
import pandas as pd
import pytest
import shapely

from geohydro.engine.errors import VectorError
from geohydro.engine.vector import VectorDataset
from geohydro.engine.vector import ops
from geohydro.engine.vector.io import WRITE_FORMATS, list_layers, read_vector, write_vector


def _points(crs="EPSG:32639"):
    g = shapely.points(np.array([[500000.0, 2900000.0], [500100.0, 2900050.0],
                                 [500200.0, 2899900.0]]))
    attrs = pd.DataFrame({"name": ["W1", "W2", "W3"], "head": [12.5, 13.0, np.nan],
                          "count": [1, 2, 3]})
    return VectorDataset("wells", g, attrs, crs=crs)


def _polys(crs="EPSG:32639"):
    g = np.array([shapely.box(500000, 2900000, 501000, 2901000),
                  shapely.box(501000, 2900000, 502000, 2900500)], dtype=object)
    return VectorDataset("zones", g, pd.DataFrame({"zone": ["A", "B"]}), crs=crs)


@pytest.mark.parametrize("fmt", list(WRITE_FORMATS))
def test_round_trip_all_write_formats(tmp_path, fmt):
    ds = _points()
    ext = WRITE_FORMATS[fmt][1]
    back = read_vector(write_vector(ds, tmp_path / f"out{ext}"))
    assert back.n_features == 3
    assert back.geom_types() == {"Point": 3}
    if fmt == "kml":  # KML is always WGS 84 lon/lat
        assert back.crs == "EPSG:4326"
        xy = ops.reproject(back, "EPSG:32639").geometry
        assert np.allclose(shapely.get_x(xy), shapely.get_x(ds.geometry), atol=1e-3)
        assert "Name" in back.attributes or "name" in back.attributes
        # LIBKML's empty standard fields (altitudeMode, tessellate, ...) are dropped
        assert not {"altitudeMode", "tessellate", "extrude", "drawOrder"} & set(back.attributes)
    else:
        assert back.crs == "EPSG:32639"
        assert np.array_equal(shapely.get_coordinates(back.geometry),
                              shapely.get_coordinates(ds.geometry))
        assert list(back.attributes["name"]) == ["W1", "W2", "W3"]
        assert back.attributes["head"].iloc[0] == 12.5
        assert np.isnan(back.attributes["head"].iloc[2])
    assert back.source.sha256 and back.source.read_options["driver"]


def test_polygons_round_trip_and_multi_promotion(tmp_path):
    ds = _polys()
    mixed = ds.copy(geometry=np.array([ds.geometry[0], shapely.MultiPolygon(
        [ds.geometry[1], shapely.box(503000, 2900000, 503100, 2900100)])], dtype=object))
    for ext in (".shp", ".gpkg", ".geojson"):
        back = read_vector(write_vector(mixed, tmp_path / f"m{ext}"))
        assert back.family == "polygon"
        assert np.isclose(ops.measures(back)["area"].sum(), 1e6 + 5e5 + 1e4)


def test_shapefile_without_prj_warns_and_has_no_crs(tmp_path):
    p = write_vector(_points(), tmp_path / "noprj.shp")
    p.with_suffix(".prj").unlink()
    back = read_vector(p)
    assert back.crs is None
    assert any("no coordinate reference system" in w for w in back.metadata["warnings"])


def test_zipped_shapefile(tmp_path):
    p = write_vector(_points(), tmp_path / "w.shp")
    z = tmp_path / "w.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            if p.with_suffix(ext).exists():
                zf.write(p.with_suffix(ext), "w" + ext)
    back = read_vector(z)
    assert back.n_features == 3 and back.crs == "EPSG:32639"


def test_gpkg_layers(tmp_path):
    p = write_vector(_points(), tmp_path / "multi.gpkg")
    layers = list_layers(p)
    assert layers[0][0] == "multi"
    assert read_vector(p, layer="multi").n_features == 3


def test_shapefile_field_name_collision(tmp_path):
    ds = _points()
    ds.attributes["long_field_name_1"] = 1
    ds.attributes["long_field_name_2"] = 2
    with pytest.raises(VectorError, match="10 characters"):
        write_vector(ds, tmp_path / "x.shp")


def test_overwrite_protection(tmp_path):
    p = write_vector(_points(), tmp_path / "a.geojson")
    with pytest.raises(VectorError, match="exists"):
        write_vector(_points(), p)
    write_vector(_points(), p, overwrite=True)


def test_missing_and_bad_files(tmp_path):
    with pytest.raises(VectorError, match="not found"):
        read_vector(tmp_path / "none.shp")
    bad = tmp_path / "bad.geojson"
    bad.write_text("this is not json")
    with pytest.raises(VectorError):
        read_vector(bad)


def test_invalid_geometry_reported_and_repaired():
    bow = shapely.Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])  # self-intersecting
    ds = VectorDataset("bow", np.array([bow], dtype=object), None, crs="EPSG:32639")
    assert ds.validity()["invalid_geometry"] == 1
    fixed, n = ops.repair(ds)
    assert n == 1 and shapely.is_valid(fixed.geometry[0])
    assert np.isclose(shapely.area(fixed.geometry[0]), 0.5)  # two triangles of 0.25


def test_planar_measures():
    m = ops.measures(_polys())
    assert np.allclose(m["area"], [1e6, 5e5])
    assert np.allclose(m["length"], [4000, 3000])
    assert (m["method"] == "planar").all()
    assert np.allclose(m[["centroid_x", "centroid_y"]].iloc[0], [500500, 2900500])


def test_geodesic_length_equator_analytic():
    """1° of longitude along the equator = a·π/180 on WGS 84 (a = 6 378 137 m)."""
    ds = VectorDataset("eq", np.array([shapely.LineString([(0, 0), (1, 0)])], dtype=object),
                       None, crs="EPSG:4326")
    m = ops.measures(ds)
    assert m["method"].iat[0].startswith("geodesic")
    assert math.isclose(m["length"].iat[0], 6378137.0 * math.pi / 180, rel_tol=1e-12)


def test_geodesic_area_matches_equal_area_projection():
    """Small lon/lat polygon: geodesic area vs Lambert azimuthal equal-area (ellipsoidal)."""
    poly = shapely.segmentize(shapely.box(50.0, 25.0, 50.1, 25.1), 0.001)
    ds = VectorDataset("p", np.array([poly], dtype=object), None, crs="EPSG:4326")
    geo = ops.measures(ds)["area"].iat[0]
    laea = "+proj=laea +lat_0=25.05 +lon_0=50.05 +ellps=WGS84 +units=m"
    proj = ops.transform_coords(np.array([poly], dtype=object), "EPSG:4326", laea)
    assert math.isclose(geo, shapely.area(proj[0]), rel_tol=1e-6)


def test_add_measures_units():
    out = ops.add_measures(_polys())
    assert "area_m2" in out.attributes and "perim_m" in out.attributes
    geo = ops.add_measures(ops.reproject(_polys(), "EPSG:4326"))
    assert np.allclose(geo.attributes["area_m2"], [1e6, 5e5], rtol=3e-3)  # UTM scale ≈0.9996²


def test_reproject_round_trip_and_record():
    ds = _points()
    there = ops.reproject(ds, "EPSG:4326")
    assert there.crs == "EPSG:4326" and there.xy_units == "deg"
    back = ops.reproject(there, "EPSG:32639")
    assert np.allclose(shapely.get_coordinates(back.geometry),
                       shapely.get_coordinates(ds.geometry), atol=1e-6)
    assert back.metadata["processing"][-1]["operation"] == "reproject"
    with pytest.raises(VectorError, match="no CRS"):
        ops.reproject(ds.copy(crs=None), "EPSG:4326")


def test_buffer_refuses_geographic_and_has_correct_area():
    ds = _points()
    b = ops.buffer(ds, 10.0, quad_segs=64)
    # inscribed 256-gon area = ½·n·r²·sin(2π/n)
    n = 256
    expected = 0.5 * n * 100 * math.sin(2 * math.pi / n)
    assert np.allclose(shapely.area(b.geometry), expected)
    with pytest.raises(VectorError, match="projected"):
        ops.buffer(ops.reproject(ds, "EPSG:4326"), 10.0)


def test_clip_extent_and_polygon():
    ds = _points()
    out = ops.clip(ds, (499950, 500150, 2899950, 2900100))
    assert list(out.attributes["name"]) == ["W1", "W2"]
    polys = ops.clip(_polys(), shapely.box(500500, 2900000, 501500, 2900250))
    assert np.allclose(shapely.area(polys.geometry), [500 * 250, 500 * 250])


def test_dissolve():
    g = np.array([shapely.box(0, 0, 1, 1), shapely.box(1, 0, 2, 1), shapely.box(5, 5, 6, 6)],
                 dtype=object)
    ds = VectorDataset("d", g, pd.DataFrame({"k": ["a", "a", "b"]}), crs="EPSG:32639")
    out = ops.dissolve(ds, "k")
    assert list(out.attributes["count"]) == [2, 1]
    assert np.allclose(shapely.area(out.geometry), [2, 1])
    assert np.isclose(shapely.area(ops.dissolve(ds).geometry[0]), 3)


def test_points_to_table_with_field_and_z():
    t = ops.points_to_table(_points(), "head")
    assert list(t.columns[:3]) == ["X", "Y", "Z"]
    assert t["Z"].iloc[1] == 13.0 and t["source_row"].tolist() == [1, 2, 3]
    z3 = VectorDataset("z", shapely.points(np.array([[0, 0, 5.0], [1, 1, 6.0]])), None)
    assert ops.points_to_table(z3)["Z"].tolist() == [5.0, 6.0]
    mp = VectorDataset("mp", np.array([shapely.MultiPoint([(0, 0), (1, 1)])], dtype=object),
                       pd.DataFrame({"v": [7]}))
    assert ops.points_to_table(mp, "v")["Z"].tolist() == [7, 7]
    with pytest.raises(VectorError, match="not a point layer"):
        ops.points_to_table(_polys())


def test_contains_mask_and_polygon_union():
    u = ops.polygon_union(_polys())
    inside = ops.contains_mask(u, np.array([500500, 501500, 501500, 503000.0]),
                               np.array([2900500, 2900250, 2900750, 2900000.0]))
    assert inside.tolist() == [True, True, False, False]
    with pytest.raises(VectorError, match="no polygons"):
        ops.polygon_union(_points())


def test_dataset_queries():
    ds = _points()
    assert ds.family == "point"
    assert ds.bounds() == (500000.0, 500200.0, 2899900.0, 2900050.0)
    assert set(ds.numeric_fields()) == {"head", "count"}
    with pytest.raises(VectorError):
        VectorDataset("x", np.array([shapely.Point(0, 0)], dtype=object),
                      pd.DataFrame({"a": [1, 2]}))
