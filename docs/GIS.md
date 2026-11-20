# GIS data, map layers and layer management (Phase 3)

This document covers vector and raster data, base maps, GIS map layers, map
furniture, and undo/redo. Grid calculations (terrain, volumes, density) are in
`docs/GRID_MATH.md`. The code is in `geohydro/engine/vector/`,
`geohydro/engine/raster/`, `geohydro/engine/mapping/gis_render.py` and
`geohydro/project/undo.py`.

## 1. Vector data

### 1.1 Formats

Reading goes through GDAL/OGR (pyogrio). The formats below are tested and
offered in the file dialog. Other GDAL-readable formats may work but are not
tested.

| Format | Read | Write | Notes |
|---|---|---|---|
| ESRI Shapefile (`.shp`) | ✓ | ✓ | CRS from `.prj`. Field names truncated to 10 characters by the format; collisions are made unique and reported. |
| Zipped shapefile (`.zip`) | ✓ | – | Read directly, without unzipping. |
| GeoJSON (`.geojson`, `.json`) | ✓ | ✓ | |
| GeoPackage (`.gpkg`) | ✓ | ✓ | Multi-layer files: the layer is chosen on import. |
| KML / KMZ | ✓ | ✓ (KML) | Coordinates are WGS 84 lon/lat by definition. Empty default KML fields are dropped on read. |
| FlatGeobuf (`.fgb`) | ✓ | ✓ | Written without a spatial index, to keep feature order. |
| GML, DXF, GPX, MapInfo TAB/MIF | ✓ | – | Read only. Not covered by tests in this phase. |

Rules:

* **Coordinates** are read exactly as stored. Z values of 3-D geometries are
  kept. M values are dropped.
* **CRS.** The CRS comes from the file. A file without a CRS gives a layer
  with **no CRS and a warning**; a CRS is never guessed. You can assign one in
  the Properties panel, which changes metadata only and does not transform
  coordinates. The assignment is recorded in the history.
* **Invalid geometries** (for example self-intersecting polygons) are counted
  and reported on import. They can be repaired with Vector Processing ▸
  Repair (§1.3).
* **Shapefile geometry types.** A layer that mixes Polygon and MultiPolygon is
  written as multi-part, as the format requires.

### 1.2 Measures

* **Projected CRS.** Area and length are planar (GEOS) in CRS units. These are
  *grid* measures. They differ from ground measures by the projection's scale
  error: in UTM, lengths within about ±0.1 % and areas within about ±0.2 %
  inside the zone.
* **Geographic CRS.** Area, perimeter and length are geodesic on the WGS 84
  ellipsoid (Karney 2013, PROJ `Geod`), in m² and m. Planar areas in degrees
  are never reported.

Validation (automated tests):

| Check | Reference | Result | Test |
|---|---|---|---|
| Geodesic length | 1° of longitude on the equator = a·π/180 | relative error < 10⁻¹² | `test_geodesic_length_equator_analytic` |
| Geodesic area | Lambert azimuthal equal-area (ellipsoidal) projection, 0.1° × 0.1° polygon at 25° N | relative diff < 10⁻⁶ | `test_geodesic_area_matches_equal_area_projection` |
| Planar measures | analytic squares and rectangles | exact | `test_planar_measures` |
| Round trips | every writable format | geometry, attributes and CRS preserved | `test_round_trip_all_write_formats` |

A real bug was found by the analytic length test during development and
fixed: line lengths were doubled because the ring-closing routine was used for
lines.

### 1.3 Processing

Data ▸ Vector Processing… offers the operations below. Each one creates a
**new layer** and leaves the original unchanged. The operation and its
parameters are recorded in the new layer's processing log and in the project
history, and the operation can be undone.

| Operation | Notes |
|---|---|
| Reproject | PROJ through pyproj. Recorded in the layer's processing log. |
| Buffer | **Refused in a geographic CRS** (a distance in degrees is not a distance). Reproject first. |
| Clip | Clips to the polygons of another layer, which is reprojected if needed. Attributes are kept unchanged; they are not apportioned by area. |
| Dissolve | Merges all features, or merges by an attribute. |
| Add area / length fields | The measures of §1.2 as new attribute columns, with the unit in the column name. |
| Repair | GEOS `make_valid`. The number of features repaired is recorded. |
| Points → point dataset (Data ▸ Vector Points to Point Dataset) | Point layer to point dataset. Z comes from a numeric field or from the 3-D coordinate. Rows whose Z is not a number are excluded and counted in a QC report. The result can be gridded, posted and analysed like an imported CSV. |

## 2. Raster data

### 2.1 Rasters as grids

A raster stores values for **cells**; a GeoHydro grid stores values at
**nodes**. One grid node is placed at the centre of every cell:

```
x_i = x_left + (i + ½)·Δx,     y_j = y_top − (j + ½)·|Δy|
```

* No value is interpolated or shifted in this conversion.
* Rows are reordered so that row 0 is the south row.
* NoData and masked cells become blank.
* Band scale and offset are applied: `z = raw·scale + offset`.

The following exceptions each change values and are recorded in the grid
metadata and shown as warnings:

* **Rotated or sheared rasters**, or rasters georeferenced only by ground
  control points, are warped to north-up with the chosen resampling.
* **Reprojection on import** (optional: "reproject to project CRS") is a warp
  with the chosen resampling (default bilinear). Areas outside the source
  raster become blank, not 0.
* **Very large rasters** (more cells than the grid limit) are read reduced by
  an integer factor, using block averaging of valid cells (GDAL `average`).
  The factor is recorded.

GeoTIFF export writes float64 by default (float32 optional), with DEFLATE
compression, NaN as NoData, and the CRS.

### 2.2 Rasters as images (base maps)

RGB(A) and paletted rasters are imported as display images. Use them as base
maps (aerial photos, scanned maps, hillshades exported from other software).

* Bands that are not 8-bit are stretched linearly between their 2nd and 98th
  percentiles, **for display only**.
* Transparency comes from the alpha band or the NoData mask.
* Images larger than 4096 pixels on the long side are downsampled for display.
  The original file is not changed.
* An image in another CRS is reprojected on the fly to the map CRS with
  nearest-neighbour resampling, and the map shows a note saying so.

**Images carry colours, not values.** No calculation is ever done on an
image. To analyse a raster, import it as a grid.

Validation: rasters written by GeoHydro Pro as ESRI ASCII and converted to
GeoTIFF by GDAL's own `gdal_translate` read back with identical geometry and
values (`test_matches_gdal_conversion_of_esri_ascii`). Further tests cover
NoData, scale/offset, south-up rasters, rotated rasters, reprojection,
decimation, palettes and 16-bit stretching (`tests/test_raster.py`, 17 tests).

## 3. Map layers

A map holds an ordered list of layers, drawn bottom to top. The Layers panel
lists them with the top layer first. For each layer you can:

* **Show or hide** it with the tick box.
* **Reorder** it with ▲ and ▼.
* **Remove** it.
* Set its **opacity** (0–1) in the Properties panel.

| Layer | Source | Symbology |
|---|---|---|
| Contours, filled contours, colour relief | grid | see `docs/MAPPING.md`. Colour relief can make values below a threshold transparent ("Transparent below"). |
| Post | point dataset | see `docs/MAPPING.md` |
| Vector | vector layer | single colour; **categorized** (one colour per value of a field, up to 40 categories); **graduated** (2–12 classes of a numeric field, quantile or equal-interval breaks). Fill and outline colour, line width, marker and size, labels from a field. |
| Base map image | raster image | as stored. Added at the bottom of the layer list. |

Rules:

* Vector layers and images in another CRS than the map are **reprojected on
  the fly** to the map CRS for drawing. The stored data are not changed, and
  the map shows a note.
* **Graduated classes.**
  * Equal interval: breaks at `min + k·(max − min)/n`.
  * Quantile: breaks at the k/n quantiles (linear interpolation between order
    statistics). Duplicate breaks are merged, so fewer classes may result.
  * Features with a missing value are drawn grey and listed as "no data".

## 4. Map furniture

Every element below is set in the Properties panel when the page is selected
("Page & Map Elements"). All elements are exported with the map.

| Element | Options |
|---|---|
| Title, subtitle | text |
| Legend | show; title; position (corners); text size. Contour, post, vector and image layers that are visible and marked "show in legend" are listed with their symbols, categories or classes. |
| North arrow | show; position, or drag in the page view. Points to true north, computed from the map CRS. |
| Scale bar | show; position, or drag in the page view |
| Colour scale | show; label |
| Coordinate grid | tick labels and grid lines in map coordinates; optional **latitude/longitude graticule** in degrees and minutes on a projected map (automatic or fixed interval) |
| Inset (location map) | show; position; size. A small overview map, at least 3× the main map extent, drawing the layers marked "show in inset" without labels, with the main map extent outlined. |
| Text boxes | Insert ▸ Text Box…; text, position (fraction of the map frame), size, frame. Clear the text to delete a box. |
| Logo | Insert ▸ Logo Image… (PNG or JPEG, under 2 MB, embedded in the project); show, position, width in mm |

### 4.1 Export for publication

| Format | Notes |
|---|---|
| PNG, JPEG | Raster formats at a chosen resolution (default 300 dpi, up to 1200). |
| TIFF | LZW compressed, with the resolution written in the file. Common for journal submissions. |
| PDF, SVG | Vector formats. Fonts in PDF are embedded as TrueType (Type 42), so text stays editable and searchable, as many publishers require (tested). |

## 5. Undo and redo

Edit ▸ Undo (Ctrl+Z) and Redo (Ctrl+Y) cover:

* Imports, creating or removing grids, maps, vector layers and images.
* Renaming, and CRS or unit assignments.
* Grid-math results.
* Every map edit: layers, symbology, furniture, dragged elements, extent.

The menu names the action, for example "Undo Create grid".

* **Snapshots.** After each completed action the project content is
  snapshotted. Data arrays are shared between snapshots, not copied. This is
  safe because no GeoHydro operation modifies an array in place (tested). Map
  documents are copied in full.
* **Depth.** The last 30 actions can be undone. The history starts fresh when
  a project is opened or created.
* **What is not rolled back.** The processing history is an append-only
  record, so an undo adds an `edit.undo` entry instead of deleting entries.
  Exported files stay on disk after an undo.
* **Open documents** are reopened on the restored objects after an undo or
  redo.

## 6. Project file

Vector layers and images are stored inside the `.ghproj` file (format v3; see
`docs/PROJECT_FORMAT.md`):

* Geometries are stored as WKB and attributes as typed columns, gzip
  compressed and checksummed.
* Images are stored as compressed RGBA arrays.
* Files from Phase 1 and 2 (format v1, v2) are upgraded in memory when opened.
  The file on disk is unchanged until you save (tested with a stored v2
  file).

## 7. Sample data

`samples/data/gis/` holds synthetic data generated by
`samples/generate_samples.py --gis` (seed 20261120) for a fictitious site in
UTM zone 39N:

* a 50 m DEM (GeoTIFF)
* an RGB base image in WGS 84 (GeoTIFF)
* the site boundary (GeoJSON, WGS 84)
* wadi channels (Shapefile)
* land-use polygons with runoff coefficients (GeoPackage)
* boreholes with water levels (GeoPackage)
* 420 flood reports (GeoJSON, WGS 84)

`samples/gis_demo_project.ghproj` (File ▸ Open GIS Demo Project) holds three
finished maps: terrain and drainage, flood-report density, and land use.

**The data are invented, for demonstration only.** They do not describe any
real place and must not be used for engineering.

## 8. Not included in Phase 3

The following are not implemented and are not offered in the program:

* Editing vector geometries (digitising).
* Web tile base maps (OpenStreetMap or satellite tiles). These need network
  access and licence terms, and are planned for a later phase.
* LAS/LAZ point clouds and 3-D views. These were moved from Phase 3 to
  Phase 4.
* NetCDF (Phase 6).
