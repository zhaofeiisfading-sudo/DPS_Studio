# TASK-010 旧软件输出指纹重建、已知真值验证与 STFT 参数决策

## 观察到的事实

1. 开始前审计：HEAD 为 `4cfaa500ab47800dec4259d9bb0cd6fe29db6943`；指定解释器测试基线由外层审计实测为
   221 passed。输入文件均存在，暂存区为空。
2. 旧软件 CSV：226 行，其中 measured=
   199、zero_masked=27；
   时间范围 [0.0, 0.719999999999914] µs，measured 范围
   [0.0863999999999123, 0.719999999999914] µs。
3. 时间步长：min/median/max=[3.199999999877967, 3.199999999992601, 3.200000000107006] ns；
   相对 3.2 ns 的最大十进制表示误差为
   1.22033050332e-10 ns，判定为严格 3.2 ns 输出网格。
4. 速度量化：最小非零间隔为
   0.12109375 m/s；所有 measured 值均为
   0.12109375 m/s 的整数倍，速度列单位为 m/s，km/s 列换算一致。
5. 指纹推断：频率网格间距为
   156250 Hz，按实际采样率得到
   inferred nfft=255999.999913。该结论仅称为
   **legacy output fingerprint inference**，不是源码确认。
6. 当前基线无插值整数帧对齐：

- pdv_channel_1: offset=+4 frames (+12.8 ns), paired=199, bias=-0.479256 m/s, MAE=1.15327 m/s, RMSE=1.73714 m/s, max=8.2204 m/s, r=0.999741.
- pdv_channel_2: offset=+4 frames (+12.8 ns), paired=199, bias=-0.25984 m/s, MAE=1.16668 m/s, RMSE=1.70955 m/s, max=8.33343 m/s, r=0.999528.

7. 固定统计区间：起跳 0–0.08 µs、平台 0.08–0.50 µs、下降
   0.50–0.6336 µs；边界未按结果移动。
8. 当前双通道基线全区间绝对差中位数为 0.0440576 m/s；
   最接近旧软件的有限配置对应值为 0.121094 m/s。
9. 最接近旧软件的有限参数组合为 `blackman_w416_n256000_discrete`：

- pdv_channel_1: RMSE=0.527416 m/s, r=0.999958, offset=+4 frames.
- pdv_channel_2: RMSE=1.46436 m/s, r=0.99982, offset=+4 frames.

10. 256000 点诊断采用分批 RFFT；CSV 中的内存值是数组尺寸解析估算。
    完整 STFT 单份复谱风险与分批工作集分别报告，未伪装为操作系统实测峰值。

## 基于输出指纹的推测

11. 旧软件并非“只是输出点更多”：旧软件 measured 与当前 hop 128 都是 3.2 ns 网格；
    旧文件覆盖区间更短，而不是用更密的时间步长取胜。
12. 平台相邻变化与旧软件相邻变化的两通道平均相关系数为
    0.719027；下降段为 0.908466。
    旧软件平台 |first difference| 中位数为
    0.847656 m/s、
    second-difference RMS 为
    2.29265 m/s；当前两通道均值分别为
    0.537147 和 0.750028 m/s。
    旧软件与当前曲线的相邻变化在下降段方向相关，支持其中一部分为共同物理结构；剩余不具双通道重复性的差异仍不能解释为真值。 因而旧软件不是纯随机制造全部不平整度，但其额外高频粗糙幅度
    没有在两条当前采集通道中等幅复现。
13. 旧软件不能当作物理真值。与旧软件 RMSE 最小只用于重建输出指纹，不单独决定默认参数。
14. FFT 网格、窗函数/窗长的真实分辨能力、三点亚频点估计、绝对测量准确度是四个不同概念；
    大 NFFT 只加密网格，不能单独提高窗限制下的真实频率分辨率。
15. 768 点窗是否过度时间平均，以已知真值下降定位与短窗谱带竞争共同判定；
    不从旧软件曲线外观直接下结论。已知真值的低噪声与真实代理噪声下降形状显示，
    推荐 high-time 配置相对当前基线的转折段 RMSE 改善比例为
    54.722%，但 5% 阈值起始帧没有改善。

## 已知真值测试结果

16. 合成数据包含恒频、缓慢调频、0.73→0.28 GHz 快速下降和较弱竞争谱带；
    随机种子固定为 20260714。
17. 噪声包含无噪声、固定中等噪声（每单位峰值幅值的标准差 σ=0.30）和真实数据 pre-event/plateau 幅值代理；
    后者标准差比为 0.00703762。该代理可能含相干仪器/光学成分，不代表完整实验噪声。
18. 配置汇总：

- hann_w768_n4096_subbin: mean frequency RMSE=5.44472e+06 Hz, velocity RMSE=4.21966 m/s, plateau jitter=4.94025e+06 Hz, wrong-branch frames=0, mean runtime=0.01034 s.
- hann_w512_n4096_subbin: mean frequency RMSE=7.15966e+06 Hz, velocity RMSE=5.54874 m/s, plateau jitter=6.76576e+06 Hz, wrong-branch frames=0, mean runtime=0.00983981 s.
- blackman_w416_n4096_subbin: mean frequency RMSE=8.52019e+06 Hz, velocity RMSE=6.60315 m/s, plateau jitter=8.16958e+06 Hz, wrong-branch frames=8, mean runtime=0.0101975 s.
- blackman_w416_n256000_discrete: mean frequency RMSE=8.52427e+06 Hz, velocity RMSE=6.60631 m/s, plateau jitter=8.17388e+06 Hz, wrong-branch frames=7, mean runtime=0.651227 s.

19. 已知真值逐行结果完整保存在 `synthetic_truth_results.csv`，含频率 bias/RMSE、
    速度 RMSE、平台 jitter、下降起始误差、转折段 RMSE、最大逐点误差和错误分支帧数。
20. 大 NFFT 是否必要：生产默认建议为
    `False`；原因是
    nfft=256000 only densifies the FFT grid; it does not by itself increase the window-limited physical frequency resolution。

## 最终参数建议

21. 最终选择为方案 **C**。默认 profile：
    `hann_w768_n4096_subbin`；备用 profile：
    `hann_w512_n4096_subbin`。
22. 当前默认参数是否改变：
    `False`。若存在备用 profile，
    只能由用户显式选择，不实现静默自动选择。balanced 默认使用 Hann/768/640/hop 128/nfft 4096；high-time-resolution 使用 Hann/512/384/hop 128/nfft 4096，时间支持由 19.2 ns 降至 12.8 ns，但未填零频率尺度由约 52.08 MHz 增至 78.12 MHz，平台抖动和竞争谱带风险更高。
23. 本轮实际新增开发文件为
    `scripts/audit_legacy_velocity_reference.py`、`tests/unit/test_legacy_velocity_audit.py`，
    以及 `outputs/task010_legacy_velocity_audit/` 下审计产物；没有修改 core 数值算法。
24. 生产回归：本轮前后完整数值指纹匹配为 `True`；
    与 TASK-009 外部指纹匹配为 `True`。覆盖当前 STFT、baseline ridge、
    refined ridge、apparent/display velocity、TASK-008A/B、NaN 掩码和状态计数。
    当前 8 个 CSV 的逐文件 SHA-256 前后匹配为
    `True`。
25. 最终质量门（指定解释器、审计产物生成后实测）：`pytest` 为 232 passed、1 个
    `.pytest_cache` 权限警告；`ruff check .` 全部通过；`mypy src` 对 34 个源文件零问题；
    `git diff --check` 无空白错误，仅报告 3 个既存 tracked 文件的 LF/CRLF 提示。
26. 输入 SHA-256：原始 CSV 前后为 `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353` / `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`；
    旧软件 CSV 前后为 `a1b65d9c207948335b020e6b63cf7b34c5e6284b7cbbffd3780bfd81eb447af5` / `a1b65d9c207948335b020e6b63cf7b34c5e6284b7cbbffd3780bfd81eb447af5`。
27. `git diff --stat`：

```text
 scripts/plot_real_velocity.py         |   2 +-
 src/dps_studio/core/ridge/__init__.py |  37 ++++-
 src/dps_studio/core/ridge/models.py   | 295 +++++++++++++++++++++++++++++++++-
 3 files changed, 329 insertions(+), 5 deletions(-)
```

28. 完整 `git status --short --branch`：

```text
## main
 M scripts/plot_real_velocity.py
 M src/dps_studio/core/ridge/__init__.py
 M src/dps_studio/core/ridge/models.py
?? data/reference/
?? docs/
?? outputs/
?? run_demo_pipeline.bat
?? scripts/assess_real_ridge_diagnostics.py
?? scripts/assess_real_ridge_quality.py
?? scripts/audit_legacy_velocity_reference.py
?? scripts/compare_real_ridge_refinement.py
?? scripts/plot_real_stft.py
?? scripts/run_demo_pipeline.py
?? src/dps_studio/core/ridge/diagnostic_models.py
?? src/dps_studio/core/ridge/diagnostics.py
?? src/dps_studio/core/ridge/quality_models.py
?? src/dps_studio/core/ridge/refinement.py
?? src/dps_studio/core/ridge/spectral_quality.py
?? tests/fixtures/test.csv
?? tests/unit/test_demo_plot_rendering.py
?? tests/unit/test_legacy_velocity_audit.py
?? tests/unit/test_ridge_diagnostics.py
?? tests/unit/test_ridge_refinement.py
?? tests/unit/test_ridge_spectral_quality.py
?? tests/unit/test_window_length_diagnostics.py
```

29. 暂存区为空：`True`。本脚本未执行 git add、commit、
    restore、reset 或 clean。
30. 未开始 LiF、GUI、AI、自动追踪、自动分支切换、通道选择或融合；
    未让 `run_demo_pipeline.bat` 调用本审计脚本。

## 输出索引

- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_fingerprint.json`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\production_regression_after.json`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\production_regression_comparison.json`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\alignment_metrics.csv`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\roughness_metrics.csv`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\configuration_comparison.csv`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\nfft_candidate_comparison.csv`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\synthetic_truth_results.csv`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\development_noise_proxy.csv`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_vs_current_channel_1_aligned.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_vs_current_channel_2_aligned.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_vs_current_aligned.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_minus_current_residual.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_vs_best_reconstruction.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_current_plateau_detail.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_current_decline_detail.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_current_first_difference.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\legacy_reconstruction_residual.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\configuration_error_comparison.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\synthetic_constant_frequency_errors.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\synthetic_fast_decline_comparison.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\two_channel_repeatability_by_configuration.png`
- `D:\Code\Python_Projects\DPS_Studio\outputs\task010_legacy_velocity_audit\task010_report.json`
