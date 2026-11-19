# TASK-024 Phase 2 · STFT vs M4

| 执行记录 | 内容 |
|---|---|
| 执行者 | Codex |
| 日期 | 2026-11-19，America/New_York |
| 仓库 | `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN` |
| 分支 | `codex/research_2/global-path-ridge-v2` |
| 基线 HEAD | `c2568241f6959b49a2b9b380ef1022bf5badff00` |
| 运行环境 | Windows 11，PowerShell 7，项目 Python 3.12.13 |

## 科学计算与界面

- 核心由导入的均匀采样 `SignalRecord` 运行。中心为 `np.arange(384, n-383, 128)`，默认频带为 50–6000 MHz，上限受 `0.49*fs` 约束。非均匀时间轴显式报错，避免静默重采样。
- B1 调用现有 512 点、128 hop、4096 FFT、去均值 Hann 策略。默认两幅时频图绑定同一幅 B1 功率矩阵与 dB 上下限。两图及全曲线图共享 X/Y 范围。25.6 ns 二次去趋势副对照只发布完整窗，边界缺测为 NaN 并带质量标记。
- M4 的原样本窗、同侧权重及全窗和分半去趋势结果按唯一中心复用，候选相位和每项检验门限保持冻结口径。初验、长窗复验和缺口复验在批次内检查取消标志。可选 M4 底图从已有频谱取各尺度、合格调频模板的最大白化相干功率，在 M4 原生频格渲染并用独立 dB 范围。
- 同一个原波形评估器提供短窗正弦/调频 R²、长窗调频 R²、分半相干和局部中心 SNR。八类差异覆盖每帧，缺失短窗证据的 B1 独有发布归入弱/缺证据。关注区域由逐帧差异、DC 阶跃、触轨退出、起跳和调频率导出。
- 图层保留 NaN 断口、被拒点与原候选。点选后单帧面板显示 ±16 ns 原样本、6.4 ns 拟合、检测到的阶跃/触轨和拒绝原因。频率默认用 GHz。用户确认正有限真空波长后，界面可按法向反射 `v = (λ₀/2) f` 切换无符号表观速度，NaN 保留。窗口/角度修正未参与计算。
- `20260630-1_ch1` 在 747.026015 µs 的 B1 发布为约 0.335 GHz，6.4 ns R² 约 0.989。M4 此帧未发布，原因是 `pre_edge_side_veto`，附近的事件为触轨退出。短窗拟合强度本身只能支持局部振荡。

## 改动文件

| 路径 | 文件 |
|---|---|
| `src/dps_studio/core/stft_m4/` | `__init__.py`、`waveform.py`、`engine.py`、`models.py`、`comparison.py`、`_coherent.py`、`_pursuit.py`、`_m4.py`、`_evidence.py` |
| `src/dps_studio/core/segmentation/` | `strategies.py`，增加可选显式中心与取消检查 |
| `src/dps_studio/gui/comparison/` | `__init__.py`、`theme.py`、`worker.py`、`plots.py`、`inspector.py`、`workspace.py`、`capture.py` |
| `src/dps_studio/gui/` | `research_window.py`、`app.py`，第 4 工作区及显式捕获入口 |
| `scripts/build/` | `specs/pdv_research.spec`、`check_build_inputs.py` |
| `tests/unit/` | `test_task024_stft_m4_core.py`、`gui/test_task024_compare_workspace.py` |
| `docs/tasks/TASK-024/` | `PHASE_2_VERIFICATION.md` |

开工时已有未跟踪的 `scripts/research/task024/` 和 `tests/unit/test_task024_study.py`，完整保留。Production、原始数据、物理修正及默认参数处于任务保护边界。Git 未暂存、提交或推送任务文件。

## 截图入口

`--compare-capture-spec <path>` 在真实 Qt 事件循环中导入外部数据，使用正式工作区的异步计算、视图切换和点选逻辑。输入与输出相对 JSON 文件解析，列号从 0 开始，输出使用新文件。测量频率缩放经 `frequency_range_ghz` 指定，`zoom_ns` 为选中帧两侧各自的时间长度。[实机截图 spec](../../../artifacts/TASK-024/phase2/capture-final-spec.json)。

## Windows 冻结包复核

PyInstaller 6.21 在 TASK-024 的临时目录构建成功。实际 EXE 的 PYZ 含对比核心与 GUI 模块，目录无项目原始数据与研究产物。构建清单中项目模块均来自 Research，运行验证仅保留 Windows 系统 PATH，移除了 Python 搜索路径变量。归档检查确认排除了 `matplotlib`、`dps_studio.research` 与 `scripts`。

使用外部 `20260630-1.csv` 在 Windows Qt 原生窗口内计算和捕获四次。截图痕迹显示同底图模式的两套色标完全相同，四次捕获的三个视图范围逐值相同。1600×960、1366×768 都复核了标题、控件、表头和证据行。既有 `--startup-smoke-test` 通过，Qt、Shiboken 和 SciPy 运行路径均来自冻结包。

- [1600×960 并排](../../../artifacts/TASK-024/phase2/final-1600.png)
- [1366×768 差异高亮](../../../artifacts/TASK-024/phase2/final-1366.png)
- [上下并排与 M4 相干底图](../../../artifacts/TASK-024/phase2/final-coherent.png)
- [单图表观速度与原始电压](../../../artifacts/TASK-024/phase2/final-velocity.png)
- [捕获 JSON](../../../artifacts/TASK-024/phase2/capture-final.json) · [启动烟测](../../../artifacts/TASK-024/phase2/frozen-final-startup.json)

PyInstaller hook 对可选的 `pyqtgraph.opengl`、`scipy.special._cdflib` 以及 macOS 专用动态库发出警告。Windows 2D 工作区实机运行、截图库和启动烟测均完成。

## 数值对拍与耗时

B1 的发布、候选和调频率与 TASK-023 `run_baselines("B1")` 在共同中心逐值一致。M4 的 `accepted_hz`、`candidate_hz`、`chirp_hz_s`、`secondary_hz`、`persistent_cw_overlap` 和 `verification_window_ns` 与 TASK-023 冻结实现逐值一致，包含 NaN 位置。原电压 R²、相干和 SNR 通过逐点浮点比较。实际采样率以原始时间列核验，`20201211m` 和 `20201214m` 均约 40 GS/s，80 GS/s 对照使用 `20221017a`。

下表来自最终 pytest 在同一进程中依次运行 TASK-023 与新核心的单次冷运行。已载入电压，不计文件 I/O 和 GUI。耗时包括各自的证据计算，新核心省去了工作区用不到的历史 256 点谱门控诊断。

| 通道 | 采样率 | TASK-023 M4 | 新核心 M4 | 耗时变化 |
|---|---:|---:|---:|---:|
| `20201211m_ch1` | 40 GS/s | 2.842 s | 2.955 s | +4.0% |
| `20221017a_ch1` | 80 GS/s | 19.545 s | 15.252 s | −22.0% |
| `20260630-1_ch1` | 40 GS/s | 26.194 s | 16.885 s | −35.5% |

短记录的多次运行有波动，最终这次略慢。另对 `20201214m_ch1` 显式启用 8 GHz 上限，M4 与对应频带的冻结实现逐值一致，共有 128 个发布帧高于 6 GHz。

## 验证结果

| 检查 | 结果 |
|---|---|
| TASK-024 定向 pytest | 21 通过，涵盖 Phase 1、真实数据对拍、运行中取消、波长换算、GUI 和捕获入口 |
| GUI 全量覆盖 | 28 模块，231 项通过，含 27 个既有模块 |
| Ruff | 全部通过 |
| mypy `--strict --explicit-package-bases` | 226 个源文件通过 |
| `scripts/build/check_build_inputs.py` | 通过 |
| 仓库卫生测试与只读检查 | 11 项 pytest 通过，工作区和暂存区检查通过 |
| Windows 冻结包与已有启动烟测 | 通过 |

GUI 第一轮有两个模块失败。原诊断测试读取既有停靠栏状态字段，恢复字段名后 18 项通过。新增对比测试暴露多轴回写，改为一次同步 X/Y 后 3 项通过。综合结果保留第一轮和修复后两次记录，完整回归的其他 26 个模块均首轮通过。[全量与复验汇总](../../../artifacts/TASK-024/phase2/gui-final.json) · [定向测试 JUnit](../../../artifacts/TASK-024/phase2/task024-final.xml)。

运行 GUI 检查时，通过 `-PythonArgs` 传递 `check_gui.py --task TASK-024`，解决 PowerShell 包装器将 `--task` 绑定到自身 `-Task` 的参数冲突。
