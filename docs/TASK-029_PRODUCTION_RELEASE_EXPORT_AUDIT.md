# TASK-029 — Production 发布与导出独立审计

日期：2026-10-04；仓库：`D:\Code\Python_Projects\DPS_Studio`；分支：`main`；起始 HEAD：`3f3110c2`。开始时工作树干净，`main...origin/main [ahead 1]`。本任务未提交、推送或操作其他 worktree。

编号依据：Production 报告最后为 TASK-019A，但指定 Obsidian 目录已有 Research TASK-028。采用下一未占用编号 TASK-029，避免与现有日志冲突。没有访问或修改 Research 工作树。

**Verdict：版本分歧和正式 JSON 缺少导入 provenance 是真实问题，已经修复。连续简表包含未通过正式质量门的显示点也是事实，但属于既有设计；保留默认行为，新增显式质量筛选两列模式。三项运行组件缺失及外部 0.348 μs 提前量均未在当前证据中复现。另独立复现并修复了构建 PATH 污染引起的 Qt/ICU DLL 冲突。**

证据文件：[外部反馈审计与真实示例运行](D:/Code/Python_Projects/DPS_Studio/artifacts/task029/audit_evidence.json)、[构建、启动、版本、检查及 raw SHA-256](D:/Code/Python_Projects/DPS_Studio/artifacts/task029/verification.json)。历史用户反馈仅作为待验证假说。

| 反馈 | 判定 | Evidence / root cause | 是否修改、文件与验证 | Remaining risk |
| --- | --- | --- | --- | --- |
| shiboken6 runtime 缺失 | **NOT REPRODUCED** | 当前 `release/PDV_Studio_v0.1.3`、`iconfix` 和历史 ZIP 都有 `Shiboken.pyd`、`shiboken6.abi3.dll`；历史 ZIP 隔离解压启动成功。新 clean build 同样完整，并从解压目录加载 shiboken6。无法确定外部曾接收的原始包及人工补件前状态。 | 不添加臆测性 hidden import 或手工复制 DLL。新增构建完整性检查与隔离 smoke；`tools/build_production_release.py`、`tests/unit/test_production_release.py`。 | 外部原始交付包、解压过程、后续人工改动未提供，无法判定历史丢失阶段。 |
| qwindows.dll 缺失 | **NOT REPRODUCED** | 当前发布目录及 ZIP 包含 `_internal/PySide6/plugins/platforms/qwindows.dll`。新隔离 smoke 的 `qt_platform=windows`，主窗口可见；历史 ZIP 也显示主窗口。 | 不按猜测更改 Qt 收集路径。沿用 PyInstaller PySide6 hooks；同上完整性及启动验证。 | 尚未在另一台物理电脑验证系统运行库及 Windows 版本兼容性。 |
| SciPy `_ccallback_c` 缺失 | **NOT REPRODUCED** | 当前发布目录及 ZIP 有 `_internal/scipy/_lib/_ccallback_c.cp312-win_amd64.pyd`。新 EXE 在实际 GUI 主循环显式导入该模块，路径位于独立解压目录；真实 STFT/export 回归通过。 | 不盲目升级 SciPy，也不手工补 runtime；沿用 SciPy hooks，加文件检查与显式 import smoke。 | 外部出现导入错误时的完整 traceback、依赖版本及原始包均缺失。 |
| 自动起跳约提前 0.348 μs | **NOT REPRODUCED** | **NOT REPRODUCED DUE TO MISSING INPUT DATA**。仓库存在多发 CSV，但没有可靠信息将其中两发对应到外部反馈，亦无外部完整设置。静态审计确认这是频谱候选，不是时域幅值跃迁估计；长静段白噪声回归未生成事件候选。 | **不修改起跳算法或阈值**。新增静段测试；完整既有事件与 GUI 测试通过。人工采用/覆盖机制保持。 | 弱相干干扰可能满足频谱门；候选不等于物理起跳。没有复现或声称修复 0.348 μs。 |
| 连续两列 CSV 包含未通过质量门的 candidate | **NOT A BUG / INTENDED BEHAVIOR**，现象 **CONFIRMED** | 正式 writer 直接写 `ChannelAnalysis.plot_velocity_m_s`，默认行选择只考虑分析范围和用户的事件前行选项；不存在正式质量过滤。显示曲线使用同帧 working fallback，正式不可靠速度保留 NaN。既有测试已明确要求这一行为。仓库示例两通道分别证实 230/241 个有限显示点不是 `measured`；这不是外部两发的 126/165。 | 保留连续简表；新增 `quality_passed_only=False` 默认选项、GUI 复选框、`_quality_passed` 文件名、明确 metadata。筛选简表仍两列，详细 CSV 保留诊断行。修改 export models/writer、GUI、翻译；新增逐值/质量/空结果/无源文件覆盖测试。 | `measured` 只代表现有谱质量门通过，不能确认物理支路身份。筛选时间序列有缺口，不能当作完整连续采样。 |
| 发布 0.1.3、导出/包内版本 0.1.0 | **CONFIRMED** | `packaging/release_version.txt`、真实发布目录、README 均标 0.1.3；初始 pyproject、包 `__version__`、export 默认值是 0.1.0。读取历史 EXE 的 PYZ 包常量也得到 0.1.0。因此不是仅凭外部描述认定。 | 恢复统一来源 `src/dps_studio/__init__.py` 的 `__version__=0.1.3`；Hatch 动态版本、spec/PE metadata、GUI application/About、正式 JSON、production script 共用该来源。旧 release_version.txt 改为来源说明。新 frozen package、FileVersion/ProductVersion、wheel METADATA、GUI 和 JSON 均为 0.1.3；仅在当前专用 Conda 环境执行项目 `pip install --no-deps -e .` 同步安装元数据，运行依赖未升级。 | 历史 release 文件和既有导出仍保留历史内容；使用本任务的新包。其他旧环境重新安装项目后才会同步其 dist-info。 |
| import mapping / 输入时间单位没有进入 metadata | **CONFIRMED** | importer 原来已在 SignalRecord 保存列索引与换算系数；单位标签未记录，STFT/正式 writer 未传递这些 provenance。旧正式 JSON 不含原始映射与输入单位。 | 增加可选明确单位参数，GUI 从原始选项记录单位；通过 `SignalRecord.metadata → STFTResult.source_metadata → JSON.input_provenance` 传递。保持列索引和 scale 原有键，不重复建映射系统；补充 delimiter/encoding/header。修改 importer、STFT 的元数据字段、GUI adapter、writer；GUI/core/JSON 测试全部通过。 | 旧调用未明确传入单位时记录 null，不从 SI 或 scale 猜原单位；已有旧结果无法追溯恢复缺失的信息。 |
| 两发真实数据可正常分析，主段与独立处理接近 | **UNKNOWN / MISSING EVIDENCE** | 外部两发身份和独立处理参考缺失。本任务确认的是仓库说明书指定的 `docs/原始数据.csv` 可完成导入、Balanced STFT、ridge、速度与两种 export，不替代独立物理结果对比。 | 正常 Production 分析回归及已有真实数据 suite 通过；新增可复现 `tools/audit_production_feedback.py`。 | 没有对外部“两发”或“独立结果接近”作定量背书。 |

**独立发现的真实打包问题（CONFIRMED，已修复）**

未限制构建 PATH 的第一次全新构建包含上述三个组件，但清空 Python/Conda/Qt 环境后，启动报 `ImportError: DLL load failed while importing QtCore`，Windows 提示缺少过程。其 `Analysis-00.toc` 明确将根目录 `icuuc.dll` 收集自：

`C:\Users\89484\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\icuuc.dll`

该 Poppler ICU 不导出 Qt 所导入的无版本后缀符号；源码环境中的 Qt 实际加载 `C:\Windows\SYSTEM32\icuuc.dll`。这是 build 阶段收集了不兼容的同名 DLL，既不是三个被点名组件缺失，也不是 ZIP 丢件。失败产物和日志保留在 `build/task029_release/`。

正式构建入口现在是 [build_production_release.py](D:/Code/Python_Projects/DPS_Studio/tools/build_production_release.py)。它限制构建 PATH 为所选 Python 环境与 Windows 目录，并清除继承的 Python/Conda/Qt 注入变量；运行 smoke 的 PATH 仅含 Windows 目录。它为全新的 output root 执行 `--clean`，检查 runtime，写 ZIP，独立解压，核对每个文件 SHA-256，启动真正的 Windows Qt 窗口，在 GUI 主循环报告实际模块路径后正常关闭。没有手工 DLL 复制，也没有清理或覆盖旧发布包。输出 root 已存在时明确失败。

构建入口会调用以下实际命令（当前 Python 及依赖版本保持原样）：

```powershell
& 'D:\miniconda3\envs\dps-studio\python.exe' tools/build_production_release.py --output-root build/task029_release_verified

# 上述入口实际调用：
& 'D:\miniconda3\envs\dps-studio\python.exe' -m PyInstaller --clean --noconfirm --workpath D:\Code\Python_Projects\DPS_Studio\build\task029_release_verified\work --distpath D:\Code\Python_Projects\DPS_Studio\build\task029_release_verified\dist D:\Code\Python_Projects\DPS_Studio\packaging\pdv_studio.spec
```

后续构建请给一个未存在的 output root。直接从包含第三方 DLL 目录的 shell 调用 PyInstaller 不经过该环境限制，不能作为本任务验证过的发布流程。

环境：Python 3.12.13；PyInstaller 6.21.0；hooks-contrib 2026.6；PySide6/shiboken6 6.11.1；SciPy 1.18.0；NumPy 2.5.1。仓库没有锁文件，完整构建环境版本记录在 manifest，不声称不同依赖版本构建会字节一致。

新构建的 450 个文件与 ZIP 解压文件 SHA-256 全部一致。ZIP SHA-256：`c695f5cd4387e5ec483c9b52493e2c604a2f61b08a1a0b8173766e50f214df4d`。新 smoke 的 `event_loop_entered=true`、`window_visible=true`、`qt_platform=windows`，正常退出 0；PySide6/shiboken6/SciPy 模块全从 `C:\Users\89484\AppData\Local\Temp\dps_production_release_ssrtl2pt\PDV_Studio_v0.1.3` 加载。

历史 iconfix ZIP 共 453 个文件，也通过独立解压和只含 Windows PATH 的窗口启动、正常关闭测试。与当前 iconfix 目录的 ZIP 成员差异只有用户说明书 PDF，三个 runtime 成员一致；本任务没有读取或重写 PDF 内容。缺失发生在哪个历史环节仍无证据。

**起跳量及科学适用边界**

实际路径为 `compute_stft → ridge/refinement → spectral_quality → detect_signal_existence → build_stream_event_candidates → GUI候选 → 用户采用`。candidate 模块消费最终 `SignalDetectionResult`，没有直接对原始时域电压做 RMS/幅值起跳检测，也不通过速度门槛定义起跳。

谱质量使用同一 STFT 帧内、候选峰保护带以外的背景频率 bin：`peak_to_background_db = 20 log10(|peak| / median(|background bins|))`，竞争峰量使用其最大值；不是事件前静段的时间 baseline。当前 Production TOML 设置新段背景对比 10 dB、建立后的 tracking 7 dB、竞争峰 3 dB、连续 3 帧、至少 1 个窗内周期以及 150 MHz 相邻频率步长约束。事件候选进一步要求至少 8 帧、帧中心跨度至少 20 ns、最大相邻频率步长 150 MHz。没有原始电压绝对幅值下限、时间 baseline-relative amplitude 门或独立的原始信号 prominence 条件。

搜索被现有分析 ROI 与频率范围限制；primary 为最早的合格测量段。GUI 优先显示该候选，必要时保留 detector 的低置信度兼容候选。当前正式 event reference 初始 unset，不自动将建议变成真值；用户选择采用自动候选或手动设置才更新正式 reference。采用后会影响事件相对时间、事件前显示及后续相关分析，所以人工选择仍有实际后果。已有 ROI 可以约束搜索，没有新增重复的时间范围系统。

这些频谱比值对整体幅值缩放不敏感，不能仅据此确认物理事件身份。此次没有证实“长静段噪声提前触发”这一具体 bug：固定种子的 32,768 点静段白噪声没有生成 event-level primary。此测试不排除实验相干干扰。本任务不修改默认 STFT、ridge/速度/窗口/角度物理、LiF、Research 算法或事件阈值。

**两列导出的精确定义**

默认两列为 `time_s` 或 `time_from_event_s` 加 `display_velocity_m_s`，继续读取 `ChannelAnalysis.plot_velocity_m_s`：连续修正 working velocity，可包含同帧 refined/coarse fallback 与显式事件前显示平台。它不是“全部通过质量筛选”的正式测量表。既有 detail CSV 继续分别记录正式 apparent/angle-corrected/corrected velocity、continuous/display velocity、ridge flags、signal state、working source、selection origin/rank 和 display-only 标志，不可靠正式值为 NaN。

新增复选框默认关闭，文字说明“两列，时间序列可能有缺口”。勾选后，简表输出与所选时间坐标配对的 **正式 `corrected_velocity_m_s`**，仅选择 `signal_state == measured`、正式修正速度有限、非显示平台的帧。所有文件名带 `_quality_passed`，详细 CSV 保留原来的诊断行范围；JSON 增加 `simple_export`，记录 mode、过滤规则、来源、列名、排除数、可能有缺口及详细表未过滤。没有平滑、插值、补点，也不在默认模式静默删点。

metadata 对 `input_provenance`/`simple_export` 的扩展是新增字段，保留原 formal-result-v6 schema、原顶层字段和 detail 列集合。筛选模式具有明确不同的 velocity 列名；两种模式都恰好两列。

真实说明书示例：80,000 行，时间列 0，两路电压列 1/2，输入 s/V，SI 内部不变；Balanced 全数据范围，当前正式 quality/correction 配置。每通道连续简表 620 行；ch1 质量简表 390 行、有限非 measured 显示点 230；ch2 质量简表 379 行、有限非 measured 显示点 241。输入文件 SHA-256 前后均为 `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。自动候选只记录为建议，本次导出的正式 reference 为 null。

**验收与关键输出**

| 检查 | 结果与路径 |
| --- | --- |
| 完整 pytest | **637 passed in 53.22s**；`build/task029_checks/pytest_final.txt`。默认宿主 pytest 临时目录曾因权限失败，使用全新 `--basetemp build/task029_tests_full2` 后完成；测试本身没有被跳过或削弱。 |
| Ruff | `python -m ruff check .`：All checks passed；`build/task029_checks/ruff_final.txt`。 |
| strict mypy | `python -m mypy --strict src/dps_studio`：80 source files，零问题；`build/task029_checks/mypy_final.txt`。 |
| clean build / runtime | 新目录 `build/task029_release_verified/`；完整 manifest 为 `release_manifest.json`；GUI Windows 主循环/正常退出通过。 |
| 新发布包 | [PDV_Studio_v0.1.3.zip](D:/Code/Python_Projects/DPS_Studio/build/task029_release_verified/PDV_Studio_v0.1.3.zip)。历史 `release/` 未改；交付应使用此新 ZIP。 |
| wheel / 安装包元数据 | `build/task029_checks/wheels/dps_studio-0.1.3-py3-none-any.whl`；wheel METADATA 与 installed editable metadata 均 0.1.3；runtime 依赖版本保持。 |
| 真实示例 export | `build/task029_real_export/`；两种 CSV、两种完整 detail 及 JSON；命令 `python tools/audit_production_feedback.py --output-directory build/task029_real_export`（重跑时指定新目录）。 |
| 回归测试 | 新 `test_production_feedback_audit.py`、`test_production_release.py`；扩展 GUI export/import/About、reader、package version 测试。证明筛选值来自 formal correction 而非 display，并覆盖零可靠点的 header-only CSV。 |
| 原始数据 | 全 suite 涉及 raw；开始前/结束后 **24 文件 SHA-256 全部一致**，明细保存于 verification.json；`git diff -- data/raw` 为空。 |
| diff 检查 | `git diff --check` 通过。只有 Git 既有 CRLF 转换提醒，没有 whitespace error。 |

构建非阻断 warning 为未安装可选 pyqtgraph OpenGL、SciPy hook 提及未找到 `_cdflib`；实际 Production GUI 和 SciPy 分析通过。未增加这些可选依赖，也未把 warning 解释为缺失 `_ccallback_c`。

**Git 状态及修改范围**

结束状态仍为 `main...origin/main [ahead 1]`。19 个已有文件修改，新增两个测试、两个工具、此报告、两个紧凑 JSON 证据文件。`build/` 中的大型包、wheel、导出与测试临时产物保持 ignored；无 commit/push/merge/rebase/cherry-pick。

完整命令输出：[git status](D:/Code/Python_Projects/DPS_Studio/build/task029_checks/git_status_final.txt)、[git diff --stat](D:/Code/Python_Projects/DPS_Studio/build/task029_checks/git_diff_stat_final.txt)。

`git diff --stat`（仅 tracked 修改，不含新文件）：

```text
 packaging/pdv_studio.spec                        | 25 ++++++-
 packaging/release_version.txt                    |  3 +-
 pyproject.toml                                   |  5 +-
 scripts/production_outputs.py                    |  8 +--
 src/dps_studio/__init__.py                        |  2 +-
 src/dps_studio/core/export/models.py              |  6 +-
 src/dps_studio/core/export/writer.py              | 83 ++++++++++++++++++++---
 src/dps_studio/core/io/delimited.py               | 36 ++++++++++
 src/dps_studio/core/time_frequency/models.py      |  7 +-
 src/dps_studio/core/time_frequency/stft.py         |  1 +
 src/dps_studio/gui/app.py                         | 32 +++++++++
 src/dps_studio/gui/data_controller.py             |  8 +++
 src/dps_studio/gui/import_dialog.py               |  2 +
 src/dps_studio/gui/main_window.py                 | 15 +++-
 src/dps_studio/gui/translations/pdv_studio_en.qm   | Bin 79927 -> 81366 bytes
 src/dps_studio/gui/translations/pdv_studio_en.ts   | 18 +++++
 tests/unit/gui/test_task017_result_export.py      | 52 ++++++++++++++
 tests/unit/test_delimited_io.py                   |  6 ++
 tests/unit/test_package.py                       |  9 ++-
 19 files changed, 291 insertions(+), 27 deletions(-)
```

关键 diff 限定为：版本来源统一；build/release 完整性和 PATH 环境；GUI 启动 smoke；显式筛选导出；原始 mapping/unit 传递与测试。STFT 的修改仅附带元数据，不改任何数值计算。

不应按未经验证的建议修改起跳阈值、为某发硬编码区间、把默认连续简表改为删点表、手工补 DLL、升级依赖或改物理公式。后续如需验证外部两发，应获得确切原始 CSV、完整分析设置、未人工补件的发布 ZIP 与错误日志，再独立复现。本任务已完成并停止，不进入下一 TASK。
