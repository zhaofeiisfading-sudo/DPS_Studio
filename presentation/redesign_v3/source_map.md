# DPS Studio 组会汇报来源映射

## 来源使用规则

- 当前结构与参数以真实源代码、`configs/demo_dual_profile.toml` 和 `run_20260724_004901_103968` 的 manifest 为准。
- `PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md` 的第 17 节是 TASK-012A-R 后的更新事实；此前章节中的旧路径、旧搜索下限和“workflow 尚未实现”等内容不再作为当前结论。
- `balanced_diagnostic/` 只提供开发诊断图和逐帧诊断数据，不替代正式 production 输出。
- 旧软件图与 CSV 只用于开发历史；其来源和处理参数尚未由实验组确认。
- 所有速度均称为“无符号表观速度”，不写成 LiF 修正后的真实界面速度。

## 逐页映射

| 页码 | 主题 | 图像来源 | 数据/参数/论断来源 |
| ---: | --- | --- | --- |
| 01 | 封面 | 无实验图；原生线条 | `README.md`；`configs/demo_dual_profile.toml`；`scripts/production_outputs.py` 的 interpretation guards |
| 02 | 三个问题与术语 | 无 | `README.md`；`src/dps_studio/core/physics/velocity.py`；`presentations/PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md` §17 |
| 03 | 原始双通道输入 | 原图：`presentations/group_meeting/20260726_redesign/assets/real/raw_voltage_dual_channel.png`；PPT 内复制：`assets/real/raw_voltage_dual_channel.png` | `configs/demo_dual_profile.toml` 的列映射与缩放；`scripts/run_demo_pipeline.py`；`src/dps_studio/core/io/` |
| 04 | 时域波形为何不足 | 无实验图；原生算法示意 | `src/dps_studio/core/time_frequency/stft.py`；`src/dps_studio/core/analysis_profiles.py` |
| 05 | 完整单边 STFT | 原图：`presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/stft_full_band.png`；PPT 内复制：`assets/real/full_stft_balanced_ch1.png` | `balanced/profile_manifest.json` 的 Nyquist、显示范围与搜索范围；`scripts/production_outputs.py` |
| 06 | 局部 STFT 与脊线 | 原图：`presentations/data/balanced_diagnostic/pdv_channel_1_stft_detail.png`、`pdv_channel_1_stft_spectrogram_with_refined_ridge.png`；PPT 内复制：`assets/real/local_stft_balanced_ch1.png`、`local_stft_ridge_balanced_ch1.png` | `src/dps_studio/core/ridge/peak.py`；`src/dps_studio/core/ridge/refinement.py`；`src/dps_studio/core/workflow/analysis.py` |
| 07 | 拍频换算表观速度 | 无实验图；公式为原生文本 | `src/dps_studio/core/physics/velocity.py`；`configs/demo_dual_profile.toml` 的 `vacuum_wavelength_m`；run manifest 的 wavelength status |
| 08 | 当前参数 | 无实验图；原生表格和代码框 | `configs/demo_dual_profile.toml`；`src/dps_studio/core/analysis_profiles.py`；`src/dps_studio/core/workflow/config.py` |
| 09 | 参数取舍 | 无实验图；原生取舍轴和数值表 | `balanced/profile_manifest.json`、`high_time_resolution/profile_manifest.json`；`presentations/PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md` §17.3 |
| 10 | 真实 profile 对比 | 原图：正式 run 的 `balanced/.../stft_analysis_band_with_ridge.png` 与 `high_time_resolution/.../stft_analysis_band_with_ridge.png`；PPT 内复制：`assets/real/ridge_balanced_ch1.png`、`ridge_high_time_ch1.png` | 两个 `profile_manifest.json` 的 channel 1 首个候选速度、最大相邻频率步长、峰—背景谱对比度中位数 |
| 11 | 正式全时间表观速度 | 原图：`presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_full_time.png`；PPT 内复制：`assets/real/full_velocity_balanced_ch1.png` | `scripts/production_outputs.py` 的 formal candidate、display zero、two-endpoint bridge 规则；`apparent_velocity.csv` |
| 12 | 起跳、平台、下降细节 | 原图：正式 run 的 `apparent_velocity_event_detail.png`；诊断目录的 `pdv_channel_1_presentation_with_plateau_detail.png`、`pdv_channel_1_decline_detail.png`；PPT 内复制：`assets/real/event_detail_balanced_ch1.png`、`plateau_detail_balanced_ch1.png`、`decline_detail_balanced_ch1.png` | `balanced/profile_manifest.json` 的 event onset diagnostics；`balanced_diagnostic/pdv_channel_1_refined_ridge_velocity.csv` |
| 13 | 双通道对比 | 原图：`presentations/data/balanced_diagnostic/two_channel_presentation_velocity.png`；PPT 内复制：`assets/real/two_channel_velocity.png` | `balanced/quality_summary.csv`；`balanced/profile_manifest.json`；`scripts/production_outputs.py` 的 no selection/averaging/fusion guard |
| 14 | 开发历史 | 原图：`presentations/data/旧软件速度时间图.png`、`presentations/data/balanced_diagnostic/pdv_channel_1_presentation_velocity.png`；PPT 内复制：`assets/real/legacy_velocity.png`、`current_presentation_velocity.png` | `data/reference/legacy/README.md`；`data/reference/legacy/legacy_velocity_time.csv`；当前 workflow/config/manifest 源码 |
| 15 | 已完成能力 | 无实验图；原生状态分栏 | `README.md`；`pyproject.toml`；`src/dps_studio/core/`；`src/dps_studio/core/workflow/`；`scripts/production_outputs.py`；审计报告 §17 |
| 16 | 当前问题 | 原图：`presentations/data/balanced_diagnostic/two_channel_spectral_quality_comparison.png`；PPT 内复制：`assets/real/two_channel_quality.png` | `balanced_diagnostic/*spectral_quality.csv`；`src/dps_studio/core/ridge/spectral_quality.py`；run manifest interpretation guards |
| 17 | 下一步 | 无实验图；原生依赖时间线 | 当前未实现项来自 `README.md`、`src/dps_studio/gui/`、`src/dps_studio/plugins/`、`src/dps_studio/core/physics/velocity.py` 与审计报告 §17 |
| 18 | 总结 | 无 | 对前 17 页经核验事实与边界的压缩，不新增论断 |

## 数值来源

| 数值 | 当前值 | 来源 | 使用位置 |
| --- | ---: | --- | --- |
| 事件起点 | `554.668 µs` | `configs/demo_dual_profile.toml` | 参数、速度图参考线 |
| 分析终点 | `555.45 µs` | 同上 | 正式候选区间 |
| 演示真空波长 | `1.55 µm` | 同上；run manifest 明确标记未确认 | 速度换算与边界说明 |
| Balanced STFT | Hann / 768 / 640 / hop 128 / nfft 4096 | `src/dps_studio/core/analysis_profiles.py`；profile manifest | 第 8–10 页 |
| High time STFT | Hann / 512 / 384 / hop 128 / nfft 4096 | 同上 | 第 8–10 页 |
| 脊线搜索范围 | `0.05–2.0 GHz` | 两个 profile；两个 profile manifest | 第 5、8 页 |
| 完整单边频谱上限 | 约 `20 GHz` | profile manifest 的实际 Nyquist | 第 5 页 |
| Balanced / ch1 首个候选速度 | `537.9387 m/s` | `balanced/quality_summary.csv` | 第 10、13 页 |
| High time / ch1 首个候选速度 | `531.9810 m/s` | `high_time_resolution/quality_summary.csv` | 第 10 页 |
| Balanced / ch2 首个候选速度 | `531.8331 m/s` | `balanced/quality_summary.csv` | 第 13 页 |
| Balanced / ch1、ch2 峰—背景中位数 | `52.5301 / 55.7844 dB` | `balanced/quality_summary.csv` | 第 13 页 |
| Balanced / ch1、ch2 峰—竞争峰中位数 | `13.2956 / 19.8805 dB` | 同上 | 第 13 页 |

## 未核验或不能作为当前事实的内容

- `vacuum_wavelength_m = 1.55e-6`：配置中的演示值，尚未由实验记录确认。
- 旧软件速度曲线：来源、参数和处理步骤尚未由实验组确认，不是物理真值。
- LiF、折射率、入射角、窗口修正、有符号速度：当前未实现。
- 谱对比度、连续性、相关频率局部峰：当前是描述性诊断量，不是 SNR、准确度、置信度或经验证的物理分支判据。
