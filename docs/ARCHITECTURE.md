# Architecture (Phases 1–2)

## Layers

```
 ┌─────────────────────────────┐   ┌───────────────────────────┐
 │ geohydro.desktop (PySide6)  │   │ web/ (planned: FastAPI +  │
 │ main window, dialogs,       │   │ React/TypeScript)         │
 │ widgets, documents          │   │                           │
 └──────────────┬──────────────┘   └─────────────┬─────────────┘
                │ calls                           │ will call the same API
 ┌──────────────▼─────────────────────────────────▼─────────────┐
 │ geohydro.project   Project model, .ghproj storage, migrations │
 ├──────────────────────────────────────────────────────────────┤
 │ geohydro.engine    data (readers, parsing, QC, statistics,    │
 │                    dataset, importer), crs, units,            │
 │                    interpolation, gridding, mapping,          │
 │                    capabilities; planned science modules      │
 └──────────────────────────────────────────────────────────────┘
        NumPy · pandas · SciPy · openpyxl · PyProj · Matplotlib
```

Rules:

1. `geohydro.engine` and `geohydro.project` never import Qt. This is what lets the planned
   web backend run identical calculations and read/write the same project files.
2. All user-visible strings live in the desktop layer, ready for translation (Arabic/RTL
   switching is wired in `desktop/i18n.py`; no translations exist yet).
3. `engine/capabilities.py` is the single registry of implemented versus planned features.
   The menus, ribbon, explorer and start page derive their enabled/planned state from it,
   so a feature cannot appear active in the UI until it is registered as implemented.
4. Long operations run off the GUI thread (`desktop/workers.py`); engine modules log via
   Python `logging` (`geohydro.*`), which the Output Console displays thread-safely.

## Import pipeline

`read_table` (raw strings, exactly as in the source) → `guess_xyz` (suggestion only) →
`run_qc` (numeric parsing with explicit masks, exclusions, duplicate handling) →
`PointDataset` (clean data + source fingerprint + settings + QC report). The import wizard
calls `preview`/`qc_preview`, which are the same functions on a row-limited read, so the
preview is exactly what will be imported. Details: [DATA_IMPORT.md](DATA_IMPORT.md).

## Gridding and mapping (Phase 2)

* `engine/interpolation/`: one class per method behind a common `Interpolator` interface
  (`fit`, `predict`, `parameters`), shared data preparation, KD-tree search and anisotropy,
  variograms. No UI code.
* `engine/gridding/`: grid model (node registered, row 0 = south), grid file formats,
  `grid_data()` orchestration (preparation → interpolation → blanking → residuals →
  provenance metadata) and leave-one-out cross-validation. `methods.METHODS` is the method
  registry the dialog is built from.
* `engine/mapping/`: `MapDocument` (plain data, JSON), levels and palettes, and
  `render_map()`/`export_map()` on a plain Matplotlib `Figure`. The desktop page view and
  export use the same renderer, and a web or batch backend can too.
* Desktop: `dialogs/grid_dialog.py`, `dialogs/variogram_dialog.py`,
  `documents/grid_document.py`, `documents/map_document.py`, with the main-window wiring in
  `desktop/gridmap.py` (a mixin, keeping `main_window.py` from growing further).

Methods and limitations: [GRIDDING.md](GRIDDING.md), [MAPPING.md](MAPPING.md).

## Persistence

`.ghproj` = one SQLite database, format version 2 (grids and maps added; v1 files migrate). See [PROJECT_FORMAT.md](PROJECT_FORMAT.md).
The `project_manifest()` JSON is the platform-neutral description intended for the web
platform and for synchronisation (Phase 7).

## Desktop composition

| Component | Module |
|---|---|
| Main window, actions, menus, ribbon wiring | `desktop/main_window.py` |
| Ribbon | `desktop/widgets/ribbon.py` |
| Project Explorer | `desktop/widgets/project_explorer.py` |
| Properties panel | `desktop/widgets/properties_panel.py` |
| Output Console | `desktop/widgets/output_console.py` |
| Status bar | `desktop/widgets/status_bar.py` |
| Import wizard | `desktop/dialogs/import_wizard.py` |
| Dataset document (table / preview / statistics / QC) | `desktop/documents/dataset_document.py` |
| Point preview (matplotlib) | `desktop/widgets/point_preview.py` |
| Grid Data dialog, variogram dialog | `desktop/dialogs/grid_dialog.py`, `variogram_dialog.py` |
| Grid document (preview / statistics / provenance) | `desktop/documents/grid_document.py` |
| Map page view and layout editing | `desktop/documents/map_document.py` |
| Gridding and mapping actions | `desktop/gridmap.py` |
| Theme and original icons | `desktop/theme.py`, `desktop/icons.py` |

## Deviations from the suggested structure (section 27)

* Code lives in an installable package `geohydro/` (`geohydro/engine`, `geohydro/desktop`,
  `geohydro/project`) instead of top-level `engine/` and `desktop/` folders. Reason: avoids
  name clashes with other packages called `engine`, enables `pip install -e .` and a
  console entry point, and lets the web backend import the engine as a normal package.
* The desktop SQLite project layer lives in `geohydro/project/` (not `database/`), because
  it is part of the shared engine contract; `database/` is reserved for the cloud
  PostgreSQL/PostGIS schema.
* `docker-compose.yml` is not provided yet: there is no service to compose until the
  backend exists (Phase 7). Creating a non-functional file would misrepresent the state.
