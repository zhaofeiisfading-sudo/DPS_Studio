# TASK-024 Phase 3 · Windows 发布验收

| 执行记录 | 内容 |
|---|---|
| 执行者与日期 | Codex CLI，2026-11-19 America/New_York |
| 仓库 | `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN` |
| 分支与 HEAD | `codex/research_2/global-path-ridge-v2` · `c2568241f6959b49a2b9b380ef1022bf5badff00`，含 Phase 1/2 工作树内容 |
| 工具 | PowerShell 7，`D:\miniconda3\envs\dps-studio\python.exe`（Python 3.12.13），PyInstaller 6.21.0，PySide6 6.11.1 |

## 界面

- 中区曲线图的纵轴缩短为「速度 (m/s)」，时频图保留「表观速度 (m/s)」。右侧保留法向反射关系 `v = λ₀f/2` 及窗口、角度修正说明。Windows 原生画面中两处轴标签在 1366×768 与 1600×960 均完整。
- 原波形的轴标签和刻度使用 `#263746`。标题行图例随残差与原电压切换，拟合线型区分已发布与候选，原电压图标出基线、阶跃、触轨退出和触轨点。
- `f min`、`f max` 采用一位小数，最低正输入为 0.1 MHz，默认显示 50.0 与 6000.0 MHz。真空波长输入采用三位小数。
- 捕获入口支持绝对 `time_range_us`。报告记录冻结程序路径、原生窗口暴露状态、所选帧实测读数，以及各图的范围和色标。

## 正式发布包

```powershell
pwsh -NoProfile -File scripts/build/build_windows.ps1 -Task TASK-024 -Python D:\miniconda3\envs\dps-studio\python.exe -DistDirectory release/TASK-024
```

[release/TASK-024/PDV_Studio_Research](../../../release/TASK-024/PDV_Studio_Research/) 包含 `PDV Studio Research.exe` 和 `_internal/`。共 **452 个文件，241,266,701 B（241.267 MB，230.090 MiB）**。EXE SHA-256 为 `2bfd80385fc4962ce754f08ee2497d4fe66bc7b91e84c06bdb659ca364de76c0`。

- PYZ 中已逐项核对 `dps_studio.core.stft_m4` 与 `dps_studio.gui.comparison` 的 16 个模块。PYZ 构建记录中的 152 个 `dps_studio` 模块均来自本 Research 源码树。
- 磁盘文件集合与 `COLLECT-00.toc` 一致。235 个二进制条目来自指定解释器环境、允许的 Windows 系统目录或本次 EXE。配置、ICO、下拉 SVG 和英文 QM 与源码 SHA-256 一致。归档及发布树中未发现 `data/raw`、`artifacts`、`scripts`、`matplotlib`、`dps_studio.research` 或额外二进制。[包核验](../../../artifacts/TASK-024/exe_verify/package_audit.json)
- PyInstaller 报告了可选 `pyqtgraph.opengl`、`scipy.special._cdflib` 和 macOS 动态库的 hook 警告。Windows 启动与 2D 工作区捕获均通过。[构建日志](../../../artifacts/TASK-024/exe_verify/build_windows.log)

## 正式 EXE 启动与截图

启动和捕获均执行正式发布目录里的 EXE。子进程使用 `System32`、`Windows` 两个 PATH 条目，环境中无 Python 或 Conda 注入变量。`QT_QPA_PLATFORM=windows`，在本机 200% 显示缩放下用 `QT_SCALE_FACTOR=0.5` 使捕获 DPR 为 1。使用真实可见、已暴露的 Windows Qt 窗口捕获客户区。`--startup-smoke-test` 的 `event_loop_entered`、`window_visible`、`window_exposed` 均为 true。12 条 Qt、Shiboken、SciPy 运行路径均指向发布包的 `_internal/`。[启动 JSON](../../../artifacts/TASK-024/exe_verify/startup_smoke.json) · [启动环境](../../../artifacts/TASK-024/exe_verify/launch_environment.json)

七份 spec 从六个原始文件载入七个通道，`time_column=0`，ch1 与 ch2 分别为 `voltage_column=1` 与 `2`。八张图均由 `--compare-capture-spec` 生成。每张图的三组 `view_ranges` 逐值相等，左、右 `levels_db` 逐值相等，且 PNG 文件头分辨率与截图报告一致。第 08 张的右图隐藏，其范围和色标仍同步。任务消息的部分 GHz 上限字符损坏，按各案例实测轨迹选取，实际范围列在下表。表中色标为各图共同的 dB 范围，原始精度见 JSON。[截图汇总](../../../artifacts/TASK-024/exe_verify/capture_summary.json)

| 图 | 通道 | PNG | 帧号 / 时间 (µs) | 类别 / M4 决策 | 三图共同 X (µs) / Y | 左右共同色标 (dB) |
|---|---|---|---|---|---|---|
| [01](../../../artifacts/TASK-024/figures/exe_screenshots/exe_01_20201211m_weak_decline_win.png) | `20201211m_ch1` | 1600×960 | 270 / 108.373602 | `m4_added_supported` / `accepted` | 108.33–108.41 / 0.4–1.4 GHz | −29.2292 至 0.2039 |
| [02](../../../artifacts/TASK-024/figures/exe_screenshots/exe_02_20221017a_weak_tail_win.png) | `20221017a_ch1` | 1600×960 | 518 / 88.292232 | `m4_added_supported` / `accepted` | 88.20–88.34 / 2.0–4.2 GHz | −15.9692 至 27.0098 |
| [03](../../../artifacts/TASK-024/figures/exe_screenshots/exe_03_20260630-1_ch2_competing_cw_win.png) | `20260630-1_ch2` | 1600×960 | 1015 / 747.211615 | `branch_diff_major` / `accepted` | 747.18–747.26 / 0–2.0 GHz | −29.6896 至 24.4699 |
| [04](../../../artifacts/TASK-024/figures/exe_screenshots/exe_04_20201214m_onset_and_8ghz.png) | `20201214m_ch1` | 1600×960 | 78 / 82.959202 | `m4_dropped_strong_risk` / `lowfreq_sustained_failed` | 82.91–83.05 / 0–7.2 GHz | −29.4562 至 3.6669 |
| [05](../../../artifacts/TASK-024/figures/exe_screenshots/exe_05_ch3_cfar_weak_and_noise.png) | `ch3_ch1` | 1600×960 | 377 / 183.795753 | `m4_added_supported` / `accepted` | 183.74–183.90 / 0.5–5.0 GHz | −34.3685 至 4.8982 |
| [06](../../../artifacts/TASK-024/figures/exe_screenshots/exe_06_20260630-1_ch1_fail_preonset_1p83ghz.png) | `20260630-1_ch1` | 1600×960 | 49 / 744.120415 | `m4_added_supported` / `accepted` | 744.06–744.20 / 0–2.5 GHz | −33.4460 至 19.5490 |
| [07](../../../artifacts/TASK-024/figures/exe_screenshots/exe_07_20260630-1_ch1_fail_overreject_r2_0989.png) | `20260630-1_ch1` | 1600×960 | 957 / 747.026015 | `m4_dropped_strong_risk` / `pre_edge_side_veto` | 746.96–747.08 / 0–1.0 GHz | −33.4460 至 19.5490 |
| [08](../../../artifacts/TASK-024/figures/exe_screenshots/exe_08_20260607_ch2_fail_dual_branch_velocity_1366.png) | `20260607_ch2` | 1366×768 | 547 / 555.720254 | `branch_diff_major` / `accepted` | 555.66–555.78 / 0–930 m/s | −29.6277 至 26.3328 |

- **01** B1 与 25.6 ns STFT 均未发布。M4 发布 0.816327 GHz，选中帧由 25.6 ns 波形证据支持。 [spec](../../../artifacts/TASK-024/exe_verify/exe_01_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_01_report.json)
- **02** 约 91 ns 的连续高调频弱尾延伸到 2.771118 GHz。视野中有 58 帧 M4 发布，所选尾末帧 B1 和 25.6 ns STFT 均未发布。 [spec](../../../artifacts/TASK-024/exe_verify/exe_02_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_02_report.json)
- **03** B1 跳到 0.505840 GHz，M4 主支路为 0.233236 GHz，次支路为 0.509437 GHz。 [spec](../../../artifacts/TASK-024/exe_verify/exe_03_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_03_report.json)
- **04** B1 发布起跳前 0.235603 GHz，M4 拒绝该帧。8 GHz 搜索下，截图内 27 个 M4 发布帧为 6.375–6.395 GHz。 [spec](../../../artifacts/TASK-024/exe_verify/exe_04_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_04_report.json)
- **05** M4 发布 3.508361 GHz，B1 和 25.6 ns STFT 未发布。图中保留弱尾新增、噪声拒点与噪声段边缘的零星发布。 [spec](../../../artifacts/TASK-024/exe_verify/exe_05_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_05_report.json)
- **06** 静态窗口内 M4 发布 26 个 1.817–1.844 GHz 窄带候选。选中帧为 1.827017 GHz。该段波形支持振荡，归属仍未确定。 [spec](../../../artifacts/TASK-024/exe_verify/exe_06_07_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_06_07_report.json)
- **07** B1 发布 0.334712 GHz，6.4 ns 调频拟合 R² = 0.988717。原电压窗显示 1 次触轨退出和 237 个触轨样本。 [spec](../../../artifacts/TASK-024/exe_verify/exe_06_07_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_06_07_report.json)
- **08** 1550 nm 已确认。B1 与 M4 分别显示 663.292 和 203.315 m/s，M4 次支路为 665.595 m/s。可见 M4 在两条支路间的较晚切换。 [spec](../../../artifacts/TASK-024/exe_verify/exe_08_spec.json) · [报告](../../../artifacts/TASK-024/exe_verify/exe_08_report.json)

完整平台与紧凑布局的补充实测使用同一正式 EXE。第 04 例在 82.974–83.340 µs 有 114/114 个平台中心发布在 6.375–6.472 GHz。第 02 例的尾末帧后，88.2923–88.34 µs 与 0–6 GHz 范围内无 M4 发布。第 08 例另捕获 1600×960 速度模式，纵轴与右侧波长说明均可读。[完整平台](../../../artifacts/TASK-024/exe_verify/qa_plateau_report.json) · [弱尾后段](../../../artifacts/TASK-024/exe_verify/qa_tail02_report.json) · [1600×960 速度](../../../artifacts/TASK-024/exe_verify/qa_velocity1600_report.json)

Phase 3 实测的是所选测量窗口与算法输出。第 04 张保留起跳帧的自动分类和拒绝原因，第 06 张保留静态杂波帧的「波形支持」分类。第 05 张的 CFAR 因果对照见 Phase 1 的门槛消融。[Phase 1 实测报告](../../../artifacts/TASK-024/study/analysis_report.md)

## 复测与边界

| 检查 | 结果 |
|---|---|
| TASK-024 核心、GUI、Phase 1 定向 pytest | 21 通过，0 跳过。[JUnit](../../../artifacts/TASK-024/exe_verify/phase3-focused.xml) |
| `check_gui.py --task TASK-024` | 28 模块、231 项全部通过，0 失败，0 跳过，0 重试。[全量 JSON](../../../artifacts/TASK-024/exe_verify/gui-regression.json) |
| `ruff check` | 通过 |
| `mypy --strict --explicit-package-bases` | 任务相关 226 个文件通过，覆盖 `src`、构建脚本、TASK-024 研究工具和三份定向测试 |
| `scripts/build/check_build_inputs.py` | 通过 |
| 仓库卫生 | 11 项通过，工作树及暂存区只读审计通过 |
| Windows onedir、启动烟测、8 张原生 EXE 截图 | 通过 |

额外对整个 `src scripts tests` 运行严格 mypy，历史脚本和测试共返回 796 项诊断。该命令超出本阶段的检查范围。

本阶段修改 `src/dps_studio/gui/comparison/{plots,theme,inspector,workspace,capture}.py` 与 `tests/unit/gui/test_task024_compare_workspace.py`。构建使用 Phase 2 已有 spec。发布前后六个输入文件的 SHA-256 一致。暂存区为空，Release 与验证产物由现有 Git ignore 规则排除。受保护路径的 Git 状态无变动，Production 无写入。
