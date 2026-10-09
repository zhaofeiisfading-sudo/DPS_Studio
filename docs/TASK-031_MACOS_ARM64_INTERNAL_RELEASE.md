# TASK-031 — macOS arm64 内部发布实现与原生验收

阶段日期：第一阶段 2026-10-04；第二阶段 2026-10-09（Asia/Shanghai）。软件版本：`dps_studio.__version__ = 0.1.4`。

**首次远端验收：MACOS INTERNAL RELEASE BLOCKED。** 第二阶段已通过 GitHub MCP 实际 dispatch，真实 Mac runner 在 portable pytest 阶段失败。已保存完整日志/evidence，完成最小测试修复和 Windows 回归。2026-10-09 用户已授权将本次测试修复及必要报告更新提交并 push 到 origin/main，再对新 SHA dispatch；后续任何再次 commit/push 仍需新授权。正式 Mac ZIP 尚未生成，不能宣布 PASS。

## 第二阶段真实执行记录（2026-10-09）

开始时本地 `main`、`HEAD=origin/main=dda50631240208c0d694bdf575b458d33277a6dc`、工作区 clean。GitHub MCP 独立读取在线 main，同一 SHA，commit message 为第一阶段的 macOS pipeline 提交。workflow ID `374642166` 已启用，在线 YAML 包含 workflow_dispatch，并与本地文件一致。

使用实际暴露的 `actions_run_trigger(method=run_workflow, ref=main)` 直接执行，返回 **204 No Content / queued**。没有要求用户点击页面，也没有使用 CLI/REST 凭据回退。dispatch 前此 workflow 无旧运行；只 dispatch **一次**，未 rerun。

| 运行证据 | 实际值 |
| --- | --- |
| run URL / ID | [37912988005](https://github.com/zhaofeiisfading-sudo/DPS_Studio/actions/runs/37912988005) |
| job URL / ID | [internal-release / 113762349593](https://github.com/zhaofeiisfading-sudo/DPS_Studio/actions/runs/37912988005/job/113762349593) |
| workflow / event / branch | macOS arm64 internal release / workflow_dispatch / main |
| head_sha | `dda50631240208c0d694bdf575b458d33277a6dc` |
| run number / attempt | 1 / 1 |
| UTC 开始 / 完成 | 2026-10-09 09:42:22 / 09:45:20 |
| 上海时间开始 / 完成 | 2026-10-09 17:42:22 / 17:45:20 |
| runner label / 实际 image | macos-15 / macos-15-arm64 |
| macOS / build | 15.7.9 / 24G830 |
| runner image version | 20260907.0337.1 |
| host / Python architecture | arm64，uname 与 platform.machine 的断言步骤成功 |
| build Python | conda-forge Python 3.12.13，osx-arm64；版本断言成功，安装日志为 cp312 wheels |
| final run status / conclusion | completed / failure |

Miniforge provisioning、架构/版本断言、固定依赖安装和 pip check 全部成功。安装日志确认当前约束文件中的 NumPy 2.5.1、SciPy 1.18.0、pandas 3.0.3、matplotlib 3.11.0、PySide6/Essentials/Addons/shiboken6 6.11.1、PyQtGraph 0.14.0、Pydantic 2.13.4、pydantic-core 2.46.4、PyInstaller 6.21.0、hooks-contrib 2026.6、Pillow 12.3.0、pytest 9.1.1、Ruff 0.15.21、mypy 2.2.0 安装成功。日志中 conda info 的 base interpreter 版本不代替目标 build Python 的实际版本断言。

### 真实失败与验收范围

Mac portable pytest：**2 failed, 695 passed, 18 deselected in 70.00s**；JUnit 为 697 tests、2 failures、0 errors、0 skipped。18 项显式排除项与原合同一致。失败节点：

- `tests/unit/test_run_demo_pipeline_modes.py::test_failed_production_does_not_update_latest_run`
- `tests/unit/test_run_demo_pipeline_modes.py::test_successful_production_updates_latest_run_and_prints_simple_exports`

两项均进入 `scripts/run_demo_pipeline.py:73` 后抛出：

```text
FileNotFoundError: Input file does not exist: /Users/runner/work/DPS_Studio/DPS_Studio/data/raw/20260607.csv
```

根因已由日志和源码共同确认：两项输出/运行指针单元测试 mock 了信号读取与生产导出，却继承 `demo_dual_profile.toml` 的私有 raw input。真实入口在 mock 前先检查文件是否存在并计算 SHA，因此 hosted checkout 缺少 raw 时失败。本地第一阶段有 raw，未暴露这一间接依赖。此失败不是 STFT/ridge/quality/velocity/LiF 数值错误，也没有暂时性基础设施失败证据，故不盲目 rerun。

| 正式验收项 | 本次远端结果 |
| --- | --- |
| native macos-15 / arm64 / Python 3.12.13 | PASS |
| portable pytest | FAIL：695 passed、2 failed、18 deselected |
| Ruff / strict mypy | SKIPPED（上游 pytest 失败），不记为 Mac PASS |
| PyInstaller / PDV Studio.app / ICNS | SKIPPED，未构建 |
| native Cocoa / event loop | NATIVE_GUI_NOT_VERIFIED，build step 未执行；pytest 的 offscreen 不替代此项 |
| app 内 PySide6 / shiboken6 / SciPy 来源 | NOT VERIFIED，尚无 app runtime |
| file/lipo/otool / native dependency audit | NOT RUN |
| ad-hoc codesign | NOT VERIFIED；notarization=NOT_PERFORMED |
| frozen scientific smoke / Windows–Mac 数值回归 | NOT RUN |
| ZIP roundtrip / 正式 ZIP / 正式 ZIP SHA-256 | NOT RUN / NOT GENERATED / N/A |

JUnit 确认 `test_public_scientific_chain_matches_windows_reference` 在 Mac 源码环境通过；这不替代尚未执行的 frozen runtime 数值验收。

### 下载并保留的失败证据

本次仅有 **PDV-Studio-macos-arm64-internal-evidence** artifact，ID `11607113542`，16,702 bytes；没有正式发布 ZIP artifact。使用 GitHub connector 的实际 artifact download 工具取得并保存，未读取或泄露 GitHub access token。

外层 evidence artifact ZIP SHA-256：`0801b54e97728d3111b7fd646dece9cfdd3bffa89982db4546e11f75b9db2854`，与 GitHub artifact digest/上传日志完全相同。**此哈希属于证据 ZIP，不是正式 Mac 发布 ZIP。**

本地目录：`build/task031_phase2_20261009/`：

- `dispatch.json`：预期 SHA、dispatch 回执与首次 run 关联。
- `run_evidence.json`：真实 run、job、全部 steps 和 artifact metadata。
- `job_113762349593.log`：完整 job log。
- `evidence_artifact.zip`：下载的原始证据 ZIP。
- `evidence/task031_ci_checks/portable.txt`、`portable.xml`：解出的完整 pytest 输出/JUnit。

artifact 中只有上述两个 pytest 文件。环境/签名/启动/build manifest 尚未产生，因为 build step 未执行；没有将其缺失解释成通过。未创建或覆盖 `release/PDV_Studio_v0.1.4_macos_arm64.zip`。

### 最小本地修复与 Windows 回归

仅修改 `tests/unit/test_run_demo_pipeline_modes.py`：测试 helper 显式选用合法已提交的 `docs/原始数据.csv`，用于已有 mock 的运行指针/输出报告测试。不是 raw fallback，未改变生产默认 TOML、pipeline 入口或任何科学算法；也没有新 deselect/skip。新增 2 项测试分别检查明确的公开输入/列映射，以及显式输入缺失时仍报错、不得替换 fixture。

| 本地修复验证 | 实际结果 |
| --- | --- |
| 该模块 targeted pytest | 10 passed in 9.04s |
| 完整 Windows real-data pytest（含 Windows release/packaging tests） | **717 passed in 83.40s**，无 skip/xfail |
| portable + 私有 raw 不可用的只读 I/O guard 演练 | **699 passed, 18 deselected in 55.59s** |
| Ruff | All checks passed |
| strict mypy（src + 3 个 Mac 工具） | 87 source files，无问题 |

仅为本地演练加载 `build/task031_phase2_20261009/portable_no_raw_guard.py`，令 Python 对本仓库 raw 的存在检查返回不可用并阻止读取；文件留在原位置，没有 rename/delete/替代数据。这不是正式 CI 或 Mac 原生验收，guard 不进入 Git/workflow。日志/JUnit 均保留在同一目录。

本阶段开始/结束 **24 raw 文件（含 .gitkeep）SHA-256 全部一致**。Research 未访问、未修改；core、configs、GUI、Windows/Mac build scripts、spec、workflow、约束依赖没有改动。Git 仍在 main，HEAD 与 origin/main 未变；本地未提交改动仅为该测试模块和本报告，另新增仓库外的当日 Obsidian 日志。未 commit/push/merge/rebase/cherry-pick，未建分支/worktree，未提交生成产物。

**首次停止点（2026-10-09 用户授权后解除）：** 用户明确允许提交本次已确认测试修复及必要报告更新、push origin/main，然后对包含修复的新 SHA dispatch。授权不覆盖后续新修复的再次提交。此处记录的首次 run 失败结论保持不变，不用本地 PASS 覆盖远端结果。修复提交信息：`test: remove private raw dependency from pipeline output tests`。

当日日志：`D:\Research\Notes\05项目\dps\2026-10-09_TASK-031_macOS-arm64内部发布.md`。仍需人工检查的 Mac 图标、首次打开、原生对话框、中文/空格路径、语言/QSettings、快捷键和 Retina 布局均待正式构建成功后验证。

---

以下为第一阶段历史记录（2026-10-04）：**READY_TO_PUSH_FOR_MACOS_CI**；当时未 dispatch、未生成 Mac ZIP。用户随后手工提交并推送了 `dda50631240208c0d694bdf575b458d33277a6dc`。下文未验收/未 push 等表述只记录当时状态，最新结论以上述第二阶段为准。

## 起始与 Git 边界

| 项目 | 实际结果 |
| --- | --- |
| 仓库 | `D:\Code\Python_Projects\DPS_Studio` |
| branch | `main` |
| 起始 HEAD / origin/main | `82a8b59e5a3f840c7f468329d96064c15df874f1`，相同 |
| 起始工作区 | clean |
| 实现结束 HEAD | 同上，未提交 |
| Git 写操作 | 未 commit、push、merge、rebase、cherry-pick；未创建 branch/worktree |
| Research worktree | 未访问、未修改 |
| 受保护范围 | core、科学默认配置、Windows spec/build script、PNG/ICO 均无 diff |

本报告对应上述 Production commit 加当前未提交的 TASK-031 改动。用户提交后的构建 commit 由 workflow 的实际 `git rev-parse HEAD` 记录；参考文件另记录生成基线的 Production commit，并核验所有 core Python 文件的内容 SHA，避免将包装提交的新 SHA 误当作科学算法变化。

## 实现文件

| 文件 | 合同 |
| --- | --- |
| `.github/workflows/macos-arm64-internal.yml` | 仅 workflow_dispatch；macos-15；contents: read；Miniforge；无 tag、无自动 GitHub Release |
| `packaging/macos-arm64-constraints.txt` | 固定当前 Production 依赖和验收工具版本 |
| `packaging/pdv_studio_macos.spec` | 独立 Analysis/PYZ/EXE/COLLECT/BUNDLE；windowed arm64；稳定 bundle ID；版本来自现有单一来源 |
| `tools/build_macos_release.py` | 新输出根、环境/架构、构建、Mach-O、签名、ditto ZIP 往返、最终 Cocoa/scientific smoke、哈希证据 |
| `tools/build_macos_icon.py` | 标准 10 张 iconset PNG + 原生 iconutil；正式 master 只读 |
| `tools/generate_macos_portable_reference.py` | 在 Windows Production 可重复生成新的参考；拒绝覆盖既有目的文件 |
| `tools/__init__.py` | 工具模块的明确包边界，供 strict mypy 和门槛测试导入 |
| `src/dps_studio/release/__init__.py` | 发布验证包；core 不依赖它或 GUI |
| `src/dps_studio/release/portable_reference.py` | 公共 API 科学链、确定性 synthetic、精确判定和浮点容差合同 |
| `src/dps_studio/gui/release_smoke_macos.py` | dyld 实际已加载 image 路径；正常退出在 event loop 返回后记录 |
| `src/dps_studio/gui/release_smoke.py` | 仅增加 Darwin dispatch；保留完整 kernel32/qwindows 探测 |
| `src/dps_studio/gui/app.py` | 隐藏 Mac smoke 增加数值快照、QApplication/MainWindow/lifecycle/退出证据；失败时保留 Cocoa 生命周期诊断 |
| `tests/conftest.py` | 显式 `--portable-ci` 合同；默认完整套件不变 |
| `tests/reference/macos_portable_reference_v014.json` | 约 249 KiB；完整 1-D 结果、无 spectrum arrays、无私有 raw 拷贝 |
| `tests/unit/test_macos_internal_release.py` | 66 项门槛测试，含科学链、外部 native origins、错误架构、签名和 ZIP 损坏拒绝 |
| 本报告 | 第一阶段证据、待验收项和第二阶段入口 |

ICNS 必须由 Mac 的 `iconutil` 产生，当前 Windows 没有这个工具，故未伪造或提交 ICNS。工具默认目标为 `src/dps_studio/gui/icons/pdv_studio.icns`；CI 构建在独立 evidence/icon 目录生成同名资产并打入 `.app` 的图标与 `dps_studio/gui/icons` 资源路径。evidence 会包含 ICNS、master/output SHA 和实际生成命令。Finder/Dock 的实际图标显示待 Mac 验收。

## 依赖与环境

本地实际解释器：`D:\miniconda3\envs\dps-studio\python.exe`；Windows AMD64；Python **3.12.13**。PATH 中另一个 base Python 3.9.1 未被用来构建、测试或生成数值参考。

| 依赖 | 固定版本 |
| --- | --- |
| Python（conda-forge osx-arm64） | 3.12.13 |
| NumPy / SciPy | 2.5.1 / 1.18.0 |
| pandas / matplotlib | 3.0.3 / 3.11.0 |
| PySide6 / Essentials / Addons / shiboken6 | 全部 6.11.1 |
| PyQtGraph | 0.14.0 |
| Pydantic / pydantic-core | 2.13.4 / 2.46.4 |
| PyInstaller / hooks-contrib | 6.21.0 / 2026.6 |
| Pillow | 12.3.0 |
| pytest / Ruff / mypy | 9.1.1 / 0.15.21 / 2.2.0 |

这些版本与当前本地安装重新核对一致，无升级、降级或全局安装。Mac 的安装、求解和原生加载尚未实际运行。workflow 对 `uname -m`、Python machine 和 patch 版本进行硬检查；不使用 setup-python 代替所要求的 Miniforge Python。

## 三层数据与测试合同

1. **Portable CI**：`pytest --portable-ci` 显式 deselect 4 项私有 raw 测试和 14 项 Windows 发布测试；日志逐项列明原因。其余原有测试和新增测试保留。GUI 单元测试步骤可用 offscreen，独立 release Cocoa 进程强制使用 cocoa。
2. **Release scientific smoke**：只使用合法已提交的 `docs/原始数据.csv`，以及明确标注 synthetic 的确定性 fixture。不上传、拷贝或替换 `data/raw`。
3. **Full local real-data suite**：默认 `pytest` 仍执行全部 raw regression 和 Windows byte fingerprints；没有删除、skip 或 synthetic fallback。GitHub public CI 不声称执行此层。

此次本地真实结果：

| 验证 | 结果 |
| --- | --- |
| FULL LOCAL REAL-DATA SUITE（Windows） | **715 passed in 54.21s**，含原 649 项和新增 66 项，无 skip/xfail |
| PORTABLE CI（本地 Windows 演练） | **697 passed, 18 deselected in 54.78s** |
| 新增发布门槛最终复核 | **66 passed in 3.19s** |
| Ruff | **All checks passed** |
| mypy --strict | **87 source files，无问题**，含新 release 包与 3 个新工具 |
| mypy --strict --platform darwin（本机类型检查演练） | **87 source files，无问题**；不等于 Mac 原生运行 |
| workflow YAML | 解析通过；静态验证不代表 Mac job 成功 |
| Mac portable suite | **NOT RUN** |

本地日志与 JUnit：`build/task031_checks/pytest_full_final.txt`、`full_windows_final.xml`、`pytest_portable_final.txt`、`portable_windows_final.xml`、`ruff_final.txt`、`mypy_final.txt`。

## Windows 数值参考与跨平台比较

生成命令（目的路径必须新建）：

```powershell
& 'D:\miniconda3\envs\dps-studio\python.exe' tools/generate_macos_portable_reference.py --output build/task031_reference_reproduced.json --export-root build/task031_reference_reproduced_exports
```

参考包含输入 SHA、版本、Production commit、Python/依赖、core 源码 SHA、完整配置、balanced profile、STFT 参数、频率轴、ridge/refinement、apparent/corrected velocity、NaN/quality/事件判定、行数和导出 schema。完整一维序列用于逐点比较；离散序列使用无损 run-length encoding。NaN 用 JSON null 表示，不使用非标准 JSON NaN。没有序列化巨大二维谱。

| 证据 | SHA-256 |
| --- | --- |
| 数值参考 JSON | `fb00178bef2a74e315ed65ef37b74ff965cee2715767e98ef2dff0908934e564` |
| Windows 示例 CSV 原始字节 | `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353` |
| 示例仅规范 CRLF/LF 的内容 | `6e87e8e7a4d79a0d3ca3e4f0d9f237e1ddbdebe4a93fa48db0dcf281d74c29f8` |
| Windows 默认 TOML 原始字节 | `a34a1f2eaa1aaa637bdf3c5b7131f1b244ec65f80f986c1827277076c9c18ac5` |
| TOML 仅规范 CRLF/LF 的内容 | `aab087c0bb43ad28a0401a126f79ca69c44d78a374bd65618cdeb37e2fd5d494` |

独立新目录重复生成后，JSON **SHA 完全一致**。此字节重现结果仅指相同 Windows 环境的参考生成，不要求 Windows/Mac 浮点字节一致。

`git ls-files --eol` 实际显示示例为 `i/lf w/crlf`，默认 TOML 为 `i/lf w/mixed`。Mac 比较严格检查只规范 CRLF/LF 的内容 SHA，并在 evidence 保留双方实际文件字节 SHA 与差异；读取前后同一文件的原始字节 SHA 仍必须相同。除 Git 换行差异外不放宽输入或配置内容检查，也不改写源文件。

真实示例：80,000 samples；Hann、window=768、overlap=640、hop=128、nfft=4096；代表采样率 `39999999986.359764 Hz`，来自原始时间轴。两通道各 620 frames；continuous/detailed 各 620 行，quality-passed 分别 390/379 行。continuous 为 `time_s,display_velocity_m_s`；quality-passed 为 `time_s,corrected_velocity_m_s`。原始单位 s/V，输出使用 SI；JSON version/provenance 已验证。

Synthetic：40 GHz、8192 samples、2048-sample silent prefix、明确给定的 chirped beat 与微弱确定性第二频率成分；没有随机 seed 漂移或替代 raw。

按 TASK-029A 合同：

| 量 | rtol | atol |
| --- | --- | --- |
| frequency grid / discrete ridge | 1e-12 | 1e-6 Hz |
| refined ridge | 1e-9 | 1e-3 Hz |
| apparent / corrected velocity | 1e-9 | 1e-5 m/s |
| time axis | 0 | 0 |

完整 NaN mask、ridge bin、selected bin、quality/refinement flags、signal states、working source、event segment/frame selection、行数和 schema 单独严格相等。浮点比较报告每通道和 synthetic 的最大绝对/相对误差，以及近零相对分母尺度。任一离散判定变化使发布失败，必须调查；没有增加容差、平滑、插值或删点机制。Windows 与自身重复结果通过；**Windows/Mac 数值回归 NOT RUN**。

## 原生 Mac 发布门槛

运行入口：`python tools/build_macos_release.py --output-root build/task031_macos_release`。输出根必须不存在，避免删除历史输出；随后 PyInstaller 使用独立新 work/dist 和 --clean。Windows 环境明确拒绝此入口，不生成假 `.app`。

对整个 bundle 中实际 Mach-O 文件运行 `file`、`lipo -archs`、`otool -arch arm64 -L/-l`，要求每个 native binary 包含 arm64，并要求 executable、Python、QtCore/Gui/Widgets、shiboken、SciPy、Cocoa 类别齐备。依赖/rpath 只允许系统路径或正确的 loader/executable/rpath 引用，bundle 目标必须存在且留在 app 内。

PyInstaller 的实际 ad-hoc 签名必须通过 `codesign --verify --deep --strict` 和 `codesign -dv --verbose=4`。初次构建验签失败可显式 ad-hoc 重签并再次验证；ZIP 解压后验签失败不能用重签掩盖。成功 metadata 必须是 `codesign=AD_HOC`、`notarization=NOT_PERFORMED`，不声明 Developer ID/notarized。[PyInstaller 6.21 原生架构和签名说明](https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.21.0/doc/feature-notes.rst)

归档采用 `ditto -c -k --keepParent`；解压采用 `ditto -x -k`。当前 Apple DTS 建议分发软件时避免 `--sequesterRsrc`，因此没有照搬任务中的示例参数。[Apple DTS 建议](https://developer.apple.com/forums/thread/775923)、[Apple 对 ZIP 元数据布局的说明](https://developer.apple.com/forums/thread/690457)

往返严格比较 root/目录/文件类型、mode、symlink target、字节 SHA 和文件集合；拒绝越出 bundle 的链接，并重新验证签名和 Mach-O。正式交付仅上传验证后的 ZIP。

最终重新解压的 `Contents/MacOS/PDV Studio` 在独立 cwd、系统 PATH 下启动，去除 Python/Conda/Qt/DYLD 等注入；`QT_QPA_PLATFORM=cocoa`。实际 dyld images 必须证明 QtCore/Cocoa/shiboken/SciPy native images 来自最终解压 app。QApplication、MainWindow、visible、event loop、cocoa、arm64 和正常退出码 0 都是门槛；exposed 按任务要求记录，不伪造。失败/超时写 `NATIVE_GUI_NOT_VERIFIED` 并使 workflow 失败，**没有 offscreen fallback**。

成功 evidence 至少包含：`environment.json`、`dependency_versions.json`、`build_manifest.json`、`mach_o_audit.txt`、`codesign_audit.txt`、`startup_smoke.json`、`analysis_regression.json`、`hash_manifest.json`；还包含 icon/生成记录和 build log。失败仍上传可取得的诊断和前序测试日志。environment 只保存相关清理策略，不公开整个 runner 环境变量值。

## Windows 发布回归

使用未修改的 `tools/build_production_release.py` 和 `packaging/pdv_studio.spec`，在新目录构建最新工作区：

```powershell
& 'D:\miniconda3\envs\dps-studio\python.exe' tools/build_production_release.py --output-root build/task031_windows_release_final --analysis-smoke-input docs/原始数据.csv
```

**真实构建/ZIP/解压/原生 Windows GUI/scientific smoke PASS**：退出 0；platform=windows；visible/exposed/event_loop_entered 全部 true；PySide6、shiboken、SciPy、Qt DLL、qwindows 都从重新解压的发布目录加载。ZIP 文件集合/SHA 一致，运行后包内文件不变。两种 CSV 与 detailed/JSON/provenance/version 均通过。

Windows 验证 ZIP SHA-256：`5aeba841d1f9d350f68bc9ab11106b6f81318ecb88484a9245db66699e9750c5`。产物：`build/task031_windows_release_final/PDV_Studio_v0.1.4.zip`；证据：`build/task031_windows_release_final/release_manifest.json`。没有覆盖既有 `release/`。

## Raw 保护

开始/结束共 **24 文件（含 .gitkeep）**，逐文件 SHA-256 全部相同；`git diff -- data/raw` 为空。证据：`build/task031_checks/raw_before.json`、`raw_verification.json`。未上传、复制、写入或删除 raw；未创建 raw 替代 fixture。

## macOS 验收状态与第二阶段

| 验收项 | 本阶段实际状态 |
| --- | --- |
| 计划 runner / architecture | macos-15 / arm64；官方能力不是实际 job 证据 |
| 实际 runner / macOS / uname / Python | NOT RUN |
| workflow run URL / ID | NOT RUN，用户尚未 push |
| Mac portable tests / Ruff / mypy | NOT RUN |
| PDV Studio.app / ICNS / Cocoa plugin | NOT BUILT / NOT VERIFIED |
| file/lipo/otool | NOT RUN |
| Cocoa / bundle-local runtime | NATIVE_GUI_NOT_VERIFIED |
| codesign | NOT VERIFIED；实现目标 AD_HOC |
| notarization | NOT_PERFORMED（不属于本任务） |
| Mac scientific / Windows-Mac regression | NOT RUN |
| Mac ZIP / roundtrip / ZIP SHA-256 | NOT GENERATED / NOT VERIFIED / N/A |
| 本地 Windows / raw | PASS / unchanged |

正式目标仍为 `PDV_Studio_v0.1.4_macos_arm64.zip`。workflow artifact 名称为 `PDV-Studio-macos-arm64-internal-zip`，证据 artifact 为 `PDV-Studio-macos-arm64-internal-evidence`。

用户手工 commit/push 后进入第二阶段：运行 workflow_dispatch，读取真实 run/job steps/失败日志/artifact；按实际结果修复，再验证全部 Mac 门槛。只有完整证据成立才写 MACOS INTERNAL RELEASE PASS。若 hosted runner 不能完成原生 Cocoa，保持 BLOCKED 并报告实际失败原因。

仍需真 Mac 手工验证：Finder/Dock 图标、下载与首次打开、中文/空格路径、原生文件对话框、语言/QSettings 恢复、菜单/Command 快捷键、Retina 字体布局、代表性用户数据导出。当前只计划 macOS 15，不宣称 13/14 支持；内部 ad-hoc 发布不等于 Apple 身份认证。

Obsidian 轻量日志：`D:\Research\Notes\05项目\dps\2026-10-04_TASK-031_macOS-arm64内部发布.md`。

推荐提交信息：`build: add macOS arm64 internal release pipeline and portable verification`。
