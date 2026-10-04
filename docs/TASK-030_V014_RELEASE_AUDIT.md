# TASK-030 — PDV Studio v0.1.4 正式发布审计

**RELEASE PASS — VERIFIED**

日期：2026-10-04。直接使用 `D:\Code\Python_Projects\DPS_Studio` 的 `main`；开始和结束 HEAD 均为 `3f3110c29f4c0e6f5890b6b2a4d112657ad7583d`。起始工作树包含 TASK-029 的未提交修改，完整保留。没有创建 branch/worktree、clone、commit、push、merge、rebase 或 cherry-pick，没有修改 Research。

正式 source of truth：

- [release folder](D:/Code/Python_Projects/DPS_Studio/release/PDV_Studio_v0.1.4)
- [PDV_Studio_v0.1.4.zip](D:/Code/Python_Projects/DPS_Studio/release/PDV_Studio_v0.1.4.zip)
- ZIP SHA-256：`0e6db59fbb16e226642fec240acc61b68537d892e025b6fb1835402b557b12dd`
- ZIP 大小：95,564,106 bytes；正式目录共 **452 文件**。
- [完整验收证据](D:/Code/Python_Projects/DPS_Studio/artifacts/task030/verification.json)

**TASK-029 源码复核：VERIFIED**

检查了实际 `git diff`、版本来源、importer、SignalRecord/STFT 元数据链、正式 export 行选择、GUI 复选框/About、spec、构建入口和回归测试。初始 diff 保存在 `build/task030_checks/task029_starting_diff.txt`，没有仅依据 TASK-029 报告判断正确。

| 项目 | 实际源码及验证结果 |
| --- | --- |
| A. Single source of truth | `src/dps_studio/__init__.py` 是唯一手写运行版本；Hatch 动态版本、GUI、export、spec/PE、manifest、artifact/ZIP 名称从它派生。 |
| B. JSON provenance | reader 保存零基列映射、scale 与明确输入单位，经 `SignalRecord.metadata → STFTResult.source_metadata → input_provenance` 到正式 JSON；不从 SI 数据猜单位。旧调用未提供单位时仍允许 null。 |
| C. 两列 CSV | 默认仍是 `time + display_velocity_m_s`，没有质量删点；质量筛选默认关闭，显式用户选择后仍两列，使用正式 `corrected_velocity_m_s`、独立 `_quality_passed` 名称、过滤 metadata 及时间缺口说明。详细表保留完整诊断行。 |
| D. PATH / ICU | 正式 build 只继承所选 Python 环境和 Windows PATH，去除 Python/Conda/Qt 注入。当前 Analysis TOC 的 **233 个 native entries** 没有外部来源，没有收集第三方 ICU；没有手工补 DLL。 |
| E. Runtime 完整性 | bundle 中存在 PySide6 QtCore/Qt6Core、shiboken6 native、qwindows、SciPy `_ccallback_c`。两次独立解压实际加载均成功。 |
| F. Startup smoke | 当前 smoke 在 GUI event loop 内运行，主窗口 `visible=true` 且 `exposed=true`，平台 `windows`；增加 Windows API 查询实际已加载 native DLL 路径，排除仅报告 Python 包入口路径的证据不足。 |

本任务只升级版本、补充发布验收路径与 JSON `software_version` 兼容别名，没有发现需要改变科学实现的 release blocker。`software_version` 与既有 `dps_studio_version` 使用同一个 Options 版本值，未建立第二个版本来源。

**版本一致性：全部 VERIFIED / 0.1.4**

| 位置 | 证据 |
| --- | --- |
| package / installed metadata | `__version__ == importlib.metadata.version('dps-studio') == 0.1.4`。当前专用环境只重装本项目 editable metadata：`pip install --no-deps -e .`；运行依赖未升级。 |
| pyproject / wheel | Hatch 从唯一版本源读取；`build/task030_checks/wheels/dps_studio-0.1.4-py3-none-any.whl` 的 METADATA 是 0.1.4。 |
| GUI application / About | applicationVersion 0.1.4；About 从同一 package version 格式化，GUI 回归通过。实际最终 EXE startup 的 version/gui_version 都是 0.1.4。 |
| JSON | source 和 frozen release 的连续/quality JSON 均 `software_version == dps_studio_version == 0.1.4`。 |
| Frozen package / PE | 从最终 EXE 的 PYZ 读取 package 常量 0.1.4；Windows FileVersion/ProductVersion 均 0.1.4。 |
| manifest / release / ZIP | BUILD_INFO、build manifest、正式目录名和 ZIP 名均由唯一版本源生成，为 0.1.4。 |

历史 0.1.0–0.1.3 发布文件、历史 JSON、TASK-029 报告和 artifact 没有更新为新版本。

**正式构建前检查：VERIFIED**

```powershell
& 'D:\miniconda3\envs\dps-studio\python.exe' -m pytest -q --tb=short --basetemp build/task030_tests_full1 -o cache_dir=build/task030_pytest_cache
& 'D:\miniconda3\envs\dps-studio\python.exe' -m ruff check .
& 'D:\miniconda3\envs\dps-studio\python.exe' -m mypy --strict src/dps_studio
```

- pytest：**649 passed in 53.69s**，包括原 637 项和 12 项新增 release gate 回归；没有 skip、xfail、删测试或放宽规则。
- Ruff：**All checks passed!**
- strict mypy：**Success: no issues found in 81 source files**。
- 日志：`build/task030_checks/{pytest,ruff,mypy}.txt`。

新增测试验证：普通 GUI 参数不启用 smoke；无效 smoke 参数显式失败；native DLL 外部加载阻止接受；必须有 exposed window 和完整 native report；ZIP 额外/缺失/变化文件均失败；已有 ZIP 不覆盖；真实分析同时保持连续与 quality 两列模式及版本/provenance。

**构建与正式 artifact 流程：VERIFIED**

```powershell
& 'D:\miniconda3\envs\dps-studio\python.exe' tools/build_production_release.py --output-root build/task030_release_v014 --release-root release --analysis-smoke-input 'docs/原始数据.csv'
```

output root 开始时不存在，正式 v0.1.4 目录和 ZIP 也不存在。入口实际调用 PyInstaller `--clean --noconfirm`，独立 work/dist 位于 `build/task030_release_v014/`，并强制使用以下 build PATH：

`D:\miniconda3\envs\dps-studio;D:\miniconda3\envs\dps-studio\Library\bin;D:\miniconda3\envs\dps-studio\Scripts;C:\Windows\System32;C:\Windows`

环境：Python **3.12.13**；PyInstaller **6.21.0**；hooks-contrib **2026.6**；PySide6 **6.11.1**；shiboken6 **6.11.1**；SciPy **1.18.0**；NumPy **2.5.1**。版本从真实安装环境记录。构建沿用原 spec/hooks，不新增手工 DLL 复制或科学配置。

build output 生成动态版本 README 和 BUILD_INFO；先从 build output 创建候选 ZIP，独立解压校验并启动/分析。候选验证通过后，完整复制到正式 `release/PDV_Studio_v0.1.4`，逐文件 SHA 核对；再**从正式 release directory 创建** `release/PDV_Studio_v0.1.4.zip`。最后使用这个最终 ZIP 在另一个全新临时目录重复完整验收。没有将 build/dist/work 当作正式发布目录。

正式最终 ZIP 解压目录：

`C:\Users\89484\AppData\Local\Temp\dps_production_release_ybclhgrm\PDV_Studio_v0.1.4`

它位于 repo、build tree、Python 和 Conda environment 之外。启动 cwd 是新的临时目录，PATH 只有 `C:\Windows\System32;C:\Windows`，删除继承的 Python、Conda、Qt/PySide/QML、virtualenv 和 `_PYI_` 注入变量。没有通过源码入口启动。

**最终 release ZIP 本身启动：VERIFIED**

最终实际启动命令等价于：

```text
<独立解压目录>/PDV_Studio_v0.1.4/PDV Studio.exe
  --startup-smoke-test <临时目录>/startup.json
  --analysis-smoke-input <临时目录>/example.csv
```

实际结果：`event_loop_entered=true`、`window_visible=true`、`window_exposed=true`、`qt_platform=windows`、`version=gui_version=0.1.4`，**正常 exit code 0**。Windows `GetModuleHandleW/GetModuleFileNameW` 返回实际模块路径，并通过目录边界检查：

| 实际加载的模块 | 相对于最终独立解压的 v0.1.4 目录 |
| --- | --- |
| PySide6 QtCore extension / Qt6Core | `_internal/PySide6/QtCore.pyd`、`_internal/PySide6/Qt6Core.dll` |
| Qt6Gui / Qt6Widgets | `_internal/PySide6/Qt6Gui.dll`、`_internal/PySide6/Qt6Widgets.dll` |
| shiboken6 extension / runtime | `_internal/shiboken6/Shiboken.pyd`、`_internal/shiboken6/shiboken6.abi3.dll` |
| Windows Qt plugin | `_internal/PySide6/plugins/platforms/qwindows.dll` |
| SciPy `_ccallback_c` | `_internal/scipy/_lib/_ccallback_c.cp312-win_amd64.pyd` |

全部来自该 v0.1.4 解压目录，没有来自 Miniconda、系统 Python、Codex、源码或其他 release 的上述模块。不是仅以“进程存活”判断通过。build ZIP 也独立通过同样检查，其临时目录与 final ZIP 不同。

两次解压都严格比较**文件集合及每个文件 SHA-256**，均与对应发布目录一致；运行后 package 文件集合和 SHA 仍不变。最终 ZIP SHA 再次独立读取确认，与 manifest 一致。完整 manifest 在 `build/task030_release_v014/release_manifest.json`。

**真实分析 / export：VERIFIED**

合法样例为说明书指定 `docs/原始数据.csv`：80,000 行、3 列，明确映射 time=0、voltage=1/2、输入 s/V，内部 SI。它被复制到临时目录，EXE 不访问源码 CSV。输入 SHA-256：`ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。

source regression 与两次 frozen EXE regression 均执行公共 core 的：import → Balanced STFT → ridge → quality → velocity → angle/window correction → 正式 export。最终 release EXE 的 core module 路径也位于自己的 `_internal`；它使用包内原 scientific defaults。完整分析在实际 GUI event loop 内完成，**未声称进行了导入对话框或按钮点击的自动操作**。

| 通道 | 连续两列 CSV | quality-passed 两列 CSV | detailed CSV |
| --- | --- | --- | --- |
| ch1 | 620 行；`time_s,display_velocity_m_s` | 390 行；`time_s,corrected_velocity_m_s` | 两种模式均保留 620 诊断行 |
| ch2 | 620 行；`time_s,display_velocity_m_s` | 379 行；`time_s,corrected_velocity_m_s` | 两种模式均保留 620 诊断行 |

逐值验证连续 CSV 等于原 `plot_velocity_m_s`，筛选 CSV 等于 measured/finite/non-platform 的正式修正速度。检查 detail quality flags、working source、metadata 的 filtering/gaps/name、零基原映射、s/V 单位和 1.0 SI scale。两种 JSON 的软件版本均 0.1.4，原文件哈希不变。

source 输出：`build/task030_real_export/`。最终 EXE 输出：`C:\Users\89484\AppData\Local\Temp\dps_production_release_ybclhgrm\analysis_export/`；结果路径与统计记录于 verification.json。

**验收 gates：全部 VERIFIED**

| Gate | 结果 |
| --- | --- |
| main / 无新 branch 或 worktree | PASS |
| 0.1.4 版本一致性 | PASS |
| pytest / Ruff / mypy strict | PASS |
| source 与 release-side 真实分析 | PASS |
| continuous / quality 两列格式 | PASS |
| detailed diagnostics / JSON provenance | PASS |
| clean PyInstaller build / runtime 完整性 | PASS |
| build ZIP 隔离启动 | PASS |
| **最终 release ZIP 隔离启动** | **PASS** |
| visible + exposed window / Qt event loop / windows platform | PASS |
| shiboken6 / qwindows / SciPy native 本地加载 | PASS |
| ZIP 文件集合 / 所有 SHA-256 / ZIP SHA | PASS |
| raw SHA-256 / 历史发布保护 | PASS |
| git diff --check | PASS |

**raw / 历史 / scientific 边界：VERIFIED**

开始和结束对全部 **24 raw 文件**计算 SHA-256，全部一致，`git diff -- data/raw` 为空；不移动、改名、格式化或清理 raw。历史 release 的 **2,256 文件**逐一哈希及文件集合核对，全部保持，没有覆盖或删除历史版本。

按 TASK-030 起始源文件 SHA 复核，仅已有 package init、export writer 和 GUI app 源文件变化；新增 `gui/release_smoke.py`。STFT/profile、ridge、candidate/event threshold、quality、continuity、velocity/angle/LiF 和 scientific defaults 均保持原字节。STFT 在累计 Git diff 中显示的 metadata 修改来自已完成 TASK-029，不是本次科学算法改动。

本任务增量文件：`src/dps_studio/__init__.py`（唯一版本源）、`core/export/writer.py`（同源 software_version 别名）、`gui/app.py` 与新 `gui/release_smoke.py`（native/analysis smoke）、`tools/build_production_release.py`（正式 stage/final ZIP 严格复验）、`tests/unit/test_production_release.py` 和新 `test_v014_release_verification.py`；本报告与 `artifacts/task030/verification.json`。其他 TASK-029 修改原样保留。

**Git：VERIFIED**

`main...origin/main [ahead 1]`，HEAD 没变。工作区包含 TASK-029/030 的未提交修改和新增文件，保留供用户人工确认，未 commit/push。正式 release/build 产物继续按原 `.gitignore` 排除。

完整最终 [git status](D:/Code/Python_Projects/DPS_Studio/build/task030_checks/git_status_final.txt)、[git diff --stat](D:/Code/Python_Projects/DPS_Studio/build/task030_checks/git_diff_stat_final.txt)、[git diff --check](D:/Code/Python_Projects/DPS_Studio/build/task030_checks/git_diff_check_final.txt) 在检查目录保存。`git diff --stat` 仅计 tracked 文件；新增的 tools/tests/smoke/report/JSON 需同时查看 git status。

**NOT VERIFIED / remaining risks**

没有在另一台物理电脑或较旧 Windows 版本进行兼容性验证；本机验证是隔离环境下独立 EXE 运行，不声称跨系统全面兼容。外部“两发”及 0.348 μs 起跳偏差仍缺对应数据，未复现，也没有因此改阈值。连续 display 的低质量候选属于已说明的导出语义，筛选仍是用户显式选项。构建保留可选 OpenGL 和 SciPy hook `_cdflib` warning，实际 Production GUI、SciPy/STFT、分析/export 已验证通过，无此次发现的 release blocker。

指定的 Obsidian 轻量日志已写入 `D:\Research\Notes\05项目\dps\2026-10-04_TASK-030_v0.1.4正式发布.md`。本任务完成后停止，不进入下一 TASK。
