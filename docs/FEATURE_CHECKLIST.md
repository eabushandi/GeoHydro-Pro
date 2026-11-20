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
| Undo / redo | ⬜ moved to Phase 3 (not done in Phase 2) |

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
| Map layout | 🟡 | page view with page size/orientation/margins, property editing, draggable scale bar and north arrow. Free-form layout (several frames, insets, logos, text boxes) planned |
| Annotations | 🟡 | stored and drawn; no interactive annotation tool yet |
| Export PNG, JPEG, SVG, PDF | ✅ | exact page size; never overwrites silently |
| Project format v2 (grids, maps) with v1 migration | ✅ | `test_project_storage.py` |
| Grid math, vector maps, base maps, point-density maps, raster-layer maps | ⬜ | moved to Phase 3 |
| Vector import (shapefile, GeoJSON …) | ⬜ | moved to Phase 3 |
| Undo / redo | ⬜ | moved to Phase 3 |
| Windows CI | ✅ | 9/9 jobs, 179/179 tests each (run 44677653777) |
| Interactive check on desktop Windows 10/11 | ⬜ | CI runs on Windows Server images only |

## Later phases (all ⬜ planned, visible but disabled in the UI)

* Phase 3: grid math, vector/base/point-density/raster maps, vector import, undo/redo,
  3D surfaces and point clouds, raster/DEM import, LAS/LAZ, slope, aspect,
  hillshade, curvature, profiles, cut/fill volumes.
* Phase 4: DEM conditioning, D8, flow accumulation, streams, watersheds.
* Phase 5: shoreline baselines/transects, EPR, LRR, NSM, SCE, beach profiles.
* Phase 6: flood susceptibility (screening), stormwater, groundwater and water-quality
  surfaces, NetCDF, PDF/Excel reports.
* Phase 7: accounts, cloud sync, licensing, subscriptions, payments, admin dashboard,
  website, web application.
* Phase 8: validation campaign, security/performance testing, Windows installer, cloud
  deployment, Arabic interface.
