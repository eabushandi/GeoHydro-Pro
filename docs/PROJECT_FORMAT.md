# GeoHydro Pro project format (`.ghproj`) — version 3

A project is a single **SQLite 3** database file with the extension `.ghproj`.
Implementation: `geohydro/project/storage.py`.

## Why SQLite

Transactional, a single portable file, identical on Windows/Linux/macOS, readable from
Python on the planned web backend, inspectable with standard tools, and it supports schema
migrations (development rule J).

## Tables

### `meta` (key/value)

| key | meaning |
|---|---|
| `format_name` | always `GeoHydroPro.Project` |
| `format_version` | integer, currently `3` (v1 = Phase 1, points only; v2 adds grids and maps; v3 adds vector layers and raster images) |
| `app_version` | application version that wrote the file |
| `project_uuid` | stable project identity (hex UUID) |
| `revision` | integer, incremented on every save |
| `created`, `modified`, `saved_at` | UTC ISO-8601 timestamps |
| `data_encoding` | `csv+gzip` |

### `project`

One row (`id = 1`), column `manifest`: JSON produced by `project_manifest()` — name,
description, author, default CRS, default units, visualisation/UI settings, output files
list, and a summary of datasets (id, name, CRS, units, point count, source info), grids
(id, name, size, method), maps (id, name), vector layers (id, name, CRS, feature count,
geometry types) and images (id, name, CRS, size). This JSON
is the platform-neutral description intended for the web platform and synchronisation.

### `datasets`

| column | content |
|---|---|
| `id` | dataset UUID (hex) |
| `position` | order in the Project Explorer |
| `name`, `kind` | display name; `points` in Phase 1 |
| `crs` | authority code (e.g. `EPSG:32639`), WKT, or NULL (undefined) |
| `xy_units`, `z_units` | unit codes (`m`, `ft`, `deg`, `mg/L` …) |
| `labels` | JSON `{x, y, z}` original source column names |
| `source` | JSON: absolute path, format, SHA-256, size, mtime, resolved read options |
| `import_settings` | JSON: column mapping, missing tokens, NoData values, QC options |
| `qc_report` | JSON: counts per check and exclusion reason, warnings |
| `columns` | JSON list `[{name, dtype}]`, dtype ∈ `float, int, bool, string` |
| `n_rows` | row count (verified on load) |
| `data_encoding` | `csv+gzip` |
| `data` | gzip-compressed UTF-8 CSV of the imported table; floats written with `%.17g` (exact round trip) |
| `data_sha256` | SHA-256 of `data` (verified on load) |

Dataset tables always contain `X`, `Y`, optional `Z`, `source_row` (1-based data row in the
source file) and any other source columns.

### `grids` (format v2)

| column | content |
|---|---|
| `id`, `position`, `name` | grid UUID, Explorer order, display name |
| `crs`, `xy_units`, `z_units`, `z_label` | as for datasets |
| `geometry` | JSON: `x_min, x_max, y_min, y_max, nx, ny` (node registered) |
| `metadata` | JSON provenance: method and title, parameters as requested and as used, data preparation, blanking, residuals, solver, cross-validation (if run), software, created, elapsed time, warnings; or the source file for imported grids |
| `notes` | free text |
| `data_encoding` | `npy-f8+gzip` |
| `data` | gzip-compressed NumPy `.npy` of the float64 Z array, shape `(ny, nx)`, row 0 = south, `NaN` = blank. Bit-exact round trip. |
| `data_sha256` | SHA-256 of `data` (verified on load, together with shape = geometry) |

### `maps` (format v2)

| column | content |
|---|---|
| `id`, `position`, `name` | map UUID, Explorer order, display name |
| `document` | JSON `MapDocument`: page, orientation, margins, CRS, extent, layers (type, source id, style, levels), colour bar, scale bar, north arrow, coordinate grid, annotations. Layers refer to datasets and grids by id; a missing source is reported, not an error. See `docs/MAPPING.md`. |

### `vectors` (format v3)

| column | content |
|---|---|
| `id`, `position`, `name` | layer UUID, Explorer order, display name |
| `crs`, `xy_units` | as for datasets (`deg` for geographic CRSs) |
| `created`, `notes` | UTC timestamp, free text |
| `source` | JSON: path, format, SHA-256, size, mtime, read options (layer name) — or null for layers created in the project |
| `metadata` | JSON: driver, read report, invalid-geometry count, warnings, processing log (reproject, buffer, clip, dissolve, measures, repair with their parameters) |
| `columns` | JSON list `[{name, dtype}]`, dtype ∈ `float, int, bool, string, datetime` |
| `n_features` | feature count (verified on load) |
| `attr_encoding`, `attributes`, `attr_sha256` | `csv+gzip` attribute table as for datasets; datetimes stored as ISO 8601 text |
| `geom_encoding`, `geometry`, `geom_sha256` | `wkb-list+gzip`: for each feature a little-endian uint32 length followed by ISO WKB (Z kept); length 2³²−1 = no geometry. Bit-exact round trip. |

### `images` (format v3)

| column | content |
|---|---|
| `id`, `position`, `name` | image UUID, Explorer order, display name |
| `crs` | as for datasets |
| `extent` | JSON `[x0, x1, y0, y1]`, outer cell edges |
| `created`, `notes`, `source`, `metadata` | as for vectors (metadata: band mapping, stretch, downsampling, warnings) |
| `data_encoding`, `data`, `data_sha256` | `npy-u1+gzip`: NumPy `.npy` of the `(ny, nx, 4)` uint8 RGBA array, row 0 = north |

### `history`

Append-only processing history: `timestamp` (UTC), `action` (e.g. `dataset.import`,
`dataset.rename`, `dataset.assign_crs`, `project.metadata`, `dataset.export_csv`,
`grid.create`, `grid.rename`, `grid.remove`, `grid.export`, `map.create`, `map.rename`,
`map.remove`, `map.export`, `project.migrate`; from v3 also `vector.import`, `vector.create`,
`vector.rename`, `vector.remove`, `vector.assign_crs`, `vector.export`, `image.import`,
`image.rename`, `image.remove`, `grid.volume`, `grid.profile`, `edit.undo`, `edit.redo`), `details` (JSON — for imports this includes the source checksum, read
options, import settings and QC summary), `app_version`.

## Safety guarantees

* **Loading never writes.** The file is opened read-only and copied into memory.
* **Older versions** are migrated in memory through `MIGRATIONS[from_version]`; the upgraded
  file is written only when the user saves. The previous file is kept as `.bak`.
* **Newer versions** are refused with a message asking the user to update.
* **Atomic save:** written to a temporary file in the same folder, fsynced, then
  `os.replace`d over the target. The previous file is copied to `<name>.ghproj.bak`.
* **No silent overwrite:** saving raises `ProjectOverwriteError` if the target is another
  project or not a project, and `ProjectConflictError` if the target holds a *newer revision
  of the same project* (e.g. saved from another device). The UI asks the user explicitly
  (overwrite newer / Save As / cancel).
* **Integrity:** SQLite `PRAGMA integrity_check`, per-dataset SHA-256 and row-count checks,
  per-grid SHA-256 and shape checks, per-vector-layer SHA-256 and feature-count checks and
  per-image SHA-256 checks on load (`Project → Validate Project` runs them on demand).
* **Source data is never modified.** The project stores an imported copy plus the source
  file's checksum, so a later change to the source can be detected.

## Versioning policy

Increase `FORMAT_VERSION` for any schema or semantic change, and register a migration from
the previous version in `MIGRATIONS`. Each migration receives an in-memory SQLite connection
and must be covered by a test with a stored fixture file of the old version.

## Migrations

| From | To | Change | Test |
|---|---|---|---|
| 1 | 2 | adds the empty `grids` and `maps` tables | `test_v1_project_migrates_to_v2` with the stored v1 file `tests/fixtures/project_format_v1.ghproj` |
| 2 | 3 | adds the empty `vectors` and `images` tables; map documents gain legend, inset, logo, text-box and graticule fields, filled with defaults when read | `test_v2_project_migrates_to_v3_without_changes` with the stored v2 file `tests/fixtures/project_format_v2.ghproj` |

A migrated project opens marked as modified, with a `project.migrate` history entry; the
older file on disk is unchanged until the user saves. Migrations chain (v1 → v2 → v3).
