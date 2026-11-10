# 模型实际视觉分段

所有频率/时间来自当前真实原始波形。无独立测速真值，证据支持、门控通过和物理支路身份分开；`requires experimental confirmation` 适用于全部支路。没有用任何合成信号选择参数或验收。

Codex 使用图像工具实际查看全部 14 张原始全程图和 14 张起跳局部图，随后才生成算法重建。视觉冻结 JSON、UTC 时间和这 28 张 PNG 的 SHA-256 在 [visual_freeze.json](../../../artifacts/TASK-017/data/visual_freeze.json)。算法入口验证标注/输入哈希。原图仅包含电压、统一 1024 点和 256 点 Hann 图，不包含重建轨迹。用户两张图仅作示意，没有拷贝分界时间或阶段数。

`stationary` 是背景/静止操作先验，绝非 AC 耦合无信号的零速度实测；有直流前驱或干扰的不确定段另标 unknown。阶段名称描述拍频形态，不证明速度方向或目标身份。置信度是视觉判断等级；±ns 是边界合理范围，不是统计置信区间。`ch3` 不强行标平台。两个回升段来自同一文件的两通道，只有一个文件层面的案例。

| 阶段 | 段数 |
| --- | --- |
| acceleration | 1 |
| decline | 14 |
| noise | 14 |
| onset | 14 |
| plateau | 17 |
| rebound | 2 |
| stationary | 13 |
| unknown | 10 |
| weak_signal | 17 |

## 20201210m_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 138.700 | 138.720 | stationary | high | 0.000 | 5.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 138.720 | 138.755 | unknown | medium | 5.000 | 1.500 | Slow DC precursor; no resolved moving beat |
| s02 | 138.755 | 138.767 | onset | high | 1.500 | 4.000 | Voltage step and first sustained ~3.7 GHz oscillations |
| s03 | 138.767 | 139.220 | plateau | high | 4.000 | 10.000 | Narrow nearly horizontal ~3.7 GHz ridge |
| s04 | 139.220 | 139.355 | decline | high | 10.000 | 8.000 | Main ridge bends downward toward ~2.3 GHz |
| s05 | 139.355 | 139.470 | unknown | medium | 8.000 | 15.000 | Discontinuous lower branch; identity cannot be followed |
| s06 | 139.470 | 139.700 | noise | high | 15.000 | 0.000 | Main coherent ridge lost; residual background |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20201210m_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20201210m_ch1__onset_review.png)

## 20201211m_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 107.500 | 107.700 | stationary | high | 0.000 | 8.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 107.700 | 107.738 | unknown | medium | 8.000 | 1.500 | DC excursion before establishment of GHz beat |
| s02 | 107.738 | 107.751 | onset | high | 1.500 | 4.000 | Negative impulse and establishment of ~4.8 GHz beat |
| s03 | 107.751 | 108.270 | plateau | high | 4.000 | 10.000 | Sustained ~4.8 GHz ridge, background remains strong |
| s04 | 108.270 | 108.385 | decline | high | 10.000 | 10.000 | Resolved downward branch |
| s05 | 108.385 | 108.475 | weak_signal | medium | 10.000 | 12.000 | Weak lower branches and ambiguous handoff |
| s06 | 108.475 | 108.500 | noise | high | 12.000 | 0.000 | No sustained main branch |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20201211m_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20201211m_ch1__onset_review.png)

## 20201214m_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 82.700 | 82.910 | stationary | high | 0.000 | 10.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 82.910 | 82.959 | unknown | medium | 10.000 | 2.000 | Large low-frequency baseline structure; no certified zero |
| s02 | 82.959 | 82.974 | onset | high | 2.000 | 5.000 | Bipolar transient followed by ~6.3 GHz oscillations |
| s03 | 82.974 | 83.340 | plateau | high | 5.000 | 10.000 | Narrow plateau ABOVE 6 GHz; excluded by fixed baseline band |
| s04 | 83.340 | 83.445 | decline | high | 10.000 | 10.000 | ~6.3 GHz ridge slopes downward |
| s05 | 83.445 | 83.485 | unknown | medium | 10.000 | 8.000 | Abrupt branch handoff from ~4.6 to ~2 GHz |
| s06 | 83.485 | 83.550 | decline | high | 8.000 | 12.000 | Lower branch continues downward |
| s07 | 83.550 | 83.610 | weak_signal | medium | 12.000 | 15.000 | Weak low-frequency tail |
| s08 | 83.610 | 83.700 | noise | high | 15.000 | 0.000 | No reliable continuous ridge |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20201214m_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20201214m_ch1__onset_review.png)

## 20221017a_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 87.459 | 87.719 | unknown | medium | 0.000 | 1.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 87.719 | 87.726 | onset | high | 1.000 | 3.000 | Abrupt strong ~4.4 GHz beat above pre-existing ~1.5-2 GHz background |
| s02 | 87.726 | 88.150 | plateau | high | 3.000 | 8.000 | Stable narrow ~4.4 GHz line; amplitude decays later |
| s03 | 88.150 | 88.245 | decline | high | 8.000 | 12.000 | Continuous downward ridge |
| s04 | 88.245 | 88.310 | weak_signal | medium | 12.000 | 15.000 | Ridge fades toward background |
| s05 | 88.310 | 88.459 | noise | high | 15.000 | 0.000 | No reliable continuing beat |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20221017a_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20221017a_ch1__onset_review.png)

## 20231019-ch1_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 89.304 | 89.419 | stationary | high | 0.000 | 1.200 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 89.419 | 89.427 | onset | high | 1.200 | 3.000 | Impulse followed by high-amplitude ~4.1 GHz oscillations |
| s02 | 89.427 | 89.610 | plateau | high | 3.000 | 12.000 | Nearly horizontal main branch |
| s03 | 89.610 | 89.765 | acceleration | high | 12.000 | 10.000 | Gradual upward drift toward ~4.4 GHz |
| s04 | 89.765 | 89.985 | decline | high | 10.000 | 8.000 | Main ridge falls toward ~2.2 GHz |
| s05 | 89.985 | 90.040 | unknown | medium | 8.000 | 10.000 | Abrupt low-branch handoff; no unique identity |
| s06 | 90.040 | 90.120 | weak_signal | medium | 10.000 | 15.000 | Weak rising low-frequency tail, ambiguous branch |
| s07 | 90.120 | 90.304 | noise | high | 15.000 | 0.000 | No reliable coherent tail |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20231019-ch1_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20231019-ch1_ch1__onset_review.png)

## 20260607_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 553.960 | 554.668 | stationary | high | 0.000 | 2.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 554.668 | 554.682 | onset | high | 2.000 | 4.000 | Oscillations grow with ~0.7 GHz line and parallel multiples |
| s02 | 554.682 | 555.170 | plateau | high | 4.000 | 12.000 | Persistent ~0.7 GHz line plus ~1.4/2.1 GHz components |
| s03 | 555.170 | 555.340 | decline | high | 12.000 | 12.000 | All visible parallel ridges bend downward |
| s04 | 555.340 | 555.510 | weak_signal | medium | 12.000 | 12.000 | Low-frequency tail with poor cycle support |
| s05 | 555.510 | 555.660 | unknown | medium | 12.000 | 15.000 | Pulse and competing low-frequency branches |
| s06 | 555.660 | 555.960 | noise | high | 15.000 | 0.000 | No sustained main ridge |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260607_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260607_ch1__onset_review.png)

## 20260607_ch2

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 553.960 | 554.668 | stationary | high | 0.000 | 2.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 554.668 | 554.682 | onset | high | 2.000 | 4.000 | Own-channel voltage oscillations establish ~0.7 GHz; upper clipping possible |
| s02 | 554.682 | 555.170 | plateau | high | 4.000 | 12.000 | Own-channel narrow line and parallel multiples |
| s03 | 555.170 | 555.340 | decline | high | 12.000 | 12.000 | Parallel ridges bend downward |
| s04 | 555.340 | 555.510 | weak_signal | medium | 12.000 | 12.000 | Low-frequency weak tail |
| s05 | 555.510 | 555.660 | unknown | medium | 12.000 | 15.000 | Competing residual branches and pulses |
| s06 | 555.660 | 555.960 | noise | high | 15.000 | 0.000 | Main line no longer reliable |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260607_ch2/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260607_ch2__onset_review.png)

## 20260630-1_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 743.954 | 746.216 | stationary | high | 0.000 | 2.500 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 746.216 | 746.239 | onset | high | 2.500 | 5.000 | Voltage leaves background and clips; ~0.55 GHz plus many harmonics |
| s02 | 746.239 | 746.730 | plateau | high | 5.000 | 15.000 | Stable fundamental-like line and odd harmonic ladder; target identity unverified |
| s03 | 746.730 | 746.915 | decline | high | 15.000 | 10.000 | Harmonic ladder bends downward |
| s04 | 746.915 | 746.995 | weak_signal | medium | 10.000 | 12.000 | Low-frequency minimum; amplitude dropout |
| s05 | 746.995 | 747.110 | rebound | high | 12.000 | 12.000 | Visible line and multiples rise after minimum |
| s06 | 747.110 | 747.245 | weak_signal | medium | 12.000 | 20.000 | Abrupt fading and very low-frequency tail |
| s07 | 747.245 | 748.954 | noise | high | 20.000 | 0.000 | No continuing coherent main branch |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260630-1_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260630-1_ch1__onset_review.png)

## 20260630-1_ch2

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 743.954 | 746.216 | stationary | high | 0.000 | 2.500 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 746.216 | 746.239 | onset | high | 2.500 | 5.000 | Own-channel clipped oscillations and harmonic ladder |
| s02 | 746.239 | 746.730 | plateau | high | 5.000 | 15.000 | Own-channel stable ~0.55 GHz branch and harmonics |
| s03 | 746.730 | 746.915 | decline | high | 15.000 | 10.000 | Own-channel parallel lines bend downward |
| s04 | 746.915 | 746.995 | weak_signal | medium | 10.000 | 12.000 | Amplitude minimum, branch support degrades |
| s05 | 746.995 | 747.110 | rebound | high | 12.000 | 12.000 | Own-channel low branch rises after minimum |
| s06 | 747.110 | 747.245 | weak_signal | medium | 12.000 | 20.000 | Fading low-frequency tail |
| s07 | 747.245 | 748.954 | noise | high | 20.000 | 0.000 | No reliable continuing main branch |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260630-1_ch2/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260630-1_ch2__onset_review.png)

## 20260630-2_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 539.713 | 540.216 | stationary | high | 0.000 | 2.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 540.216 | 540.234 | onset | high | 2.000 | 5.000 | Strong clipped oscillations and ~0.85 GHz line |
| s02 | 540.234 | 540.780 | plateau | high | 5.000 | 12.000 | Horizontal fundamental-like ridge with harmonics |
| s03 | 540.780 | 540.900 | weak_signal | medium | 12.000 | 12.000 | Amplitude dropout; visible branch continuity uncertain |
| s04 | 540.900 | 540.970 | plateau | high | 12.000 | 12.000 | Line reappears at similar frequency; no physical identity proof |
| s05 | 540.970 | 541.105 | decline | high | 12.000 | 10.000 | Parallel lines slope downward |
| s06 | 541.105 | 541.210 | plateau | high | 10.000 | 12.000 | Short low-frequency shelf, several cycles only |
| s07 | 541.210 | 541.290 | weak_signal | medium | 12.000 | 15.000 | Fading branch and amplitude modulation |
| s08 | 541.290 | 541.713 | noise | high | 15.000 | 0.000 | Motion-like ridge disappears |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260630-2_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260630-2_ch1__onset_review.png)

## 20260630-2_ch2

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 539.713 | 540.216 | stationary | high | 0.000 | 2.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 540.216 | 540.234 | onset | high | 2.000 | 5.000 | Own-channel bipolar transient followed by ~0.85 GHz beat |
| s02 | 540.234 | 540.780 | plateau | high | 5.000 | 12.000 | Narrow own-channel line; weaker multiples than ch1 |
| s03 | 540.780 | 540.900 | weak_signal | medium | 12.000 | 12.000 | Amplitude dropout |
| s04 | 540.900 | 540.970 | plateau | high | 12.000 | 12.000 | Line re-establishes; identity conditional |
| s05 | 540.970 | 541.105 | decline | high | 12.000 | 10.000 | Visible downward bend |
| s06 | 541.105 | 541.210 | plateau | high | 10.000 | 12.000 | Short low-frequency shelf |
| s07 | 541.210 | 541.290 | weak_signal | medium | 12.000 | 15.000 | Fading weak tail |
| s08 | 541.290 | 541.713 | noise | high | 15.000 | 0.000 | No reliable coherent ridge |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260630-2_ch2/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260630-2_ch2__onset_review.png)

## 20260701_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 656.191 | 656.846 | stationary | high | 0.000 | 2.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 656.846 | 656.863 | onset | high | 2.000 | 5.000 | Clipped beat establishes ~0.7 GHz and higher multiples |
| s02 | 656.863 | 657.630 | plateau | high | 5.000 | 12.000 | Persistent main line, slight drift; harmonics evolve |
| s03 | 657.630 | 657.735 | decline | high | 12.000 | 12.000 | Main and second line bend downward together |
| s04 | 657.735 | 657.860 | weak_signal | medium | 12.000 | 18.000 | Weak low-frequency terminal shelf |
| s05 | 657.860 | 658.191 | noise | high | 18.000 | 0.000 | No continuing narrow main ridge |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260701_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260701_ch1__onset_review.png)

## 20260701_ch2

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 656.191 | 656.846 | stationary | high | 0.000 | 2.000 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 656.846 | 656.863 | onset | high | 2.000 | 5.000 | Own-channel transient and established ~0.7 GHz oscillations |
| s02 | 656.863 | 657.630 | plateau | high | 5.000 | 12.000 | Narrow own-channel fundamental-like line |
| s03 | 657.630 | 657.735 | decline | high | 12.000 | 12.000 | Own-channel lines turn downward |
| s04 | 657.735 | 657.860 | weak_signal | medium | 12.000 | 18.000 | Weak terminal shelf |
| s05 | 657.860 | 658.191 | noise | high | 18.000 | 0.000 | No continuing narrow line |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/20260701_ch2/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/20260701_ch2__onset_review.png)

## ch3_ch1

| ID | 起始 µs | 结束 µs | 阶段 | 置信 | 起始±ns | 结束±ns | 原始视觉证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s00 | 182.580 | 183.646 | stationary | medium | 0.000 | 2.500 | Background label only; NOT measured zero; pre-existing tone possible |
| s01 | 183.646 | 183.661 | onset | medium | 2.500 | 6.000 | Impulse followed by intermittent ~3.6-3.9 GHz oscillations |
| s02 | 183.661 | 183.800 | weak_signal | medium | 6.000 | 10.000 | Broad intermittent ridge and amplitude fades; no stable platform |
| s03 | 183.800 | 183.875 | unknown | medium | 10.000 | 10.000 | Abrupt change toward ~1.3 GHz then broadband terminal burst |
| s04 | 183.875 | 184.580 | noise | medium | 10.000 | 0.000 | Burst ends; no reliable continuous ridge |

[冻结分段图](../../../artifacts/TASK-017/figures/comparison_v01/ch3_ch1/frozen_segmentation.png) · [原始起跳复核图](../../../artifacts/TASK-017/figures/visual_review/ch3_ch1__onset_review.png)
