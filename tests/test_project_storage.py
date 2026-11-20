"""Project format tests: round trip, integrity, versioning, safe saving."""

import hashlib
import shutil
import sqlite3

import numpy as np
import pandas as pd
import pytest

from geohydro.engine.data import ImportSettings, import_point_file
from geohydro.engine.data.importer import apply_crs
from geohydro.engine.errors import (
    ProjectConflictError,
    ProjectFormatError,
    ProjectIntegrityError,
    ProjectOverwriteError,
)
from geohydro.project import FORMAT_VERSION, Project, load_project, save_project
from geohydro.project import storage
from geohydro.project.storage import decode_frame, encode_frame, project_manifest, read_header


@pytest.fixture
def project(samples):
    p = Project(name="Test", description="desc", author="QA", default_crs="EPSG:32639")
    s = apply_crs(ImportSettings("Easting_m", "Northing_m", "Elevation_m"), "EPSG:32639")
    p.add_dataset(import_point_file(samples / "terrain_survey_utm39n.csv", settings=s, name="terrain"))
    p.add_dataset(import_point_file(samples / "groundwater_wells.xlsx", name="wells"))
    p.settings["colour_scale"] = "geohydro"
    return p


def test_frame_codec_exact_roundtrip():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "X": rng.uniform(4e5, 5e5, 200), "Y": rng.uniform(2.8e6, 2.9e6, 200),
        "Z": np.append(rng.normal(0, 1e-9, 199), np.nan), "source_row": np.arange(200),
        "id": [f"P{i},\"q\"" for i in range(200)], "flag": [True, False] * 100,
    })
    blob, cols, sha = encode_frame(df)
    out = decode_frame(blob, cols)
    pd.testing.assert_frame_equal(out, df, check_exact=True)
    assert hashlib.sha256(blob).hexdigest() == sha


def test_save_load_roundtrip(project, tmp_path):
    path = save_project(project, tmp_path / "p")
    assert path.suffix == ".ghproj" and project.revision == 1 and not project.dirty
    q = load_project(path)
    assert (q.name, q.description, q.author, q.default_crs, q.uuid) == (
        "Test", "desc", "QA", "EPSG:32639", project.uuid)
    assert q.settings == {"colour_scale": "geohydro"}
    assert list(q.datasets) == list(project.datasets)
    for did, ds in project.datasets.items():
        d2 = q.datasets[did]
        pd.testing.assert_frame_equal(d2.data, ds.data, check_exact=True)
        assert (d2.name, d2.crs, d2.xy_units, d2.z_units, d2.z_label) == (
            ds.name, ds.crs, ds.xy_units, ds.z_units, ds.z_label)
        assert d2.source == ds.source and d2.qc_report == ds.qc_report
    assert [h.action for h in q.history] == [h.action for h in project.history]
    assert q.revision == 1 and not q.dirty


def test_revision_increments_and_backup(project, tmp_path):
    path = save_project(project, tmp_path / "p.ghproj")
    project.name = "Renamed"
    save_project(project)
    assert project.revision == 2
    assert read_header(path)["revision"] == 2
    bak = path.with_name(path.name + ".bak")
    assert bak.exists() and read_header(bak)["revision"] == 1
    assert not list(tmp_path.glob(".*.tmp"))


def test_conflict_detection(project, tmp_path):
    path = save_project(project, tmp_path / "p.ghproj")
    other = load_project(path)  # second copy (e.g. another device)
    other.name = "edited elsewhere"
    save_project(other)  # revision 2 on disk
    project.name = "stale edit"
    with pytest.raises(ProjectConflictError):
        save_project(project)  # still at revision 1
    assert load_project(path).name == "edited elsewhere"  # newer data untouched
    save_project(project, force=True)
    assert load_project(path).name == "stale edit" and project.revision == 3


def test_refuses_to_overwrite_other_project_or_file(project, tmp_path):
    target = tmp_path / "x.ghproj"
    save_project(Project(name="Other"), target)
    with pytest.raises(ProjectOverwriteError):
        save_project(project, target)
    assert load_project(target).name == "Other"
    save_project(project, target, overwrite=True)
    assert load_project(target).name == "Test"
    junk = tmp_path / "junk.ghproj"
    junk.write_text("not a project")
    with pytest.raises(ProjectOverwriteError):
        save_project(project, junk)
    assert junk.read_text() == "not a project"


def test_checksum_mismatch_detected(project, tmp_path):
    path = save_project(project, tmp_path / "p.ghproj")
    con = sqlite3.connect(path)
    blob = con.execute("SELECT data FROM datasets LIMIT 1").fetchone()[0]
    con.execute("UPDATE datasets SET data=? WHERE position=0", (blob[:-1] + bytes([blob[-1] ^ 1]),))
    con.commit()
    con.close()
    with pytest.raises(ProjectIntegrityError):
        load_project(path)


def test_not_a_project(tmp_path):
    p = tmp_path / "x.ghproj"
    p.write_text("hello")
    with pytest.raises(ProjectFormatError):
        load_project(p)
    con = sqlite3.connect(tmp_path / "y.ghproj")
    con.execute("CREATE TABLE meta(key TEXT, value TEXT)")
    con.commit()
    con.close()
    with pytest.raises(ProjectFormatError):
        load_project(tmp_path / "y.ghproj")


def test_newer_format_rejected(project, tmp_path):
    path = save_project(project, tmp_path / "p.ghproj")
    con = sqlite3.connect(path)
    con.execute("UPDATE meta SET value=? WHERE key='format_version'", (str(FORMAT_VERSION + 1),))
    con.commit()
    con.close()
    with pytest.raises(ProjectFormatError, match="Please update"):
        load_project(path)


def test_migration_runs_in_memory_and_preserves_file(project, tmp_path, monkeypatch):
    """Simulate a future v2 format: a v1 file must be upgraded in memory only."""
    path = save_project(project, tmp_path / "p.ghproj")
    before = path.read_bytes()
    calls = []

    def v1_to_v2(conn):
        calls.append(1)
        conn.execute("ALTER TABLE datasets ADD COLUMN extra TEXT DEFAULT ''")

    monkeypatch.setattr(storage, "FORMAT_VERSION", FORMAT_VERSION + 1)
    monkeypatch.setitem(storage.MIGRATIONS, FORMAT_VERSION, v1_to_v2)
    q = load_project(path)
    assert calls == [1]
    assert q.dirty and q.history[-1].action == "project.migrate"
    assert path.read_bytes() == before  # original untouched until saved
    assert len(q.datasets) == 2


def test_missing_migration_is_an_error(project, tmp_path, monkeypatch):
    path = save_project(project, tmp_path / "p.ghproj")
    monkeypatch.setattr(storage, "FORMAT_VERSION", FORMAT_VERSION + 1)
    with pytest.raises(ProjectFormatError, match="No migration"):
        load_project(path)


def test_manifest_is_json_serialisable(project):
    import json

    m = json.loads(json.dumps(project_manifest(project)))
    assert m["format_version"] == FORMAT_VERSION
    assert [d["name"] for d in m["datasets"]] == ["terrain", "wells"]


def test_sample_project_loads(samples):
    p = load_project(samples.parent / "sample_project.ghproj")
    assert {d.name for d in p.datasets.values()} == {"Terrain survey", "Monitoring wells"}


def test_project_model_operations(project):
    did = next(iter(project.datasets))
    project.rename_dataset(did, "renamed")
    with pytest.raises(ValueError):
        project.rename_dataset(did, "wells")
    with pytest.raises(ValueError):
        project.rename_dataset(did, "  ")
    project.assign_crs(did, "EPSG:4326", True)
    assert project.datasets[did].xy_units == "deg"
    project.set_metadata(name="New")
    with pytest.raises(KeyError):
        project.set_metadata(bogus=1)
    removed = project.remove_dataset(did)
    assert removed.name == "renamed" and did not in project.datasets
    actions = [h.action for h in project.history]
    assert actions[-4:] == ["dataset.rename", "dataset.assign_crs", "project.metadata", "dataset.remove"]


def test_duplicate_dataset_names_get_suffix(samples):
    p = Project()
    a = p.add_dataset(import_point_file(samples / "contaminant_survey.txt", name="same"))
    b = p.add_dataset(import_point_file(samples / "contaminant_survey.txt", name="same"))
    assert (a.name, b.name) == ("same", "same (2)")


def test_save_copy_to_new_location_keeps_uuid(project, tmp_path):
    p1 = save_project(project, tmp_path / "a.ghproj")
    shutil.copy(p1, tmp_path / "b.ghproj")
    project.name = "changed"
    save_project(project, tmp_path / "b.ghproj")  # same project, same revision: allowed
    assert load_project(tmp_path / "b.ghproj").name == "changed"


# ---------------------------------------------------------------- format v2: grids and maps
def _add_grid_and_map(project):
    from geohydro.engine.gridding.grid import Grid, GridGeometry
    from geohydro.engine.mapping.levels import LevelSpec
    from geohydro.engine.mapping.model import ContourLayer, MapDocument, PostLayer
    g = GridGeometry(440000.0, 441000.0, 2885000.0, 2885500.0, 21, 11)
    z = np.random.default_rng(1).normal(10, 3, g.shape)
    z[0, :4] = np.nan
    z[5, 5] = 1e-300  # tiny values survive the codec exactly
    grid = project.add_grid(Grid(g, z, name="G", crs="EPSG:32639", z_label="Head",
                                 metadata={"method": "idw", "parameters": {"power": 2.0}}))
    ds = next(iter(project.datasets.values()))
    doc = project.add_map(MapDocument(name="M", title="Map", crs="EPSG:32639", layers=[
        ContourLayer(grid_id=grid.id, levels=LevelSpec("interval", interval=0.5)),
        PostLayer(dataset_id=ds.id)]))
    doc.north_arrow.xy = (0.9, 0.8)
    return grid, doc


def test_grid_and_map_roundtrip(project, tmp_path):
    grid, doc = _add_grid_and_map(project)
    path = save_project(project, tmp_path / "p.ghproj")
    q = load_project(path)
    g2 = q.grids[grid.id]
    np.testing.assert_array_equal(g2.z, grid.z)  # NaN positions and values bit-exact
    assert g2.geometry == grid.geometry and g2.metadata == grid.metadata
    assert (g2.name, g2.crs, g2.z_label) == ("G", "EPSG:32639", "Head")
    assert q.maps[doc.id].to_dict() == doc.to_dict()
    hdr = read_header(path)
    assert hdr["format_version"] == FORMAT_VERSION == 3
    m = project_manifest(q)
    assert [x["name"] for x in m["grids"]] == ["G"] and [x["name"] for x in m["maps"]] == ["M"]
    assert any("Grid 'G'" in r for r in storage.verify_project_file(path))


def test_grid_checksum_and_shape_mismatch_detected(project, tmp_path):
    _add_grid_and_map(project)
    path = save_project(project, tmp_path / "p.ghproj")
    con = sqlite3.connect(path)
    blob = con.execute("SELECT data FROM grids").fetchone()[0]
    con.execute("UPDATE grids SET data=?", (blob[:-1] + bytes([blob[-1] ^ 1]),))
    con.commit()
    con.close()
    with pytest.raises(ProjectIntegrityError):
        load_project(path)
    # Same data with a geometry that does not match its shape
    path2 = save_project(project, tmp_path / "p2.ghproj")
    con = sqlite3.connect(path2)
    con.execute("UPDATE grids SET geometry=replace(geometry, '\"nx\": 21', '\"nx\": 22')")
    con.commit()
    con.close()
    with pytest.raises(ProjectIntegrityError):
        load_project(path2)


def test_remove_grid_used_by_map_is_reported(project):
    grid, doc = _add_grid_and_map(project)
    assert project.maps_using(grid.id) == [doc]
    project.remove_grid(grid.id)
    assert grid.id in doc.referenced_ids() and grid.id not in project.grids
    assert project.history[-1].action == "grid.remove"


def test_v1_project_migrates_to_current(tmp_path):
    from pathlib import Path
    src = Path(__file__).parent / "fixtures" / "project_format_v1.ghproj"
    assert read_header(src)["format_version"] == 1
    p = load_project(src)
    assert p.dirty and p.history[-1].action == "project.migrate"
    assert p.history[-1].details == {"from_version": 1, "to_version": 3}
    assert p.grids == {} and p.maps == {}
    assert {d.name for d in p.datasets.values()} == {"Terrain survey", "Monitoring wells"}
    # Saving writes the current format; the original v1 file is never modified in place
    out = save_project(p, tmp_path / "migrated.ghproj")
    assert read_header(out)["format_version"] == 3
    assert read_header(src)["format_version"] == 1


def test_sample_project_has_grids_and_maps(samples):
    p = load_project(samples.parent / "sample_project.ghproj")
    assert len(p.grids) == 2 and len(p.maps) == 2
    for m in p.maps.values():
        assert m.referenced_ids() <= set(p.datasets) | set(p.grids)


def test_v2_project_migrates_to_v3_without_changes(tmp_path):
    """The Phase 2 sample project (format 2) opens unchanged and saves as format 3."""
    from pathlib import Path
    src = Path(__file__).parent / "fixtures" / "project_format_v2.ghproj"
    assert read_header(src)["format_version"] == 2
    p = load_project(src)
    assert p.history[-1].details == {"from_version": 2, "to_version": 3}
    assert len(p.grids) == 2 and len(p.maps) == 2 and p.vectors == {} and p.images == {}
    out = save_project(p, tmp_path / "v3.ghproj")
    q = load_project(out)
    assert read_header(out)["format_version"] == 3 and read_header(src)["format_version"] == 2
    for gid, g in p.grids.items():
        np.testing.assert_array_equal(q.grids[gid].z, g.z)
    assert {k: m.to_dict() for k, m in q.maps.items()} == {k: m.to_dict() for k, m in p.maps.items()}


def _vector_and_image():
    import shapely
    from geohydro.engine.data.dataset import SourceInfo
    from geohydro.engine.raster import RasterImage
    from geohydro.engine.vector import VectorDataset
    geoms = np.array([shapely.Point(1, 2, 3), None,
                      shapely.Polygon([(0, 0), (1, 0), (1, 1)], [[(0.2, 0.1), (0.8, 0.1), (0.8, 0.6)]]),
                      shapely.MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]])], dtype=object)
    attrs = pd.DataFrame({"name": ["a", "b", "c", "d"], "v": [1.5, np.nan, 3.0, 4.0],
                          "n": [1, 2, 3, 4], "ok": [True, False, True, True],
                          "when": pd.to_datetime(["2024-01-02 03:04:05", None, "2025-06-07 00:00:00", "2026-11-20 12:00:00"])})
    src = SourceInfo(path="/data/x.gpkg", format="GeoPackage", sha256="ab" * 32, size_bytes=10,
                     modified="2026-11-20T00:00:00+00:00", read_options={"layer": "x"})
    vec = VectorDataset("Layer", geoms, attrs, crs="EPSG:32639", source=src,
                        metadata={"warnings": ["w"], "validity": {"features": 4}})
    rgba = np.random.default_rng(0).integers(0, 256, (7, 9, 4), dtype=np.uint8)
    img = RasterImage("Base", rgba, (500000.0, 500090.0, 2900000.0, 2900070.0), crs="EPSG:32639",
                      metadata={"bands": [1, 2, 3]})
    return vec, img


def test_vector_and_image_roundtrip(project, tmp_path):
    import shapely
    vec, img = _vector_and_image()
    project.add_vector(vec)
    project.add_image(img)
    assert project.history[-2].action == "vector.import"
    assert project.history[-1].action == "image.import"
    path = save_project(project, tmp_path / "v.ghproj")
    q = load_project(path)
    v2, i2 = q.vectors[vec.id], q.images[img.id]
    assert v2.name == "Layer" and v2.crs == "EPSG:32639" and v2.source == vec.source
    assert v2.geometry[1] is None
    for a, b in zip(vec.geometry, v2.geometry):
        assert (a is None and b is None) or shapely.equals_exact(a, b, 0)
    assert shapely.has_z(v2.geometry[0])
    pd.testing.assert_frame_equal(v2.attributes, vec.attributes, check_dtype=False)
    assert v2.attributes["n"].dtype.kind == "i" and v2.attributes["ok"].dtype == bool
    assert v2.metadata == vec.metadata
    np.testing.assert_array_equal(i2.rgba, img.rgba)
    assert i2.extent == img.extent and i2.crs == img.crs
    assert q.item(vec.id) is v2 and q.item(img.id) is i2
    m = project_manifest(q)
    assert m["vectors"][0]["features"] == 4 and m["images"][0]["size"] == [7, 9]
    res = storage.verify_project_file(path)
    assert any("Vector layer 'Layer': 4 features" in r for r in res)
    assert any("Image 'Base': 9 x 7 pixels" in r for r in res)


def test_vector_without_attributes_and_corruption(project, tmp_path):
    import shapely
    from geohydro.engine.vector import VectorDataset
    v = VectorDataset("bare", np.array([shapely.Point(0, 0)] * 3, dtype=object), None)
    project.add_vector(v)
    path = save_project(project, tmp_path / "b.ghproj")
    assert load_project(path).vectors[v.id].n_features == 3
    con = sqlite3.connect(path)
    blob = con.execute("SELECT geometry FROM vectors").fetchone()[0]
    con.execute("UPDATE vectors SET geometry=?", (blob[:-1] + bytes([blob[-1] ^ 1]),))
    con.commit()
    con.close()
    with pytest.raises(ProjectIntegrityError):
        load_project(path)


def test_vector_and_image_rename_remove(project):
    vec, img = _vector_and_image()
    project.add_vector(vec)
    project.add_vector(vec.copy())
    assert sorted(v.name for v in project.vectors.values()) == ["Layer", "Layer (2)"]
    with pytest.raises(ValueError):
        project.rename_vector(vec.id, "Layer (2)")
    project.rename_vector(vec.id, "Rivers")
    project.add_image(img)
    project.rename_image(img.id, "Satellite")
    assert project.remove_image(img.id).name == "Satellite"
    assert project.remove_vector(vec.id).name == "Rivers"
    assert [h.action for h in project.history[-3:]] == ["image.rename", "image.remove", "vector.remove"]
