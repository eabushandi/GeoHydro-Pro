# Gridding and interpolation (Phase 2)

This document describes how GeoHydro Pro turns scattered point data into a
regular grid: the grid conventions, every interpolation method with its
equations, assumptions and limitations, the quality measures reported, and how
each method was validated. It is the scientific documentation required by
specification sections 7 and 26.

> Grids produced by GeoHydro Pro are computed estimates. They are not
> certified engineering results. The choice of method and parameters, and the
> judgement of whether a surface is fit for a purpose, rest with the user.

Code: `geohydro/engine/gridding/` (grid model, file formats, orchestration,
cross-validation) and `geohydro/engine/interpolation/` (the methods).

## 1. Grid conventions

| Item | Convention |
|---|---|
| Registration | Node-registered: values are at grid nodes. `x_min`/`x_max` are the first and last node, not cell edges. |
| Array layout | `z` has shape `(ny, nx)`; row 0 is the **south** (minimum Y) row, column 0 the west column. |
| Spacing | `dx = (x_max − x_min)/(nx − 1)`, `dy` likewise. Square cells by default. |
| NoData | `NaN` in memory ("blank" nodes). Written as each file format's own blank value. |
| Size limit | 25 million nodes per grid (`MAX_NODES`); Minimum Curvature is limited to 1 million nodes. |
| Units | X/Y in the dataset's horizontal units, Z in its Z units. Distances (search radius, ranges, smoothing) are in X/Y units. |
| CRS | Copied from the source dataset. Gridding is done in the dataset's coordinates, so projected (metric) coordinates should be used for distance-based methods. Gridding geographic (degree) coordinates treats a degree of longitude and of latitude as equal lengths, which is only acceptable over small areas near the equator; the user is responsible for choosing a projected CRS. |

Default geometry: the data extent, with a "nice" spacing (1, 2, 2.5 or 5 × 10ᵏ,
the largest such value not above extent/(n−1)) so the long side has at least
about 100 nodes. The Grid Data dialog lets the user set limits and spacing.

## 2. Data preparation (all methods)

`prepare_points` runs before every method and reports what it did:

* rows with a missing or non-finite X, Y or Z are excluded and counted;
* points closer together than the *coincident-point tolerance* (exact matches
  when 0) are merged into one point at the position of the first, with Z taken
  as the `mean`, `median`, `first`, `min` or `max` of the group. Merging is
  necessary because coincident points with different Z make exact
  interpolators (triangulation, Kriging, RBF) singular. The number of merged
  points is recorded in the grid metadata and shown as a warning.

## 3. Search neighbourhood and anisotropy

Local methods (IDW, Nearest Neighbour, Kriging) use a KD-tree neighbourhood:

* **Search radius** (`None` = unlimited) in X/Y units along the major axis.
* **Maximum neighbours** (`None` = all points).
* **Minimum neighbours**: a node with fewer neighbours is left blank.

**Geometric anisotropy** is described by an angle (direction of the major
axis, degrees counter-clockwise from east, +X) and a ratio (minor range /
major range, 0 < ratio ≤ 1). Coordinates are rotated by −angle so the major
axis lies on X′, then Y′ is divided by the ratio. All distances (search and
weights) are measured in this transformed frame. For Kriging the anisotropy
belongs to the variogram model.

## 4. Methods

Each method below lists its equations, parameters, whether it honours the data
exactly, its assumptions and limitations, and how it is tested
(`tests/test_interpolation.py`, `tests/test_gridding.py`).

### 4.1 Inverse Distance Weighting (IDW)

Shepard (1968):

    z*(x0) = Σ wᵢ zᵢ / Σ wᵢ,   wᵢ = 1 / (dᵢ² + s²)^(p/2)

`p` = power (default 2), `s` = smoothing distance (default 0). With `s = 0`
the method is exact: a node that coincides with a data point takes its value.

* Assumptions: nearby points are more similar than distant ones; no
  statistical model.
* Limitations: produces "bull's-eyes" around data points; estimates never
  exceed the data range (no extrapolation of trends); flat spots at data
  points; results depend strongly on power and neighbourhood.
* Tests: exactness at data points, weights reproduce a constant, smoothing
  removes exactness, anisotropy changes the neighbourhood as expected,
  accuracy on the synthetic terrain.

### 4.2 Nearest Neighbour

Each node takes the Z of the closest data point (in the anisotropic frame).
Nodes with no point inside the search radius are blank. Useful for
categorical or already-gridded data; produces a stepped (Voronoi) surface.

### 4.3 Linear Triangulation (TIN)

Delaunay triangulation of the data (SciPy/Qhull); each node inside the convex
hull is interpolated linearly within its triangle (barycentric weights).
Exact; reproduces planes exactly; nodes outside the convex hull are blank.
Limitations: surface has slope discontinuities across triangle edges; long
thin triangles at the hull edge give poor estimates.

### 4.4 Natural Neighbour (Sibson)

Sibson (1981). For a node q, insert q into the Voronoi diagram of the data;
the weight of point pᵢ is the area q's new cell "steals" from pᵢ's cell,
divided by the area of q's new cell: `z(q) = Σ (Aᵢ/A) zᵢ`.

Implementation: an exact geometric construction, not a raster approximation.
The Delaunay triangles whose circumcircles contain q form the Bowyer–Watson
cavity; the stolen region for each natural neighbour is the convex polygon
formed by the circumcentres of the new triangles at that neighbour and of the
old cavity triangles that share it (Watson 1992; Sambridge et al. 1995).

* Properties verified by tests: exact at data points, linear precision
  (planes are reproduced exactly inside the hull), weights non-negative and
  summing to 1.
* Nodes outside the convex hull are blank; nodes on the hull boundary take
  linear interpolation along that edge (the limit of Sibson's interpolant).
* Performance: about 2–3 s per 10,000 nodes on the development machine;
  the dialog warns above 250,000 nodes.

### 4.5 Radial Basis Functions (RBF)

Uses SciPy's `RBFInterpolator`:

    s(x) = Σ wᵢ φ(‖x − xᵢ‖) + P(x)

with a low-degree polynomial `P` (degree chosen by SciPy per kernel). Kernels:
thin-plate spline, multiquadric, inverse multiquadric, inverse quadratic,
Gaussian, linear, cubic, quintic. `smoothing = 0` interpolates exactly;
`smoothing > 0` gives a least-squares approximation.

* Shape parameter ε (multiquadric, inverse kernels, Gaussian): when left
  blank it is set to 1 / (mean nearest-neighbour spacing) and the value used is
  recorded in the grid metadata.
* **Neighbours**: limits each estimate to the nearest k points (local RBF).
  Global RBF (all points) solves an n × n dense system, O(n³): practical up to
  a few thousand points.
* Limitations: can overshoot and oscillate between widely spaced data,
  especially with Gaussian kernels; results depend on ε.

### 4.6 Minimum Curvature

Briggs (1974), with tension after Smith & Wessel (1990). The grid surface z
minimises

    E(z) = (1 − T) Σ [z_xx² + 2 z_xy² + z_yy²]     (total squared curvature)
         +      T  Σ [z_x² + z_y²]                (tension / membrane term)
         +      W  Σₖ [Bₖ z − dₖ]²                (fit to the data)

with finite differences in grid-index units (so T does not depend on the
coordinate units; rectangular cells are handled through dy/dx). `Bₖ z` is the
bilinear interpolation of the grid at data point k, so data need not lie on
nodes. Away from the data the stationarity condition is the tensioned
biharmonic equation `(1 − T)∇⁴z − T∇²z = 0`.

* **Boundary conditions**: grid edges are free (the natural boundary
  conditions of the energy above). No edge values are imposed.
* **Trend**: a least-squares plane is removed from the data first and added
  back afterwards, as GMT `surface` does. Planes are therefore reproduced
  exactly.
* **Tension** `T` (0–1, default 0): 0 gives the pure minimum-curvature
  (thin-plate) surface, which can overshoot between data; larger values
  reduce overshoot.
* **Fit weight** `W` = `fit_weight` × the mean diagonal of the curvature
  operator (default `fit_weight` = 10⁴), so data are honoured closely but not
  necessarily exactly. When several points fall in one cell they are fitted in
  the least-squares sense.
* Solver: the sparse linear system is solved directly (SciPy `spsolve`); a
  relative ridge of 10⁻⁹ guarantees solvability. Limit: 1 million nodes.
* Known behaviour (documented, not hidden): with tension and sparse data, the
  surface between distant data relaxes towards the fitted plane rather than
  passing smoothly between data values ("sag"). With dense data, tension
  reduces overshoot as intended (a test verifies tension 0.5 roughly halves
  the overshoot of a step).
* Differences from Surfer/GMT: those programs use iterative relaxation with
  convergence limits; this implementation solves the same discrete
  minimisation directly. Results will be close but not identical.

### 4.7 Ordinary Kriging (OK)

Point kriging with an unknown constant mean, solved in variogram form (which
also admits the unbounded linear and power models). For a node x0 with
neighbours x₁…x_k:

    | Γ   1 | |λ|   |γ0|        z*(x0) = Σ λᵢ zᵢ
    | 1ᵀ  0 | |μ| = | 1|        σ²(x0) = Σ λᵢ γ(xᵢ − x0) + μ

Γᵢⱼ = γ(xᵢ − xⱼ), γ0ᵢ = γ(xᵢ − x0).

### 4.8 Universal Kriging (UK)

As OK, but the mean is a polynomial drift `m(x) = Σ aₗ fₗ(x)`:

    | Γ   F | |λ|   |γ0|        z*(x0) = Σ λᵢ zᵢ
    | Fᵀ  0 | |μ| = |f0|        σ²(x0) = λᵀγ0 + μᵀf0

Drift: `linear` (1, x, y) or `quadratic` (1, x, y, x², xy, y²), evaluated in
coordinates centred on the node and scaled by the neighbourhood size (this
improves conditioning; it does not change the result).

### 4.9 Kriging: common notes

* Both are genuine geostatistical kriging. The word "Kriging" is used only for
  these two methods.
* Kriging honours the data exactly (γ(0) = 0 at data locations, also with a
  nugget).
* **Kriging variance** σ² can be written as a second grid. It depends on the
  variogram model and the data configuration, not on the data values, and is
  only as meaningful as the variogram model.
* Neighbourhood: default 32 nearest points; global kriging (all points) is
  limited to 1,500 points. Systems are solved in batches with
  `numpy.linalg.solve`. A node whose local system is singular is left blank and the
  number of such nodes is reported as a warning.
* **Validation against an independent implementation**: OK and UK estimates and
  variances are compared with PyKrige 1.7.3 for spherical, exponential and linear models
  with a global neighbourhood (test tolerance 10⁻⁹ for OK and 10⁻⁸ for UK; measured
  agreement about 10⁻¹³ and 10⁻¹⁰). PyKrige has no moving-neighbourhood option, so
  local-search kriging is checked through its properties (exactness, zero variance at data,
  variance approaching the sill far from data, local = global when the neighbourhood holds
  all points). The test is skipped where PyKrige is not installed; CI installs it.

## 5. Variograms

Experimental semivariogram (Matheron's estimator):

    γ(h) = 1 / (2 N(h)) Σ [z(xᵢ) − z(xᵢ + h)]²

* Lag classes (default 15) up to a maximum lag (default half the data
  bounding-box diagonal).
* Directional variograms: pairs whose separation azimuth lies within ±tolerance
  of the direction (modulo 180°).
* Above 3,000 points a reproducible random subsample (fixed seed) is used, and
  the result says so.

Models (`a` = range, `c` = partial sill, `c0` = nugget; γ(0) = 0):

| Model | γ(h), h > 0 | Meaning of range |
|---|---|---|
| Spherical | c0 + c[1.5h/a − 0.5(h/a)³] for h < a; c0 + c beyond | actual range |
| Exponential | c0 + c[1 − exp(−3h/a)] | practical range (95 % of sill) |
| Gaussian | c0 + c[1 − exp(−3h²/a²)] | practical range (95 % of sill) |
| Linear | c0 + s·h (slope s) | – |
| Power | c0 + s·h^ω, 0 < ω < 2 | – |
| Nugget | c0 | – |

**Fitting**: weighted least squares with Cressie's (1985) weights
`N(h)/γ_model(h)²`, iterated from ordinary least-squares start values, with
bounds that keep every parameter physically valid. When a fitted parameter
reaches a bound (for example a range at the upper limit because the variogram
never levels off), a warning is shown. Automatic fitting is a convenience: the
variogram should always be inspected.

**Trend**: when the data have a strong regional trend (for example a
hydraulic gradient), a variogram of the raw values keeps rising and the fit
reaches its range bound. Use Universal Kriging with a drift, with a variogram
fitted to the detrended data. The sample project's groundwater-head grid shows
this approach.

## 6. Blanking

After interpolation, nodes can be blanked (set to NoData):

* outside the convex hull of the data;
* farther than a given distance from the nearest data point.

The number of blanked nodes is recorded. Triangulation and Natural Neighbour
always leave nodes outside the hull blank.

## 7. Quality measures

### 7.1 Residuals at the data points

After gridding, the grid is sampled at each data point by **bilinear
interpolation** and compared with the observation:

    residual = observed − grid

Reported: number of points compared (points outside the grid or on blank
cells are counted but excluded), mean error, mean absolute error, RMSE and
maximum absolute residual. For an exact method the residuals are not zero:
they measure how well the *grid* (at its spacing, with bilinear sampling)
represents the data. They shrink as the spacing is reduced.

### 7.2 Leave-one-out cross-validation

Each validation point is removed, re-estimated from the remaining points with
the same method and parameters, and compared with its observed value:

    error = estimate − observed

| Metric | Definition |
|---|---|
| ME (bias) | mean(error) |
| MAE | mean(|error|) |
| RMSE | √mean(error²) |
| Max abs. error | max(|error|) |
| R² | 1 − SSE/SST, with SST about the mean of the observations (can be negative) |
| Pearson r | correlation of estimates and observations |
| Kriging only: MSE_std | mean(error/σ) — should be near 0 |
| Kriging only: MSSE | mean((error/σ)²) — should be near 1; far above 1 means the variogram understates the uncertainty |

With more points than the chosen maximum (default 500), a random subsample
with a fixed seed is validated and the result says so. For Minimum Curvature
(a grid-only method) each re-estimate grids the data and samples the grid
bilinearly, so its errors include the grid-resolution effect.

Note the sign conventions: residuals are observed − grid, cross-validation
errors are estimate − observed. Both are stated in the interface.

## 8. Reproducibility and provenance

Every grid stores in its metadata: method and title, all parameters as
requested and as used (including automatically chosen values such as RBF ε),
data preparation (excluded and merged points), blanking, residuals, solver
details, elapsed time, software version, creation time and any warnings. The
project history logs the creation. Cross-validation results, when run from the
dialog for the same method, are stored with the grid.

## 9. Validation results on the synthetic terrain

`samples/generate_samples.py` creates a terrain survey of 300 points from a
known analytic surface, so gridded results can be compared with the truth.
`tools/validate_gridding.py` reproduces the table below: a 41 × 41 grid at
200 m spacing over the interior of the survey, default parameters, a Gaussian
variogram fitted automatically (sill 42.5, practical range 4,364 m, nugget
0.0025), and leave-one-out cross-validation of all 300 points.

| Method | RMSE vs. true surface | CV RMSE | CV R² | MSSE |
|---|---|---|---|---|
| IDW (power 2, 64 neighbours) | 1.342 | 1.243 | 0.936 | – |
| Nearest Neighbour | 1.437 | 1.010 | 0.958 | – |
| Linear Triangulation | 0.538 | 0.473 | 0.991 | – |
| Natural Neighbour | 0.506 | 0.461 | 0.991 | – |
| RBF (thin-plate spline) | 0.165 | 0.228 | 0.998 | – |
| Minimum Curvature (T = 0) | 0.298 | 0.298 | 0.997 | – |
| Ordinary Kriging | 0.118 | 0.210 | 0.998 | 8.72 |
| Universal Kriging (linear drift) | 0.118 | 0.211 | 0.998 | 8.66 |

Elevations span about 4–30 m. These numbers show the methods behave as
expected on smooth data; they are not a general ranking. Note the MSSE of
about 8.7: on this smooth synthetic surface the fitted Gaussian model has a
very small nugget, and its kriging variance understates the actual errors by a
factor of about 3 in standard deviation. Kriging variances should not be read
as reliable uncertainties without checking MSSE. This is reported, not hidden.
The accuracy test (`test_accuracy_against_known_sample_surface`) guards these
results with regression limits.

## 10. Grid files

See `geohydro/engine/gridding/io.py`.

| Format | Read | Write | Notes |
|---|---|---|---|
| Surfer 6 text (`DSAA`, `.grd`) | yes | yes | blank value 1.70141e38 |
| Surfer 6 binary (`DSBB`, `.grd`) | yes | yes | float32 values |
| Surfer 7 binary (`DSRB`, `.grd`) | yes | yes | float64 values |
| ESRI ASCII (`.asc`) | yes | yes | cell-registered; written with `xllcenter` so there is no half-cell shift; needs square cells |
| XYZ node table (`.csv`, `.xyz`) | – | yes | one row per node |

The Surfer layouts follow Golden Software's published format descriptions and
are covered by round-trip tests here. **They have not yet been checked against
files written by Surfer itself**; that check is open. Grid files carry no CRS,
so an imported grid takes the project default CRS and a warning says so.
Writing never overwrites an existing file unless the user confirms it in the
save dialog.

## 11. Planned (not in Phase 2)

Grid math and calculus (slope, aspect, volumes, residual grids between
surfaces), cokriging, kriging with external drift, block kriging, faults and
breaklines in gridding, and gridding of very large datasets out of core.

## References

* Briggs, I. C. (1974). Machine contouring using minimum curvature. *Geophysics* 39(1), 39–48.
* Cressie, N. (1985). Fitting variogram models by weighted least squares. *Mathematical Geology* 17(5), 563–586.
* Isaaks, E. H. & Srivastava, R. M. (1989). *An Introduction to Applied Geostatistics*. Oxford University Press.
* Matheron, G. (1963). Principles of geostatistics. *Economic Geology* 58, 1246–1266.
* Sambridge, M., Braun, J. & McQueen, H. (1995). Geophysical parametrization and interpolation of irregular data using natural neighbours. *Geophys. J. Int.* 122, 837–857.
* Shepard, D. (1968). A two-dimensional interpolation function for irregularly-spaced data. *Proc. 23rd ACM National Conference*, 517–524.
* Sibson, R. (1981). A brief description of natural neighbour interpolation. In *Interpreting Multivariate Data*, Wiley, 21–36.
* Smith, W. H. F. & Wessel, P. (1990). Gridding with continuous curvature splines in tension. *Geophysics* 55(3), 293–305.
* Watson, D. F. (1992). *Contouring: A Guide to the Analysis and Display of Spatial Data*. Pergamon.
