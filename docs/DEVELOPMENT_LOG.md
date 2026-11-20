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

## 2026-11-20 — Repository and Windows CI

* Published to the private GitHub repository `eabushandi/GeoHydro-Pro`. Secrets and
  personal-data review before the first push: nothing found. Added `.gitignore` and
  `.gitattributes`, extended README (dependencies, platform status, roadmap).
* CI matrix: `windows-2022`, `windows-2025`, `ubuntu-24.04` × Python 3.11, 3.12, 3.13.
  First run (44670581483): 9/9 jobs green, 88/88 tests each, no code changes needed.
* Open item: GitHub warns that `actions/checkout@v4`, `setup-python@v5` and
  `upload-artifact@v4` target Node.js 20 (forced onto Node.js 24 by the runner). Not a
  failure; bump the action versions when convenient.

## 2026-11-20 — Phase 2: Core Mapping (v0.2.0)

**Built**

* Gridding engine: node-registered grid model, grid statistics, Surfer 6 text / 6 binary /
  7 binary and ESRI ASCII grid files (read/write), XYZ node export.
* Eight interpolation methods behind one interface: IDW, Ordinary and Universal Kriging,
  Minimum Curvature with tension, exact Sibson Natural Neighbour, Nearest Neighbour, Linear
  Triangulation, RBF. Shared data preparation (invalid rows, coincident points), KD-tree
  search, geometric anisotropy, blanking.
* Variograms (experimental, directional, six models, weighted least-squares fitting with
  bound warnings), residual analysis and leave-one-out cross-validation.
* Map engine independent of Qt: contour, filled contour, colour relief and post layers,
  palettes, colour bar, scale bar (geodesic for geographic CRSs), true-north arrow from
  PROJ grid convergence, coordinate grid, titles; export to PNG, JPEG, SVG, PDF.
* Desktop: Grid Data dialog with cross-validation, variogram dialog, grid document
  (preview, statistics, provenance), map page view with layer list, property editing and
  draggable scale bar and north arrow; Grid and Mapping menus and ribbon pages enabled.
* Project format v2 (grids and maps) with a tested migration from v1. The sample project
  now includes a minimum-curvature terrain grid, a universal-kriging head grid and two maps.
* Documentation: `docs/GRIDDING.md`, `docs/MAPPING.md`; `tools/validate_gridding.py`.

**Decisions**

* Kriging is solved in variogram form so that unbounded models (linear, power) work;
  batched solves keep it fast. Verified against PyKrige rather than built on it, so the
  engine has no PyKrige dependency at run time.
* Minimum Curvature solves the discrete energy minimisation directly with a sparse solver
  (limit 1M nodes) instead of iterative relaxation; it removes a least-squares plane first,
  as GMT `surface` does.
* The scale bar shows grid distance in projected CRSs (no scale-factor correction) and is
  computed at the centre latitude for geographic CRSs, labelled as such.
* Grid math, vector/base/raster/point-density maps, vector import and undo/redo were moved
  to Phase 3 rather than delivered partially.

**Issues found and fixed during testing**

* Nice grid spacing rounded up and gave odd spacings; now the largest nice value not above
  the target.
* Minimum Curvature lost accuracy on planes as grids grew (ridge too strong); fixed with
  plane detrending and a relative ridge. Planes now reproduce to 1e-13.
* Directional variograms were slow; vectorised and capped with a fixed-seed subsample.
* North arrow drew at the figure corner, colour bar and titles were misplaced; fixed by
  rotating the arrow geometry directly and placing elements from the final axes position.
* **Dragging the scale bar or north arrow did nothing**: Matplotlib's `AnchoredOffsetbox`
  ignores `set_offset`, so the stock draggable helper could not move it. Replaced with a
  helper that re-anchors the box; covered by a test that drives real mouse events.
* A negative contour interval was stored before being rejected; validation now happens
  before any change.
* Singular local kriging systems silently produced blank nodes; they are now counted and
  reported as a warning.
* Post-map labels spilled outside the map frame; they are clipped.
* The Grid Data dialog clipped its right column at its default size; widened.
* Sample project: a spherical variogram fitted to the raw well heads ran its range to the
  upper bound because of the regional gradient (the dialog warned). The sample now uses
  Universal Kriging with a variogram fitted to detrended heads.

**Known limitations** (also in GRIDDING.md / MAPPING.md)

* Surfer grid formats are round-trip tested but not yet checked against files written by
  Surfer.
* On the smooth synthetic terrain the fitted Gaussian variogram gives MSSE ≈ 8.7: kriging
  variances understate actual errors there.
* Minimum Curvature with tension sags towards the fitted plane between sparse data.
* Layout editing is a page view with properties and draggable elements, not a free-form
  layout editor.

**Result:** 179 automated tests pass locally and on all 9 CI jobs (run 44677653777:
windows-2022, windows-2025, ubuntu-24.04 × Python 3.11–3.13).

## 2026-11-20 — Phase 3: Advanced GIS and Spatial Analysis (v0.3.0)

**Environment added:** rasterio 1.5.2 (GDAL 3.12.2 in its wheels), pyogrio 0.13.0,
shapely 2.2.0 as run-time dependencies; scikit-learn 1.9.1 as a development-only reference
for the kernel-density tests. GDAL 3.8.4 command-line tools (Ubuntu package) produced the
`gdaldem` reference fixtures; they are not needed at run time or on CI.

**Decisions**

* GDAL is reached through rasterio and pyogrio wheels, not a system GDAL, so the Windows
  build bundles one known GDAL/PROJ.
* A raster cell becomes one grid node at the cell centre, with no interpolation. Every
  operation that does change values on import (warping rotated rasters, reprojection,
  decimation of very large rasters) is recorded in the grid metadata and shown as a
  warning.
* Rasters can be imported either as grids (values, usable in calculations) or as images
  (colours only, base maps). Images are never used in a calculation.
* A file without a CRS gives a layer without a CRS and a warning. A CRS is never guessed;
  assigning one changes metadata only and is recorded in the history.
* Buffers are refused in a geographic CRS; areas and lengths there are geodesic (PROJ
  `Geod`) instead of planar degrees.
* The grid calculator parses expressions with Python's `ast` module and evaluates only a
  whitelist of operators and functions; it never calls `eval`.
* Terrain derivatives follow Horn (1981) and Zevenbergen–Thorne (1987) exactly as stated in
  `docs/GRID_MATH.md`, and are checked against `gdaldem` rather than re-derived.
* Kernel density is called "kernel density" and is checked against scikit-learn. No
  interpolation in this phase is called Kriging; the only Kriging in the program remains
  the genuine Ordinary and Universal Kriging of Phase 2.
* Undo/redo snapshots project content after every completed action and shares data arrays
  between snapshots instead of copying them. This relies on no operation modifying an
  array in place, which a test checks. The processing history stays append-only.
* Desktop wiring for Phase 3 lives in a new `GISMixin` (`desktop/gis.py`); commands take a
  values dictionary so they run with or without a dialog, which is how the GUI tests drive
  them.
* LAS/LAZ point clouds and 3-D surfaces were moved to Phase 4 rather than delivered
  partially. Web tile base maps need network access and licence terms and remain planned.

**Issues found and fixed during testing**

* Line lengths were doubled because the ring-closing routine was also used for lines;
  found by the analytic geodesic-length test.
* KML import produced empty default fields; FlatGeobuf export reordered features (spatial
  index). Both fixed and tested.
* The parameter dialog overflowed when a numeric range exceeded a 32-bit spin box; ranges
  are now clamped.
* A numeric-field check failed on pandas string columns (`np.issubdtype` on `StringDtype`);
  replaced with `pandas.api.types.is_numeric_dtype`.
* Reading a grid file wrongly replaced its own CRS with the project default; the default
  is now applied only to grids that carry none, with the original warning text kept.
* The reader tests broke when the `samples/data/gis/` folder was added; they now skip
  directories.
* Documentation review against the code corrected: the calculator function list, blank
  propagation of `min`/`max`, GeoTIFF compression (DEFLATE, not LZW), the project-file
  encoding name, a migration test name, an unmeasured disk-size figure (replaced by the
  measured artifact size), and the Simpson 3/8 accuracy statement.
* scikit-learn was missing from `requirements-dev.txt`, which would have failed CI.

**Known limitations** (also in GRID_MATH.md / GIS.md)

* The `gdaldem` fixtures come from GDAL 3.8.4 and are not regenerated by CI. The GDAL
  command-line comparison of raster import runs only where those tools are installed
  (skipped on CI).
* Simpson 3/8 uses a trapezoidal end panel when the interval count is not a multiple of 3,
  which can make it less accurate than Simpson 1/3 (documented with measured errors).
* Kernel density has no edge correction. Aspect on projected grids is relative to grid
  north, not true north.
* Clip keeps attributes unchanged; they are not apportioned by area.
* GML, DXF, GPX and MapInfo are readable through GDAL but not covered by tests.
* All sample data are synthetic. Surfer grid formats are still not checked against files
  written by Surfer.
* The Windows build is unsigned and has only been tested on Windows Server CI images, not
  interactively on desktop Windows 10/11.
