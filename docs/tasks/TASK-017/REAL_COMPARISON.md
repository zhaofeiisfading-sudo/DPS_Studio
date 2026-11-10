# 真实数据完整比较与阶段建议

所有频率/时间来自当前真实原始波形。无独立测速真值，证据支持、门控通过和物理支路身份分开；`requires experimental confirmation` 适用于全部支路。没有用任何合成信号选择参数或验收。

主比较共 28 个方法/控制/路由，14 通道，392 个完整方法流。前 25 个在 full_v01，3 个 DC 控制在 dc_controls_v01；全部轨迹的最终共同中心、CSV、门控和原始诊断在 analysis_v03。这些路由不是 28 个相互独立的算法。每条 CSV 保留原始合法候选、非法原始值、缺失原因、门控、谱支持、原始电压残差、跳变可复算数据、来源、阶段和通道；波长/速度字段 NaN。

| stage | method | centers | candidate_n | gated_n | supported_n |
| --- | --- | --- | --- | --- | --- |
| onset | M1_balanced | 69 | 69 | 53 | 55 |
| plateau | M1_balanced | 2342 | 2342 | 1924 | 1942 |
| decline | M1_balanced | 699 | 699 | 554 | 554 |
| onset | stft_short | 69 | 69 | 65 | 61 |
| plateau | stft_short | 2342 | 2342 | 2227 | 2227 |
| decline | stft_short | 699 | 699 | 667 | 660 |
| onset | tone_refine | 69 | 69 | 69 | 57 |
| plateau | tone_refine | 2342 | 2342 | 2202 | 2216 |
| decline | tone_refine | 699 | 699 | 394 | 627 |
| onset | dechirp | 69 | 66 | 64 | 63 |
| plateau | dechirp | 2342 | 2200 | 2197 | 2197 |
| decline | dechirp | 699 | 657 | 646 | 633 |
| onset | visual_onset_dechirp | 69 | 68 | 66 | 64 |
| plateau | visual_onset_dechirp | 2342 | 2342 | 2339 | 2339 |
| decline | visual_onset_dechirp | 699 | 699 | 687 | 674 |
| onset | visual_onset_varpro | 69 | 69 | 68 | 64 |
| plateau | visual_onset_varpro | 2342 | 2342 | 2339 | 2339 |
| decline | visual_onset_varpro | 699 | 699 | 686 | 673 |
| onset | M4_specialized | 69 | 69 | 65 | 61 |
| plateau | M4_specialized | 2342 | 2342 | 2202 | 2216 |
| decline | M4_specialized | 699 | 699 | 668 | 662 |
| onset | demean1024_control | 69 | 69 | 57 | 60 |
| plateau | demean1024_control | 2342 | 2339 | 2202 | 2227 |
| decline | demean1024_control | 699 | 695 | 590 | 657 |
| onset | demean512_control | 69 | 69 | 62 | 63 |
| plateau | demean512_control | 2342 | 2338 | 2227 | 2227 |
| decline | demean512_control | 699 | 694 | 667 | 658 |
| weak_signal | M1_balanced | 624 | 624 | 482 | 487 |
| weak_signal | stft_short | 624 | 624 | 527 | 491 |
| weak_signal | tone_refine | 624 | 624 | 469 | 472 |
| weak_signal | dechirp | 624 | 624 | 565 | 514 |
| weak_signal | visual_onset_dechirp | 624 | 624 | 565 | 514 |
| weak_signal | visual_onset_varpro | 624 | 624 | 563 | 514 |
| weak_signal | M4_specialized | 624 | 624 | 454 | 471 |
| weak_signal | demean1024_control | 624 | 624 | 512 | 488 |
| weak_signal | demean512_control | 624 | 624 | 523 | 492 |
| acceleration | M1_balanced | 97 | 97 | 97 | 97 |
| acceleration | stft_short | 97 | 97 | 97 | 97 |
| acceleration | tone_refine | 97 | 97 | 97 | 97 |
| acceleration | dechirp | 97 | 97 | 97 | 97 |
| acceleration | visual_onset_dechirp | 97 | 97 | 97 | 97 |
| acceleration | visual_onset_varpro | 97 | 97 | 97 | 97 |
| acceleration | M4_specialized | 97 | 97 | 97 | 97 |
| acceleration | demean1024_control | 97 | 97 | 97 | 97 |
| acceleration | demean512_control | 97 | 97 | 97 | 97 |
| rebound | M1_balanced | 72 | 72 | 72 | 72 |
| rebound | stft_short | 72 | 72 | 72 | 72 |
| rebound | tone_refine | 72 | 72 | 72 | 72 |
| rebound | dechirp | 72 | 72 | 72 | 72 |
| rebound | visual_onset_dechirp | 72 | 72 | 72 | 72 |
| rebound | visual_onset_varpro | 72 | 72 | 72 | 72 |
| rebound | M4_specialized | 72 | 72 | 72 | 72 |
| rebound | demean1024_control | 72 | 72 | 72 | 72 |
| rebound | demean512_control | 72 | 72 | 72 | 72 |

表中 n 为相关中心数量，不能用于独立重复推断。逐通道、逐阶段与完整分母见 segment_metrics.csv；没有单一综合评分。`raw_tone_r2/raw_chirp_r2` 及残差 RMS 是在同一 256 点原始支撑的样本内模型比较，不是误差、置信度或独立验证；有更灵活参数的拟合较好也不能证明物理正确。相邻跳变阈值为 250 MHz，只作描述，快速真实过程同样可能超过它，不能自动删点。

## Research 决策表

| 实际条件/阶段 | 推荐候选 | 次选 | 本批证据与覆盖 | 失败/适用条件 |
|---|---|---|---|---|
| 起跳伴 DC 基线或下限泄漏 | 显式去均值短窗 / 阶段短窗 | 视觉起跳 Dechirp、VarPro | 同频带去均值512支持63/69，基准55/69；20201210m视觉VP3/3 | 手工边界晚移会丢点；瞬态支持不等于主支路；保留原候选 |
| 主线清晰的起跳 | 保留 STFT 并查看候选 | 以上专项作为对照 | 多数通道起跳 S 无净计数增加 | 不为高覆盖而强行换法 |
| 快速下降 | 短窗基线投影；比较 VarPro/Dechirp | 阶段专项有符号 chirp | 基准554/699 S，去均值512为658，视觉VP673，M4为662 | Native自动事件可整条失效；长tone局部定频模型可能失配；频带也有差异 |
| 短暂回升 | 保留 STFT 作对照，证据不足以专推 | 短窗、Dechirp、VarPro | 同一文件双通道，72/72多法均有支持 | 只有一个独立文件；无专项净优势证据 |
| 窄带平台 | 先核对频带和 DC，再比较短/长窗 | 长窗正弦精修 | tone2216/2342 S，短均值2227，视觉VP2339；6.3GHz例有频带影响 | 本批不证明长窗更准确；长窗会混合边界；需报告残差/竞争峰 |
| 弱信号/塌陷 | 保留多法冲突与 NaN | Dechirp/VarPro 条件性候选 | 基准487/624 S，Dechirp/视觉VP514；长tone472 | 无法可靠复原所有弱段；不桥接消光；模型候选不作测量 |
| 静止/低频先验 | 先验独立记录，不输出实测零 | 低频 GLRT 仅实验条件满足时手选 | 本批起跳 GLRT0/69 G；无确认低速目标 | 低频模型、周期数和前端未知；不能凭先验产生速度 |
| 固定杂散 | 本批证据不足以专推 Clutter VP | 原始 VarPro并行对照 | 14/14前缀未达扣除条件，结果退化为VP | 未测试到符合相干固定杂散条件的真实正例；目标在前缀时存在误扣风险 |

前后缀噪声候选可有谱支持，但没有可确认运动身份；本次没有准确率、真实 RMSE、符号速度或校正速度结论。ACMD 变体、LS Matrix Pencil 与正则化时域法真实运行且保留负结果，起跳 S 为60/62/58，没有优于简单去均值短窗的总体证据。ACMD 是现有单模态启发式变体；时域法有模型正则化，其内部模型初始化/频率基函数不等于对缺失测量作事后插值。未新增滤波或曲线平滑。

## 成本与可复现性

metadata.json 逐方法记录实际 wall time、窗口、频带、代码来源；Context 初始化另列。数值库单线程，但有 3 条真实记录并发，因此只报告执行成本，不作方法间硬件加速比。路由成本是所有用到整轨组件成本之和，包含重算，不是优化后按段 GUI 延迟。

| method | median | min | max |
| --- | --- | --- | --- |
| M1_balanced | 0.634 | 0.310 | 1.978 |
| M2_task014_gui | 0.639 | 0.310 | 1.978 |
| M3_parameters | 3.237 | 1.813 | 7.599 |
| M4_specialized | 26.996 | 12.362 | 63.381 |
| TASK014_research_simple | 3.140 | 1.043 | 16.743 |
| acmd | 0.150 | 0.018 | 0.319 |
| balanced_wide8 | 0.659 | 0.336 | 1.994 |
| clutter_varpro | 3.874 | 0.109 | 8.145 |
| dechirp | 0.755 | 0.004 | 1.686 |
| demean1024_control | 0.554 | 0.253 | 1.437 |
| demean512_control | 0.502 | 0.254 | 1.249 |
| detrend1024_control | 0.618 | 0.262 | 1.571 |
| formal_long2048 | 0.690 | 0.333 | 1.756 |
| formal_short512 | 0.669 | 0.331 | 1.795 |
| low_glrt | 13.709 | 4.266 | 31.723 |
| matrix_pencil | 0.289 | 0.006 | 0.596 |
| short_wide8 | 0.702 | 0.314 | 1.721 |
| signed_dechirp | 4.540 | 2.484 | 12.063 |
| stage_stft1024 | 0.676 | 0.312 | 1.749 |
| stft_long | 0.815 | 0.419 | 2.111 |
| stft_low | 1.646 | 0.719 | 4.143 |
| stft_short | 0.578 | 0.324 | 1.471 |
| time_domain | 0.431 | 0.008 | 0.904 |
| tone_refine | 3.281 | 1.652 | 8.635 |
| unclipped_short | 0.578 | 0.299 | 1.618 |
| varpro | 3.712 | 0.006 | 7.647 |
| visual_onset_dechirp | 0.931 | 0.501 | 2.029 |
| visual_onset_varpro | 3.881 | 2.199 | 8.323 |
