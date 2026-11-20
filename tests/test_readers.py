"""Data import tests: format, delimiter, header, decimal and encoding handling."""

import hashlib

import pandas as pd
import pytest

from geohydro.engine.data.readers import ReadOptions, list_sheets, read_table
from geohydro.engine.errors import DataReadError


def test_csv_comma_with_header(write):
    p = write("a.csv", "x,y,z\n1,2,3\n4,5,6\n")
    t = read_table(p)
    assert t.columns == ["x", "y", "z"]
    assert t.options.delimiter == ","
    assert t.options.header == "yes"
    assert t.total_data_rows == 2
    assert t.frame.iloc[1].tolist() == ["4", "5", "6"]


def test_csv_without_header_gets_default_names(write):
    p = write("a.csv", "1,2,3\n4,5,6\n")
    t = read_table(p)
    assert t.options.header == "no"
    assert t.columns == ["Column_1", "Column_2", "Column_3"]


def test_semicolon_and_decimal_comma(write):
    p = write("eu.csv", "E;N;Z\n1,5;2,25;3,0\n4,5;5,5;-6,75\n")
    t = read_table(p)
    assert t.options.delimiter == ";"
    assert t.options.decimal == ","
    assert t.frame["Z"].tolist() == ["3,0", "-6,75"]  # raw text is preserved


def test_tab_delimited_dat(write):
    p = write("s.dat", "A\tB\tC\n1.5\t2\t3\n")
    t = read_table(p)
    assert t.options.delimiter == "\t" and t.source_format == "dat"


def test_xyz_whitespace_no_header(write):
    p = write("p.xyz", "  1.0   2.0  3.0\n4.0 5.0    6.0\n")
    t = read_table(p)
    assert t.options.delimiter == "whitespace"
    assert t.columns == ["X", "Y", "Z"]
    assert t.frame.shape == (2, 3)


def test_comments_blank_lines_and_skip_rows(write):
    p = write("c.txt", "TITLE LINE\n# comment\n\nid x y v\n# mid comment\na 1 2 3\nb 4 5 6\n")
    t = read_table(p, ReadOptions(skip_rows=1))
    assert t.columns == ["id", "x", "y", "v"]
    assert t.total_data_rows == 2


def test_quoted_fields(write):
    p = write("q.csv", 'name,x,y\n"Well, North",1,2\n')
    t = read_table(p)
    assert t.frame.iloc[0, 0] == "Well, North"


def test_ragged_rows_warn(write):
    p = write("r.csv", "x,y,z\n1,2,3\n4,5\n7,8,9\n")
    t = read_table(p)
    assert t.frame.shape == (3, 3)
    assert any("unexpected number of fields" in w for w in t.warnings)


def test_duplicate_and_blank_header_names(write):
    p = write("d.csv", "x,x,,z\n1,2,3,4\n")
    t = read_table(p)
    assert t.columns == ["x", "x_2", "Column_3", "z"]


def test_cp1252_encoding_fallback(write):
    p = write("enc.csv", "Station,Temp °C\nA,1\n", encoding="cp1252")
    t = read_table(p)
    assert t.options.encoding == "cp1252"
    assert t.columns[1] == "Temp °C"


def test_utf8_bom(write):
    p = write("bom.csv", "﻿X,Y\n1,2\n")
    t = read_table(p)
    assert t.columns == ["X", "Y"]


def test_max_rows_truncates_but_reports_total(write):
    p = write("big.csv", "x,y\n" + "".join(f"{i},{i}\n" for i in range(100)))
    t = read_table(p, ReadOptions(max_rows=10))
    assert len(t.frame) == 10 and t.total_data_rows == 100 and t.truncated


def test_missing_file():
    with pytest.raises(DataReadError):
        read_table("does/not/exist.csv")


def test_empty_file(write):
    with pytest.raises(DataReadError):
        read_table(write("e.csv", "# only a comment\n\n"))


def test_binary_file_rejected(tmp_path):
    p = tmp_path / "bin.txt"
    p.write_bytes(b"\x00\x01\x02" * 100)
    with pytest.raises(DataReadError):
        read_table(p)


def test_planned_format_reports_phase(tmp_path):
    p = tmp_path / "dem.tif"
    p.write_bytes(b"II*\x00")
    with pytest.raises(DataReadError, match="Phase 3"):
        read_table(p)


def test_decimal_comma_with_comma_delimiter_rejected(write):
    with pytest.raises(DataReadError):
        read_table(write("x.csv", "a,b\n1,2\n"), ReadOptions(delimiter=",", decimal=","))


def test_xlsx_read_and_sheets(tmp_path):
    p = tmp_path / "w.xlsx"
    df = pd.DataFrame({"E": [1.5, 2.25], "N": [3.0, 4.0], "Z": [10.125, None]})
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        pd.DataFrame({"note": ["x"]}).to_excel(xw, sheet_name="Info", index=False)
        df.to_excel(xw, sheet_name="Data", index=False)
    assert list_sheets(p) == ["Info", "Data"]
    t = read_table(p, ReadOptions(sheet="Data"))
    assert t.columns == ["E", "N", "Z"]
    assert t.frame["E"].tolist() == ["1.5", "2.25"]
    assert t.frame["N"].tolist() == ["3", "4"]
    assert t.frame["Z"].tolist() == ["10.125", ""]
    with pytest.raises(DataReadError):
        read_table(p, ReadOptions(sheet="Nope"))


def test_xlsx_float_precision_preserved(tmp_path):
    p = tmp_path / "prec.xlsx"
    v = 2885054.123456789
    w = -0.000123456789012345
    pd.DataFrame({"x": [v], "y": [w]}).to_excel(p, index=False)
    t = read_table(p)
    # values stored in the workbook are reproduced exactly (no rounding by the reader)
    assert float(t.frame["x"][0]) == v
    assert float(t.frame["y"][0]) == w


def test_all_sample_files_read(samples):
    for f in (p for p in samples.iterdir() if p.is_file()):   # gis/ holds GIS files
        t = read_table(f)
        assert t.total_data_rows > 0, f


def test_reading_never_modifies_source(samples):
    for f in (p for p in samples.iterdir() if p.is_file()):
        before = hashlib.sha256(f.read_bytes()).hexdigest()
        read_table(f)
        assert hashlib.sha256(f.read_bytes()).hexdigest() == before
