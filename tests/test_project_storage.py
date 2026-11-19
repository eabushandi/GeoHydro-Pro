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
