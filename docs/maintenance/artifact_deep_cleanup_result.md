# Artifact deep cleanup result

**清理未执行。** 自动审批拒绝了删除命令；49 个待删项目仍全部存在。

| 指标 | 结果 |
|---|---:|
| 清理前 | 7,549,603,367 字节（7.550 GB） |
| 清理后 | 7,549,603,367 字节（7.550 GB） |
| 释放 | 0.000 GB |
| 文件数（前 / 后） | 11,614 / 11,614 |
| 删除文件数 | 0 |
| 删除目录数 | 0 |

按 TASK 统计的实际释放空间均为 0 GB。

## 当前最大的 20 个目录

以下路径均相对 `artifacts`，GB 按 10⁹ 字节计算。

| 目录 | GB |
|---|---:|
| `task023f_proposal_recall_recovery/20260912T100142Z` | 3.990 |
| `task023f_proposal_recall_recovery` | 3.990 |
| `task023f_proposal_recall_recovery/20260912T100142Z/lineages` | 3.583 |
| `task023h_raw_domain_evidence/20260913T132656Z` | 1.032 |
| `task023h_raw_domain_evidence` | 1.032 |
| `task026_frequency_representation/20260915T055008Z` | 0.822 |
| `task026_frequency_representation` | 0.822 |
| `task023h_raw_domain_evidence/20260913T132656Z/lineages` | 0.486 |
| `task023e_cross_scale_evidence/20260911T151301Z` | 0.431 |
| `task023e_cross_scale_evidence` | 0.431 |
| `task023e_cross_scale_evidence/20260911T151301Z/generated_waveforms` | 0.410 |
| `task027_non_ai_open_exploration/20260928T135421Z` | 0.370 |
| `task027_non_ai_open_exploration` | 0.370 |
| `task023h_raw_domain_evidence/20260913T132656Z/streams` | 0.356 |
| `task021a_global_path` | 0.355 |
| `task023f_proposal_recall_recovery/20260912T100142Z/real_streams` | 0.181 |
| `task021b_global_path_real_calibration` | 0.168 |
| `task021a_global_path/run_20260826_task021b_real_calibration_final` | 0.111 |
| `task021a_global_path/run_20260826_task021b_real_calibration_v2` | 0.111 |
| `task021a_global_path/run_20260826_task021b_real_calibration` | 0.101 |

artifacts 仍大于 3 GB。超过 200 MB 的主要历史中间目录仍在，原因是自动审批拒绝了删除操作。删除最多空间的目录：无实际删除。

TASK-028 指定的核心报告、配置、结果表和 figures 均仍存在；当前未发现 `task029*` 目录。`research_clean_sync` 核心报告、data/raw、Production 均未触碰。

删除前统计见 `artifact_deep_cleanup_before.csv`；保留与待删清单分别见 `artifact_keep_manifest.csv`、`artifact_delete_manifest.csv`。待删清单仅为计划，未执行。下一步需在允许执行这些已核对路径的环境中清理。
