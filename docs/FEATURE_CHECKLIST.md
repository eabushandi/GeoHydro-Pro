# Feature completion checklist

Legend: ✅ implemented and covered by automated tests · 🟡 implemented, partial (see note) ·
⬜ planned (shown disabled in the UI with its phase).

## Phase 1 — Foundation (section 29 tasks)

| # | Task | Status | Evidence |
|---|---|---|---|
| 1–3 | Project directory, architecture, dependency files | ✅ | `pyproject.toml`, `requirements*.txt`, `docs/ARCHITECTURE.md` |
| 4 | Shared scientific engine foundation | ✅ | `geohydro/engine` (Qt-free); `tests/test_qc.py`, `test_statistics_crs_units.py` |
| 5–6 | Desktop shell and professional main window | ✅ | `desktop/main_window.py`; `test_gui.py::test_main_window_structure` |
| 7 | Menu (17 menus) and ribbon (9 tabs) | ✅ | `test_main_window_structure`, `test_planned_features_are_disabled_and_labelled` |
| 8 | Project Explorer (all spec categories; future ones marked planned) | ✅ | `test_explorer_categories` |
| 9 | Properties panel (editable project/dataset properties) | ✅ | `test_properties_edit_rename_and_crs` |
| 10 | Output Console (levels, filter, save log) | ✅ | `test_console_filter` |
| — | Status bar (cursor X/Y, nearest Z, CRS, scale, grid, status) | ✅ | `test_preview_cursor_updates_status_bar` |
| 11 | CSV, XLSX, XYZ import (+ TXT, DAT) | ✅ | `test_readers.py`, `test_importer.py` |
| 12 | Functional data preview (parsed, raw, point locations, live QC) | ✅ | `test_import_wizard_*` |
| 13 | Project save/load, versioned format | ✅ | `test_project_storage.py`, `test_save_open_roundtrip_through_ui` |
| 14 | Sample scientific datasets | ✅ | `samples/` (synthetic, documented generator) |
| 15 | Run the application | 🟡 | Run offscreen on Linux and on Windows Server 2022/2025 (CI). Not yet run interactively on desktop Windows 10/11. |
| 16–17 | Automated tests, fix errors | ✅ | 88 passed at Phase 1; 179 at Phase 2 — `docs/TEST_RESULTS.md` |

### Data import workflow (section 6)

| Step | Status |
|---|---|
| Select input files (multiple) | ✅ |
| Preview the data | ✅ |
| Select X, Y, Z columns (auto-suggested) | ✅ |
| Define CRS (validated via PyProj) | ✅ |
| Set measurement units | ✅ (labels; no conversion on import by design) |
| Detect missing values (tokens, blanks, NoData) | ✅ |
| Identify duplicate coordinates (exact / tolerance) | ✅ |
| Filter invalid observations | ✅ |
| Import multiple datasets | ✅ |
| Save imported datasets into the project | ✅ |
| Clear error reporting | ✅ (wizard banner, console, QC report) |
| Preserve source data | ✅ (read-only, checksum stored and tested) |

### Project management (section 16) — Phase 1 scope

| Item | Status |
|---|---|
| Create / save / reopen projects | ✅ |
| Organise datasets (rename, remove, export) | ✅ |
| Save processing settings (import settings per dataset) | ✅ |
| Analysis history | ✅ (processing history table + dialog) |
| Manage output files | 🟡 outputs list recorded for CSV, grid and map exports; no output manager UI yet |
| Export complete projects | 🟡 `.ghproj` is self-contained; JSON manifest export ✅; zip bundle with source files ⬜ |
| Versioning, conflict detection, never overwrite without confirmation | ✅ |
| Windows ↔ Web portability | 🟡 format is platform-neutral; web side not built |

### Other Phase 1 items

| Item | Status |
|---|---|
| CRS inspector and coordinate transform tool | ✅ |
| Export dataset to CSV (refuses to overwrite source) | ✅ |
| Project integrity validation | ✅ |
| i18n architecture (RTL switch, translator hook) | 🟡 hooks only; no translations |
| Web application foundation (roadmap Phase 1 item) | ⬜ not started — out of this thread's scope |
| CI workflow (Windows + Linux) | ✅ 9/9 jobs pass (windows-2022, windows-2025, ubuntu-24.04 × Py 3.11–3.13) |
| Undo / redo | ✅ delivered in Phase 3 (see below) |

## Phase 2 — Core Mapping (section 28)

| Item | Status | Evidence / note |
|---|---|---|
| Gridding engine (grid model, limits, spacing, NoData, CRS) | ✅ | `engine/gridding/grid.py`; `test_gridding.py` |
| Inverse Distance Weighting (power, smoothing, search, anisotropy) | ✅ | `test_interpolation.py` |
| Ordinary Kriging (genuine; variance grid) | ✅ | matches PyKrige to ~1e-13 (`test_kriging_matches_pykrige`) |
| Universal Kriging (linear / quadratic drift) | ✅ | matches PyKrige to ~1e-10 |
| Minimum Curvature (tension, free edges, plane detrending) | ✅ | reproduces planes; tension reduces overshoot; limited to 1M nodes |
| Natural Neighbour (exact Sibson) | ✅ | exactness, linear precision, weight properties |
| Nearest Neighbour | ✅ | |
| Linear Triangulation | ✅ | |
| Radial Basis Functions (8 kernels, local or global) | ✅ | compared with SciPy directly |
| Search radius, neighbours, anisotropy, coincident points, blanking | ✅ | |
| Variogram: experimental (directional), 6 models, WLS fitting with warnings | ✅ | `test_interpolation.py` |
| Grid preview, grid statistics, residual analysis | ✅ | grid document; `test_gui_phase2.py` |
| Cross-validation: RMSE, MAE, ME, R², kriging standardised errors | ✅ | `test_gridding.py`, dialog test |
| Scientific documentation for every method | ✅ | `docs/GRIDDING.md` (equations, assumptions, limitations, validation table) |
| Grid files: Surfer 6 text / 6 binary / 7 binary, ESRI ASCII (read/write), XYZ (write) | 🟡 | round-trip tested; **not yet checked against files written by Surfer** |
| Contour maps (intervals, labels, major lines) | ✅ | `test_mapping.py` |
| Filled contour maps | ✅ | |
| Colour relief maps | ✅ | |
| Post maps (symbols, colour by Z, labels) | ✅ | |
| Palettes (uniform, conventional, diverging; reversible) | ✅ | |
| Legend (colour bar), scale bar, north arrow (true north), coordinate grid, titles | ✅ | convergence sign tested; geographic scale bar labelled with its latitude |
| Transparency, layer order, multi-layer maps | ✅ | |
| Map layout | 🟡 | page view with page size/orientation/margins, property editing, draggable scale bar and north arrow. Phase 3 added inset, logo and text boxes; several independent map frames on one page are still planned |
| Annotations | 🟡 | stored and drawn; no interactive annotation tool yet |
| Export PNG, JPEG, SVG, PDF | ✅ | exact page size; never overwrites silently |
| Project format v2 (grids, maps) with v1 migration | ✅ | `test_project_storage.py` |
| Grid math, vector maps, base maps, point-density maps, raster-layer maps | ✅ | delivered in Phase 3 (see below) |
| Vector import (shapefile, GeoJSON …) | ✅ | delivered in Phase 3 |
| Undo / redo | ✅ | delivered in Phase 3 |
| Windows CI | ✅ | 9/9 jobs, 179/179 tests each (run 44677653777) |
| Interactive check on desktop Windows 10/11 | ⬜ | CI runs on Windows Server images only |

## Phase 3 — Advanced GIS and Spatial Analysis (v0.3.0)

| Item | Status | Evidence / note |
|---|---|---|
| Grid calculator (grids A–D, math functions, `where`, `isblank`, `fillblank`, resampling to a common geometry) | ✅ | safe expression parser, no `eval`; `test_gridmath.py`; `docs/GRID_MATH.md` §1 |
| Grid filters (mean, median, min, max, range, std, high-pass, Gaussian; blank-aware), blanking by polygon, clipping | ✅ | mean filter equals SciPy `uniform_filter` in the interior |
| Slope, aspect, hillshade (Horn) | ✅ | match `gdaldem` (GDAL 3.8.4 fixtures): 3.1e-5°, 0.0022°, ≤ 0.51/255 |
| Curvature (Zevenbergen–Thorne: profile, plan, total) | ✅ | exact on a paraboloid |
| Profiles along typed vertices or a line feature, CSV export | ✅ | `test_gridmath.py`, `test_gui_phase3.py` |
| Volumes: trapezoidal, Simpson 1/3, Simpson 3/8; cut/fill against a level or grid | ✅ | analytic paraboloid/plane tests; Simpson 3/8 accuracy caveat documented |
| Vector import: Shapefile (and zipped), GeoJSON, GeoPackage, KML/KMZ, FlatGeobuf | ✅ | `test_vector.py` round trips; CRS never guessed |
| Vector import: GML, DXF, GPX, MapInfo | 🟡 | offered as read-only through GDAL; **not covered by tests** |
| Vector export (Shapefile, GeoJSON, GeoPackage, KML, FlatGeobuf) | ✅ | round-trip tested |
| Vector processing: reproject, buffer, clip, dissolve, area/length fields, repair | ✅ | each creates a new layer, logged and undoable |
| Geodesic area/length in geographic CRSs | ✅ | analytic equator length < 1e-12; area vs LAEA < 1e-6 |
| Vector points → point dataset (Z from field or 3-D coordinate) | ✅ | QC report for rejected rows |
| Raster import as grid (GeoTIFF and GDAL formats; NoData, scale/offset, south-up, rotated, reprojection, decimation) | ✅ | `test_raster.py` (17 tests) |
| Raster import as base-map image (RGB, RGBA, paletted, 16-bit stretch) | ✅ | display only; never used in calculations |
| GeoTIFF export of grids | ✅ | DEFLATE, NaN NoData, CRS |
| Point density: KDE (5 kernels, bandwidth rules), point counts, weights, per km² | ✅ | matches scikit-learn to 7e-15 (compact kernels) / 1.1e-6 (Gaussian) |
| Vector, raster and point integration on one map | ✅ | on-the-fly reprojection to the map CRS, with a note on the map |
| Undo / redo (30 steps, imports, edits, grid math, map edits) | ✅ | `test_undo.py`, `test_gui_phase3.py` |
| Multiple layers: visibility, order, opacity, symbology (single, categorized, graduated) | ✅ | `test_mapping_gis.py` |
| Legend, north arrow, scale bar, coordinate grid, lat/lon graticule | ✅ | |
| Inset location map, text boxes, logo image | ✅ | |
| Several independent map frames on one page | ⬜ | planned |
| Interactive annotation drawing tool | ⬜ | planned (text boxes are placed by position) |
| Publication export: PNG, JPEG, TIFF (LZW, dpi tag), PDF and SVG with embedded TrueType fonts | ✅ | TIFF and PDF font embedding tested |
| Project format v3 (vectors, images) with v1/v2 migration | ✅ | `test_project_storage.py` |
| Scientific documentation (equations, assumptions, limitations, validation) | ✅ | `docs/GRID_MATH.md`, `docs/GIS.md` |
| Sample GIS datasets and GIS demo project | ✅ | synthetic, seed 20261120; self-test opens and exports it |
| Windows installer, portable zip, frozen self-test, silent install/uninstall | ✅ | *windows-package* run 44708856484 (Windows Server 2022) |
| Windows CI | ✅ | 9/9 jobs, 317 passed + 1 skipped each (run 44708856501) |
| Installation and troubleshooting guide | ✅ | `docs/WINDOWS_INSTALL.md` |
| Code signing | ⬜ | needs a paid certificate; planned for production |
| Web tile base maps (OpenStreetMap, satellite) | ⬜ | planned (network access and licence terms) |
| LAS/LAZ point clouds, 3-D surfaces | ⬜ | moved to Phase 4 |
| Interactive check on desktop Windows 10/11 | ⬜ | CI runs on Windows Server images only |

## Later phases (all ⬜ planned, visible but disabled in the UI)

* Phase 4: 3-D surfaces and point clouds, LAS/LAZ, DEM conditioning, D8, flow
  accumulation, streams, watersheds.
* Phase 5: shoreline baselines/transects, EPR, LRR, NSM, SCE, beach profiles.
* Phase 6: flood susceptibility (screening), stormwater, groundwater and water-quality
  surfaces, NetCDF, PDF/Excel reports.
* Phase 7: accounts, cloud sync, licensing, subscriptions, payments, admin dashboard,
  website, web application.
* Phase 8: validation campaign, security/performance testing, code signing, cloud
  deployment, Arabic interface.
