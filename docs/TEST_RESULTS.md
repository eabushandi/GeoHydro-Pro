# Test results

Run: 2026-11-19, Linux (Ubuntu 24.04, x86-64), Python 3.13.18, Qt offscreen platform.

**Result: 88 passed in 11.53s**

Not run on Windows (no Windows environment available; CI workflow prepared).

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
