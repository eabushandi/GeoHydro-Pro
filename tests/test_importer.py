"""End-to-end import of the shipped sample datasets with known expected results."""

import hashlib

import numpy as np
import pytest

from geohydro.engine.data import ImportSettings, import_point_file, preview, qc_preview
from geohydro.engine.data.importer import apply_crs
from geohydro.engine.capabilities import CAPABILITIES, is_implemented
from geohydro.engine.errors import CRSError


def test_terrain_sample_values(samples):
    ds = import_point_file(samples / "terrain_survey_utm39n.csv")
    assert ds.n_points == 300 and ds.has_z
    assert (ds.x_label, ds.y_label, ds.z_label) == ("Easting_m", "Northing_m", "Elevation_m")
    assert ds.data.iloc[0][["X", "Y", "Z"]].tolist() == [440913.239, 2893846.831, 7.482]
    assert ds.data["Point_ID"].iloc[0] == "TS0001"
    assert ds.source.sha256 == hashlib.sha256((samples / "terrain_survey_utm39n.csv").read_bytes()).hexdigest()


def test_terrain_sample_matches_generating_surface(samples):
    """Imported values deviate from the documented reference surface only by the
    added N(0, 0.15) noise - a check that coordinates were parsed correctly."""
    import sys
    sys.path.insert(0, str(samples.parent))
    from generate_samples import terrain_surface

    ds = import_point_file(samples / "terrain_survey_utm39n.csv")
    resid = ds.data["Z"].to_numpy() - terrain_surface(ds.data["X"].to_numpy(), ds.data["Y"].to_numpy())
    assert abs(resid.mean()) < 0.05
    assert 0.10 < resid.std() < 0.20


def test_errors_sample_expected_qc(samples):
    ds = import_point_file(samples / "field_readings_with_errors.csv")
    q = ds.qc_report
    assert q["source_rows"] == 40
    assert q["imported_rows"] == 35 and q["excluded_rows"] == 5
    assert q["duplicate_groups"] == 2 and q["duplicate_z_conflicts"] == 1
    assert ds.source.read_options["delimiter"] == ";" and ds.source.read_options["decimal"] == ","


def test_errors_sample_dedupe(samples):
    s = ImportSettings("East", "North", "Level", duplicate_policy="keep_first")
    ds = import_point_file(samples / "field_readings_with_errors.csv", settings=s)
    assert ds.n_points == 33 and ds.qc_report["duplicates_removed"] == 2


def test_geographic_sample(samples):
    s = apply_crs(ImportSettings("Longitude", "Latitude", "SST_degC", z_units="degC"), "EPSG:4326")
    ds = import_point_file(samples / "stations_wgs84.dat", settings=s)
    assert ds.xy_units == "deg" and ds.crs == "EPSG:4326"
    assert ds.n_points == 49 and ds.qc_report["out_of_range"] == 1


def test_xyz_and_txt_samples(samples):
    b = import_point_file(samples / "bathymetry_nearshore.xyz")
    assert b.n_points == 2000 and b.data["Z"].max() < 1.0
    c = import_point_file(samples / "contaminant_survey.txt")
    assert c.n_points == 80 and c.z_label == "Benzene_ugL"


def test_preview_is_truncated_but_import_is_complete(samples):
    t, s = preview(samples / "bathymetry_nearshore.xyz", max_rows=100)
    res = qc_preview(t, s)
    assert len(t.frame) == 100 and t.total_data_rows == 2000 and res.report.preview_only


def test_invalid_crs_rejected():
    with pytest.raises(CRSError):
        apply_crs(ImportSettings("x", "y"), "EPSG:0")


def test_capability_registry_honesty():
    implemented = {k for k, c in CAPABILITIES.items() if c.implemented}
    assert all(CAPABILITIES[k].phase == 1 for k in implemented)
    assert not is_implemented("grid.ok") and not is_implemented("hydro.d8")
    assert "planned" in CAPABILITIES["grid.idw"].label
    from geohydro.engine import gridding, hydrology, interpolation
    for mod in (gridding, hydrology, interpolation):
        assert mod.STATUS == "planned"
