# Grid mathematics, terrain analysis, volumes and point density (Phase 3)

This document states what each Phase 3 grid operation computes, the
equations, the assumptions and limits, and how each one was validated. The
code is in `geohydro/engine/gridmath/` (the module docstrings repeat these
equations next to the code). Results are computed as stated; they are **not
certified engineering results**, and no result in GeoHydro Pro should be used
for design without independent checking by a qualified engineer.

General rules that apply to every operation:

* Every operation returns a **new grid**; inputs are never modified. The
  method, parameters, source grids and warnings are stored in the new grid's
  metadata and in the project's processing history.
* Blank nodes (NaN) are never filled silently. Where an operation cannot
  produce a value (a blank input, a 3×3 window crossing a blank, a division
  by zero) the result node is blank and the number of such nodes is reported
  as a warning.
* Grids are node registered (see `docs/GRIDDING.md` §1): `z[j, i]` is the
  value at `x_min + i·Δx`, `y_min + j·Δy`, and row 0 is the southern row.
* Operations that combine grids require the same CRS (or none on both) and
  refuse otherwise.

## 1. Grid calculator

Evaluates an expression node by node. Variables `A`, `B`, `C`, `D` name the
input grids.

| Element | Allowed |
|---|---|
| Arithmetic | `+ − * / **` (power), unary `−` |
| Comparison | `< <= > >= == !=` (result 1 or 0) |
| Logic | `&` (and), `\|` (or), applied to comparison results |
| Functions | `abs sqrt exp log (ln) log10 sin cos tan asin acos atan atan2 sinh cosh tanh floor ceil round degrees radians min max minimum maximum clip where isblank fillblank` (`min`/`max` ignore a blank operand; `minimum`/`maximum` propagate it) |
| Constants | `pi e nan blank` |

* The expression is parsed into a syntax tree and only the elements above are
  evaluated. Python's `eval` is not used, so an expression cannot run code or
  read files (tested).
* The result has the geometry of grid `A`. Other grids with a different
  geometry are **resampled** to it (bilinear by default, or nearest) and a
  warning names each resampled grid.
* A blank in any input gives a blank result (NaN arithmetic), except in
  `isblank(A)`, `fillblank(A, value)`, and `min`/`max`, which return the
  other operand when one is blank.
* Infinite or undefined results (division by zero, `log` of a non-positive
  number, `sqrt` of a negative number) are blanked and counted in the
  warnings. They are never replaced by a number.

### Resampling

* **bilinear**: from the four surrounding nodes; blank if any of the four is
  blank.
* **nearest**: the closest node.
* Nodes outside the source grid are blank. Nothing is extrapolated.

## 2. Filters (moving window)

Each output node is computed from a `size × size` window centred on it
(`size` odd, at least 3).

| Filter | Value |
|---|---|
| mean | arithmetic mean of the valid nodes in the window (low-pass) |
| median | median of the valid nodes |
| minimum, maximum, range | min, max, max − min |
| std | standard deviation with n − 1 |
| highpass | z − mean (local anomaly) |
| gaussian | normalised Gaussian-weighted mean, σ in XY units, kernel truncated at 4σ |

* Blank nodes are ignored. At the grid edge the window is truncated to the
  part inside the grid.
* A node that is blank in the input stays blank; filters never fill gaps.
* `min_valid` (default 1) is the number of valid nodes a window needs. Nodes
  with fewer valid nodes in their window are blanked and counted.
* `passes` (1 to 20) applies the filter repeatedly.

## 3. Terrain derivatives

Notation (row index increases northwards):

```
nw  n  ne
w   c  e       Δx, Δy: node spacing in metres
sw  s  se
```

### 3.1 Slope, aspect and hillshade (Horn 1981)

```
p = ∂z/∂x = [(ne + 2e + se) − (nw + 2w + sw)] / (8 Δx)
q = ∂z/∂y = [(nw + 2n + ne) − (sw + 2s + se)] / (8 Δy)

slope      S = arctan √(p² + q²)          degrees, or percent = 100·tan S
aspect     A = atan2(−p, −q) in [0°, 360°)   direction of steepest descent,
                                             clockwise from grid north
hillshade  H = 255 · max(0, cos Z·cos S + sin Z·sin S·cos(Az − A))
           Z = 90° − sun altitude, Az = sun azimuth
```

This is the Horn (1981) estimator used by GDAL `gdaldem`, ArcGIS and QGIS.
The Z factor multiplies elevations before `S` and `A` are computed.

### 3.2 Curvature (Zevenbergen and Thorne 1987)

```
zx  = (e − w) / (2Δx)          zy  = (n − s) / (2Δy)
zxx = (e − 2c + w) / Δx²       zyy = (n − 2c + s) / Δy²
zxy = (ne − nw − se + sw) / (4 Δx Δy)

total (Laplacian)  K  = zxx + zyy
profile            Kp = (zxx zx² + 2 zxy zx zy + zyy zy²) / (zx² + zy²)
plan               Kc = (zxx zy² − 2 zxy zx zy + zyy zx²) / (zx² + zy²)
```

* Units: 1/m.
* Kp > 0 means a concave profile (the slope flattens downhill).
* Kc > 0 means concave contours (converging flow).
* Kp and Kc are second derivatives of elevation along and across the
  gradient, and are blank where the surface is flat.
* They equal the normal-section curvatures multiplied by (1 + tan²S)^{3/2}
  (exactly for Kp, approximately for Kc). Below 10° slope the difference is
  under 5 %. This convention is stated because packages differ: some report
  the normal-section curvature, some multiply by −100.

### 3.3 Assumptions and limits

* Edge nodes, and nodes with a blank neighbour, are blank: the 3×3 window must
  be complete. This matches `gdaldem` without `-compute_edges`.
* XY and Z are converted to metres from the grid's units. A grid whose Z unit
  is not a length (for example mg/L) is refused, because its slope has no
  physical meaning.
* For geographic grids (degrees), the node spacing is converted to metres row
  by row on the WGS 84 ellipsoid:
  * `Δx = Δλ·N(φ)·cos φ`
  * `Δy = Δφ·M(φ)`
  * `M` and `N` are the meridional and prime-vertical radii of curvature.

  This is more accurate than `gdaldem`'s single scale factor. Grids that reach
  beyond 85° latitude are refused.
* On projected grids, aspect is relative to **grid north**. It differs from
  true north by the meridian convergence, within ±3° inside a UTM zone. The
  correction is not applied, and this is documented rather than hidden.

### 3.4 Profiles

A profile samples a grid along a polyline (typed vertices or one feature of a
line layer, reprojected to the grid CRS):

* Samples are taken every `spacing` along the line (default: half the smaller
  node spacing), plus every vertex.
* Values come from bilinear interpolation. A sample is blank outside the grid
  or where a contributing node is blank.
* Distances are planar on projected grids and geodesic (WGS 84) on geographic
  grids.

The profile dialog can export distance, x, y and z to CSV.

## 4. Volumes and areas

With `d = upper − lower` at each node, where the lower surface is a constant
level (in the upper grid's Z unit) or a second grid resampled to the upper
grid:

```
net volume            V  = ∬ d dA
cut (positive)        V⁺ = ∬ max(d, 0) dA      upper above lower
fill (negative)       V⁻ = ∬ max(−d, 0) dA     upper below lower
                      V  = V⁺ − V⁻  (checked and reported)
```

Integration uses tensor products of 1-D rules along X and Y:

| Rule | 1-D weights | Exact for | Error |
|---|---|---|---|
| trapezoidal | h/2·(1, 2, …, 2, 1) | bilinear surfaces | O(h²) |
| simpson | h/3·(1, 4, 2, 4, …, 4, 1) | cubics in each direction | O(h⁴) |
| simpson38 | 3h/8·(1, 3, 3, 2, …, 3, 3, 1) | cubics in each direction | O(h⁴) |

End-panel handling:

* **simpson**: with an odd number of intervals, the last three intervals use
  the 3/8 rule (still exact for cubics).
* **simpson38**: when the number of intervals is not a multiple of three, the
  remainder uses a 1/3 panel (two intervals) or a trapezoidal panel (one
  interval). In the one-interval case the result is no longer exact for
  quadratics (see the validation table). **Simpson 1/3 is the recommended
  default for smooth surfaces.**

Further notes:

* **Cut/fill split.** `V⁺` and `V⁻` apply the same rule to the clipped
  integrands, as Surfer does. Where `d` changes sign between two nodes, the
  clipped integrand has a kink. `V⁺` and `V⁻` then carry an additional error
  of order h² along the zero line, whatever the rule. `V` is unaffected. The
  number of cells that contain the zero line is reported.
* **Blank nodes.** Simpson rules need a complete grid and refuse otherwise.
  The trapezoidal rule works cell by cell (cell area × mean of its four
  corners) over cells whose four corners are valid. On a complete grid this
  equals the tensor-product rule exactly. Excluded cells are counted.
* **Areas.**
  * Planar area is the area of the included cells.
  * Surface area is the sum of the 3-D areas of the two triangles in each
    cell (diagonal SW–NE).
  * Cut and fill areas are split per cell in proportion to the corners above
    or below. They are an estimate and are labelled as one.
* **Units.** Volumes are in m³ and areas in m². Lengths in other units are
  converted. On geographic grids each row uses its WGS 84 cell area.

## 5. Blanking and clipping

* **Blank with polygons.** Blanks nodes inside, or outside, the union of the
  polygons of a vector layer.
  * A node on a polygon boundary counts as inside (GEOS `intersects`), and
    holes are respected.
  * The layer is reprojected to the grid CRS when the two differ.
  * If only one of the two has a CRS, the operation is refused rather than
    guessed.
* **Clip to rectangle.** Keeps the nodes inside `[x0, x1] × [y0, y1]`. Values
  are unchanged.

## 6. Point density

### 6.1 Kernel density

For points `xᵢ` with weights `wᵢ` (default 1) and bandwidth `h`:

```
λ(x) = Σᵢ wᵢ · K_h(‖x − xᵢ‖)
```

`K_h` is a radially symmetric kernel that integrates to 1 over the plane, so
`λ` is an **intensity**: the expected number of points (or sum of weights)
per unit area. With "probability", `λ` is divided by `Σ wᵢ`.

| Kernel | K_h(r), r < h unless stated |
|---|---|
| uniform | 1 / (π h²) |
| triangular (cone) | 3 / (π h²) · (1 − r/h) |
| epanechnikov | 2 / (π h²) · (1 − r²/h²) |
| quartic (biweight, as ArcGIS/QGIS) | 3 / (π h²) · (1 − r²/h²)² |
| gaussian | 1 / (2π h²) · exp(−r² / 2h²), h = σ, evaluated to r = 5h |

Bandwidth rules, used only when no bandwidth is typed:

* **scott**: `h = σ̄ · n^(−1/6)`, with `σ̄ = √((σx² + σy²)/2)`. This is
  Scott (1992), which equals Silverman's rule in 2-D.
* **standard_distance**: `h = 0.9 · min(SD, √(1/ln 2)·Dm) · n^(−0.2)`. SD is
  the standard distance and Dm the median distance to the mean centre. This
  is the rule documented for ArcGIS Kernel Density.

Both are data-driven **starting points, not optimal values**. The chosen
bandwidth is stored with the result.

Assumptions and limits:

* Distances are planar in the grid CRS. **Geographic coordinates are refused**
  (a bandwidth in degrees is not a distance). Reproject the points first.
* **No edge correction.** Within about one bandwidth of the edge of the study
  area, density is underestimated because part of each kernel falls outside.
  This is stated as a warning on every result.
* The Gaussian kernel omits exp(−12.5) ≈ 3.7·10⁻⁶ of each kernel's mass
  beyond 5σ (documented truncation).
* A bandwidth smaller than the grid spacing gives a spiky surface. A warning
  says so.
* "Report per km²" multiplies by 10⁶ when coordinates are in metres. The unit
  label says which applies.

### 6.2 Point count

Counts the points (or sums their weights) in the Δx × Δy cell centred on each
node. A point exactly on a cell boundary belongs to the cell to its
north-east.

## 7. Validation

Each of these comparisons is an automated test in `tests/` and runs in CI, except where
noted.
The reference data are synthetic, so they test the implementation, not the
suitability of a method for a particular site.

| Operation | Reference | Result | Test |
|---|---|---|---|
| Slope | GDAL 3.8.4 `gdaldem slope`, 61 × 41 synthetic DEM (`tests/fixtures/gdaldem`) | max abs. diff 3.1·10⁻⁵° (float32 output of gdaldem); identical blank nodes | `test_slope_matches_gdaldem` |
| Aspect | `gdaldem aspect` | max abs. diff 0.0022°; identical blank nodes | `test_aspect_matches_gdaldem` |
| Hillshade | `gdaldem hillshade` (315°/45°; 120°/30°, z = 2) | ≤ 0.51 of 255 after mapping gdaldem's byte scale (1 + 254·cos i) to 0–255, i.e. byte rounding | `test_hillshade_matches_gdaldem` |
| Slope, aspect | analytic planes in 6 directions | exact | `test_plane_slope_aspect_analytic` |
| Slope (geographic) | ellipsoidal metric spacing | as derived in §3.3 | `test_geographic_slope_uses_ellipsoid` |
| Curvature | paraboloid z = ax² + by² | exact (second differences of a quadratic) | `test_curvature_paraboloid_exact` |
| Volume, trapezoidal | ∬(x² + y²) over unit square, h = 0.1 | equals the analytic trapezoidal value 2(1/3 + h²/6) to 10⁻¹² | `test_volume_rules_on_paraboloid` |
| Volume, Simpson | same, and ∬ x³y over [0,2]×[0,1] with 9 intervals | exact (error ≤ 10⁻¹⁵) | `test_volume_rules_on_paraboloid` |
| Volume, Simpson 3/8 | paraboloid with 10, 20, 40 intervals | errors 3.3·10⁻⁴, 2·10⁻¹⁶, 5.2·10⁻⁶ (one-interval trapezoidal end panel when not a multiple of 3) | measured; see §4 |
| Cut/fill | inclined plane, zero line on a node column | cut = fill = 0.125 exactly | `test_cut_fill_plane_and_lower_grid` |
| Units and blanks | Z in feet, a blank node | 1000 m³ exactly; 4 cells excluded | `test_volume_units_blanks_and_surface_area` |
| Geographic cell areas | PROJ geodesic polygon area | within 10⁻⁴ | `test_volume_geographic_cell_areas` |
| Kernel density | scikit-learn `KernelDensity` (epanechnikov, tophat, linear, gaussian), 300 points | max relative diff 7·10⁻¹⁵ (compact kernels), 1.1·10⁻⁶ (Gaussian, 5σ truncation) | `test_matches_scikit_learn` |
| Kernel normalisation | numerical radial integral of each kernel | 1 within 10⁻⁵ (uniform: 10⁻⁴, discontinuous edge) | `test_kernels_integrate_to_one` |
| Mean filter | SciPy `uniform_filter` in the interior | equal to round-off | `test_mean_filter_matches_uniform_filter_in_interior` |
| Raster import | GDAL's own ESRI ASCII → GeoTIFF conversion of a grid written by GeoHydro Pro | identical geometry and values | `test_matches_gdal_conversion_of_esri_ascii` (runs only where the GDAL command-line tools are installed; passed in the development environment, skipped on CI runners) |

The gdaldem reference files were generated with GDAL 3.8.4. They are not
regenerated by CI.

## 8. Not included in Phase 3

The following are not implemented and are not offered in the program:

* Hydrological conditioning (sink filling), flow direction, accumulation and
  watersheds. These are Phase 4.
* Curvature conventions other than the one stated in §3.2.
* Edge-corrected kernel density.
* True-north aspect correction on projected grids.

## References

* Horn, B. K. P. (1981). Hill shading and the reflectance map. *Proc. IEEE* 69(1), 14–47.
* Zevenbergen, L. W., Thorne, C. R. (1987). Quantitative analysis of land surface topography. *Earth Surface Processes and Landforms* 12, 47–56.
* Scott, D. W. (1992). *Multivariate Density Estimation*. Wiley.
* Silverman, B. W. (1986). *Density Estimation for Statistics and Data Analysis*. Chapman & Hall.
* Karney, C. F. F. (2013). Algorithms for geodesics. *J. Geodesy* 87, 43–55.
* GDAL `gdaldem` documentation: https://gdal.org/programs/gdaldem.html
