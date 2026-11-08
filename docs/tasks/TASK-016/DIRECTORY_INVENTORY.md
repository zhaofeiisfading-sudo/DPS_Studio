# 一、二级目录盘点

计量为物理文件的逻辑大小；不遍历目录联接，不计 Git 历史；空目录不列入按文件计量表。前后快照保存在 audit。

| 目录 | 前 MiB / 文件数 | 后 MiB / 文件数 | 用途/归属 |
|---|---:|---:|---|
| `.agents` | 0.00 / 0 | 0.00 / 2 | 仓库 Skill |
| `.agents/skills` | 0.00 / 0 | 0.00 / 2 | 仓库 Skill |
| `.codex` | 0.00 / 1 | 0.00 / 0 | 既有元数据 |
| `.codex/tasks` | 0.00 / 1 | 0.00 / 0 | 既有元数据 |
| `.githooks` | 0.00 / 1 | 0.00 / 1 | 本地检查 hook |
| `.github` | 0.00 / 1 | 0.00 / 1 | 手动自动化 |
| `.github/workflows` | 0.00 / 1 | 0.00 / 1 | 手动自动化 |
| `.pytest_tmp_mergecheck` | 14.59 / 248 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/dual_profile_production0` | 4.68 / 60 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_absolute_export_retains_r0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_actual_stft_window_is_rec0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_actual_stft_window_is_rec1` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_actual_stft_window_is_rec2` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_actual_stft_window_is_rec3` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_actual_stft_window_is_rec4` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_all_selected_columns_prod0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_applies_time_and_independ0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_automatic_export_uses_cur0` | 0.62 / 7 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_background_failure_restor0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_channels_receive_independ0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_colormap_persists_without0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_confirmed_range_change_in0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_conflicting_or_duplicate_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_controller_rejects_invali0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_corridor_delete_does_not_0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_corridor_editing_stores_s0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_decoding_error_preserves_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dialog_allows_arbitrary_s0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dialog_initializes_signal0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dialog_initializes_signal1` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dialog_initializes_signal2` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dialog_initializes_signal3` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dialog_rejects_missing_du0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_disabling_pre_event_rows_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_display_connector_is_guid0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_dual_channels_and_automat0` | 0.04 / 10 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_empty_field_in_selected_o0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_empty_file_and_header_onl0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_event_metadata_case_a_can0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_event_metadata_case_b_use0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_event_metadata_case_c_con0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_event_metadata_case_d_abs0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_existing_exports_receive_0` | 0.03 / 7 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_explicit_default_profile_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_export_time_origin_is_exp0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_export_writes_simple_csv_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_extraction_mode_controls_0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_failed_production_does_no0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_full_gui_analysis_uses_re0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_generated_legacy_fixture_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_gui_export_uses_the_visib0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_guided_channels_are_indep0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_guided_mode_selection_kee0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_guided_only_velocity_sour0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_guided_results_are_backgr0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_guided_reuses_stft_auto_f0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_import_dialog_keeps_butto0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_import_mapping_semantics_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_inconsistent_row_width_is0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_independent_stft_reaches_0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp1` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp10` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp11` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp12` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp13` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp14` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp15` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp16` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp17` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp18` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp19` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp2` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp20` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp21` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp22` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp23` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp24` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp25` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp3` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp4` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp5` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp6` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp7` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp8` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_config_reports_sp9` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_name_protected_pa0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_old_layout_values0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_invalid_reader_configurat0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_later_channel_failure_pre0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_layout_settings_restore_r0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_malformed_csv_preserves_c0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_missing_source_path_uses_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_new_usability_controls_ha0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_non_numeric_time_reports_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_non_numeric_voltage_repor0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_nonuniform_time_is_preser0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_preview_boundary_is_expli0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_preview_reports_tentative0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_profile_change_invalidate0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_quoted_unselected_text_wi0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_reads_and_strips_complete0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_reads_headerless_single_c0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_reads_two_channels_scient0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_real_reader_keeps_source_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_relative_opaque_path_is_p0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_requested_time_or_voltage0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_result_mappings_are_immut0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_signal_validation_error_t0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_simple_export_fields_igno0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_simple_export_zero_overri0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_single_and_three_channel_0` | 0.39 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_single_and_three_channel_1` | 0.77 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_step6_export_target_drive0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_successful_production_upd0` | 0.00 / 5 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_toml_loads_relative_paths0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_toml_loads_validated_cust0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_toolbar_review_and_export0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_undo_clear_and_width_chan0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_unselected_nonempty_text_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_velocity_correction_contr0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_voltage_scale_keys_must_e0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_workflow_navigation_chang0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.pytest_tmp_mergecheck/test_workspace_splitter_and_bo0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t11_verify` | 75.60 / 801 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t11_verify/gate_final` | 3.03 / 23 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t11_verify/roi_tests` | 2.74 / 23 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t11_verify/v3` | 27.03 / 497 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t11_verify/v4` | 21.25 / 128 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t11_verify/v5` | 21.55 / 130 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full` | 14.60 / 271 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/dual_profile_production0` | 4.68 / 61 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_absolute_export_retains_r0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_actual_stft_window_is_rec0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_actual_stft_window_is_rec1` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_actual_stft_window_is_rec2` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_actual_stft_window_is_rec3` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_actual_stft_window_is_rec4` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_all_selected_columns_prod0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_applies_time_and_independ0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_automatic_export_uses_cur0` | 0.62 / 7 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_background_failure_restor0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_batch_runner_records_one_0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_calibration_mode_requires0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_channels_receive_independ0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_colormap_persists_without0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_confirmed_range_change_in0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_conflicting_or_duplicate_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_controller_rejects_invali0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_corrected_inventory_is_re0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_corridor_delete_does_not_0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_corridor_editing_stores_s0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_decoding_error_preserves_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dialog_allows_arbitrary_s0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dialog_initializes_signal0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dialog_initializes_signal1` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dialog_initializes_signal2` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dialog_initializes_signal3` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dialog_rejects_missing_du0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_different_explicit_inputs0` | 0.01 / 6 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_disabling_pre_event_rows_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_display_connector_is_guid0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_dual_channels_and_automat0` | 0.04 / 10 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_empty_field_in_selected_o0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_empty_file_and_header_onl0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_event_metadata_case_a_can0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_event_metadata_case_b_use0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_event_metadata_case_c_con0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_event_metadata_case_d_abs0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_existing_exports_receive_0` | 0.03 / 7 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_explicit_default_profile_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_export_time_origin_is_exp0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_export_writes_simple_csv_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_extraction_mode_controls_0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_failed_production_does_no0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_freeze_rejects_changed_ha0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_full_gui_analysis_uses_re0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_generated_legacy_fixture_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_gui_export_uses_the_visib0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_guided_channels_are_indep0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_guided_mode_selection_kee0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_guided_only_velocity_sour0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_guided_results_are_backgr0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_guided_reuses_stft_auto_f0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_import_dialog_keeps_butto0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_import_mapping_semantics_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_inconsistent_row_width_is0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_independent_stft_reaches_0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp1` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp10` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp11` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp12` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp13` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp14` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp15` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp16` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp17` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp18` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp19` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp2` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp20` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp21` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp22` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp23` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp24` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp25` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp3` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp4` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp5` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp6` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp7` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp8` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_config_reports_sp9` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_name_protected_pa0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_old_layout_values0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_invalid_reader_configurat0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_inventory_skips_invalid_f0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_later_channel_failure_pre0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_layout_settings_restore_r0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_malformed_csv_preserves_c0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_medium_result_is_excluded0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_missing_source_path_uses_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_new_usability_controls_ha0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_non_numeric_time_reports_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_non_numeric_voltage_repor0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_nonuniform_time_is_preser0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_preview_boundary_is_expli0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_preview_reports_tentative0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_processed_result_is_exclu0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_processed_result_is_exclu1` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_profile_change_invalidate0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_quoted_unselected_text_wi0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_raw_result_filter_before_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_read_only_source_and_iden0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_reads_and_strips_complete0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_reads_headerless_single_c0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_reads_two_channels_scient0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_real_mode_preserves_selec0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_real_reader_keeps_source_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_relative_opaque_path_is_p0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_requested_time_or_voltage0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_result_mappings_are_immut0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_sha256_is_stable_and_sour0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_signal_validation_error_t0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_simple_export_fields_igno0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_simple_export_zero_overri0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_single_and_three_channel_0` | 0.39 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_single_and_three_channel_1` | 0.77 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_step6_export_target_drive0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_toml_loads_relative_paths0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_toml_loads_validated_cust0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_toolbar_review_and_export0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_two_column_input_uses_for0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_undo_clear_and_width_chan0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_unselected_nonempty_text_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_velocity_correction_contr0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_voltage_scale_keys_must_e0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_workflow_navigation_chang0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.t28_sync_full/test_workspace_splitter_and_bo0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_acceptance` | 0.03 / 33 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_acceptance/test_cloud_copy_keeps_identica0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_acceptance/test_cloud_copy_preserves_a_di0` | 0.00 / 6 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_acceptance/test_cloud_copy_rejects_source0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_acceptance/test_exports_roundtrip_precisi0` | 0.01 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_acceptance/test_forced_staged_binary_is_r0` | 0.03 / 21 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_final` | 0.03 / 33 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_final/test_cloud_copy_keeps_identica0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_final/test_cloud_copy_preserves_a_di0` | 0.00 / 6 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_final/test_cloud_copy_rejects_source0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_final/test_exports_roundtrip_precisi0` | 0.01 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_final/test_forced_staged_binary_is_r0` | 0.03 / 21 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_related_v01` | 0.01 / 12 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_related_v01/test_cloud_copy_keeps_identica0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_related_v01/test_cloud_copy_preserves_a_di0` | 0.00 / 6 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_related_v01/test_cloud_copy_rejects_source0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_related_v01/test_exports_roundtrip_precisi0` | 0.01 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_release` | 0.03 / 33 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_release/test_cloud_copy_keeps_identica0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_release/test_cloud_copy_preserves_a_di0` | 0.00 / 6 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_release/test_cloud_copy_rejects_source0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_release/test_exports_roundtrip_precisi0` | 0.01 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task13_pytest_release/test_forced_staged_binary_is_r0` | 0.03 / 21 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a` | 14.58 / 245 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/dual_profile_production0` | 4.67 / 60 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_absolute_export_retains_r0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_actual_stft_window_is_rec0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_actual_stft_window_is_rec1` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_actual_stft_window_is_rec2` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_actual_stft_window_is_rec3` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_actual_stft_window_is_rec4` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_all_selected_columns_prod0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_applies_time_and_independ0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_automatic_export_uses_cur0` | 0.62 / 7 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_background_failure_restor0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_channels_receive_independ0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_colormap_persists_without0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_confirmed_range_change_in0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_conflicting_or_duplicate_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_controller_rejects_invali0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_corridor_delete_does_not_0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_corridor_editing_stores_s0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_decoding_error_preserves_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dialog_allows_arbitrary_s0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dialog_initializes_signal0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dialog_initializes_signal1` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dialog_initializes_signal2` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dialog_initializes_signal3` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dialog_rejects_missing_du0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_disabling_pre_event_rows_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_display_connector_is_guid0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_dual_channels_and_automat0` | 0.04 / 10 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_empty_field_in_selected_o0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_empty_file_and_header_onl0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_event_metadata_case_a_can0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_event_metadata_case_b_use0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_event_metadata_case_c_con0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_event_metadata_case_d_abs0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_existing_exports_receive_0` | 0.03 / 7 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_explicit_default_profile_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_export_time_origin_is_exp0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_export_writes_simple_csv_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_extraction_mode_controls_0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_failed_production_does_no0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_full_gui_analysis_uses_re0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_generated_legacy_fixture_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_gui_export_uses_the_visib0` | 0.01 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_guided_channels_are_indep0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_guided_mode_selection_kee0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_guided_only_velocity_sour0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_guided_results_are_backgr0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_guided_reuses_stft_auto_f0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_import_mapping_semantics_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_inconsistent_row_width_is0` | 0.00 / 2 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_independent_stft_reaches_0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp1` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp10` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp11` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp12` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp13` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp14` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp15` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp16` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp17` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp18` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp19` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp2` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp20` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp21` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp22` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp23` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp24` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp25` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp3` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp4` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp5` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp6` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp7` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp8` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_config_reports_sp9` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_name_protected_pa0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_old_layout_values0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_invalid_reader_configurat0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_later_channel_failure_pre0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_layout_settings_restore_r0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_malformed_csv_preserves_c0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_missing_source_path_uses_0` | 0.01 / 4 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_non_numeric_time_reports_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_non_numeric_voltage_repor0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_nonuniform_time_is_preser0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_preview_boundary_is_expli0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_preview_reports_tentative0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_profile_change_invalidate0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_quoted_unselected_text_wi0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_reads_and_strips_complete0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_reads_headerless_single_c0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_reads_two_channels_scient0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_real_reader_keeps_source_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_relative_opaque_path_is_p0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_requested_time_or_voltage0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_result_mappings_are_immut0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_signal_validation_error_t0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_simple_export_fields_igno0` | 0.00 / 3 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_simple_export_zero_overri0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_single_and_three_channel_0` | 0.39 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_single_and_three_channel_1` | 0.77 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_step6_export_target_drive0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_successful_production_upd0` | 0.00 / 5 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_toml_loads_relative_paths0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_toolbar_review_and_export0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_undo_clear_and_width_chan0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_unselected_nonempty_text_0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_velocity_correction_contr0` | 0.29 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_voltage_scale_keys_must_e0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_workflow_navigation_chang0` | 0.58 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.task_gui_baseline_tmp_20260817_a/test_workspace_splitter_and_bo0` | 0.00 / 1 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `.vscode` | 0.00 / 1 | 0.00 / 1 | 本地工程文件 |
| `CodePython_ProjectsDPS_Studio_RESEARCH_CLEANartifactsresearch_clean_task15` | 0.00 / 5 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `CodePython_ProjectsDPS_Studio_RESEARCH_CLEANartifactsresearch_clean_task15/cache` | 0.00 / 5 | 0.00 / 0 | 历史 pytest/临时输出（已核验清理） |
| `artifacts` | 8928.21 / 37989 | 2873.50 / 26099 | 生成/冻结科研成果 |
| `artifacts/TASK-008` | 0.00 / 0 | 281.58 / 11074 | 生成/冻结科研成果 |
| `artifacts/TASK-009` | 0.00 / 0 | 230.48 / 3979 | 生成/冻结科研成果 |
| `artifacts/TASK-010` | 0.00 / 0 | 660.91 / 4139 | 生成/冻结科研成果 |
| `artifacts/TASK-011` | 0.00 / 0 | 465.99 / 1287 | 生成/冻结科研成果 |
| `artifacts/TASK-012` | 0.00 / 0 | 109.70 / 867 | 生成/冻结科研成果 |
| `artifacts/TASK-013` | 0.00 / 0 | 389.97 / 2025 | 生成/冻结科研成果 |
| `artifacts/TASK-014` | 0.00 / 0 | 6.13 / 137 | 生成/冻结科研成果 |
| `artifacts/TASK-015` | 0.00 / 0 | 651.36 / 1899 | 生成/冻结科研成果 |
| `artifacts/TASK-016` | 0.00 / 0 | 17.35 / 54 | 生成/冻结科研成果 |
| `artifacts/inherited` | 0.00 / 0 | 60.02 / 638 | 生成/冻结科研成果 |
| `artifacts/research_clean_task10` | 661.12 / 4185 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task11` | 2115.85 / 3533 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task12` | 4087.04 / 9728 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task13` | 390.15 / 2046 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task14` | 327.14 / 597 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task15` | 790.70 / 2470 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task8` | 281.78 / 11121 | 0.00 / 0 | 生成/冻结科研成果 |
| `artifacts/research_clean_task9` | 274.44 / 4309 | 0.00 / 0 | 生成/冻结科研成果 |
| `build` | 2818.49 / 40248 | 0.00 / 0 | 可重建环境/打包/测试中间产物 |
| `build/task14-ci` | 938.44 / 15562 | 0.00 / 0 | 可重建环境/打包/测试中间产物 |
| `build/task14-env` | 1076.73 / 21455 | 0.00 / 0 | 可重建环境/打包/测试中间产物 |
| `build/task14-install` | 229.66 / 452 | 0.00 / 0 | 可重建环境/打包/测试中间产物 |
| `build/task14-scratch` | 573.65 / 2779 | 0.00 / 0 | 可重建环境/打包/测试中间产物 |
| `configs` | 0.02 / 4 | 0.04 / 6 | 配置 |
| `configs/research` | 0.01 / 2 | 0.03 / 4 | 配置 |
| `data` | 30.61 / 16 | 41.37 / 22 | 实验与测试输入 |
| `data/examples` | 0.00 / 1 | 0.00 / 1 | 实验与测试输入 |
| `data/processed` | 0.00 / 1 | 0.00 / 1 | 实验与测试输入 |
| `data/raw` | 30.60 / 11 | 30.60 / 11 | 实验与测试输入 |
| `data/reference` | 0.01 / 2 | 3.66 / 5 | 实验与测试输入 |
| `data/research` | 0.00 / 0 | 7.11 / 3 | 实验与测试输入 |
| `data/synthetic` | 0.00 / 1 | 0.00 / 1 | 实验与测试输入 |
| `docs` | 4.95 / 42 | 1.79 / 106 | 报告/记录 |
| `docs/deployment` | 0.01 / 3 | 0.01 / 3 | 报告/记录 |
| `docs/development` | 0.00 / 0 | 0.13 / 3 | 报告/记录 |
| `docs/learning` | 0.08 / 1 | 0.08 / 1 | 报告/记录 |
| `docs/maintenance` | 0.50 / 2 | 0.50 / 2 | 报告/记录 |
| `docs/reference` | 0.00 / 0 | 0.22 / 3 | 报告/记录 |
| `docs/tasks` | 0.00 / 0 | 0.78 / 90 | 报告/记录 |
| `docs/ui` | 0.07 / 4 | 0.07 / 4 | 报告/记录 |
| `logs` | 0.00 / 1 | 0.00 / 0 | 继承日志（已迁移） |
| `packaging` | 0.01 / 4 | 0.00 / 0 | 原构建配置（已迁移） |
| `release` | 321.00 / 456 | 365.26 / 4 | 现有发布包 |
| `release/PDV_Studio_Research_TASK012` | 229.67 / 455 | 0.00 / 0 | 现有发布包 |
| `release/TASK-011` | 0.00 / 0 | 91.29 / 1 | 现有发布包 |
| `release/TASK-012` | 0.00 / 0 | 91.33 / 1 | 现有发布包 |
| `release/TASK-014` | 0.00 / 0 | 91.32 / 1 | 现有发布包 |
| `release/TASK-015` | 0.00 / 0 | 91.33 / 1 | 现有发布包 |
| `results` | 60.02 / 645 | 0.00 / 0 | 继承输出（已迁移） |
| `results/task007_bandwidth_20261028` | 60.02 / 644 | 0.00 / 0 | 继承输出（已迁移） |
| `scripts` | 1.86 / 110 | 1.97 / 179 | 执行与维护脚本 |
| `scripts/__pycache__` | 0.47 / 13 | 0.00 / 0 | 执行与维护脚本 |
| `scripts/build` | 0.00 / 0 | 0.01 / 9 | 执行与维护脚本 |
| `scripts/dev` | 0.00 / 1 | 0.01 / 3 | 执行与维护脚本 |
| `scripts/launchers` | 0.00 / 0 | 0.01 / 4 | 执行与维护脚本 |
| `scripts/maintenance` | 0.00 / 1 | 0.05 / 12 | 执行与维护脚本 |
| `scripts/research` | 0.00 / 0 | 1.47 / 143 | 执行与维护脚本 |
| `scripts/workflows` | 0.00 / 0 | 0.41 / 8 | 执行与维护脚本 |
| `src` | 5.24 / 237 | 3.88 / 191 | 可安装源码 |
| `src/dps_studio` | 5.24 / 237 | 3.88 / 191 | 可安装源码 |
| `tests` | 1.68 / 134 | 1.01 / 116 | 测试与夹具 |
| `tests/fixtures` | 0.02 / 2 | 0.02 / 2 | 测试与夹具 |
| `tests/unit` | 1.61 / 128 | 0.94 / 110 | 测试与夹具 |
| `tools` | 0.10 / 6 | 0.00 / 0 | 原零散工具（已迁移） |

`.git` 当前 4.97 MiB，未做历史清理；46 个外部联接单列在 RETAINED_ITEMS。

主要剩余体积来自冻结 TASK-010/015 运行结果、TASK-008 实验与图件、保留的 TASK-011 数值 reference、TASK-013 历史成果/备份，以及 4 个现有发布 ZIP；这些没有被按名字判为垃圾。
