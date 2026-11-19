# Data import and quality control — methodology

Implementation: `geohydro/engine/data/` (`readers.py`, `parsing.py`, `columns.py`, `qc.py`,
`statistics.py`, `importer.py`).

## 1. Reading

| Format | Reader behaviour |
|---|---|
| CSV, TXT, DAT | Encoding auto-detected in order UTF-8 (with/without BOM) → Windows-1252 → Latin-1. Blank lines and lines starting with the comment prefix (default `#`) are ignored. Optional *skip leading rows*. Delimiter auto-detected (tab, semicolon, comma, pipe, whitespace — in that priority, accepting the first giving ≥2 fields on ≥90 % of lines). Quoted fields are supported. |
| XYZ | As above; defaults to whitespace and names the first three columns X, Y, Z when there is no header. |
| XLSX / XLSM | Read with openpyxl in read-only, cached-value mode (formula *results* as last saved by Excel). Worksheet selectable. Numbers are converted to text with full precision (`repr`), dates to ISO-8601. |

* **Header detection:** the first row is a header if it contains a non-numeric cell in a
  column whose following rows are ≥80 % numeric, or if it is entirely text while data rows
  are not. Always overridable.
* **Decimal separator:** auto-detected as comma when values like `12,5` outnumber `12.5`
  and the delimiter is not a comma. Comma decimal with comma delimiter is rejected.
* **Ragged rows** are padded/truncated and reported as a warning.
* Every cell is kept as the original **text**; conversion to numbers is a separate,
  audited step. The source file is opened read-only and never modified (tested by checksum).
* Formats not yet supported (GeoTIFF, ASC, Shapefile, GeoPackage, NetCDF, LAS …) are refused
  with a message naming their planned phase.

## 2. Column mapping

`guess_xyz` suggests X/Y/Z from column names (e.g. *Easting*, *Lon*, *X (m)*; *Northing*,
*Lat*; *Elevation*, *Water_Level*, *Depth*…), considering only columns that are ≥80 %
numeric. Surface-type names are preferred over generic values or concentrations. The user
confirms or changes the mapping; Z is optional (XY-only point sets are allowed).

## 3. Numeric parsing (per X/Y/Z value)

Each value is classified as exactly one of:

* **missing** — blank or equal to a missing-value token
  (default `NA, N/A, NaN, nan, NULL, null, None, -, *, #N/A`; editable);
* **non-numeric** — present but not a finite number (e.g. `4521x88`, `inf`);
* **NoData** — numeric and equal to a sentinel (default `-9999, -99999, 1.70141e38`,
  compared with relative tolerance 1e-9; editable);
* **valid**.

## 4. Quality-control checks

| Check | Default action | Option |
|---|---|---|
| Missing / non-numeric / NoData X, Y or Z | row excluded; counted per column and per reason (first reason wins) | keep rows with NaN |
| Geographic range (only when the CRS is geographic): lon ∉ [-180, 360] or lat ∉ [-90, 90] | row excluded | keep |
| Duplicate locations: identical X/Y, or within a tolerance (connected components of the pairs closer than the tolerance, KD-tree) | **reported only**, rows kept, warning shown | keep first; or keep first location with the mean Z of the group |
| No CRS and all coordinates within ±180 | warning (may be degrees) | — |

The QC report lists source rows, imported rows, excluded rows, counts per column and per
reason, duplicate groups (and how many have differing Z), and removed duplicates. The
imported table carries `source_row` so every point can be traced to its source row.

## 5. Coordinate reference systems and units

* A CRS is **assigned** as metadata (any EPSG code, WKT or PROJ string understood by PyProj).
  Coordinates are never transformed implicitly. Choosing a geographic CRS sets XY units to
  degrees; a metric projected CRS sets metres.
* Units are labels; values are not converted on import (metric is the default). Exact
  conversion factors are in `engine/units.py` (international foot 0.3048 m, US survey foot
  1200/3937 m).
* The CRS tool transforms single coordinates with PyProj (`always_xy=True`). Reference
  check in tests: (51°E, 0°N) → (500000 m, 0 m) in UTM 39N.

## 6. Statistics

`describe`: count, min, max, range, mean, median, quartiles (linear interpolation, NumPy
default), standard deviation and variance with the sample estimator (n−1), coefficient of
variation, adjusted Fisher–Pearson skewness (SciPy, `bias=False`). NaN/inf are ignored.

`spatial_summary`: extent, bounding-box area, point density, nearest-neighbour distance
(min/mean/max, KD-tree). Distances are in coordinate units and are only metric for projected
coordinates; the UI warns when coordinates are in degrees.

Validation: tests compare against hand-computed values and SciPy reference functions.

## 7. Assumptions and limitations

* Files are read fully into memory; the wizard preview uses the first 2,000 rows (the QC
  summary states when it covers a preview only). Very large files (tens of millions of
  rows) will need the chunked reader planned for later phases.
* XLSX formula cells return Excel's last cached value; workbooks never saved by Excel may
  return empty values for formulas.
* Duplicate detection with a tolerance can chain points (A near B, B near C ⇒ one group).
* The geographic range check accepts longitudes up to 360° (0–360 convention).
* Missing-value tokens are matched exactly (case-sensitive) after trimming whitespace.
