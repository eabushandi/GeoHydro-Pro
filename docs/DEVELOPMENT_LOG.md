# Development log

## 2026-11-19 — Phase 1 foundation (v0.1.0)

**Environment inspected:** Ubuntu 24.04 container, Python 3.13.18, 4 CPU, 15 GB RAM. No
scientific packages or Qt preinstalled. Installed into a virtual environment: PySide6 6.8.1
(Qt 6.8 LTS), NumPy 2.5.5, pandas 3.1.1, SciPy 1.18.1, openpyxl 3.1.5, PyProj 3.8.0
(PROJ 9.8.1), Matplotlib 3.11.2, pytest 9.2.0, pytest-qt 4.5.0. Qt system libraries
(`libegl1`, `libgl1`, `libxkbcommon0`…) installed for the offscreen platform. No Windows
machine is available in this environment.

**Decisions**

* Package layout `geohydro/{engine,project,desktop}` instead of top-level folders (see
  ARCHITECTURE.md for the reasons).
* Project file = SQLite (`.ghproj`) with per-dataset gzip CSV blobs and SHA-256 checksums;
  migrations applied in memory only.
* Readers keep every cell as source text; numeric conversion happens in QC with explicit
  masks so each rejected value is explained.
* Duplicates are reported but kept by default (preserve source data); removal is opt-in.
* CRS is assigned, never silently reprojected.
* A capability registry drives the enabled/planned state of every menu and ribbon entry.
* GDAL deferred: not needed for tabular import; avoids the hardest Windows dependency until
  raster/vector work starts.

**Issues found and fixed during testing**

* `pandas.to_numeric(...).to_numpy()` returned a read-only array under pandas 3 → copy
  explicitly before masking.
* Z-column suggestion chose `TDS_mgL` over `Water_Level_mAMSL` → surface-type names now take
  priority over concentrations/values.
* Ribbon labels were elided, `&` in tab names became mnemonics, brand label overlapped the
  ribbon → short ribbon labels via `iconText`, escaped `&&`, brand moved to the menu bar,
  ribbon spans full window width.
* Statistics view showed metres for dimensionless quantities (CV, skewness) and for
  variance → per-row units (m² for variance, none for CV/skewness).
* Excel dates at midnight rendered with a `T00:00:00` suffix → rendered as dates.
* A test assumed openpyxl writes full float precision; the *writer* rounds 0.1+0.2 to 0.3.
  The reader was correct; the test was changed to use values stored exactly.

**Result:** 88 automated tests pass (Linux, offscreen). Screenshots in `docs/screenshots/`.
