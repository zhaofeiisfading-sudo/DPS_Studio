# TASK-029A — PDV Studio macOS 发布可行性与 GitHub Actions 审计

日期：2026-10-04（Asia/Shanghai）。版本：**0.1.4**。本任务仅审计、核验和设计，未实现 macOS build，未创建 workflow，未触发 GitHub Actions。

**最终可行性等级：MACOS_READY_WITH_MODERATE_CHANGES。**

这是根据真实源码、具体版本分发文件与 GitHub 设置得出的**条件性可行性判断**，不是 macOS 发布通过声明。科学核心未发现 Windows 原生依赖；主要依赖具备 arm64 分发；推荐原生 arm64、固定 `macos-15` hosted runner、独立 macOS spec/script。当前 Windows 发布入口不能直接承担 macOS 发布；完整 CI 还缺实验测试数据。实际 Mac 安装、Cocoa 启动、归档签名与跨平台数值比较均 **NOT VERIFIED**。

## 1. 起始状态与同步门槛

以下为实际运行记录，完整结构化证据保存在 [audit_evidence.json](D:/Code/Python_Projects/DPS_Studio/build/task029a_audit_20261004/audit_evidence.json)。

```text
pwd
D:\Code\Python_Projects\DPS_Studio

git branch --show-current
main

git status
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean

git rev-parse HEAD
8b049a4a741ad7188745b7d791c97070d196c2ec

git rev-parse origin/main
8b049a4a741ad7188745b7d791c97070d196c2ec

git remote -v
origin https://github.com/zhaofeiisfading-sudo/DPS_Studio.git (fetch)
origin https://github.com/zhaofeiisfading-sudo/DPS_Studio.git (push)

git log --oneline --decorate -5
8b049a4a (HEAD -> main, origin/main, origin/HEAD) release: finalize v0.1.4 production audit and packaging
3f3110c2 清理缓存文件
07a1e0f8 1.3.0
b4c25e33 (worktree-packaging-v0.1.3) 修改bug
9ac14521 优化处理流程，简化为四步，放宽门控条件，新增人工选定是否分析起跳点
```

**VERIFIED：**GitHub 插件实际读取 [GitHub main](https://api.github.com/repos/zhaofeiisfading-sudo/DPS_Studio/branches/main)，SHA 同为上述 HEAD；没有把本地 tracking ref 当作唯一在线证据。远端递归 Git tree 未截断，本地/远端 **1,347 个文件对象的路径、mode 与 blob SHA 全部一致**，没有缺失或额外对象。无需 fetch、merge 或其他 Git 写操作。

## 2. GitHub repository 与源码完整性

**VERIFIED：**[repository API](https://api.github.com/repos/zhaofeiisfading-sudo/DPS_Studio) 返回 owner `zhaofeiisfading-sudo`、repository `DPS_Studio`、default branch `main`、visibility `public`；archived=false、disabled=false。remote URL 为上节所列 HTTPS 地址。

| 检查对象 | 远端实际状态 | 对 macOS 的含义 |
| --- | --- | --- |
| pyproject.toml、README.md、.gitignore | 已提交且对象一致 | 构建/依赖定义与说明可取得 |
| src/dps_studio、packaging、tools、scripts、configs、tests | 已提交且对象一致 | 当前实现与 Windows pipeline 可审计 |
| configs/pdv_studio_defaults.toml | 已提交 | GUI 的默认配置不需要本地未提交文件 |
| gui/icons/pdv_studio.ico、pdv_studio_master.png | 已提交 | 运行图标与高分辨率源图均可取得 |
| gui/translations/pdv_studio_en.qm、.ts | 已提交 | 编译后的实际翻译资源可取得 |
| docs/原始数据.csv | 已提交 | 可用于初始真实 STFT/export smoke |
| resources/ | 当前没有此根目录 | GUI 未引用该目录，不属于缺失必需资源 |
| .github/ | 当前没有此目录或 workflow | 未来需要新增，不是已有 workflow 丢失 |
| data/raw | 远端仅 .gitkeep | 完整现有 pytest 无法取得其直接引用的实验 CSV |
| data/reference/legacy/*.csv | 被忽略，远端无 CSV | 独立 legacy 审计脚本也不能照搬为干净 CI 步骤 |
| build、dist、release、outputs | 按现有规则忽略 | 生成产物应重新生成，不能作为 CI 必需输入 |

GUI 非 Python 资源的实际查找链为 `runtime_paths → application_resource_root/package_resource_path → defaults TOML / ICO / QM`，三类必需资源全部在 GitHub。未发现 GUI 依赖被忽略的本地图像或配置。用户导入的实验数据不是应用启动的内置资源。

**GITHUB_SOURCE_INCOMPLETE：这里指完整 macOS CI 验证输入不完整，运行源码与内置 GUI 资源完整。**具体缺失、已经由测试源码和远端树共同证实的文件是：

- `data/raw/20260607.csv`
- `data/raw/20260630-1.csv`
- `data/raw/20260630-2.csv`
- `data/raw/20260701.csv`

[.gitignore](D:/Code/Python_Projects/DPS_Studio/.gitignore:57) 明确忽略 raw，且上述文件本地存在、远端不存在。直接读取它们的测试包括 [test_task018c_real_regression.py](D:/Code/Python_Projects/DPS_Studio/tests/unit/test_task018c_real_regression.py:32)、[test_task015a_analysis.py](D:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_task015a_analysis.py:413)、[test_task015c_r_event_reference_views.py](D:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_task015c_r_event_reference_views.py:443)、[test_legacy_velocity_audit.py](D:/Code/Python_Projects/DPS_Studio/tests/unit/test_legacy_velocity_audit.py:284)。这些测试没有因缺数据自动 skip 的保护。

不能为通过 CI 把全部 raw 推入 public repo，也不能给 `data/raw` 写入替代数据。未来应增加明确的只读实验 fixture 来源，使用 workspace 之外受控的数据路径，并保留 SHA 验证；公开普通测试和发布 smoke 可使用现有合法已提交示例及确定性合成数据。实际实验回归 job 在输入不可用时必须明确失败或标为未验收，不能把它遗漏后仍声称完整套件通过。

## 3. 当前平台相关源码分类

检查了真实 src、packaging、tools、scripts 与测试；对 core 的 import 使用 AST 复核，绝非仅根据 Python 技术栈判断。

| 分类 | 真实位置与发现 | 结论 |
| --- | --- | --- |
| CROSS_PLATFORM | core 的绝对导入仅标准库、NumPy、SciPy 和本项目 core | 未发现 core→GUI、WinDLL、winreg、win32api、Windows shell 或原生 Windows 扩展依赖 |
| CROSS_PLATFORM | STFT 使用 scipy.signal.get_window/stft，float64/complex128、SI | 科学核心没有移植所需算法改动证据 |
| CROSS_PLATFORM | pathlib、明确 UTF-8/用户 encoding、CSV newline、tomllib | 未发现 core 手写 Windows 分隔符或驱动器路径依赖 |
| CROSS_PLATFORM | export 的 Windows 安全文件名/保留名约束 | 保守的跨平台文件名约束，非 Windows API，继续保留 |
| WINDOWS_PACKAGING_ONLY | spec 无条件 import PyInstaller.utils.win32.versioninfo，生成 PE VERSION_INFO，ICO | Windows spec 不能原样作为正式 Mac spec |
| WINDOWS_PACKAGING_ONLY | build script 要求 .exe/.pyd/.dll/qwindows，C:\Windows PATH、Conda Library/bin、Scripts | Windows 原生收集、隔离与验收条件 |
| WINDOWS_PACKAGING_ONLY | .bat、PowerShell 开发入口、历史 Windows 手工验收脚本 | Mac 不执行这些入口，不需改科学核心 |
| WINDOWS_GUI_SPECIFIC | gui/release_smoke.py 的 loaded_runtime_paths 调用 kernel32/GetModuleHandleW/GetModuleFileNameW | 仅隐藏 smoke 路径使用，普通 GUI import 不执行；Mac smoke 必须另设实现 |
| UNKNOWN | styles.py 选择 Microsoft YaHei UI 9pt | Qt 有字体回退，但 Mac 字形、行高、布局未实测；不能宣称已出现字体 bug |
| UNKNOWN | 原生图标、文件对话框、菜单、Retina、持久设置行为 | 静态接口通用，实际 Cocoa 行为待真机验证 |
| WINDOWS_CORE_SPECIFIC | 无已证实项 | 不能将文件名安全策略误报为 Windows 科学依赖 |

[app.py](D:/Code/Python_Projects/DPS_Studio/src/dps_studio/gui/app.py:59) 正常启动创建 QApplication/MainWindow；只有显式 `--startup-smoke-test` 才调用 native 路径探测。Mac 普通 GUI 可行性与当前 Windows smoke 不可用是两个不同事实。

## 4. 具体依赖版本与 arm64 分发

当前专用环境 `D:\miniconda3\envs\dps-studio\python.exe` 实际为 Python **3.12.13 / AMD64 / 64 bit**，项目版本 0.1.4。pyproject 目前是下限约束，未锁定下列完整版本，因此不能仅运行 `pip install .[dev]` 后声称复现 Windows release 的依赖。

以下逐个查询具体版本的 PyPI JSON，排除 yanked wheel，以 Python 3.12/cp312、abi3 与 macOS 15 arm64 tags 做兼容性匹配，记录 wheel SHA 和 upload time。**DEPENDENCIES_ARM64_READY** 指分发与声明兼容性已核实；没有在本机伪称完成 macOS 安装或 native 加载。

| 包 | 当前真实版本 | 匹配分发的代表性 tag | 证据 |
| --- | --- | --- | --- |
| Python | 3.12.13 | conda-forge osx-arm64 原生 CPython | [conda-forge release metadata](https://api.anaconda.org/release/conda-forge/python/3.12.13) |
| NumPy | 2.5.1 | cp312-cp312-macosx_11_0_arm64；另有 14_0 | [具体版本文件](https://pypi.org/pypi/numpy/2.5.1/json) |
| SciPy | 1.18.0 | cp312-cp312-macosx_12_0_arm64；另有 14_0 | [具体版本文件](https://pypi.org/pypi/scipy/1.18.0/json) |
| pandas | 3.0.3 | cp312-cp312-macosx_11_0_arm64 | [具体版本文件](https://pypi.org/pypi/pandas/3.0.3/json) |
| matplotlib | 3.11.0 | cp312-cp312-macosx_11_0_arm64 | [具体版本文件](https://pypi.org/pypi/matplotlib/3.11.0/json) |
| PySide6 | 6.11.1 | cp310-abi3-macosx_13_0_universal2 | [具体版本文件](https://pypi.org/pypi/PySide6/6.11.1/json) |
| PySide6 Essentials/Addons | 6.11.1 | 同版本 cp310-abi3 / 13_0 universal2 | [Essentials](https://pypi.org/pypi/PySide6_Essentials/6.11.1/json)、[Addons](https://pypi.org/pypi/PySide6_Addons/6.11.1/json) |
| shiboken6 | 6.11.1 | cp310-abi3-macosx_13_0_universal2 | [具体版本文件](https://pypi.org/pypi/shiboken6/6.11.1/json) |
| PyQtGraph | 0.14.0 | py3-none-any | [具体版本文件](https://pypi.org/pypi/pyqtgraph/0.14.0/json) |
| Pydantic | 2.13.4 | py3-none-any | [具体版本文件](https://pypi.org/pypi/pydantic/2.13.4/json) |
| pydantic-core | 2.46.4 | cp312-cp312-macosx_11_0_arm64 | [具体版本文件](https://pypi.org/pypi/pydantic_core/2.46.4/json) |
| PyInstaller | 6.21.0 | py3-none-macosx_10_13_universal2 | [具体版本文件](https://pypi.org/pypi/pyinstaller/6.21.0/json) |
| hooks-contrib | 2026.6 | py3-none-any | [具体版本文件](https://pypi.org/pypi/pyinstaller-hooks-contrib/2026.6/json) |
| Pillow（图标/测试） | 12.3.0 | cp312-cp312-macosx_11_0_arm64 | [具体版本文件](https://pypi.org/pypi/pillow/12.3.0/json) |

PySide6 的 abi3 wheel 覆盖 Python 3.12，universal2 wheel 包含 arm64；这不等于整个应用必须做 universal2。SciPy 声明 NumPy>=2.0,<2.8，实际 2.5.1 满足；PySide6/Essentials/Addons/shiboken6 的精确 6.11.1 依赖一致。继续读取传递依赖，contourpy、kiwisolver、fonttools、dateutil、typing 系列等都有匹配分发；macOS-only 的 macholib 可取得，当前 Windows 未安装它是正常 marker 结果。当前 pytest 9.1.1、Ruff 0.15.21、mypy 2.2.0 也有匹配分发。

**Python provisioning 的已证实差异：**[Python 3.12.13 官方页面](https://www.python.org/downloads/release/python-31213/) 说明它是 source-only security release，不再提供官方二进制 installer。本次实际读取 [actions/python-versions manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json)：3.12.13 条目没有 darwin 文件，3.12.10 有 darwin arm64/x64；不能把 `setup-python: 3.12.13` 当作已证实的 Mac 安装方案。conda-forge 的 3.12.13 已确认有非 debug osx-arm64 包，推荐通过原生 Miniforge/Conda 取得同一 patch 版本。未自动升级、降级或安装任何依赖。

Qt 6.11 官方目标为 macOS 13+、arm64/x86_64；所核查 wheels 的声明可以支持该下限，但在 macOS 15 上构建并不能证明实际应用支持 macOS 13/14。初始正式测试目标先定 macOS 15；更低版本需独立 smoke 与 Mach-O deployment target 核验。[Qt 支持配置](https://doc.qt.io/qt-6.11/macos.html)

## 5. GitHub Actions 的实际状态与 runner

GitHub 插件读到在线 repo、branch、tree 和 runs。插件的 fetch 白名单不允许 workflows/permissions 端点；本机没有 gh CLI，故按本任务授权使用已有 Git credential manager 认证直接执行只读 REST GET。凭据仅在进程内使用，未输出或保存 token。

| 证据层次 | 实际结果 |
| --- | --- |
| repo Actions permissions API | HTTP 200；enabled=true、allowed_actions=all、sha_pinning_required=false |
| workflows API | HTTP 200；total_count=0 |
| runs API | total_count=0 |
| repository runners API | HTTP 200；total_count=0，表示没有注册 self-hosted runner；不表示没有 hosted runner |
| workflow token defaults | read；不能批准 PR review；本任务草案仅需 contents: read |
| macOS hosted job 在本 repo 实际运行 | **NOT VERIFIED**，未创建/调度 workflow |
| 账户剩余 artifact storage/实时服务容量 | **NOT VERIFIED**，不能由 enabled=true 推断实际调度或上传一定成功 |

核查 [GitHub hosted runners 官方表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) 和 [runner-images 官方清单](https://github.com/actions/runner-images/blob/main/README.md)：

- 标准 arm64：`macos-14`、`macos-15`、`macos-26`、`macos-latest`；当前清单 latest 指向 macOS 26。另有 Xcode preview 标签，本项目无需使用。
- 标准 Intel：`macos-15-intel`、`macos-26-intel`。
- 推荐 **`macos-15` / arm64**，固定 OS 标签，避免 latest 随迁移改变 OS。不编造 `macos-15-arm64` 标签。
- public repo 的标准 hosted runner 免费；private repo 同样有 arm64 标签，但使用账户分钟额度及后续计费。larger runner 属不同计划/付费条件，本项目无必要以其作为前提。

因此，**官方架构支持 VERIFIED、repo Actions 已启用 VERIFIED、此 repo 实际 arm64 调度 NOT VERIFIED**。目前没有已证实的 GitHub 基础设施 blocker，也无需因误认为没有 hosted arm64 而要求购买/self-host Apple Silicon Mac。

## 6. PyInstaller 架构方案

[现有 spec](D:/Code/Python_Projects/DPS_Studio/packaging/pdv_studio.spec:6) 与 [Windows build script](D:/Code/Python_Projects/DPS_Studio/tools/build_production_release.py:33) 已逐项审计。qwindows.dll、.pyd/.dll 模式、Windows PATH、PE version metadata、EXE 名称、kernel32 路径确认和 windows platform 验收均属于 Windows 入口。

| 方案 | 优点 | 当前项目代价 |
| --- | --- | --- |
| A：跨平台 spec + 两个脚本 | 能共享一部分 Analysis/datas 配置 | 需要改已经验证的 Windows spec，分支混合 PE/BUNDLE、图标与 signing，增加 Windows 回归面 |
| B：Windows spec + 独立 macOS spec，各自脚本 | 保持 Windows 已验证路径；Mac 可清晰处理 .app、framework、Cocoa、权限与签名 | 少量 Analysis/resource 声明重复，可通过资源合同测试控制一致性 |
| C：立刻抽象统一发布框架或更换打包器 | 以后可能集中维护 | 本项目内部发布规模不足以支持这次额外重构 |

**推荐 B。**新 spec 构造 onedir + BUNDLE 的 `PDV Studio.app`，明确 `target_arch="arm64"`，使用 ICNS，Info.plist 的 version 从唯一 package version 派生，并声明稳定 bundle identifier；保留 Qt GUI 不需要的 argv_emulation=false。保留原包内 TOML、QM 和正常运行图标。不要重构 scientific core。

PyInstaller 是在目标系统构建本机应用的打包路径，不是从当前 Windows 环境输出可验证的 Mac .app。具体 6.21.0 的架构/签名行为已查阅 [该版本 feature notes](https://github.com/pyinstaller/pyinstaller/blob/v6.21.0/doc/feature-notes.rst) 和 [bundle spec 文档](https://pyinstaller.org/en/stable/spec-files.html)。

Mac 不能照搬现有 ZIP/staging 实现：它用默认 `shutil.copytree` 和 `zipfile.write/extractall`，没有保留 symlink、执行权限的完整合同。PyInstaller 6.21 的官方文档说明非 Windows bundle 使用 symlink；未来应用原生 `ditto` 或明确保留 link 的归档工具，重新解压核验文件类型、link target、mode、字节 SHA 与 codesign，而非仅复制文件内容。[6.21 归档要求](https://github.com/pyinstaller/pyinstaller/blob/v6.21.0/doc/common-issues-and-pitfalls.rst)

## 7. Qt / Cocoa GUI

**GUI_MACOS_CHANGES_REQUIRED：主要针对发布 smoke 的平台探测，不是已经证实普通交互 GUI 无法运行。**

| 项目 | 静态检查结果与后续验收 |
| --- | --- |
| Qt platform | Mac 应为 cocoa；收集并实际加载 libqcocoa.dylib，不能用 offscreen 替代 native acceptance |
| QFileDialog | 使用 Qt 的 getOpenFileName/getExistingDirectory，无 Windows API；验证中文/空格路径、取消、原生对话框与输出目录 |
| QMessageBox | 使用标准 Qt 接口；验证模态警告、错误路径和 About |
| QSettings | 正常使用 organization/application metadata，无 registry API；验证 Mac 偏好设置、语言与窗口恢复 |
| icon | Qt 现有运行图标用 ICO，不能将此等同 .app 的 ICNS；最终 Dock/Finder 图标用新 ICNS |
| translations | QM 路径统一 resolver，英文 translator 在建 widget 前安装；验证中文/英文切换 |
| font/layout | Microsoft YaHei UI 会回退，9pt/最小窗口大小需实测；没有依据在本任务修改字号 |
| shortcuts | Open/Quit 使用 StandardKey；Ctrl+Z 不能直接判为 Mac bug，Qt 在 Apple 平台将 Ctrl 映射为 Command |
| flags/high-DPI | 未找到 Win32 window flags 或关闭 Qt6 DPI 的设置；验证 Retina、屏幕缩放、滚动与菜单 |
| resources | _MEIPASS + pathlib 适合 frozen 场景；验证 .app 的 Frameworks/Resources 与 symlink 布局 |
| export | 输出需要显式选择用户目录；不能向已签名 .app 内写分析结果；当前 GUI 已要求用户选择目录 |

[Cocoa 的 Qt 定义](https://doc.qt.io/qt-6.11/qguiapplication.html#platformName-prop)、[Apple shortcut 映射](https://doc.qt.io/qt-6/qkeysequence.html)、[Qt Mac 注意事项](https://doc.qt.io/qt-6.11/macos-issues.html) 支持上述平台设计；实际应用交互仍 NOT VERIFIED。未来仅在复现字体、路径或对话框问题后修改对应 GUI。

现有隐藏 smoke 在 Mac 会进入 Windows-only native 探测。建议新增 Darwin native probe，通过 `_dyld_image_count/_dyld_get_image_name` 获取实际已加载 images，同时记录 PySide6 QtCore、shiboken native extension 与 SciPy extension 的 __file__。Qt framework、libqcocoa 与 SciPy .so 的 resolved 路径必须位于重新解压的 .app 内；系统 Apple frameworks 则单列允许，不能要求所有系统 image 都在 bundle。

## 8. 图标与 .app

**VERIFIED：**现有正式 master PNG 实际为 **1254×1254 RGBA**，已提交。已有 ICO 多尺寸资产，当前没有 SVG、ICNS。

可从该 master 生成 Mac iconset（包括 1024px Retina 主帧），用 `iconutil` 生成 `pdv_studio.icns`；无须重新生成或更改设计，也无须把 ICO 当作正式 Mac icon。未来检查 alpha/边缘、Finder/Dock 显示与 Info.plist 图标项。本任务未生成 ICNS。

## 9. signing / notarization 与内部测试

**可以在不购买 Apple Developer Program 的情况下生成内部测试用独立 .app。**优先采用 ad-hoc signed arm64 bundle，明确说明其身份保证的上限；不发布“Apple 正式认证”声明。

| 模式 | 含义 | 当前目标 |
| --- | --- | --- |
| unsigned / ad-hoc internal | unsigned 不能满足所有 arm64 native 验签条件；ad-hoc 验证代码结构/完整性，不提供 Apple 认可的开发者身份 | 推荐 ad-hoc，PyInstaller 默认尝试签名，必须检查实际结果 |
| Developer ID signed | 使用 Apple Developer ID Application certificate，相关身份与分发条件需有效开发者账号/证书 | 本次非必要前提 |
| Apple notarized | Developer ID 签名、提交 Apple 服务、取得 ticket，必要时 staple | 后续对外分发任务，当前未实现 |

[6.21 PyInstaller 签名说明](https://github.com/pyinstaller/pyinstaller/blob/v6.21.0/doc/feature-notes.rst)、[Apple Developer ID](https://developer.apple.com/help/account/certificates/create-developer-id-certificates) 与 [Apple membership](https://developer.apple.com/programs/whats-included/) 支持这一区别。ad-hoc 的 `codesign --verify` 通过不等于 `spctl`/Gatekeeper 认可，更不等于 notarization。

下载引入的 quarantine 与 Gatekeeper 可能阻止首次打开；内部可信 app 可按 [Apple 支持的单应用 Open Anyway 流程](https://support.apple.com/en-us/102445)处理。CI 未经下载隔离的启动不能证明这一用户流程。不能将全局关闭 Gatekeeper、安全策略或无条件清除 quarantine 作为正式交付方案。

## 10. 未来 macOS 验证合同

未来正式 TASK 至少完成以下 gates，证据必须标明 CI 自动化与真实 Mac 人工验收的区别。

1. 干净 arm64 macOS 环境：记录 sw_vers、uname -m、Python sys.executable/version、依赖版本、commit、PATH；新工作目录，不复用 Windows release，不混 Rosetta x86_64 Python。
2. 分发与测试：固定现有依赖版本，确认 pip/Conda 求解、native imports 和 GUI 前置测试；处理本报告的 fixture 输入与数值测试问题后运行声明范围的 pytest/Ruff/mypy。
3. 原生 PyInstaller build：新 output root、clean 构建、正确 .app/BUNDLE，生成 Info.plist 与 ICNS，依赖由 hooks 收集；不手工搬 Windows DLL。
4. Mach-O 验收：file/lipo 检查 bootloader、Python、Qt、shiboken、SciPy 及所有非系统 native library 包含 arm64；otool -L 检查加载依赖，允许系统路径与可解析的 @rpath/@loader_path/@executable_path，拒绝指向构建 Conda、Homebrew 或源码的外部路径；检查 LC_RPATH/deployment target。
5. 签名：记录 codesign -dv，执行 codesign --verify --deep --strict；明确 ad-hoc。spctl assessment 作为 Gatekeeper 状态证据，其对内部 ad-hoc 的拒绝不得伪写为正式签名通过。
6. ZIP：从最终已验证 .app 创建保留 symlink/权限的 ZIP，再解压到 workspace/build/Conda 之外目录，按 lstat 比较类型、link target、mode 与文件 SHA；对重新解压 app 再次执行 codesign。
7. Native GUI：从重新解压的 Contents/MacOS executable 启动，cwd 为独立临时目录，PATH 仅系统目录，清除继承 Python/Conda/Qt/DYLD 注入，保留正常 Mac 登录会话；QTimer 在真实 app.exec 内报告 MainWindow 创建、visible/exposed、platformName=cocoa、正常退出码 0。
8. Native origin：通过 Darwin loaded image 探测确认 Qt/shiboken/Cocoa/SciPy 原生组件来自该 .app；__file__、QPlugin 路径与运行时 images 共同验证，不能仅以包名 import 成功验收。
9. Real scientific smoke：使用已提交合法示例的独立副本，SHA 前后不变；实际 import → STFT → ridge → quality → apparent/corrected velocity → 连续和 quality-only export，检查两列 schema、provenance、诊断/NaN/flags、版本来源。
10. Windows/Mac 数值比较：同 commit、配置、输入、依赖版本，使用第 11 节容差与结构检查；不得改科学默认阈值以通过。
11. 最终交付：再计算最终 ZIP SHA-256；上传前后下载到独立目录对 SHA 与 .app/启动复验。Git/raw 边界和测试日志一起记录。

GitHub runner-images 的 [自动 GUI 登录配置](https://raw.githubusercontent.com/actions/runner-images/main/images/macos/scripts/build/configure-autologin.sh)表明 native GUI smoke 值得尝试，但不是本 repo 本次窗口启动证据。未来 job 先检查 GUI session，再执行上述 Cocoa event-loop smoke，并在可用时获取窗口截图。offscreen unit tests 保持独立进程，不能把 tests 的 QT_QPA_PLATFORM=offscreen 环境传给 native smoke。

**Hosted CI 验证上限：**visible/exposed、Cocoa、正常退出及截图可以证明软件报告的窗口与绘制状态，不能证明有操作员肉眼看见，也不能覆盖真实用户的 Finder/Gatekeeper、Retina、多屏、原生文件对话框和输入设备操作。如果 runner 无 GUI session 或窗口暴露失败，native gate 必须失败或明确 NOT VERIFIED，不能降格成“进程存活”或 offscreen 后放行。

构建可用 hosted Mac，无需自购硬件/self-host；正式人工 GUI/Gatekeeper 验收仍建议一台真实 Apple Silicon Mac。self-hosted runner 仅在 hosted native GUI 限制无法满足目标时成为备选，不是当前已证实的必要条件。

## 11. 跨平台数值一致性

当前 STFT 明确 float64/complex128，SciPy 窗口和一侧谱、无 boundary/padding；不同编译器、FFT/向量化、FMA、数学库与 BLAS/线程实现可能导致正常末位差异。连续 ridge 的比较/argmax、峰值拟合、门控边界可能把小幅谱差放大为离散决策差异；不能一概视为正常。

以下是**未来回归的初始验收建议，不是测得的 Windows–Mac 差值**：

| 比较量 | 初始建议 rtol | 初始建议 atol | 附加要求 |
| --- | --- | --- | --- |
| STFT frequency grid（Hz） | 1e-12 | 1e-6 Hz | shape、nfft、Fs、窗/重叠和 hop 完全相同 |
| STFT complex spectrum（可选诊断） | 1e-10 | 1e-12 × 同一非零谱幅尺度（V） | 零/低幅部分使用绝对界，不用接近零分母 |
| discrete ridge frequency（Hz） | 1e-12 | 1e-6 Hz | 良好分离峰的所选 bin 应一致 |
| refined ridge frequency（Hz） | 1e-9 | 1e-3 Hz | quality/NaN mask 与正常段身份一致 |
| apparent velocity（m/s） | 1e-9 | 1e-5 m/s | 使用相同波长、来源和 mask |
| corrected velocity（m/s） | 1e-9 | 1e-5 m/s | 同一 correction/angle 参数；记录非线性敏感段 |

速度建议需同时核对现有 v_app=λf/2 的误差传播 Δv_app=λΔf/2；corrected velocity 用现有修正映射的局部敏感度判断，不能因为表中通用 atol 自动忽略异常。每组输出记录 finite 区 max absolute difference、带明确近零分母尺度的 max relative difference，NaN mask、quality flags、候选来源、时间轴、row counts 和导出 schema 则单独比较。

若发生一个或多个频率 bin 跳变、flags/NaN/事件时刻变化，必须检查真实峰竞争与门控余量，定位差异并复核；不能平滑、插值、删点或统一放宽阈值。正式 tolerance 必须在真实双平台运行后再确认。

**已证实的现有测试风险：**[test_legacy_velocity_audit.py](D:/Code/Python_Projects/DPS_Studio/tests/unit/test_legacy_velocity_audit.py:284) 对 STFT/refinement/quality 数组使用硬编码 SHA-256；脚本由 ndarray.tobytes 计算。这是 Windows 已验证字节基线，不能假定在 Mac 必然通过。当前未运行 Mac，因此其实际失败仍 NOT VERIFIED。未来保留原 Windows 指纹验收，增加明确的跨平台数值合同；输入文件 SHA 与“不修改同一进程内数组”的字节检查继续严格保留，不应随数值比较容差放宽。

## 12. arm64 / Intel / universal2 策略

推荐先只发布 **arm64**，适合科研内部小规模 Apple Silicon 用户。确有 Intel 用户时，再增加独立 x86_64 job 与包 `PDV_Studio_v0.1.4_macos_x86_64.zip`，使用明确 Intel 标签和同样验收合同。

当前 NumPy/SciPy 的已核查匹配分发是单架构 native wheel；PySide6 wheel 为 universal2 并不能使所有依赖同时具备双架构。universal2 需要完整双架构 Python/所有 native extensions、更复杂的收集和双机测试，现阶段收益不足；不能简单用 lipo 拼接两个 PyInstaller executable 来冒充有效 universal2。[PyInstaller 6.21 架构限制](https://github.com/pyinstaller/pyinstaller/blob/v6.21.0/doc/feature-notes.rst)

当前版本唯一来源仍为 package __version__，未来包名应动态派生。以当前真实状态举例：`PDV_Studio_v0.1.4_macos_arm64.zip`，不是声称本次已经产生该包。

## 13. 预计实施修改范围

预计 **moderate**，集中在打包、native 验收与测试输入，约 6–9 个新增文件、3–5 处已有文件的小范围修改；这只是范围估计，不是已完成 diff。

| 类别 | 未来拟新增/修改 |
| --- | --- |
| packaging | 新增 packaging/pdv_studio_macos.spec：BUNDLE、ICNS、Info.plist、target_arch |
| build | 新增 tools/build_macos_release.py：POSIX PATH、symlink/权限、Mach-O、签名、最终 ZIP 复验 |
| native probe | 新增 gui/release_smoke_macos.py；小范围修改 gui/release_smoke.py，按平台 dispatch，Windows 探测保持原实现 |
| icons | 新增 gui/icons/pdv_studio.icns 与可复现生成说明，不覆盖原 PNG/ICO |
| constraints | 新增可审计的 Mac build constraints，固定当前 runtime/dev 版本及必需 Mac-only 依赖 |
| tests | 新增 Cocoa/native/Mach-O/archive 合同测试；为真实实验 tests 增加只读 fixture root；保留 Windows fingerprint 并新增数值比较 |
| workflow | 新增 .github/workflows/macos-arm64-internal.yml，仅未来正式实施 |
| docs | 增加 Mac 内部安装/验收/Gatekeeper 说明与实际 release evidence |

**不应动的现有 Windows 文件/范围：**现有 Windows spec、PE metadata/release_version、Windows build script 的 DLL/PATH/EXE gates、ICO/master PNG、.bat/PowerShell 入口、历史 release/ZIP；Windows tests 和原 fingerprint 不能删掉或降格。共享 GUI smoke 的最小平台 dispatch 需要新增 Windows 回归保证，不能把 kernel32 路径改成通用假报告。core、scientific defaults、STFT/ridge/quality/candidate/velocity/angle/LiF 均不需要也不应借移植重构。

## 14. GitHub Actions 设计草案（不创建 workflow）

这是流程设计，不是当前可执行 workflow。表内未来脚本尚未实现；真实实验 fixture 与 native gates 完成后才进入正式 CI 验收。

| 阶段 | 未来 job 设计 |
| --- | --- |
| trigger | 初期 workflow_dispatch，main；不自动创建 GitHub Release，不推代码 |
| runner | macos-15，先 assert uname/Python machine=arm64 |
| permissions | contents: read；无需签名/notarization secrets |
| checkout | actions/checkout@v7，锁定本次核查 commit；记录 github.sha 与本地 HEAD |
| Python | conda-incubator/setup-miniconda@v4 的原生 Miniforge + conda-forge Python=3.12.13，使用激活的 bash -el；不误用缺 darwin 分发的 setup-python 3.12.13 |
| dependencies | 固定本报告真实版本；pip install -c <future constraints> -e ".[dev]"；不允许源代码包意外编译/版本漂移被忽略，记录实际 resolved list |
| tests | portable 普通 tests + 有明确只读数据来源的实验 regression；保留 Windows byte fingerprint job，运行 Ruff 与 strict mypy；不得把不足 649 的子集报告成全部通过 |
| build | python tools/build_macos_release.py --output-root <new runner-temp root>；当前不存在，是待实施入口 |
| verification | .app、architecture/otool/signature、最终 ZIP 重解压、Cocoa/native origin、STFT/export、跨平台 comparison、Git/raw boundary |
| naming | 从 __version__ 与实际 arm64 派生 PDV_Studio_v0.1.4_macos_arm64.zip |
| upload | actions/upload-artifact@v7 上传已验收 ZIP（archive:false 可直接上传单文件）；evidence/manifest 另一个 artifact，不裸传 .app 目录 |
| final check | 未来 verifier job 下载最终 ZIP，重验发布 ZIP 自身 SHA，重新解压/启动；保留失败 logs，不把 upload success 当 release pass |

本次实际查到 refs：checkout v7 commit `3d3c42e5aac5ba805825da76410c181273ba90b1`；upload-artifact v7 commit `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`；setup-miniconda v4 的 annotated tag 解析到 commit `be893c923ea9cf1cf7cd510fbdde27c7e18cbdcb`。未来实现应再次核查后固定 commit，不因草案自动升级本项目依赖。[checkout](https://github.com/actions/checkout)、[Miniforge action 的 Apple Silicon 示例](https://github.com/conda-incubator/setup-miniconda)、[upload-artifact 当前接口](https://github.com/actions/upload-artifact)

Actions artifact 传裸目录会损失文件权限，因此选择先生成 .app ZIP 再上传，保持 ZIP 字节不变。发布 ZIP SHA 与 Actions 外层 artifact digest 的含义必须分别标注；下载后重新计算发布 ZIP SHA。[artifact 权限与归档行为](https://github.com/actions/upload-artifact)

## 15. 风险排序

| 等级 | 风险 | 证据与处理 |
| --- | --- | --- |
| P0 blocker（直接照搬完整 CI） | 4 个 raw CSV 不在 GitHub，测试无条件读取 | VERIFIED；建立受控只读 fixture 来源，不修改 raw 或公开上传实验数据 |
| P0 blocker（直接复用 Windows build） | PE/spec、Windows PATH/runtime/smoke gates、无 Mac BUNDLE | VERIFIED；独立 Mac spec/script/native probe |
| P0 blocker（错误 Python provisioning） | setup-python manifest 无 3.12.13 darwin | VERIFIED；采用已核实的 conda-forge 同版本 osx-arm64 |
| P1 likely issue | Mac native dylib/framework/Qt Cocoa/SciPy hook 收集与 architecture | wheel 可取得 VERIFIED；bundle 加载 NOT VERIFIED，须真实 Mac/CI 原生 build |
| P1 likely issue | staging/ZIP flatten symlink、执行权限/签名损失 | 现有实现不包含 Mac 合同 VERIFIED；用保留 links/mode 的归档与复验 |
| P1 likely issue | ndarray 字节指纹不具跨平台浮点容差 | 测试方式 VERIFIED；实际 Mac 差异 NOT VERIFIED，保留 Windows 并加数值回归 |
| P1 likely issue | Gatekeeper/quarantine 与 CI GUI 上限 | 官方平台条件 VERIFIED；真实用户流程 NOT VERIFIED，安排人工真机验收 |
| P1 likely issue | 未锁版本导致依赖求解漂移 | pyproject 下限约束 VERIFIED；增加显式 constraints 与 resolved evidence |
| P2 cleanup | ICNS、Finder/Dock 图标、字体回退、Cmd shortcuts/Retina | PNG 源可取得 VERIFIED；其余为验收项，未复现前不改 GUI |
| P2 cleanup | 旧 Mac 支持、Intel 包、universal2 | 根据实际用户需求另开 scope，当前仅 arm64 |

没有证据支持 MACOS_BLOCKED_BY_DEPENDENCY 或 MACOS_BLOCKED_BY_GITHUB_INFRASTRUCTURE。GITHUB_SOURCE_INCOMPLETE 具体针对完整 CI 输入；现有 core/GUI 运行资源并未缺失。因此总体选择 MACOS_READY_WITH_MODERATE_CHANGES，而不是宣称当前 Mac 发布已经 READY/PASS。

## 16. 本次测试、边界与收尾

本次没有只相信 TASK-030 历史报告。直接在当前 `8b049a4a` 的真实源码上重新运行：

```powershell
& 'D:\miniconda3\envs\dps-studio\python.exe' -m pytest -q --tb=short --basetemp build/task029a_audit_20261004/pytest_temp -o cache_dir=build/task029a_audit_20261004/pytest_cache
& 'D:\miniconda3\envs\dps-studio\python.exe' -m ruff check .
& 'D:\miniconda3\envs\dps-studio\python.exe' -m mypy --strict src/dps_studio
```

**VERIFIED：649 passed in 73.87s；Ruff All checks passed；strict mypy 81 source files 无问题。**未重建 Windows release。新加的 **6 项只读 audit tests** 位于被忽略的 build evidence 目录，检查同步对象/资源、缺少 raw fixtures、具体分发、core import 边界、raw/已提交文件字节保护和 enabled 与实际 CI job 的区别；6 passed，单独 Ruff 通过。不改变 Production tests 或 runtime 源码。

当前实际结果与 TASK-030 的测试数量/检查结论一致；两次运行的环境与版本已核对。不能将这份 Windows 成绩单冒充 macOS 测试成绩。

对起始 **1,347 已提交文件**和 **24 raw 文件**记录 SHA-256 并完成结束核对，原有文件无变化，raw 文件集合/哈希完全一致。未修改 Research 仓库 `D:\Code\Python_Projects\DPS_Studio_TASK021A`，未更改 scientific defaults、原始数据或发布产物。未创建 branch/worktree、clone、commit、push、merge、rebase、cherry-pick；未发任何 GitHub 写请求。

最终 Git 预期和收尾实测：`main`，HEAD/origin/main 仍为 `8b049a4a741ad7188745b7d791c97070d196c2ec`；tracked diff 为空，唯一未跟踪工作树变更是本报告。scratch evidence 均位于已忽略的 [审计检查目录](D:/Code/Python_Projects/DPS_Studio/build/task029a_audit_20261004)。

轻量 Obsidian 日志：[2026-10-04_TASK-029A_macOS可行性审计.md](D:/Research/Notes/05项目/dps/2026-10-04_TASK-029A_macOS可行性审计.md)。它是任务授权的外部记录，不是修改 Research 源码。

**下一 TASK 建议：TASK-031 — macOS arm64 内部发布实现与原生验收。**先落实 CI 实验 fixture/数值比较合同，再增加独立 Mac 打包与 Cocoa/native smoke；构建目标是 ad-hoc internal .app 和真实最终 ZIP，正式 Developer ID/notarization 单列后续需求。本任务到此停止。
