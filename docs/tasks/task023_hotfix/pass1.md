# Production TASK-023 Hotfix · Pass 1

Production `main`，起始版本 `b6557b015683d34428c384291d4a828824962cee`。本次修改解决起跳前噪声误测速、无效频率进入速度链，以及事件前平台覆盖测量的问题。

## 真实数据

使用内置 balanced 参数、原始 CSV 的 SI 时间和电压、完整 STFT 帧时间区间以及默认 LiF 修正。每行独立分析一个通道。最后两列采用该通道的主事件候选作为已确认参考，静止显示值取 0 m/s。未设置参考时，所有未测速帧显示 NaN。

| 文件 / 通道 | 总帧数 | 有效测速 | 未设置参考时未确定 | 已确认参考时未确定 | 静止约束 | 本次撤销的测量帧（从 0 开始） |
|---|---:|---:|---:|---:|---:|---|
| 20260607.csv / pdv_channel_1 | 620 | 388 | 232 | 15 | 217 | 20, 111 |
| 20260630-1.csv / pdv_channel_2 | 1557 | 767 | 790 | 98 | 692 | 无 |
| 20260630-2.csv / pdv_channel_1 | 620 | 448 | 172 | 21 | 151 | 无 |
| 20260630-2.csv / pdv_channel_2 | 620 | 428 | 192 | 40 | 152 | 无 |
| 20260701.csv / pdv_channel_1 | 620 | 340 | 280 | 216 | 64 | 无 |
| ch2.csv / pdv_channel_1 | 620 | 122 | 498 | 143 | 355 | 404 |
| ch3.csv / pdv_channel_1 | 620 | 40 | 580 | 253 | 327 | 9, 21, 455 |
| ch4.csv / pdv_channel_1 | 620 | 46 | 574 | 272 | 302 | 55, 65, 67, 262, 387, 494 |

- `20260607.csv` 通道 1 的第 20、111 帧原修正速度为 2080.101、1443.823 m/s。两帧现为 `unstable_detection`，正式速度与工作速度均为 NaN。采用参考前的 217 帧中，有效测速为 0。设置参考后，这 217 帧满足静止显示条件。
- `20260630-1.csv` 通道 2 第 1015 帧仍由连续性候选获得有效测速。其表观速度为 163.818994486 m/s，LiF 修正速度为 131.267919899 m/s。第 697–699 帧也保留实测值，即使主事件候选位于第 706 帧。
- `20260630-2.csv` 两通道第 153 帧及 `ch2.csv` 第 355–359 帧在参考前保持未确定。8 条通道记录均无新增 `MEASURED` 帧。全部保留测量的修正速度与修改前逐帧完全相等。

## 判据及显示

1. 连续性备选峰自身须通过严格检测。左右紧邻帧均须在分析区间内、谱质量已评估、峰位不在频带边界，并达到原有严格峰值/背景门槛。迟滞检测建立的有效连续段达到配置的最短长度后，才允许相距最多两个帧索引的备选峰补入。被补入的帧不能再为其他帧提供连续段依据。
2. 工作频率直接使用正式测量频率，连续速度字段沿用同一表观速度和修正结果。边界峰、含混峰及其他未通过的谱峰保留在原始候选和诊断字段中。未评估帧与区间外帧保留各自状态。差分与局部线性加速度只使用连续有效测量，隔断处保留 NaN。
3. 静止约束仅适用于已启用平台、参考落在数据与分析区间内、且位于参考之前的非测量帧。程序从单边复 STFT 减去同窗 DC 的频谱响应，再按 Parseval 关系求每帧 AC 功率。令窗的等效噪声带宽（FFT 栅格数）为 `nfft * sum(w²) / sum(w)²`，用它乘最强频点功率。该值须不超过总 AC 功率的 25%，总 AC 功率还须不超过这些弥散频谱帧功率下四分位数的 4 倍（约 +6.02 dB）。基线取有效参考前、第一段持续测量开始前的候选帧。区间外、未评估及持续运动之后的帧均不能取得此约束。25% 与 4 倍是本次实现选取的显示判据；真实静止仍依赖事件参考和实验先验。
4. `build_display_velocity` 缺少静止证据掩码时保留 NaN。有效测量始终采用正式修正速度。保留已有的手动平台显示值设置，默认值为 0 m/s，自定义值只进入显示字段。图中实线、静止虚线各自断开，只有参考两侧相邻且分别为静止和测量的两个端点可出现虚线连接。孤立有效点单独标记。
5. 详表的 `velocity_origin` 与原始信号状态、工作脊线来源并列。简表保留 NaN。元数据给出三态总帧数和显示判据。原有 Ridge 视图已分别绘制离散候选标记与按有限值分段的工作脊线。
6. Dechirp 接口原先直接读取可回退的工作脊线。本次将同一批精化或离散诊断峰作为独立拟合初值传入，并保留原先启用事件前平台时的拟合区间排除规则。GUI 缓存使用该初值。原始电压拟合器、拟合参数、材料修正和 STFT 实现均沿用原版本。

## 核对记录

- `before_metrics.json` 只收录前两条记录。修改前复现其 STFT 复谱、时间轴、频率轴、两种正式速度和 Dechirp 加速度的全部 SHA-256。同时保存其余记录的修改前逐帧数组。回归测试保留四个日期文件的独立基线摘要。`20260607` 仅在校验副本补回旧的两项数值，以原始正式速度全数组摘要验证其余每一字节。
- 8 条通道记录的 STFT 复谱、两条坐标轴、保留的正式修正速度和未设置参考时的 Dechirp 加速度均与修改前一致。另从起始 Git 版本载入原实现，使用四个日期文件、较晚手动参考、平台开启或关闭这 8 组工况复算，Dechirp 加速度、频率变化率、中心频率、R²、逐帧质量标志全部一致。
- Windows 原生 Qt 渲染核对了 `20260607` 和 `20260630-2` 的速度视图。未设置参考及采用参考两种模式的实际简表、详表与内存逐帧相等。英文 QM 可加载，三态计数及两个图例均可正确翻译。
- 项目 Python 3.12 以 `-B` 运行。全量 `pytest -q -o cache_dir=artifacts/task023_hotfix/cache/pytest --basetemp=artifacts/task023_hotfix/tmp/codex_pytest` 共 **854 passed in 192.23s**。Ruff 全仓检查通过。严格 mypy 检查 `src/dps_studio` 下 96 个源文件，0 个问题。两者均使用本任务专用缓存。翻译编译产生 756 条已完成译文，0 条未完成。`git diff --check` 通过。
- 仓库卫生严格检查在修改前后均报告同样 5 个历史构建 ZIP 位于 `build/`，结束时退出码 1。意外根目录项、索引内生成物、重复包及 artifacts 内 raw 副本均为 0。缓存目录清单从 41 增至 42，新增项位于本次 pytest 临时目录。起止 HEAD 相同，暂存区为空。`configs/`、`data/raw/`、`AGENTS.md` 不涉及本次修改。全部任务产物位于 Production。

## 修改文件

- `docs/tasks/task023_hotfix/pass1.md`
- `src/dps_studio/core/export/writer.py`
- `src/dps_studio/core/quality/detection.py`
- `src/dps_studio/core/quality/models.py`
- `src/dps_studio/core/workflow/acceleration.py`
- `src/dps_studio/core/workflow/analysis.py`
- `src/dps_studio/core/workflow/display.py`
- `src/dps_studio/core/workflow/models.py`
- `src/dps_studio/gui/acceleration_view.py`
- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/release_workflow_smoke.py`
- `src/dps_studio/gui/result_views.py`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `tests/reference/task023_pass1_before_sha256.json`
- `tests/unit/gui/test_task015c_display_velocity.py`
- `tests/unit/gui/test_task015c_r_event_reference_views.py`
- `tests/unit/gui/test_task016r2_guided_multichannel.py`
- `tests/unit/gui/test_task019a_interactions.py`
- `tests/unit/test_display_velocity.py`
- `tests/unit/test_formal_result_export.py`
- `tests/unit/test_macos_internal_release.py`
- `tests/unit/test_manual_frequency_region.py`
- `tests/unit/test_production_feedback_audit.py`
- `tests/unit/test_signal_detection.py`
- `tests/unit/test_task016r6_working_results.py`
- `tests/unit/test_task023_hotfix_real.py`

## 本地复核材料

- `artifacts/task023_hotfix/pass1_verified.json` 记录 8 条通道的逐帧对照结果、三态计数、降级帧、原文件哈希及实际导出路径。
- `artifacts/task023_hotfix/active_dechirp_before.json` 与 `active_dechirp_after.json` 保存有参考工况的诊断数组摘要。
- `artifacts/task023_hotfix/figures/pass1/` 保存四张原生速度视图。`artifacts/task023_hotfix/tmp/pass1_export/` 保存实际 CSV 和元数据。
- `artifacts/task023_hotfix/tmp/final_suite.log` 与 `artifacts/task023_hotfix/hygiene_after.json` 保存全量测试和卫生检查结果。
