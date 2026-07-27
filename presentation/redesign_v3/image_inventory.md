# DPS Studio 组会汇报图像与数据清单

## 盘点范围与结论

- 主目录：`presentations/data/`（项目中不存在 `presentation/data/`；本次按现有真实目录读取）。
- 已逐项读取：54 张图、14 个 CSV、3 个 JSON 清单。
- 额外纳入：既有原始双通道波形图与旧软件本地导出 CSV；两者均来自项目现有材料。
- 三组完全重复文件：`完整时间轴.png`、`新软件速度时间图.png`、`完整频谱图.png` 分别与正式 run 中对应文件一致；PPT 优先引用正式 run 路径。
- 未重新运行分析脚本：现有材料已经覆盖 10 类必需内容，避免改变参数后伪装成默认结果。

## 分类统计

- 1. 原始时间—电压波形：1 项
- 2. 完整频谱图：5 项
- 3. 事件区/局部频谱图：2 项
- 4. 带脊线频谱图：6 项
- 5. 完整时间—速度图：17 项
- 6. 平台/起跳/下降段细节：10 项
- 7. 参数或 profile 对比：4 项
- 8. 双通道对比：4 项
- 9. 质量诊断：18 项
- 10. 旧软件/当前软件对比：3 项

## 全量清单

| 类别 | 路径 | run | profile | 通道 | 内容 | PPT 适用性 | 重复性 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. 原始时间—电压波形 | `presentations/group_meeting/20260726_redesign/assets/real/raw_voltage_dual_channel.png` | 项目既有材料 | 不适用/未单列 | 未单列 | 原始 CSV 两个独立电压通道的时间波形；未平滑、未插值 | 高：可作为对应主题页主图 | 否 |
| 2. 完整频谱图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/stft_full_band.png` | run_20260724_004901_103968 | balanced | pdv_channel_1 | 实际单边 STFT 全频段，0 至实际 Nyquist（约 20 GHz） | 高：可作为对应主题页主图 | 完全重复组基准 |
| 2. 完整频谱图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/stft_full_band.png` | run_20260724_004901_103968 | balanced | pdv_channel_2 | 实际单边 STFT 全频段，0 至实际 Nyquist（约 20 GHz） | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/stft_full_band.png；presentations/data/完整频谱图.png |
| 2. 完整频谱图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/stft_full_band.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_1 | 实际单边 STFT 全频段，0 至实际 Nyquist（约 20 GHz） | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/stft_full_band.png |
| 2. 完整频谱图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/stft_full_band.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_2 | 实际单边 STFT 全频段，0 至实际 Nyquist（约 20 GHz） | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/stft_full_band.png |
| 2. 完整频谱图 | `presentations/data/完整频谱图.png` | 项目既有材料 | 不适用/未单列 | 未单列 | 实际单边 STFT 全频段，0 至实际 Nyquist（约 20 GHz） | 低：与正式 run 文件完全重复 | 完全重复；基准：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/stft_full_band.png |
| 3. 事件区/局部频谱图 | `presentations/data/balanced_diagnostic/pdv_channel_1_stft_detail.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 事件附近 0–2 GHz 局部 STFT 细节 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_2_stft_detail.png |
| 3. 事件区/局部频谱图 | `presentations/data/balanced_diagnostic/pdv_channel_2_stft_detail.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 事件附近 0–2 GHz 局部 STFT 细节 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_1_stft_detail.png |
| 4. 带脊线频谱图 | `presentations/data/balanced_diagnostic/pdv_channel_1_stft_spectrogram_with_refined_ridge.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 局部频谱与离散/亚频点精修脊线叠加 | 高：可作为对应主题页主图 | 否 |
| 4. 带脊线频谱图 | `presentations/data/balanced_diagnostic/pdv_channel_2_stft_spectrogram_with_refined_ridge.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 局部频谱与离散/亚频点精修脊线叠加 | 高：可作为对应主题页主图 | 否 |
| 4. 带脊线频谱图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/stft_analysis_band_with_ridge.png` | run_20260724_004901_103968 | balanced | pdv_channel_1 | 0–2 GHz 分析显示及 0.05–2 GHz 候选脊线 | 高：可作为对应主题页主图 | 否 |
| 4. 带脊线频谱图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/stft_analysis_band_with_ridge.png` | run_20260724_004901_103968 | balanced | pdv_channel_2 | 0–2 GHz 分析显示及 0.05–2 GHz 候选脊线 | 高：可作为对应主题页主图 | 否 |
| 4. 带脊线频谱图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/stft_analysis_band_with_ridge.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_1 | 0–2 GHz 分析显示及 0.05–2 GHz 候选脊线 | 高：可作为对应主题页主图 | 否 |
| 4. 带脊线频谱图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/stft_analysis_band_with_ridge.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_2 | 0–2 GHz 分析显示及 0.05–2 GHz 候选脊线 | 高：可作为对应主题页主图 | 否 |
| 5. 完整时间—速度图 | `presentations/data/balanced_diagnostic/pdv_channel_1_full_display_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 前事件显示零、平台和下降段的表观速度全貌 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_2_full_display_velocity.png |
| 5. 完整时间—速度图 | `presentations/data/balanced_diagnostic/pdv_channel_1_presentation_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 前事件显示零、平台和下降段的表观速度全貌 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_2_presentation_velocity.png |
| 5. 完整时间—速度图 | `presentations/data/balanced_diagnostic/pdv_channel_2_full_display_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 前事件显示零、平台和下降段的表观速度全貌 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_1_full_display_velocity.png |
| 5. 完整时间—速度图 | `presentations/data/balanced_diagnostic/pdv_channel_2_presentation_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 前事件显示零、平台和下降段的表观速度全貌 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_1_presentation_velocity.png |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity.csv` | run_20260724_004901_103968 | balanced | pdv_channel_1 | 正式逐帧表观速度、状态、谱质量和显示列 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_full_preview.png` | run_20260724_004901_103968 | balanced | pdv_channel_1 | 完整 STFT 时间轴的质量未筛选开发预览；红段不是正式测量 | 低：仅可用于解释开发预览与正式结果的边界 | 完全重复组基准 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_full_time.png` | run_20260724_004901_103968 | balanced | pdv_channel_1 | 正式候选表观速度全时间图；未测区不插值 | 高：可作为对应主题页主图 | 完全重复组基准 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity.csv` | run_20260724_004901_103968 | balanced | pdv_channel_2 | 正式逐帧表观速度、状态、谱质量和显示列 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity_full_preview.png` | run_20260724_004901_103968 | balanced | pdv_channel_2 | 完整 STFT 时间轴的质量未筛选开发预览；红段不是正式测量 | 低：仅可用于解释开发预览与正式结果的边界 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity_full_time.png` | run_20260724_004901_103968 | balanced | pdv_channel_2 | 正式候选表观速度全时间图；未测区不插值 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_full_time.png；presentations/data/新软件速度时间图.png |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/apparent_velocity.csv` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_1 | 正式逐帧表观速度、状态、谱质量和显示列 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/apparent_velocity_full_preview.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_1 | 完整 STFT 时间轴的质量未筛选开发预览；红段不是正式测量 | 低：仅可用于解释开发预览与正式结果的边界 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/apparent_velocity_full_time.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_1 | 正式候选表观速度全时间图；未测区不插值 | 高：可作为对应主题页主图 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/apparent_velocity.csv` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_2 | 正式逐帧表观速度、状态、谱质量和显示列 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/apparent_velocity_full_preview.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_2 | 完整 STFT 时间轴的质量未筛选开发预览；红段不是正式测量 | 低：仅可用于解释开发预览与正式结果的边界 | 否 |
| 5. 完整时间—速度图 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/apparent_velocity_full_time.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_2 | 正式候选表观速度全时间图；未测区不插值 | 高：可作为对应主题页主图 | 否 |
| 5. 完整时间—速度图 | `presentations/data/完整时间轴.png` | 项目既有材料 | 不适用/未单列 | 未单列 | 完整时间—速度图相关材料 | 低：与正式 run 文件完全重复 | 完全重复；基准：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_full_preview.png |
| 6. 平台/起跳/下降段细节 | `presentations/data/balanced_diagnostic/pdv_channel_1_decline_detail.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 平台末段至下降段的逐帧亚频点表观速度 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_2_decline_detail.png |
| 6. 平台/起跳/下降段细节 | `presentations/data/balanced_diagnostic/pdv_channel_1_presentation_with_plateau_detail.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 平台全貌与平台逐帧波动细节 | 高：可作为对应主题页主图 | 否 |
| 6. 平台/起跳/下降段细节 | `presentations/data/balanced_diagnostic/pdv_channel_1_refined_ridge_velocity.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 离散/精修频率和表观速度的逐帧开发诊断 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 6. 平台/起跳/下降段细节 | `presentations/data/balanced_diagnostic/pdv_channel_2_decline_detail.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 平台末段至下降段的逐帧亚频点表观速度 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_1_decline_detail.png |
| 6. 平台/起跳/下降段细节 | `presentations/data/balanced_diagnostic/pdv_channel_2_presentation_with_plateau_detail.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 平台全貌与平台逐帧波动细节 | 高：可作为对应主题页主图 | 否 |
| 6. 平台/起跳/下降段细节 | `presentations/data/balanced_diagnostic/pdv_channel_2_refined_ridge_velocity.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 离散/精修频率和表观速度的逐帧开发诊断 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 6. 平台/起跳/下降段细节 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_event_detail.png` | run_20260724_004901_103968 | balanced | pdv_channel_1 | 事件起点附近的表观速度细节；含显示零与显示桥说明 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity_event_detail.png；presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/apparent_velocity_event_detail.png |
| 6. 平台/起跳/下降段细节 | `presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity_event_detail.png` | run_20260724_004901_103968 | balanced | pdv_channel_2 | 事件起点附近的表观速度细节；含显示零与显示桥说明 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_event_detail.png；presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/apparent_velocity_event_detail.png |
| 6. 平台/起跳/下降段细节 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_1/apparent_velocity_event_detail.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_1 | 事件起点附近的表观速度细节；含显示零与显示桥说明 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_event_detail.png；presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity_event_detail.png |
| 6. 平台/起跳/下降段细节 | `presentations/data/run_20260724_004901_103968/high_time_resolution/pdv_channel_2/apparent_velocity_event_detail.png` | run_20260724_004901_103968 | high_time_resolution | pdv_channel_2 | 事件起点附近的表观速度细节；含显示零与显示桥说明 | 高：可作为对应主题页主图 | 视觉近似：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_event_detail.png；presentations/data/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity_event_detail.png |
| 7. 参数或 profile 对比 | `presentations/data/balanced_diagnostic/pdv_channel_1_discrete_vs_refined_frequency.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 离散频点与三点亚频点精修频率对比 | 中高：适合作为方法/诊断证据 | 否 |
| 7. 参数或 profile 对比 | `presentations/data/balanced_diagnostic/pdv_channel_1_discrete_vs_refined_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 离散与精修表观速度对比；含显示零 | 中高：适合作为方法/诊断证据 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_2_discrete_vs_refined_velocity.png |
| 7. 参数或 profile 对比 | `presentations/data/balanced_diagnostic/pdv_channel_2_discrete_vs_refined_frequency.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 离散频点与三点亚频点精修频率对比 | 中高：适合作为方法/诊断证据 | 否 |
| 7. 参数或 profile 对比 | `presentations/data/balanced_diagnostic/pdv_channel_2_discrete_vs_refined_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 离散与精修表观速度对比；含显示零 | 中高：适合作为方法/诊断证据 | 视觉近似：presentations/data/balanced_diagnostic/pdv_channel_1_discrete_vs_refined_velocity.png |
| 8. 双通道对比 | `presentations/data/balanced_diagnostic/two_channel_continuity_comparison.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | 双通道 | 相邻成功帧的频率步长、斜率及状态诊断 | 高：可作为对应主题页主图 | 否 |
| 8. 双通道对比 | `presentations/data/balanced_diagnostic/two_channel_presentation_velocity.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | 双通道 | 前事件显示零、平台和下降段的表观速度全貌 | 高：可作为对应主题页主图 | 否 |
| 8. 双通道对比 | `presentations/data/balanced_diagnostic/two_channel_related_frequency_comparison.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | 双通道 | 主峰与二倍频/半频局部峰的描述性证据 | 高：可作为对应主题页主图 | 否 |
| 8. 双通道对比 | `presentations/data/balanced_diagnostic/two_channel_spectral_quality_comparison.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | 双通道 | 两采集通道的同类诊断量对比，不代表通道融合或准确度 | 高：可作为对应主题页主图 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_continuity_diagnostics.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 相邻成功帧的频率步长、斜率及状态诊断 | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_peak_to_background_db.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 主峰相对受保护频带外背景中位数的谱对比度（非 SNR） | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_peak_to_competitor_db.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 主峰相对剩余最强峰的谱优势量（非置信度） | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_related_frequency_contrasts.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 主峰与二倍频/半频局部峰的描述性证据 | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_related_frequency_evidence.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 主峰与二倍频/半频局部峰的描述性证据 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_ridge_continuity.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 相邻成功帧的频率步长、斜率及状态诊断 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_spectral_quality.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 逐帧谱背景和竞争峰对比度数据 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_1_stft_related_frequency_evidence.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_1 | 主脊线及二倍频/半频局部峰的诊断叠加 | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_continuity_diagnostics.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 相邻成功帧的频率步长、斜率及状态诊断 | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_peak_to_background_db.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 主峰相对受保护频带外背景中位数的谱对比度（非 SNR） | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_peak_to_competitor_db.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 主峰相对剩余最强峰的谱优势量（非置信度） | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_related_frequency_contrasts.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 主峰与二倍频/半频局部峰的描述性证据 | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_related_frequency_evidence.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 主峰与二倍频/半频局部峰的描述性证据 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_ridge_continuity.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 相邻成功帧的频率步长、斜率及状态诊断 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_spectral_quality.csv` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 逐帧谱背景和竞争峰对比度数据 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/balanced_diagnostic/pdv_channel_2_stft_related_frequency_evidence.png` | balanced_diagnostic（同一真实输入的开发诊断） | balanced | pdv_channel_2 | 主脊线及二倍频/半频局部峰的诊断叠加 | 中高：适合作为方法/诊断证据 | 否 |
| 9. 质量诊断 | `presentations/data/run_20260724_004901_103968/balanced/quality_summary.csv` | run_20260724_004901_103968 | balanced | 未单列 | 每通道候选帧、首帧、最低速度、谱对比度与连续性摘要 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 9. 质量诊断 | `presentations/data/run_20260724_004901_103968/high_time_resolution/quality_summary.csv` | run_20260724_004901_103968 | high_time_resolution | 未单列 | 每通道候选帧、首帧、最低速度、谱对比度与连续性摘要 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 10. 旧软件/当前软件对比 | `data/reference/legacy/legacy_velocity_time.csv` | legacy reference（来源待实验组确认） | 不适用/未单列 | 未单列 | 旧软件导出速度—时间曲线，仅用于历史对照，非物理真值 | 中：数据/标注来源，不直接铺满幻灯片 | 否 |
| 10. 旧软件/当前软件对比 | `presentations/data/新软件速度时间图.png` | 项目既有材料 | 不适用/未单列 | 未单列 | 当前正式 run 的表观速度全时间图；与旧软件曲线仅作开发历史对照 | 低：与正式 run 文件完全重复 | 完全重复；基准：presentations/data/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_full_time.png |
| 10. 旧软件/当前软件对比 | `presentations/data/旧软件速度时间图.png` | legacy reference（来源待实验组确认） | 不适用/未单列 | 未单列 | 旧软件导出速度—时间曲线，仅用于历史对照，非物理真值 | 高：可作为对应主题页主图 | 否 |

## 选图原则

1. 主结果图优先使用 `run_20260724_004901_103968/` 下的正式输出。
2. `balanced_diagnostic/` 仅用于解释亚频点精修、局部变化和描述性诊断，不替代正式输出。
3. `apparent_velocity_full_preview.png` 明确标为质量未筛选开发预览，不用于展示正式测量结果。
4. 双通道图只说明两个独立采集通道在这次数据中的同量级趋势，不能推出准确度、可信度或通道融合。
5. 旧软件导出及其图像来源尚需实验组确认，只用于开发历史和接口差异对照。
