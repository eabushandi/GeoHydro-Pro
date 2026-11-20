# Test results

## Phase 3 (v0.3.0) — local run

Run: 2026-11-20, Linux (Ubuntu 24.04, x86-64), Python 3.13.18, Qt offscreen platform.
NumPy 2.5.5, pandas 3.1.1, SciPy 1.18.1, Matplotlib 3.11.2, PySide6 6.8.1, PyProj 3.8.0,
rasterio 1.5.2 (GDAL 3.12.2), pyogrio 0.13.0, shapely 2.2.0. Reference libraries for
comparison tests: PyKrige 1.7.3, scikit-learn 1.9.1, GDAL 3.8.4 command-line tools.

**Result: 318 passed in 61.5 s** (0 failed, 0 skipped). All 179 Phase 1 and 2 tests are
still present and pass; none was removed or weakened. Three existing tests were adapted to
Phase 3 facts: the explorer test (Raster Images and Vector Layers are no longer "planned"),
the capability-registry honesty test (Phase 3 items implemented, hydrology still planned),
and the reader tests (they skip the new `samples/data/gis/` folder).

| Test file | Tests | Passed | Note |
|---|---|---|---|
| `tests/test_density.py` | 15 | 15 | new |
| `tests/test_gridding.py` | 22 | 22 | |
| `tests/test_gridmath.py` | 40 | 40 | new |
| `tests/test_gui.py` | 16 | 16 | |
| `tests/test_gui_phase2.py` | 16 | 16 | |
| `tests/test_gui_phase3.py` | 18 | 18 | new |
| `tests/test_importer.py` | 9 | 9 | |
| `tests/test_interpolation.py` | 37 | 37 | |
| `tests/test_mapping.py` | 11 | 11 | |
| `tests/test_mapping_gis.py` | 9 | 9 | new |
| `tests/test_project_storage.py` | 24 | 24 | +4 (vectors, images, v2 → v3 migration) |
| `tests/test_qc.py` | 18 | 18 | |
| `tests/test_raster.py` | 17 | 17 | new |
| `tests/test_readers.py` | 21 | 21 | |
| `tests/test_statistics_crs_units.py` | 9 | 9 | |
| `tests/test_undo.py` | 12 | 12 | new |
| `tests/test_vector.py` | 24 | 24 | new |
| **Total** | **318** | **318** | |

Locally `test_matches_gdal_conversion_of_esri_ascii` ran against GDAL's `gdal_translate`.
CI runners have no GDAL command-line tools, so that one test is skipped there.

### Phase 3 numerical validation

See `docs/GRID_MATH.md` §7 and `docs/GIS.md` §1.2 and §2.2 for the full tables.

* Slope, aspect, hillshade against `gdaldem` (GDAL 3.8.4 fixtures, 61 × 41 DEM): max abs.
  difference 3.1·10⁻⁵°, 0.0022°, ≤ 0.51 of 255.
* Kernel density against scikit-learn `KernelDensity`: max relative difference 7·10⁻¹⁵
  (compact kernels), 1.1·10⁻⁶ (Gaussian, 5σ truncation).
* Volumes: trapezoidal and Simpson rules against analytic integrals (exact to 10⁻¹²–10⁻¹⁵);
  cut/fill on an inclined plane exact.
* Geodesic line length on the equator: relative error < 10⁻¹²; geodesic area against an
  ellipsoidal equal-area projection: < 10⁻⁶.
* Mean filter against SciPy `uniform_filter`: equal to round-off in the interior.

### Phase 3 individual tests (new files and new storage tests)

```
tests/test_density.py::test_matches_scikit_learn[gaussian-gaussian-1e-05] PASSED
tests/test_density.py::test_matches_scikit_learn[epanechnikov-epanechnikov-1e-12] PASSED
tests/test_density.py::test_matches_scikit_learn[uniform-tophat-1e-12] PASSED
tests/test_density.py::test_matches_scikit_learn[triangular-linear-1e-12] PASSED
tests/test_density.py::test_kernels_integrate_to_one[quartic] PASSED
tests/test_density.py::test_kernels_integrate_to_one[epanechnikov] PASSED
tests/test_density.py::test_kernels_integrate_to_one[triangular] PASSED
tests/test_density.py::test_kernels_integrate_to_one[uniform] PASSED
tests/test_density.py::test_kernels_integrate_to_one[gaussian] PASSED
tests/test_density.py::test_quartic_peak_and_integral PASSED
tests/test_density.py::test_weights_probability_and_units PASSED
tests/test_density.py::test_bandwidth_rules PASSED
tests/test_density.py::test_geographic_refused_and_bad_points PASSED
tests/test_density.py::test_point_count PASSED
tests/test_density.py::test_vector_points_to_point_dataset PASSED
tests/test_gridmath.py::test_calculator_arithmetic_and_provenance PASSED
tests/test_gridmath.py::test_calculator_blanks_and_undefined_results_are_reported PASSED
tests/test_gridmath.py::test_calculator_conditionals_and_functions PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[__import__('os').system('x')] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[A.__class__] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[open('f')] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[[A PASSED
for PASSED
A PASSED
in PASSED
B]] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[lambda: PASSED
1] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[A PASSED
if PASSED
B PASSED
else PASSED
C] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions['text'] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[D[0]] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[exec('1')] PASSED
tests/test_gridmath.py::test_calculator_rejects_unsafe_expressions[abs(x=A)] PASSED
tests/test_gridmath.py::test_calculator_resamples_and_checks_crs PASSED
tests/test_gridmath.py::test_resample_nearest_and_outside PASSED
tests/test_gridmath.py::test_mean_filter_matches_uniform_filter_in_interior PASSED
tests/test_gridmath.py::test_filters_on_plane_spike_and_blanks PASSED
tests/test_gridmath.py::test_gaussian_filter_normalised_and_errors PASSED
tests/test_gridmath.py::test_slope_matches_gdaldem PASSED
tests/test_gridmath.py::test_aspect_matches_gdaldem PASSED
tests/test_gridmath.py::test_hillshade_matches_gdaldem[hillshade_315_45.tif-315-45-1] PASSED
tests/test_gridmath.py::test_hillshade_matches_gdaldem[hillshade_120_30_z2.tif-120-30-2] PASSED
tests/test_gridmath.py::test_plane_slope_aspect_analytic[1-0-270] PASSED
tests/test_gridmath.py::test_plane_slope_aspect_analytic[-1-0-90] PASSED
tests/test_gridmath.py::test_plane_slope_aspect_analytic[0-1-180] PASSED
tests/test_gridmath.py::test_plane_slope_aspect_analytic[0--1-0] PASSED
tests/test_gridmath.py::test_plane_slope_aspect_analytic[1-1-225] PASSED
tests/test_gridmath.py::test_plane_slope_aspect_analytic[-1--1-45] PASSED
tests/test_gridmath.py::test_flat_aspect_blank_and_units PASSED
tests/test_gridmath.py::test_geographic_slope_uses_ellipsoid PASSED
tests/test_gridmath.py::test_curvature_paraboloid_exact PASSED
tests/test_gridmath.py::test_plan_curvature_sign_on_a_peak PASSED
tests/test_gridmath.py::test_profile_along_line PASSED
tests/test_gridmath.py::test_weights_sum_and_exactness PASSED
tests/test_gridmath.py::test_volume_rules_on_paraboloid PASSED
tests/test_gridmath.py::test_cut_fill_plane_and_lower_grid PASSED
tests/test_gridmath.py::test_volume_units_blanks_and_surface_area PASSED
tests/test_gridmath.py::test_volume_geographic_cell_areas PASSED
tests/test_gridmath.py::test_blank_inside_outside_with_hole_and_vector_layer PASSED
tests/test_gridmath.py::test_blank_reprojects_layer_and_clip_extent PASSED
tests/test_gui_phase3.py::test_phase3_capabilities_enabled PASSED
tests/test_gui_phase3.py::test_import_vector_all_sample_formats PASSED
tests/test_gui_phase3.py::test_vector_processing_commands PASSED
tests/test_gui_phase3.py::test_import_vector_error_is_reported PASSED
tests/test_gui_phase3.py::test_import_raster_as_grid_and_image PASSED
tests/test_gui_phase3.py::test_import_raster_reprojected_to_project_crs PASSED
tests/test_gui_phase3.py::test_grid_math_commands PASSED
tests/test_gui_phase3.py::test_terrain_volume_profile PASSED
tests/test_gui_phase3.py::test_point_density_and_vector_to_points PASSED
tests/test_gui_phase3.py::test_gis_map_layers_and_properties PASSED
tests/test_gui_phase3.py::test_map_export_tiff PASSED
tests/test_gui_phase3.py::test_logo_from_file PASSED
tests/test_gui_phase3.py::test_undo_redo_round_trip PASSED
tests/test_gui_phase3.py::test_undo_resets_on_new_project PASSED
tests/test_gui_phase3.py::test_vector_properties_and_crs_assignment PASSED
tests/test_gui_phase3.py::test_save_and_reload_gis_project PASSED
tests/test_gui_phase3.py::test_gis_demo_project_opens_and_renders PASSED
tests/test_gui_phase3.py::test_param_dialog_values PASSED
tests/test_mapping_gis.py::test_vector_and_image_layers_render PASSED
tests/test_mapping_gis.py::test_symbology_colours_and_no_data PASSED
tests/test_mapping_gis.py::test_classification PASSED
tests/test_mapping_gis.py::test_inset_text_and_logo PASSED
tests/test_mapping_gis.py::test_latlon_graticule_and_dms PASSED
tests/test_mapping_gis.py::test_clear_below_masks_values PASSED
tests/test_mapping_gis.py::test_tiff_and_pdf_export PASSED
tests/test_mapping_gis.py::test_v2_document_gets_phase3_defaults PASSED
tests/test_mapping_gis.py::test_wrong_source_kind_is_reported PASSED
tests/test_raster.py::test_cell_centres_become_nodes_and_rows_flip PASSED
tests/test_raster.py::test_geotiff_round_trip_exact PASSED
tests/test_raster.py::test_geotiff_float32_option PASSED
tests/test_raster.py::test_matches_gdal_conversion_of_esri_ascii PASSED
tests/test_raster.py::test_nodata_and_mask PASSED
tests/test_raster.py::test_scale_offset_applied PASSED
tests/test_raster.py::test_south_up_raster PASSED
tests/test_raster.py::test_rotated_raster_is_warped_with_warning PASSED
tests/test_raster.py::test_reprojection_on_import PASSED
tests/test_raster.py::test_decimation_block_average PASSED
tests/test_raster.py::test_band_selection_and_errors PASSED
tests/test_raster.py::test_no_crs_and_no_georeferencing_warn PASSED
tests/test_raster.py::test_classify_and_rgb_image PASSED
tests/test_raster.py::test_palette_image_and_transparency PASSED
tests/test_raster.py::test_uint16_image_is_stretched PASSED
tests/test_raster.py::test_image_downsampled_for_display PASSED
tests/test_raster.py::test_reproject_image PASSED
tests/test_undo.py::test_undo_redo_add_rename_remove PASSED
tests/test_undo.py::test_restored_objects_are_independent_of_snapshots PASSED
tests/test_undo.py::test_arrays_are_shared_not_copied PASSED
tests/test_undo.py::test_map_edits_are_deep_copied PASSED
tests/test_undo.py::test_new_action_discards_redo_and_noop_checkpoints_skip PASSED
tests/test_undo.py::test_history_is_append_only PASSED
tests/test_undo.py::test_limit PASSED
tests/test_undo.py::test_project_properties_and_vector_layers PASSED
tests/test_undo.py::test_describe[grid.create-Create PASSED
grid] PASSED
tests/test_undo.py::test_describe[dataset.assign_crs-Assign PASSED
CRS PASSED
to PASSED
dataset] PASSED
tests/test_undo.py::test_describe[vector.import-Import PASSED
vector PASSED
layer] PASSED
tests/test_undo.py::test_describe[project.metadata-Edit PASSED
project PASSED
properties] PASSED
tests/test_vector.py::test_round_trip_all_write_formats[gpkg] PASSED
tests/test_vector.py::test_round_trip_all_write_formats[shapefile] PASSED
tests/test_vector.py::test_round_trip_all_write_formats[geojson] PASSED
tests/test_vector.py::test_round_trip_all_write_formats[kml] PASSED
tests/test_vector.py::test_round_trip_all_write_formats[fgb] PASSED
tests/test_vector.py::test_polygons_round_trip_and_multi_promotion PASSED
tests/test_vector.py::test_shapefile_without_prj_warns_and_has_no_crs PASSED
tests/test_vector.py::test_zipped_shapefile PASSED
tests/test_vector.py::test_gpkg_layers PASSED
tests/test_vector.py::test_shapefile_field_name_collision PASSED
tests/test_vector.py::test_overwrite_protection PASSED
tests/test_vector.py::test_missing_and_bad_files PASSED
tests/test_vector.py::test_invalid_geometry_reported_and_repaired PASSED
tests/test_vector.py::test_planar_measures PASSED
tests/test_vector.py::test_geodesic_length_equator_analytic PASSED
tests/test_vector.py::test_geodesic_area_matches_equal_area_projection PASSED
tests/test_vector.py::test_add_measures_units PASSED
tests/test_vector.py::test_reproject_round_trip_and_record PASSED
tests/test_vector.py::test_buffer_refuses_geographic_and_has_correct_area PASSED
tests/test_vector.py::test_clip_extent_and_polygon PASSED
tests/test_vector.py::test_dissolve PASSED
tests/test_vector.py::test_points_to_table_with_field_and_z PASSED
tests/test_vector.py::test_contains_mask_and_polygon_union PASSED
tests/test_vector.py::test_dataset_queries PASSED
tests/test_project_storage.py::test_v2_project_migrates_to_v3_without_changes PASSED
tests/test_project_storage.py::test_vector_and_image_roundtrip PASSED
tests/test_project_storage.py::test_vector_without_attributes_and_corruption PASSED
tests/test_project_storage.py::test_vector_and_image_rename_remove PASSED
```

## Phase 3 — GitHub Actions

Pending: recorded after the CI run of the Phase 3 commit.

## Phase 2 (v0.2.0) — local run

Run: 2026-11-20, Linux (Ubuntu 24.04, x86-64), Python 3.13.18, Qt offscreen platform.
NumPy 2.5.5, pandas 3.1.1, SciPy 1.18.1, Matplotlib 3.11.2, PySide6 6.8.1, PyProj 3.8.0,
PyKrige 1.7.3 (reference for the Kriging comparison tests).

**Result: 179 passed in 35.3 s** (0 failed, 0 skipped)

| Test file | Tests | Passed |
|---|---|---|
| `tests/test_gridding.py` | 22 | 22 |
| `tests/test_gui.py` | 16 | 16 |
| `tests/test_gui_phase2.py` | 16 | 16 |
| `tests/test_importer.py` | 9 | 9 |
| `tests/test_interpolation.py` | 37 | 37 |
| `tests/test_mapping.py` | 11 | 11 |
| `tests/test_project_storage.py` | 20 | 20 |
| `tests/test_qc.py` | 18 | 18 |
| `tests/test_readers.py` | 21 | 21 |
| `tests/test_statistics_crs_units.py` | 9 | 9 |

## Phase 2 — GitHub Actions (2026-11-20, run 44677653777, commit c98b49d)

All 9 jobs passed: 179 of 179 tests each (0 skipped; PyKrige installed from its Windows
wheels, so the Kriging comparison ran on every job), plus `geohydro-pro --version` and the
screenshot script driving the real application through the gridding and map views.

| Runner | Python 3.11 | Python 3.12 | Python 3.13 |
|---|---|---|---|
| `windows-2022` (Server 2022, build 20348) | 179 passed | 179 passed | 179 passed |
| `windows-2025` (Server 2025, build 26100) | 179 passed | 179 passed | 179 passed |
| `ubuntu-24.04` | 179 passed | 179 passed | 179 passed |

The warnings are deprecation notices from Matplotlib's Qt backend
(`AA_UseHighDpiPixmaps`) and similar; none come from GeoHydro Pro's calculations. The same
caveat as Phase 1 applies: these are Windows Server images running Qt offscreen, not an
interactive check on desktop Windows 10/11.

### Numerical validation

* Kriging against PyKrige 1.7.3 (spherical, exponential and linear models, global
  neighbourhood): estimates and variances must agree within 1e-9 (Ordinary) and 1e-8
  (Universal, linear drift); measured agreement is about 1e-13 and 1e-10. PyKrige has no
  moving-neighbourhood equivalent, so local-search kriging is checked by properties
  (exactness, zero variance at data, variance approaching the sill far from data, local = global when the neighbourhood holds all points) instead.
* RBF against SciPy `RBFInterpolator` called directly; Natural Neighbour exactness, linear
  precision and weight properties; Minimum Curvature plane reproduction and tension.
* Accuracy against the known generating surface of the synthetic terrain survey: see
  `docs/GRIDDING.md` section 9 (reproducible with `python tools/validate_gridding.py`).

### Phase 2 individual tests

```
tests/test_gridding.py::test_geometry_from_spacing_keeps_minimum_and_extends_maximum PASSED
tests/test_gridding.py::test_geometry_validation PASSED
tests/test_gridding.py::test_geometry_from_points_and_nice_spacing PASSED
tests/test_gridding.py::test_bilinear_sample_reproduces_plane_and_respects_blanks PASSED
tests/test_gridding.py::test_grid_file_roundtrip_exact[surfer_ascii] PASSED
tests/test_gridding.py::test_grid_file_roundtrip_exact[surfer7_binary] PASSED
tests/test_gridding.py::test_grid_file_roundtrip_exact[esri_ascii] PASSED
tests/test_gridding.py::test_surfer6_binary_roundtrip_single_precision PASSED
tests/test_gridding.py::test_read_handwritten_dsaa_and_esri_corner PASSED
tests/test_gridding.py::test_grid_file_errors PASSED
tests/test_gridding.py::test_xyz_export PASSED
tests/test_gridding.py::test_prepare_points_invalid_and_duplicates PASSED
tests/test_gridding.py::test_grid_data_records_provenance PASSED
tests/test_gridding.py::test_blanking_hull_and_distance PASSED
tests/test_gridding.py::test_all_blank_raises_and_cancel PASSED
tests/test_gridding.py::test_kriging_variance_grid PASSED
tests/test_gridding.py::test_residual_analysis_definition PASSED
tests/test_gridding.py::test_metrics_hand_computed PASSED
tests/test_gridding.py::test_loo_nearest_on_a_line_is_hand_checkable PASSED
tests/test_gridding.py::test_loo_kriging_reports_standardised_errors PASSED
tests/test_gridding.py::test_loo_subsampling_is_reported_and_reproducible PASSED
tests/test_gridding.py::test_loo_min_curvature PASSED
tests/test_gui_phase2.py::test_run_gridding_adds_grid_and_opens_document PASSED
tests/test_gui_phase2.py::test_gridding_failure_is_reported_not_raised PASSED
tests/test_gui_phase2.py::test_grid_data_dialog_request_and_cross_validation PASSED
tests/test_gui_phase2.py::test_variogram_dialog_fit_feeds_kriging PASSED
tests/test_gui_phase2.py::test_new_map_of_each_type[contour] PASSED
tests/test_gui_phase2.py::test_new_map_of_each_type[filled_contour] PASSED
tests/test_gui_phase2.py::test_new_map_of_each_type[colour_relief] PASSED
tests/test_gui_phase2.py::test_new_map_of_each_type[post] PASSED
tests/test_gui_phase2.py::test_new_map_without_source_reports_error PASSED
tests/test_gui_phase2.py::test_map_view_editing PASSED
tests/test_gui_phase2.py::test_drag_scale_bar_stores_position PASSED
tests/test_gui_phase2.py::test_export_map_all_formats PASSED
tests/test_gui_phase2.py::test_export_and_reopen_grid_file PASSED
tests/test_gui_phase2.py::test_remove_grid_used_by_map_then_validate PASSED
tests/test_gui_phase2.py::test_rename_and_remove_map PASSED
tests/test_gui_phase2.py::test_save_and_reopen_project_with_grids_and_maps PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[idw] PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[natural_neighbour] PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[nearest] PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[ordinary_kriging] PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[rbf] PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[tin] PASSED
tests/test_interpolation.py::test_exact_methods_honour_data[universal_kriging] PASSED
tests/test_interpolation.py::test_linear_precision[tin] PASSED
tests/test_interpolation.py::test_linear_precision[natural_neighbour] PASSED
tests/test_interpolation.py::test_linear_precision[rbf] PASSED
tests/test_interpolation.py::test_linear_precision[universal_kriging] PASSED
tests/test_interpolation.py::test_min_curvature_reproduces_planes_with_and_without_tension PASSED
tests/test_interpolation.py::test_nearest_matches_brute_force_voronoi PASSED
tests/test_interpolation.py::test_nearest_radius_blanks PASSED
tests/test_interpolation.py::test_idw_hand_computed_and_bounded PASSED
tests/test_interpolation.py::test_idw_search_min_points_blank PASSED
tests/test_interpolation.py::test_anisotropy_equivalent_to_rotated_and_scaled_coordinates PASSED
tests/test_interpolation.py::test_anisotropy_validation PASSED
tests/test_interpolation.py::test_natural_neighbour_weights_properties_and_brute_force PASSED
tests/test_interpolation.py::test_natural_neighbour_outside_hull_blank PASSED
tests/test_interpolation.py::test_tin_hull_and_collinear PASSED
tests/test_interpolation.py::test_rbf_matches_scipy_and_smoothing PASSED
tests/test_interpolation.py::test_min_curvature_close_to_thin_plate_spline PASSED
tests/test_interpolation.py::test_tension_reduces_overshoot PASSED
tests/test_interpolation.py::test_min_curvature_limits PASSED
tests/test_interpolation.py::test_variogram_model_values PASSED
tests/test_interpolation.py::test_experimental_variogram_hand_computed PASSED
tests/test_interpolation.py::test_directional_variogram_detects_anisotropy PASSED
tests/test_interpolation.py::test_variogram_fit_recovers_parameters PASSED
tests/test_interpolation.py::test_kriging_matches_pykrige[spherical-params0-mine0] PASSED
tests/test_interpolation.py::test_kriging_matches_pykrige[exponential-params1-mine1] PASSED
tests/test_interpolation.py::test_kriging_matches_pykrige[linear-params2-mine2] PASSED
tests/test_interpolation.py::test_kriging_properties PASSED
tests/test_interpolation.py::test_kriging_anisotropy_equals_transformed_isotropic PASSED
tests/test_interpolation.py::test_kriging_input_errors PASSED
tests/test_interpolation.py::test_accuracy_against_known_sample_surface PASSED
tests/test_interpolation.py::test_universal_kriging_singular_systems_are_reported PASSED
tests/test_mapping.py::test_level_spec_modes PASSED
tests/test_mapping.py::test_map_document_roundtrip PASSED
tests/test_mapping.py::test_render_all_layer_types PASSED
tests/test_mapping.py::test_render_reports_missing_sources_and_empty_map PASSED
tests/test_mapping.py::test_contour_levels_outside_range_warn PASSED
tests/test_mapping.py::test_true_north_sign_and_geographic_scale PASSED
tests/test_mapping.py::test_export_formats[png] PASSED
tests/test_mapping.py::test_export_formats[jpg] PASSED
tests/test_mapping.py::test_export_formats[svg] PASSED
tests/test_mapping.py::test_export_formats[pdf] PASSED
tests/test_mapping.py::test_export_resolution_and_format_checks PASSED
tests/test_project_storage.py::test_frame_codec_exact_roundtrip PASSED
tests/test_project_storage.py::test_save_load_roundtrip PASSED
tests/test_project_storage.py::test_revision_increments_and_backup PASSED
tests/test_project_storage.py::test_conflict_detection PASSED
tests/test_project_storage.py::test_refuses_to_overwrite_other_project_or_file PASSED
tests/test_project_storage.py::test_checksum_mismatch_detected PASSED
tests/test_project_storage.py::test_not_a_project PASSED
tests/test_project_storage.py::test_newer_format_rejected PASSED
tests/test_project_storage.py::test_migration_runs_in_memory_and_preserves_file PASSED
tests/test_project_storage.py::test_missing_migration_is_an_error PASSED
tests/test_project_storage.py::test_manifest_is_json_serialisable PASSED
tests/test_project_storage.py::test_sample_project_loads PASSED
tests/test_project_storage.py::test_project_model_operations PASSED
tests/test_project_storage.py::test_duplicate_dataset_names_get_suffix PASSED
tests/test_project_storage.py::test_save_copy_to_new_location_keeps_uuid PASSED
tests/test_project_storage.py::test_grid_and_map_roundtrip PASSED
tests/test_project_storage.py::test_grid_checksum_and_shape_mismatch_detected PASSED
tests/test_project_storage.py::test_remove_grid_used_by_map_is_reported PASSED
tests/test_project_storage.py::test_v1_project_migrates_to_v2 PASSED
tests/test_project_storage.py::test_sample_project_has_grids_and_maps PASSED
```

## Phase 1 (v0.1.0)

Run: 2026-11-19, Linux (Ubuntu 24.04, x86-64), Python 3.13.18, Qt offscreen platform.

**Result: 88 passed in 11.53s**

## GitHub Actions (2026-11-20, run 44670581483, commit bfb71e2)

All 9 jobs passed: 88 of 88 tests each, plus `geohydro-pro --version` and the offscreen
screenshot script driving the real application.

| Runner | Reported OS | Python 3.11 | Python 3.12 | Python 3.13 |
|---|---|---|---|---|
| `windows-2022` | Windows Server 2022 Datacenter, 10.0.20348 | 88 passed | 88 passed | 88 passed |
| `windows-2025` | Windows Server 2025 Datacenter, 10.0.26100 | 88 passed | 88 passed | 88 passed |
| `ubuntu-24.04` | Ubuntu 24.04 | 88 passed | 88 passed | 88 passed |

Build 20348 shares the Windows 10 21H2-era kernel; build 26100 is the Windows 11 24H2 code
base. These are Windows Server images running Qt offscreen, so they are strong evidence for,
but not proof of, desktop Windows 10/11 compatibility. Still unverified: an interactive run
on real Windows 10 and Windows 11 desktops (on-screen rendering, high-DPI scaling, file
dialogs, fonts).

## Local run

| Test file | Tests | Passed |
|---|---|---|
| `tests/test_gui.py` | 16 | 16 |
| `tests/test_importer.py` | 9 | 9 |
| `tests/test_project_storage.py` | 15 | 15 |
| `tests/test_qc.py` | 18 | 18 |
| `tests/test_readers.py` | 21 | 21 |
| `tests/test_statistics_crs_units.py` | 9 | 9 |

## Individual tests

```
tests/test_gui.py::test_main_window_structure PASSED
tests/test_gui.py::test_planned_features_are_disabled_and_labelled PASSED
tests/test_gui.py::test_explorer_categories PASSED
tests/test_gui.py::test_import_wizard_preview_and_qc PASSED
tests/test_gui.py::test_import_wizard_read_option_override PASSED
tests/test_gui.py::test_import_wizard_unreadable_file PASSED
tests/test_gui.py::test_import_multiple_files_into_project PASSED
tests/test_gui.py::test_preview_cursor_updates_status_bar PASSED
tests/test_gui.py::test_properties_edit_rename_and_crs PASSED
tests/test_gui.py::test_save_open_roundtrip_through_ui PASSED
tests/test_gui.py::test_conflict_is_not_silently_overwritten PASSED
tests/test_gui.py::test_unsaved_changes_prompt PASSED
tests/test_gui.py::test_export_csv_and_source_protection PASSED
tests/test_gui.py::test_remove_dataset PASSED
tests/test_gui.py::test_sample_project_opens_as_copy PASSED
tests/test_gui.py::test_console_filter PASSED
tests/test_importer.py::test_terrain_sample_values PASSED
tests/test_importer.py::test_terrain_sample_matches_generating_surface PASSED
tests/test_importer.py::test_errors_sample_expected_qc PASSED
tests/test_importer.py::test_errors_sample_dedupe PASSED
tests/test_importer.py::test_geographic_sample PASSED
tests/test_importer.py::test_xyz_and_txt_samples PASSED
tests/test_importer.py::test_preview_is_truncated_but_import_is_complete PASSED
tests/test_importer.py::test_invalid_crs_rejected PASSED
tests/test_importer.py::test_capability_registry_honesty PASSED
tests/test_project_storage.py::test_frame_codec_exact_roundtrip PASSED
tests/test_project_storage.py::test_save_load_roundtrip PASSED
tests/test_project_storage.py::test_revision_increments_and_backup PASSED
tests/test_project_storage.py::test_conflict_detection PASSED
tests/test_project_storage.py::test_refuses_to_overwrite_other_project_or_file PASSED
tests/test_project_storage.py::test_checksum_mismatch_detected PASSED
tests/test_project_storage.py::test_not_a_project PASSED
tests/test_project_storage.py::test_newer_format_rejected PASSED
tests/test_project_storage.py::test_migration_runs_in_memory_and_preserves_file PASSED
tests/test_project_storage.py::test_missing_migration_is_an_error PASSED
tests/test_project_storage.py::test_manifest_is_json_serialisable PASSED
tests/test_project_storage.py::test_sample_project_loads PASSED
tests/test_project_storage.py::test_project_model_operations PASSED
tests/test_project_storage.py::test_duplicate_dataset_names_get_suffix PASSED
tests/test_project_storage.py::test_save_copy_to_new_location_keeps_uuid PASSED
tests/test_qc.py::test_parse_numeric_masks PASSED
tests/test_qc.py::test_parse_numeric_decimal_comma PASSED
tests/test_qc.py::test_clean_data_passes_unchanged PASSED
tests/test_qc.py::test_exclusion_reasons_counted_once_per_row PASSED
tests/test_qc.py::test_keep_invalid_rows_when_requested PASSED
tests/test_qc.py::test_duplicates_reported_and_kept_by_default PASSED
tests/test_qc.py::test_duplicates_keep_first PASSED
tests/test_qc.py::test_duplicates_mean PASSED
tests/test_qc.py::test_duplicate_tolerance_groups_chains PASSED
tests/test_qc.py::test_geographic_range_check PASSED
tests/test_qc.py::test_warning_when_no_crs_and_small_coordinates PASSED
tests/test_qc.py::test_attributes_preserved_and_typed PASSED
tests/test_qc.py::test_reserved_attribute_names_are_prefixed PASSED
tests/test_qc.py::test_xy_only_dataset PASSED
tests/test_qc.py::test_invalid_mapping[s0] PASSED
tests/test_qc.py::test_invalid_mapping[s1] PASSED
tests/test_qc.py::test_invalid_mapping[s2] PASSED
tests/test_qc.py::test_guess_xyz_names PASSED
tests/test_readers.py::test_csv_comma_with_header PASSED
tests/test_readers.py::test_csv_without_header_gets_default_names PASSED
tests/test_readers.py::test_semicolon_and_decimal_comma PASSED
tests/test_readers.py::test_tab_delimited_dat PASSED
tests/test_readers.py::test_xyz_whitespace_no_header PASSED
tests/test_readers.py::test_comments_blank_lines_and_skip_rows PASSED
tests/test_readers.py::test_quoted_fields PASSED
tests/test_readers.py::test_ragged_rows_warn PASSED
tests/test_readers.py::test_duplicate_and_blank_header_names PASSED
tests/test_readers.py::test_cp1252_encoding_fallback PASSED
tests/test_readers.py::test_utf8_bom PASSED
tests/test_readers.py::test_max_rows_truncates_but_reports_total PASSED
tests/test_readers.py::test_missing_file PASSED
tests/test_readers.py::test_empty_file PASSED
tests/test_readers.py::test_binary_file_rejected PASSED
tests/test_readers.py::test_planned_format_reports_phase PASSED
tests/test_readers.py::test_decimal_comma_with_comma_delimiter_rejected PASSED
tests/test_readers.py::test_xlsx_read_and_sheets PASSED
tests/test_readers.py::test_xlsx_float_precision_preserved PASSED
tests/test_readers.py::test_all_sample_files_read PASSED
tests/test_readers.py::test_reading_never_modifies_source PASSED
tests/test_statistics_crs_units.py::test_describe_hand_computed PASSED
tests/test_statistics_crs_units.py::test_describe_matches_scipy_and_ignores_nan PASSED
tests/test_statistics_crs_units.py::test_describe_edge_cases PASSED
tests/test_statistics_crs_units.py::test_spatial_summary_grid PASSED
tests/test_statistics_crs_units.py::test_resolve_crs_variants PASSED
tests/test_statistics_crs_units.py::test_resolve_crs_invalid PASSED
tests/test_statistics_crs_units.py::test_transform_wgs84_to_utm39_reference_point PASSED
tests/test_statistics_crs_units.py::test_transform_requires_defined_crs PASSED
tests/test_statistics_crs_units.py::test_units PASSED
```
