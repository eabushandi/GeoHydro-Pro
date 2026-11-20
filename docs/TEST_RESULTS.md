# Test results

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

The Windows CI results for this version are added below once the run completes.

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
