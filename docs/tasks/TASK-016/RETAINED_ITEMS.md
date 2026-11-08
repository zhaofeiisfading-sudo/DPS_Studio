# 保留及人工判定清单

| 对象 | 处理及原因 |
|---|---|
| `artifacts/TASK-013/git_backup/`（约 154 MiB） | 可能包含独立历史/恢复信息，未证明可重建；默认保留，由用户判定。 |
| `artifacts/TASK-009/figures/`、`renders/` 等旧图版，以及 TASK-012 source_before/implementation 等快照 | 尚未逐项证明与最终成果重复；保留，不因目录名删除。 |
| `artifacts/TASK-016/retained_empty_directories/` | packaging、tools、旧 task008 的空目录树，0 个文件。删除被自动审批拒绝后可逆迁入，可由用户手动处理。 |
| `.codex/`、`.vscode/` | 原有标准元数据目录保留；空目录删除命令被自动审批拒绝，无运行数据损失。 |

## 外部目录联接

以下 46 个目录联接只记录路径和目标；未遍历、未修改目标。是否移除联接必须由其旧工作区/科研结果的拥有者判定，不得递归删除目标。

| 本地相对路径 | 外部目标 |
|---|---|
| `artifacts/clean_task4` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\clean_task4` |
| `artifacts/clean_task4a` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\clean_task4a` |
| `artifacts/clean_task4b` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\clean_task4b` |
| `artifacts/clean_task5` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\clean_task5` |
| `artifacts/clean_task7` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\clean_task7` |
| `artifacts/git_repository_audit_20260928` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\git_repository_audit_20260928` |
| `artifacts/legacy_outputs` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\legacy_outputs` |
| `artifacts/legacy_task021a_link` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts` |
| `artifacts/research_clean_sync` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\research_clean_sync` |
| `artifacts/task014_ui` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task014_ui` |
| `artifacts/task015a_ui` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task015a_ui` |
| `artifacts/task015b_ui` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task015b_ui` |
| `artifacts/task015c_r` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task015c_r` |
| `artifacts/task015c_ui` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task015c_ui` |
| `artifacts/task015d_ui` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task015d_ui` |
| `artifacts/task015e_ui` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task015e_ui` |
| `artifacts/task016_guided` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task016_guided` |
| `artifacts/task016r` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task016r` |
| `artifacts/task016r2` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task016r2` |
| `artifacts/task016r2r` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task016r2r` |
| `artifacts/task016r3` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task016r3` |
| `artifacts/task017` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task017` |
| `artifacts/task017r` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task017r` |
| `artifacts/task018a` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task018a` |
| `artifacts/task018b` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task018b` |
| `artifacts/task018c` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task018c` |
| `artifacts/task019a` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task019a` |
| `artifacts/task021a_global_path` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021a_global_path` |
| `artifacts/task021b_global_path_real_calibration` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021b_global_path_real_calibration` |
| `artifacts/task021c_cost_normalization_and_null_bridge` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021c_cost_normalization_and_null_bridge` |
| `artifacts/task021d_time_roi_multistack` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021d_time_roi_multistack` |
| `artifacts/task021e_transition_model_redesign` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021e_transition_model_redesign` |
| `artifacts/task021f_node_evidence_broadband` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021f_node_evidence_broadband` |
| `artifacts/task021g_spatiotemporal_candidate_coherence` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task021g_spatiotemporal_candidate_coherence` |
| `artifacts/task022a_imm_mht_ridge_tracker` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task022a_imm_mht_ridge_tracker` |
| `artifacts/task023d_smooth_branch_rescue` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task023d_smooth_branch_rescue` |
| `artifacts/task023e_cross_scale_evidence` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task023e_cross_scale_evidence` |
| `artifacts/task023f_proposal_recall_recovery` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task023f_proposal_recall_recovery` |
| `artifacts/task023g_beam_retention_interval_gate` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task023g_beam_retention_interval_gate` |
| `artifacts/task023h_raw_domain_evidence` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task023h_raw_domain_evidence` |
| `artifacts/task024a_strongest_segment_rescue` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task024a_strongest_segment_rescue` |
| `artifacts/task024b_trusted_core_edge_rescue` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task024b_trusted_core_edge_rescue` |
| `artifacts/task025_informative_interval` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task025_informative_interval` |
| `artifacts/task026_frequency_representation` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task026_frequency_representation` |
| `artifacts/task027_non_ai_open_exploration` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task027_non_ai_open_exploration` |
| `artifacts/task028_candidate_method_consolidation` | `D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts\task028_candidate_method_consolidation` |
