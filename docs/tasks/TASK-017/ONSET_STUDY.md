# 起跳信号恢复专项

所有频率/时间来自当前真实原始波形。无独立测速真值，证据支持、门控通过和物理支路身份分开；`requires experimental confirmation` 适用于全部支路。没有用任何合成信号选择参数或验收。

69 个共同起跳中心：Balanced 候选 69、原门控 53、短窗证据支持 55；视觉起跳 VarPro 对应 69 / 68 / 64。

C=合法频带候选；G=原方法门控输出；S=统一短窗原波形支持。S 的明示规则为：原始 256 样本窗、局部线性基线后，候选邻域功率相对谱中位数 ≥10 dB、相对冻结起跳前背景 ≥6 dB，窗内 ≥1 周期，原始实值 tone 或该法 chirp 拟合 R²≥0.20。阈值是诊断定义，未经仪器实验校准；全部方法用相同原始电压验证，包括 Clutter VarPro，绝不只验证其扣除后的残差。

S 可能接受瞬态、杂散或谐波。特别是 `20201214m` 早期一个低频瞬态候选通过 S，却不能据此认作连续约 6.3 GHz 主支路的恢复。64 个 S 点绝不等于 64 个已确认速度测量。第一支持时间是同一规则首个中心，不是物理起跳真值，也不是因果检测延迟：居中窗用到未来样本。

| method | centers | candidate_n | gated_n | supported_n | supported_common50_6_n | 支持比例% | 通道均值支持% |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 69 | 69 | 53 | 55 | 55 | 79.710 | 76.786 |
| formal_short512 | 69 | 69 | 52 | 56 | 56 | 81.159 | 76.786 |
| formal_long2048 | 69 | 69 | 62 | 57 | 57 | 82.609 | 81.429 |
| balanced_wide8 | 69 | 69 | 53 | 55 | 55 | 79.710 | 76.786 |
| short_wide8 | 69 | 69 | 52 | 56 | 56 | 81.159 | 76.786 |
| stft_short | 69 | 69 | 65 | 61 | 61 | 88.406 | 86.905 |
| stft_long | 69 | 69 | 69 | 57 | 57 | 82.609 | 83.333 |
| stft_low | 69 | 69 | 0 | 0 | 0 | 0.000 | 0.000 |
| low_glrt | 69 | 69 | 0 | 2 | 2 | 2.899 | 1.786 |
| tone_refine | 69 | 69 | 69 | 57 | 57 | 82.609 | 83.333 |
| signed_dechirp | 69 | 68 | 63 | 63 | 63 | 91.304 | 91.607 |
| stage_stft1024 | 69 | 69 | 69 | 57 | 57 | 82.609 | 83.333 |
| unclipped_short | 69 | 69 | 62 | 63 | 63 | 91.304 | 89.762 |
| dechirp | 69 | 66 | 64 | 63 | 62 | 91.304 | 88.214 |
| varpro | 69 | 66 | 65 | 61 | 59 | 88.406 | 86.429 |
| clutter_varpro | 69 | 66 | 65 | 61 | 59 | 88.406 | 86.429 |
| acmd | 69 | 66 | 60 | 60 | 59 | 86.957 | 83.214 |
| matrix_pencil | 69 | 66 | 61 | 62 | 59 | 89.855 | 86.429 |
| time_domain | 69 | 66 | 58 | 58 | 58 | 84.058 | 80.357 |
| visual_onset_dechirp | 69 | 68 | 66 | 64 | 63 | 92.754 | 93.036 |
| visual_onset_varpro | 69 | 69 | 68 | 64 | 62 | 92.754 | 93.571 |
| M2_task014_gui | 69 | 69 | 53 | 55 | 55 | 79.710 | 76.786 |
| M3_parameters | 69 | 69 | 65 | 61 | 61 | 88.406 | 86.905 |
| M4_specialized | 69 | 69 | 65 | 61 | 61 | 88.406 | 86.905 |
| TASK014_research_simple | 69 | 69 | 68 | 62 | 61 | 89.855 | 88.333 |
| demean1024_control | 69 | 69 | 57 | 60 | 60 | 86.957 | 85.595 |
| detrend1024_control | 69 | 69 | 57 | 61 | 61 | 88.406 | 87.024 |
| demean512_control | 69 | 69 | 62 | 63 | 63 | 91.304 | 89.762 |

VarPro 原生频带到 8 GHz，不能把该列直接当成与 6 GHz 基准完全等条件的算法收益。共同 50 MHz–6 GHz 支持数分别为 Balanced 55、去均值短窗 63、视觉 Dechirp 63、视觉 VarPro 62。候选覆盖 69/69 没有增长；VarPro 的 11 个新增 S 中心与 2 个 S 损失并存，净增 9。以文件/通道判断，视觉 VarPro 的净增集中在 4 个通道、4 个文件，其余 10 路净计数相同；并非 69 次独立试验。

| channel | centers | base_supported_n | supported_n | supported_gain_n | supported_loss_n | same_base_candidate_rejected_n | different_supported_candidate_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20201210m_ch1 | 3 | 0 | 3 | 3 | 0 | 0 | 3 |
| 20201211m_ch1 | 4 | 1 | 3 | 2 | 0 | 1 | 2 |
| 20201214m_ch1 | 5 | 0 | 3 | 3 | 0 | 0 | 3 |
| 20221017a_ch1 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| 20231019-ch1_ch1 | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| 20260607_ch1 | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| 20260607_ch2 | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| 20260630-1_ch1 | 8 | 7 | 7 | 1 | 1 | 0 | 1 |
| 20260630-1_ch2 | 8 | 7 | 7 | 1 | 1 | 0 | 1 |
| 20260630-2_ch1 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| 20260630-2_ch2 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| 20260701_ch1 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| 20260701_ch2 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| ch3_ch1 | 4 | 3 | 4 | 1 | 0 | 0 | 1 |

“same_base_candidate_rejected”只表示两个候选相差不超过显式容差且原 M1 拒绝，不能证明改法只撤门控；完整对照更直接：单纯把 M1 的 G 换成 C，会多显示 16 点，但其中仅 3 点满足 S。其余 13 点不能因为放宽门控就当作恢复；不同候选支路必须回查原始谱。

![起跳计数](../../../artifacts/TASK-017/figures/highlights_v01/onset_counts.png)

## 逐条起跳回答

### 20201210m_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 3 | 3 | 0 | 0 | 0 | — |
| stft_short | 3 | 3 | 3 | 2 | 0 | 1.38760807530e-04 |
| tone_refine | 3 | 3 | 3 | 2 | 0 | 1.38760807530e-04 |
| dechirp | 3 | 0 | 0 | 0 | 0 | — |
| visual_onset_dechirp | 3 | 3 | 3 | 3 | 0 | 1.38757607530e-04 |
| visual_onset_varpro | 3 | 3 | 3 | 3 | 0 | 1.38757607530e-04 |
| M4_specialized | 3 | 3 | 3 | 2 | 0 | 1.38760807530e-04 |
| demean1024_control | 3 | 3 | 1 | 1 | 1 | 1.38764007530e-04 |
| demean512_control | 3 | 3 | 2 | 2 | 1 | 1.38760807530e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20201210m_ch1__onset_card.png)

原始电压有缓慢基线抬升和随后 GHz 振荡。M1 近频带下限的候选没有支持连续主线；旧 Context 没有事件，native VarPro 全程没有候选。视觉边界让同一个 VarPro 实现计算 3 个约 3.5–3.8 GHz 起跳候选；去均值短窗/阶段短窗各支持 2 个，说明 DC 投影有主要贡献，VarPro 另多 1 个局部支持中心。这是有原始谱/电压支撑的条件性恢复，目标身份仍待实验确认。

### 20201211m_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 4 | 4 | 0 | 1 | 1 | 1.07749602410e-04 |
| stft_short | 4 | 4 | 4 | 3 | 0 | 1.07743202410e-04 |
| tone_refine | 4 | 4 | 4 | 3 | 0 | 1.07743202410e-04 |
| dechirp | 4 | 4 | 3 | 3 | 1 | 1.07743202410e-04 |
| visual_onset_dechirp | 4 | 4 | 3 | 3 | 0 | 1.07743202410e-04 |
| visual_onset_varpro | 4 | 4 | 3 | 3 | 0 | 1.07743202410e-04 |
| M4_specialized | 4 | 4 | 4 | 3 | 0 | 1.07743202410e-04 |
| demean1024_control | 4 | 4 | 3 | 3 | 1 | 1.07743202410e-04 |
| demean512_control | 4 | 4 | 3 | 3 | 1 | 1.07743202410e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20201211m_ch1__onset_card.png)

以本表比较候选/门控/支持，完整谱叠加见图册。已有主线清晰的记录，专项方法没有建立额外物理信息的证据；起跳瞬态与背景分开，未把缺失补为零。

### 20201214m_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 5 | 5 | 0 | 0 | 0 | — |
| stft_short | 5 | 5 | 1 | 0 | 0 | — |
| tone_refine | 5 | 5 | 5 | 0 | 0 | — |
| dechirp | 5 | 5 | 4 | 3 | 1 | 8.29592022800e-05 |
| visual_onset_dechirp | 5 | 4 | 3 | 2 | 1 | 8.29592022800e-05 |
| visual_onset_varpro | 5 | 5 | 5 | 3 | 2 | 8.29592022800e-05 |
| M4_specialized | 5 | 5 | 1 | 0 | 0 | — |
| demean1024_control | 5 | 5 | 1 | 2 | 0 | 8.29592022800e-05 |
| demean512_control | 5 | 5 | 2 | 2 | 0 | 8.29592022800e-05 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20201214m_ch1__onset_card.png)

全 Nyquist 图的平台高于 6 GHz；只扩到 8 GHz 而不处理 DC 起跳段仍只有 0 个 S。VarPro 原生输出约 6.3 GHz 的后续候选；早期低频瞬态即使通过 S 也不能确认为主支路。此例混合了频带排除与基线/瞬态问题，不能全部记为 VarPro 相对同频带 STFT 的优势。

### 20221017a_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| stft_short | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| tone_refine | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| dechirp | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| visual_onset_dechirp | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| visual_onset_varpro | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| M4_specialized | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| demean1024_control | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |
| demean512_control | 5 | 5 | 5 | 5 | 0 | 8.77194318200e-05 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20221017a_ch1__onset_card.png)

以本表比较候选/门控/支持，完整谱叠加见图册。已有主线清晰的记录，专项方法没有建立额外物理信息的证据；起跳瞬态与背景分开，未把缺失补为零。

### 20231019-ch1_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| stft_short | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| tone_refine | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| dechirp | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| visual_onset_dechirp | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| visual_onset_varpro | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| M4_specialized | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| demean1024_control | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |
| demean512_control | 4 | 4 | 4 | 4 | 0 | 8.94206524700e-05 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20231019-ch1_ch1__onset_card.png)

以本表比较候选/门控/支持，完整谱叠加见图册。已有主线清晰的记录，专项方法没有建立额外物理信息的证据；起跳瞬态与背景分开，未把缺失补为零。

### 20260607_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| stft_short | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| tone_refine | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| dechirp | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| visual_onset_dechirp | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| visual_onset_varpro | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| M4_specialized | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| demean1024_control | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| demean512_control | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260607_ch1__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260607_ch2

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| stft_short | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| tone_refine | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| dechirp | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| visual_onset_dechirp | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| visual_onset_varpro | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| M4_specialized | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| demean1024_control | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |
| demean512_control | 4 | 4 | 4 | 4 | 0 | 5.54670654260e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260607_ch2__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260630-1_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 8 | 8 | 6 | 7 | 1 | 7.46216414990e-04 |
| stft_short | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| tone_refine | 8 | 8 | 8 | 6 | 0 | 7.46222814990e-04 |
| dechirp | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| visual_onset_dechirp | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| visual_onset_varpro | 8 | 8 | 8 | 7 | 0 | 7.46219614990e-04 |
| M4_specialized | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| demean1024_control | 8 | 8 | 7 | 7 | 1 | 7.46216414990e-04 |
| demean512_control | 8 | 8 | 7 | 8 | 1 | 7.46216414990e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260630-1_ch1__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260630-1_ch2

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 8 | 8 | 6 | 7 | 1 | 7.46216414990e-04 |
| stft_short | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| tone_refine | 8 | 8 | 8 | 6 | 0 | 7.46222814990e-04 |
| dechirp | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| visual_onset_dechirp | 8 | 8 | 8 | 7 | 0 | 7.46219614990e-04 |
| visual_onset_varpro | 8 | 8 | 8 | 7 | 1 | 7.46219614990e-04 |
| M4_specialized | 8 | 8 | 8 | 8 | 0 | 7.46216414990e-04 |
| demean1024_control | 8 | 8 | 7 | 7 | 1 | 7.46216414990e-04 |
| demean512_control | 8 | 8 | 7 | 8 | 1 | 7.46216414990e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260630-1_ch2__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260630-2_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| stft_short | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| tone_refine | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| dechirp | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| visual_onset_dechirp | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| visual_onset_varpro | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| M4_specialized | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| demean1024_control | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| demean512_control | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260630-2_ch1__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260630-2_ch2

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| stft_short | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| tone_refine | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| dechirp | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| visual_onset_dechirp | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| visual_onset_varpro | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| M4_specialized | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| demean1024_control | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |
| demean512_control | 5 | 5 | 5 | 5 | 0 | 5.40218850320e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260630-2_ch2__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260701_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| stft_short | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| tone_refine | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| dechirp | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| visual_onset_dechirp | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| visual_onset_varpro | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| M4_specialized | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| demean1024_control | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| demean512_control | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260701_ch1__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### 20260701_ch2

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| stft_short | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| tone_refine | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| dechirp | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| visual_onset_dechirp | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| visual_onset_varpro | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| M4_specialized | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| demean1024_control | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |
| demean512_control | 5 | 5 | 5 | 5 | 0 | 6.56847266340e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/20260701_ch2__onset_card.png)

多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，不把单个跳变或更平滑曲线作优胜证据。

### ch3_ch1

| method | centers | candidate_n | gated_n | supported_n | jump_250MHz_n | first_supported_time_s |
| --- | --- | --- | --- | --- | --- | --- |
| M1_balanced | 4 | 4 | 4 | 3 | 0 | 1.83651753140e-04 |
| stft_short | 4 | 4 | 4 | 3 | 0 | 1.83651753140e-04 |
| tone_refine | 4 | 4 | 4 | 3 | 0 | 1.83651753140e-04 |
| dechirp | 4 | 4 | 4 | 4 | 0 | 1.83648553140e-04 |
| visual_onset_dechirp | 4 | 4 | 4 | 4 | 0 | 1.83648553140e-04 |
| visual_onset_varpro | 4 | 4 | 4 | 4 | 0 | 1.83648553140e-04 |
| M4_specialized | 4 | 4 | 4 | 3 | 0 | 1.83651753140e-04 |
| demean1024_control | 4 | 4 | 1 | 3 | 0 | 1.83651753140e-04 |
| demean512_control | 4 | 4 | 4 | 3 | 0 | 1.83651753140e-04 |

![原始证据与候选](../../../artifacts/TASK-017/figures/highlights_v01/ch3_ch1__onset_card.png)

可见建立段只有弱且间歇的约 3.6–3.9 GHz 支路，随后幅度塌陷、支路跳变和宽带终止脉冲。VarPro 起跳 S 比基准多 1，但不支持把整个记录连成可靠物理速度曲线；失败区与候选冲突保留。

## 边界与低频补充

| method | boundary | shift_ns | candidate_n | gated_n | supported_n |
| --- | --- | --- | --- | --- | --- |
| stft_short | none | 0.000 | 69 | 65 | 61 |
| dechirp | none | 0.000 | 68 | 66 | 64 |
| varpro | none | 0.000 | 69 | 68 | 64 |
| stft_short | start | -5.000 | 69 | 62 | 63 |
| dechirp | start | -5.000 | 69 | 67 | 65 |
| varpro | start | -5.000 | 69 | 68 | 63 |
| stft_short | start | -2.000 | 69 | 62 | 63 |
| dechirp | start | -2.000 | 69 | 67 | 65 |
| varpro | start | -2.000 | 69 | 68 | 63 |
| stft_short | start | 2.000 | 69 | 60 | 55 |
| dechirp | start | 2.000 | 61 | 60 | 56 |
| varpro | start | 2.000 | 61 | 61 | 58 |
| stft_short | start | 5.000 | 69 | 63 | 62 |
| dechirp | start | 5.000 | 46 | 46 | 46 |
| varpro | start | 5.000 | 46 | 46 | 45 |
| stft_short | end | -5.000 | 69 | 64 | 61 |
| stft_short | end | -2.000 | 69 | 65 | 61 |
| stft_short | end | 2.000 | 69 | 65 | 61 |
| stft_short | end | 5.000 | 69 | 65 | 61 |

同一原波形、原冻结起跳中心作固定分母；±2/±5 ns 改动不是新实验。起始边界迟移 +2/+5 ns 时，视觉 VarPro 的 S 由 64 降至 58/45；视觉 Dechirp 由 64 降至 56/46。裁剪短窗对起跳结束边界较稳定，对起始边界并非单调稳定；完整 CSV 保留频率差与质量状态。这限制了依靠精确人工起跳先验的推广。

低频另用 4096 样本的原始电压支撑核查 M1、低频 STFT、GLRT 中实际 ≤250 MHz 的候选，结果在 low_support_v01。13 路有足够前背景，20201210m 不足，明确记 unavailable；没有任何具有有效背景的起跳低频候选通过该长窗联合规则。该窗在 40/80 GHz 采样下为 102.4/51.2 ns，不可解释为对 7–23 ns 起跳的精确时间恢复。原生 GLRT 起跳 G 为 0/69；本批未提供可确认的低频真实目标来验证其低速优势。


## 20201210m 背景前缀重叠复核

当前 Context 的背景前缀为 4000 点（约 100.0 ns）；冻结视觉起跳位于第 2192 点（约 54.8 ns）。前缀中有 1808 点处于该边界之后，约占 45.2%。因此 quiet-prefix 假设在本案例被视觉证据直接违反，原自动能量检测确实返回 NO_CONFIRMED_ENERGY_CHANGE。混入 DC 变化和已建立振荡会改变它估计的背景尺度和阈值，是整条不生成候选的明确机制线索；没有额外做因果标定或篡改原波形。Clutter VarPro 此例前缀拟合未达扣除门槛，故不是目标被相干扣除的实证。完整数值见 [prefix_overlap.json](../../../artifacts/TASK-017/data/prefix_overlap.json)。
