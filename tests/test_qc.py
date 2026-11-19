"""Quality control tests with hand-computed expected values."""

import numpy as np
import pandas as pd
import pytest

from geohydro.engine.data.columns import guess_xyz
from geohydro.engine.data.parsing import parse_numeric
from geohydro.engine.data.qc import ImportSettings, run_qc
from geohydro.engine.errors import ColumnMappingError


def frame(rows, cols=("x", "y", "z")):
    return pd.DataFrame([[str(v) for v in r] for r in rows], columns=list(cols), dtype=object)


def test_parse_numeric_masks():
    s = pd.Series(["1.5", "", "NA", "abc", "-9999", "inf", " 2e3 "])
    p = parse_numeric(s)
    assert p.missing.tolist() == [False, True, True, False, False, False, False]
    assert p.invalid.tolist() == [False, False, False, True, False, True, False]
    assert p.nodata.tolist() == [False, False, False, False, True, False, False]
    assert p.values[0] == 1.5 and p.values[6] == 2000.0
    assert np.isnan(p.values[1:6]).all()


def test_parse_numeric_decimal_comma():
    p = parse_numeric(pd.Series(["1,5", "-2,25", "1.234,5"]), decimal=",")
    assert p.values.tolist() == [1.5, -2.25, 1234.5]


def test_clean_data_passes_unchanged():
    df = frame([[1, 2, 3], [4, 5, 6]])
    r = run_qc(df, ImportSettings("x", "y", "z"))
    assert r.report.imported_rows == 2 and r.report.excluded_rows == 0
    assert r.data["Z"].tolist() == [3.0, 6.0]
    assert r.data["source_row"].tolist() == [1, 2]


def test_exclusion_reasons_counted_once_per_row():
    df = frame([[1, 2, 3], ["", 2, 3], [1, "bad", 3], [1, 2, -9999], ["", "", ""], [7, 8, 9]])
    r = run_qc(df, ImportSettings("x", "y", "z"))
    rep = r.report
    assert rep.imported_rows == 2
    assert rep.excluded_rows == 4
    assert sum(rep.exclusions.values()) == 4
    assert rep.missing == {"x": 2, "y": 1, "z": 1}
    assert rep.invalid == {"x": 0, "y": 1, "z": 0}
    assert rep.nodata == {"x": 0, "y": 0, "z": 1}
    assert r.row_status.tolist()[0] == "ok" and r.row_status.tolist()[3].startswith("NoData")
    assert r.data["source_row"].tolist() == [1, 6]


def test_keep_invalid_rows_when_requested():
    df = frame([[1, 2, 3], [1, 2, ""]])
    r = run_qc(df, ImportSettings("x", "y", "z", exclude_invalid=False))
    assert r.report.imported_rows == 2
    assert np.isnan(r.data["Z"][1])
    assert any("kept as NaN" in w for w in r.report.warnings)


def test_duplicates_reported_and_kept_by_default():
    df = frame([[0, 0, 1], [0, 0, 1], [5, 5, 2], [5, 5, 4], [9, 9, 9]])
    r = run_qc(df, ImportSettings("x", "y", "z"))
    rep = r.report
    assert rep.duplicate_groups == 2
    assert rep.duplicate_rows == 4
    assert rep.duplicate_z_conflicts == 1
    assert rep.imported_rows == 5 and rep.duplicates_removed == 0


def test_duplicates_keep_first():
    df = frame([[0, 0, 1], [0, 0, 2], [1, 1, 3]])
    r = run_qc(df, ImportSettings("x", "y", "z", duplicate_policy="keep_first"))
    assert r.data["Z"].tolist() == [1.0, 3.0]
    assert r.report.duplicates_removed == 1
    assert r.row_status.tolist() == ["ok", "duplicate location", "ok"]


def test_duplicates_mean():
    df = frame([[0, 0, 1], [0, 0, 2], [0, 0, 6], [1, 1, 3]])
    r = run_qc(df, ImportSettings("x", "y", "z", duplicate_policy="mean"))
    assert r.data["Z"].tolist() == [3.0, 3.0]


def test_duplicate_tolerance_groups_chains():
    # 0 -- 0.4 -- 0.8 are chained within tol 0.5; 5.0 is separate
    df = frame([[0, 0, 1], [0.4, 0, 1], [0.8, 0, 1], [5, 0, 1]])
    r = run_qc(df, ImportSettings("x", "y", "z", duplicate_tolerance=0.5))
    assert r.report.duplicate_groups == 1 and r.report.duplicate_rows == 3


def test_geographic_range_check():
    df = frame([[50.5, 26.1, 1], [50.5, 126.1, 1], [400, 10, 1]])
    s = ImportSettings("x", "y", "z", crs="EPSG:4326", crs_is_geographic=True)
    r = run_qc(df, s)
    assert r.report.out_of_range == 2 and r.report.imported_rows == 1


def test_warning_when_no_crs_and_small_coordinates():
    r = run_qc(frame([[50.5, 26.1, 1]]), ImportSettings("x", "y", "z"))
    assert any("geographic" in w for w in r.report.warnings)


def test_attributes_preserved_and_typed():
    df = frame([["a", 1, 2, 3, "1.5"], ["b", 4, 5, 6, "2.5"]], cols=("id", "x", "y", "z", "tds"))
    r = run_qc(df, ImportSettings("x", "y", "z"))
    assert r.data["id"].tolist() == ["a", "b"]
    assert r.data["tds"].tolist() == [1.5, 2.5]


def test_reserved_attribute_names_are_prefixed():
    df = frame([[1, 2, 3, 9]], cols=("E", "N", "Elev", "Z"))
    r = run_qc(df, ImportSettings("E", "N", "Elev"))
    assert "attr_Z" in r.data.columns and r.data["Z"][0] == 3.0


def test_xy_only_dataset():
    r = run_qc(frame([[1, 2, 3]]), ImportSettings("x", "y", None))
    assert "Z" not in r.data.columns or r.data.columns.tolist().count("Z") == 0
    assert r.data["X"][0] == 1.0


@pytest.mark.parametrize("s", [ImportSettings(None, "y"), ImportSettings("x", "missing"),
                               ImportSettings("x", "x", "z")])
def test_invalid_mapping(s):
    with pytest.raises(ColumnMappingError):
        run_qc(frame([[1, 2, 3]]), s)


def test_guess_xyz_names():
    cases = {
        ("Point_ID", "Easting_m", "Northing_m", "Elevation_m"): ("Easting_m", "Northing_m", "Elevation_m"),
        ("Well", "X (m)", "Y (m)", "Water_Level_mAMSL", "TDS"): ("X (m)", "Y (m)", "Water_Level_mAMSL"),
        ("Station", "Longitude", "Latitude", "SST"): ("Longitude", "Latitude", "SST"),
        ("a", "b", "c"): ("a", "b", "c"),
    }
    for cols, expected in cases.items():
        df = pd.DataFrame([["1"] * len(cols)] * 3, columns=list(cols))
        if cols[0] in ("Point_ID", "Well", "Station"):
            df[cols[0]] = "ID"
        assert guess_xyz(df) == expected
