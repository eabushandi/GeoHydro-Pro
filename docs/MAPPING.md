# 2D mapping and map layout (Phase 2)

This document describes how GeoHydro Pro draws maps from grids and point
datasets, what each map element means, and the known limitations.

Code: `geohydro/engine/mapping/` (map model, levels and palettes, renderer and
export; no Qt dependency) and `geohydro/desktop/documents/map_document.py`
(the page view and layout editing in the desktop application).

## 1. Architecture

A map is a `MapDocument`: page size and orientation, margins, CRS, an optional
fixed extent, an ordered list of layers, and the map elements (title, colour
bar, scale bar, north arrow, coordinate grid, annotations). It is plain data,
saved as JSON in the project file (table `maps`).

`render_map(doc, resolve)` draws a document on a Matplotlib `Figure`. Layers
refer to their data by id, and `resolve(id)` returns the grid or dataset, so a
map always shows the current data. The same renderer is used by the desktop
page view and by export, and can be used by a future web or batch backend.
Missing sources and problems are returned as warnings and shown on the map
view; they never stop the rest of the map from drawing.

## 2. Layer types (Phase 2)

| Layer | Source | What it draws |
|---|---|---|
| Contour map | grid | contour lines at chosen levels, optional labels and major lines |
| Filled contour map | grid | colour bands between levels |
| Colour relief map | grid | continuous colour image of the grid |
| Post map | point dataset | symbols at the data points, optional colour by Z and labels |

Layers draw bottom to top in list order; the layer list in the map view shows
the top layer first. Each layer has a name, visibility and opacity
(transparency, 0–1).

### 2.1 Contour levels

`LevelSpec` sets the levels:

* **auto**: about `count` levels (default 10) at a nice interval (1, 2, 2.5 or
  5 × 10ᵏ) covering the grid's Z range;
* **interval**: a given interval, optionally between a first and last level;
  levels are multiples of the interval when no first level is given;
* **list**: explicit values.

At most 500 levels are allowed. Levels are rounded to remove floating-point
noise (0.3, not 0.30000000000000004).

### 2.2 Contour lines

Lines are computed by Matplotlib's marching-squares algorithm on the node grid,
with linear interpolation along cell edges. Blank (NaN) nodes break the
contours. Options: line colour or colour by level, line width, every n-th
level as a major line with its own width, labels (on major lines when majors
are set) with automatic or fixed decimals. When no level lies inside the grid
range, the layer draws nothing and a warning says so.

### 2.3 Filled contours

Bands between successive levels, coloured with the layer's palette. Values
below the first or above the last level are drawn with the palette's end
colours, and the colour bar shows extension arrows for them.

### 2.4 Colour relief

Each node is a pixel centred on the node (so the image covers half a cell
beyond the first and last nodes). Blank nodes are transparent. Optional
bilinear smoothing between nodes (display only; the grid is unchanged).
Colour range: the grid's Z range unless fixed minimum and maximum are given.

### 2.5 Post maps

Symbol, size, face and edge colour, optional colour by Z with a palette, and
labels from any column (numeric labels with fixed decimals). Labels are
clipped to the map frame. Above 3,000 points labels are not drawn and a
warning says so (the symbols are still drawn).

## 3. Palettes

| Palette | Use |
|---|---|
| Viridis, Cividis, Magma, Plasma | perceptually uniform; Cividis is suitable for colour-vision deficiency |
| Terrain, Earth | conventional elevation palettes (not perceptually uniform) |
| Blues, Yellow-Green-Blue | depth, water, concentration |
| Yellow-Orange-Red | concentration, hazard |
| Red-Blue, Brown-Blue-Green (diverging) | change, residuals, erosion/accretion; centre them on zero with fixed limits |
| Spectral | rainbow-like (not uniform); provided because it is widely used |

Every palette can be reversed. Non-uniform palettes can create apparent
features that are not in the data; the uniform palettes are recommended for
quantitative maps.

## 4. Map elements

* **Title and subtitle**, placed above the map frame.
* **Colour bar** for the topmost colour layer, labelled with the grid's Z
  label and units (or a custom label).
* **Coordinate grid** (graticule): tick labels in map coordinates and optional
  grid lines. With a geographic CRS the labels are shown in degrees.
* **Scale bar**, see 4.1.
* **North arrow**, see 4.2.
* **Annotations** (text at map coordinates) are stored in the model and drawn;
  an interactive annotation tool is planned.

The scale bar and north arrow have preset positions (corners) and can be
dragged with the mouse on the page view; the dragged position is stored in the
map (as a fraction of the map frame) and used for export.

### 4.1 Scale bar

The bar length is a nice value (1, 2, 2.5 or 5 × 10ᵏ) close to a quarter of
the map width, in metres or kilometres.

* **Projected CRS in metres**: the bar measures **grid (projected)
  distance**. Ground distance differs by the projection's scale factor (for UTM
  within about ±0.1 % inside the zone); the bar does not correct for this.
* **Projected CRS in other units** (for example US survey feet): the bar is
  labelled in those units.
* **Geographic CRS** (degrees): a degree of longitude has a different length
  at each latitude. The bar is computed on the WGS 84 ellipsoid **at the
  centre latitude of the map** and labelled with that latitude, for example
  "50 km (at 26.00°)". It is only correct near that latitude.
* **No CRS**: the bar is labelled in the dataset's X/Y units.

### 4.2 North arrow and grid convergence

In a projected CRS, grid north (the +Y axis) and true north differ by the grid
convergence. The north arrow points to **true north** at the map centre. The
convergence is computed numerically with PROJ (via pyproj) by projecting a
small step north along the meridian; it does not depend on sign conventions.
For example, in UTM zone 39N at easting 445,000 m (west of the central
meridian 51° E) true north is about 0.24° clockwise (east) of grid north;
east of the central meridian it is anticlockwise. A test checks both signs and
that the convergence is zero on the central meridian. In a geographic CRS the
arrow points straight up.

## 5. Page and layout

* Page sizes: A4, A3, US Letter, Tabloid; landscape or portrait; margins in
  millimetres.
* The map frame keeps equal X and Y scale (a metre is the same length in both
  directions) and is fitted inside the page margins, leaving room for titles
  and the colour bar.
* The page view shows the page at "fit" or 100 % zoom. **Keep View Extent**
  stores the current pan/zoom as the map's fixed extent; **Full Extent**
  returns to the union of the layers' extents.
* Layer order, visibility, removal and properties are edited in the map view
  and the Properties panel. Invalid values (for example a negative contour
  interval, an opacity outside 0–1 or an unknown colour) are rejected with a
  message and leave the map unchanged.

The layout editor in Phase 2 is this page view with property editing and
draggable scale bar and north arrow. A free-form layout editor (multiple map
frames, inset maps, legends for post symbols, logos and text boxes placed
anywhere on the page) is planned.

## 6. Export

`export_map` writes PNG, JPEG, SVG or PDF. The page size is exact (for
example A4 landscape at 300 dpi is 3508 × 2480 pixels, within one pixel of
rounding). Raster resolution is 50–1200 dpi (default 300). SVG and PDF are
vector output (the colour relief layer is embedded as an image). An existing
file is never overwritten unless the user confirms it in the save dialog. Each
export is recorded in the project's outputs and history.

## 7. Planned (not in Phase 2)

Vector, base (image), point-density and raster-layer maps; legends for post
symbols and line layers; free-form layout with several map frames; on-map
annotation and drawing tools; coordinate grids in a second CRS; map templates.

## 8. Validation

`tests/test_mapping.py` and `tests/test_gui_phase2.py` cover level generation,
serialisation, rendering of every layer type, missing-source and empty-range
warnings, north-arrow convergence signs, the geographic scale bar, export in
all four formats with exact pixel size, refusal to overwrite, layer editing,
mouse dragging of the scale bar, and save/reopen of maps in a project.
Visual quality was checked by inspecting rendered maps (see
`docs/screenshots/16_map_layout_relief.png` and `17_map_layout_head.png`).
