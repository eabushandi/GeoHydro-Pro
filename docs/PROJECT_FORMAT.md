# GeoHydro Pro project format (`.ghproj`) — version 1

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
| `format_version` | integer, currently `1` |
| `app_version` | application version that wrote the file |
| `project_uuid` | stable project identity (hex UUID) |
| `revision` | integer, incremented on every save |
| `created`, `modified`, `saved_at` | UTC ISO-8601 timestamps |
| `data_encoding` | `csv+gzip` |

### `project`

One row (`id = 1`), column `manifest`: JSON produced by `project_manifest()` — name,
description, author, default CRS, default units, visualisation/UI settings, output files
list, and a summary of datasets (id, name, CRS, units, point count, source info). This JSON
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

### `history`

Append-only processing history: `timestamp` (UTC), `action` (e.g. `dataset.import`,
`dataset.rename`, `dataset.assign_crs`, `project.metadata`, `dataset.export_csv`,
`project.migrate`), `details` (JSON — for imports this includes the source checksum, read
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
* **Integrity:** SQLite `PRAGMA integrity_check`, per-dataset SHA-256 and row-count checks on
  load (`Project → Validate Project` runs them on demand).
* **Source data is never modified.** The project stores an imported copy plus the source
  file's checksum, so a later change to the source can be detected.

## Versioning policy

Increase `FORMAT_VERSION` for any schema or semantic change, and register a migration from
the previous version in `MIGRATIONS`. Each migration receives an in-memory SQLite connection
and must be covered by a test with a stored fixture file of the old version.
