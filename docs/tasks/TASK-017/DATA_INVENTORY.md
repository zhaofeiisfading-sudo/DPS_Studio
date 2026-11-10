# 数据盘点

所有频率/时间来自当前真实原始波形。无独立测速真值，证据支持、门控通过和物理支路身份分开；`requires experimental confirmation` 适用于全部支路。没有用任何合成信号选择参数或验收。

当前磁盘有 10 个波形文件、14 个电压列，另有 `.gitkeep`；全部读入。10 个 SHA-256 互异，未发现字节重复。历史 TASK-009/015 的 13/17 是 10/14 加上 `data/research/TASK-009/source_data/raw_supplement/` 的 `ch1.csv`、`ch2.csv`、`ch4.csv` 三个不同输入，不是重复映射；它们位于本任务唯一数据源之外，故没有运行。历史索引中标记 PROCESSED_EXCLUDED 的 `result*.dat` 未作为电压输入，当前 raw 也没有 result 文件。

| file | samples | channels | start_s | end_s | sample_rate_hz |
| --- | --- | --- | --- | --- | --- |
| data/raw/20201210m.dat | 40000 | 1 | 1.38700007530e-04 | 1.39699982530e-04 | 39999999986.360 |
| data/raw/20201211m.dat | 40000 | 1 | 1.07500002410e-04 | 1.08499977410e-04 | 40000000008.044 |
| data/raw/20201214m.dat | 40000 | 1 | 8.27000022800e-05 | 8.36999772800e-05 | 40000000008.044 |
| data/raw/20221017a.dat | 80000 | 1 | 8.74586318200e-05 | 8.84586193200e-05 | 79999999972.720 |
| data/raw/20231019-ch1.dat | 80000 | 1 | 8.93038524700e-05 | 9.03038399700e-05 | 79999999972.720 |
| data/raw/20260607.csv | 80000 | 2 | 5.53960254260e-04 | 5.55960229260e-04 | 39999999986.360 |
| data/raw/20260630-1.csv | 200001 | 2 | 7.43954014990e-04 | 7.48954014990e-04 | 39999999986.360 |
| data/raw/20260630-2.csv | 80000 | 2 | 5.39713250320e-04 | 5.41713225320e-04 | 39999999986.360 |
| data/raw/20260701.csv | 80000 | 2 | 6.56191266340e-04 | 6.58191241340e-04 | 39999999986.360 |
| data/raw/ch3.csv | 80000 | 1 | 1.82579753140e-04 | 1.84579728140e-04 | 39999999986.360 |

上表为 SI 秒/Hz，时间小数的完整精度在 inventory.json；下表为便于阅读的原始绝对微秒。

| 文件 | 起始 µs | 终止 µs | 采样率 GHz |
| --- | --- | --- | --- |
| data/raw/20201210m.dat | 138.700 | 139.700 | 40.000 |
| data/raw/20201211m.dat | 107.500 | 108.500 | 40.000 |
| data/raw/20201214m.dat | 82.700 | 83.700 | 40.000 |
| data/raw/20221017a.dat | 87.459 | 88.459 | 80.000 |
| data/raw/20231019-ch1.dat | 89.304 | 90.304 | 80.000 |
| data/raw/20260607.csv | 553.960 | 555.960 | 40.000 |
| data/raw/20260630-1.csv | 743.954 | 748.954 | 40.000 |
| data/raw/20260630-2.csv | 539.713 | 541.713 | 40.000 |
| data/raw/20260701.csv | 656.191 | 658.191 | 40.000 |
| data/raw/ch3.csv | 182.580 | 184.580 | 40.000 |

全部输入无表头。显式映射为时间数值×1 s、电压数值×1 V，依据是现有 acquisition 配置和迁移索引，不是重新取得的仪器标定；若该继承映射错误，时间、频率和残差电压单位会整体失效。时间严格递增，最大相对步长偏差见 JSON，未重采样。物理波长、入射角、窗介质/晶向均未确认为本批记录的元数据；1550 nm 仅是旧 API 内部往返换算占位，未输出假设速度，也未执行窗口修正。

| file | sha256 |
| --- | --- |
| data/raw/20201210m.dat | 08a8b8af06dd241f6f1b2ceb08e60f8b6b110d755b867f36935e48a28495e956 |
| data/raw/20201211m.dat | b7994a2b31970daf4813583394a92556287f0eaa4aeeb1d1ec00a1f256452b84 |
| data/raw/20201214m.dat | 06da315b9e148c8589564771e172a5d9974d6a04f59ae126ce9b724007ef0798 |
| data/raw/20221017a.dat | 3228766dbac4c14e960d10fc7c663cfc99f8ab7bfd8329e7ba0c7e7aa3c2c954 |
| data/raw/20231019-ch1.dat | 4ccbe54b8def8fc3b05d8b1d25eec9a8700baa91eec679c5a2b8a04d0bf3d6dc |
| data/raw/20260607.csv | ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353 |
| data/raw/20260630-1.csv | 203b182e477e1e08214551977a00313eaf6f17a71391d83875f6f879dc3a0a74 |
| data/raw/20260630-2.csv | c0c31b2990eae228b21594276d030b83600a7ddb98c1953842e4cb80c17fa261 |
| data/raw/20260701.csv | 5ccb6530e0cc715e4a7a81327c625fce267a8b3473c0487479366ead9d9a952a |
| data/raw/ch3.csv | 401673b77829d4b2568a4b2a9b88dc649afa926b668c6c493012d8fc30115d49 |

| 通道 | 视觉质量/问题 |
|---|---|
| 20201210m_ch1（原列 1） | Slow DC precursor; no resolved moving beat; Voltage step and first sustained ~3.7 GHz oscillations; Discontinuous lower branch; identity cannot be followed |
| 20201211m_ch1（原列 1） | DC excursion before establishment of GHz beat; Negative impulse and establishment of ~4.8 GHz beat; Weak lower branches and ambiguous handoff |
| 20201214m_ch1（原列 1） | Large low-frequency baseline structure; no certified zero; Bipolar transient followed by ~6.3 GHz oscillations; Abrupt branch handoff from ~4.6 to ~2 GHz; Weak low-frequency tail |
| 20221017a_ch1（原列 1） | Background label only; NOT measured zero; pre-existing tone possible; Abrupt strong ~4.4 GHz beat above pre-existing ~1.5-2 GHz background; Ridge fades toward background |
| 20231019-ch1_ch1（原列 1） | Impulse followed by high-amplitude ~4.1 GHz oscillations; Abrupt low-branch handoff; no unique identity; Weak rising low-frequency tail, ambiguous branch |
| 20260607_ch1（原列 1） | Oscillations grow with ~0.7 GHz line and parallel multiples; Low-frequency tail with poor cycle support; Pulse and competing low-frequency branches |
| 20260607_ch2（原列 2） | Own-channel voltage oscillations establish ~0.7 GHz; upper clipping possible; Low-frequency weak tail; Competing residual branches and pulses |
| 20260630-1_ch1（原列 1） | Voltage leaves background and clips; ~0.55 GHz plus many harmonics; Low-frequency minimum; amplitude dropout; Abrupt fading and very low-frequency tail |
| 20260630-1_ch2（原列 2） | Own-channel clipped oscillations and harmonic ladder; Amplitude minimum, branch support degrades; Fading low-frequency tail |
| 20260630-2_ch1（原列 1） | Strong clipped oscillations and ~0.85 GHz line; Amplitude dropout; visible branch continuity uncertain; Fading branch and amplitude modulation |
| 20260630-2_ch2（原列 2） | Own-channel bipolar transient followed by ~0.85 GHz beat; Amplitude dropout; Fading weak tail |
| 20260701_ch1（原列 1） | Clipped beat establishes ~0.7 GHz and higher multiples; Weak low-frequency terminal shelf |
| 20260701_ch2（原列 2） | Own-channel transient and established ~0.7 GHz oscillations; Weak terminal shelf |
| ch3_ch1（原列 1） | Impulse followed by intermittent ~3.6-3.9 GHz oscillations; Broad intermittent ridge and amplitude fades; no stable platform; Abrupt change toward ~1.3 GHz then broadband terminal burst |

完整机器清单：[inventory.json](../../../artifacts/TASK-017/data/inventory.json)。