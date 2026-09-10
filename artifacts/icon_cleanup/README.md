# PDV Studio 图标清理与打包验收

- task: TASK-ICON
- date: 2026-09-10
- branch: main
- status: complete
- verdict: PASS（Explorer 使用 Windows Shell 图标提取核验；未操作缓存）
- artifact: `D:/Code/Python_Projects/DPS_Studio/release/PDV_Studio_v0.1.3_iconfix`

## 原图诊断与清理

输入仅为 `release/PDV_Studio_v0.1.3/软件图标.png`，保留原文件。
原图 RGBA，1254 × 1254，四角均为 (0,0,0,0)，alpha 范围 0–255。
alpha=0 为 498,128 个像素，0<alpha<255 为 1,072,429 个，alpha=255 为 1,959 个。
完整 256 档直方图见 `previews/alpha_report.json`。

真实根因是源图的外围低 alpha 残留，伴随部分半透明边缘的 RGB 污染；
不是缺失透明通道。距 alpha≥240 主体超过 3 像素的 5,982 个残留像素
alpha 仅为 1–9，残留包围盒甚至延伸到底部画布边缘。
主体内部 alpha 主要为 252/253，存在不必要的轻微透底。
保留的两像素边缘带内有 14 个亮白/灰中性像素，并存在量化严重的淡蓝 RGB。
这些观测支持局部边缘颜色污染，不能证明全图经历白灰背景预混合；
没有将 Windows 缓存或历史 ICO 转换推测为已证实根因。

采用 `tools/build_app_icon.py`：

- 根据直方图主体峰与边缘采样，以 alpha≥240 的最大连通域确定主体。
- 在主体外保留实测的 2 像素抗锯齿带；带外 alpha≤15 的 8,421 个残留像素全部 RGBA 归零。
- 主体 1,059,234 个像素的 RGB 逐字节保持不变，alpha 设为 255。
- 保留 6,733 个过渡 alpha，按主体中位 alpha=253 作轻微覆盖率归一化；以最近主体 RGB 去除边缘污染。
- 使用 RGBa 预乘 alpha Lanczos 下采样；以面积采样支持域限制外围振铃，并保持完全覆盖区域不透明。

最终 alpha=0 为 506,549 个，过渡像素 6,733 个，完全不透明 1,059,234 个。
透明像素 RGBA 全为零。master 保持原始 1254 × 1254，避免再采样改变主体 RGB；
ICO 为 16、20、24、32、40、48、64、128、256 px 九帧，均为 32 位 RGBA。
独立重复生成的 master 和 ICO 哈希一致，见 `reproducibility.json`。

白、黑、浅灰合成图和 ICO 小尺寸图已经视觉检查：没有外围灰框、白色 halo 或矩形底板，
圆角保留平滑过渡，16/32/48 px 可辨认主体。原设计的蓝色/青色亮边属于主体内容，予以保留。
预览：`previews/cleaned_on_white.png`、`cleaned_on_black.png`、`cleaned_on_gray.png`、
`previews/ico_contact_sheet.png`。诊断图均未放入 release。

## 正式资源与接入

正式资源目录：`src/dps_studio/gui/icons/`。
master：`pdv_studio_master.png`；Windows/Qt 共用：`pdv_studio.ico`。
不需要另增 runtime PNG。

开始前 GUI 已有 application-level QIcon 接线，spec 已有 EXE icon 和 datas 接线，
但都指向尚不存在的 `gui/icons/app.ico`。本任务保留用户已有修改，
仅将两处资源名改为正式 `pdv_studio.ico` 并补齐资源。
GUI 使用 `create_application()` → `QApplication.setWindowIcon()`，
复用 `runtime_paths.package_resource_path()`；源码以包位置解析，
frozen 以 `_MEIPASS/dps_studio/gui/icons/pdv_studio.ico` 解析。
没有新增第二套资源路径体系，不依赖 cwd、用户绝对路径或 release 根目录 PNG。

spec 的 `APP_ICON`、`datas` 和 `EXE(icon=...)` 共同接入 ICO；
`console=False` 保持原样，用户已有 `release_version.txt` 与版本读取逻辑保留。
最终 PE 为 Windows GUI subsystem=2，9 个 RT_ICON 与 ICO 对应帧逐字节一致，
包含 1 个 RT_GROUP_ICON；打包 runtime ICO 与源码 ICO 一致。
证据：`exe_resources_final.json`。

## 构建与 smoke

最初 `dist/icon_test` 构建误收集了当前工具 PATH 中 Poppler 的 ICU 78 DLL，
导致 `QtGui` 导入失败：Qt 需要无版本后缀的 Windows ICU 符号，误收集 DLL 只导出 `_78` 符号。
这是构建环境污染，已通过限定该次构建进程 PATH 重建解决，未修改系统 PATH、注册表或 GUI 功能。
首次失败日志保留为 `pyinstaller.log` 与 `packaged_test/stderr.txt`，该目录不作为发布产物。

成功构建命令（PowerShell；仅当前构建进程使用此环境）：

```powershell
$env:PATH = 'C:\Windows\System32;C:\Windows;D:\miniconda3\envs\dps-studio;D:\miniconda3\envs\dps-studio\Scripts;D:\miniconda3\envs\dps-studio\Library\bin'
& 'D:/miniconda3/envs/dps-studio/python.exe' -m PyInstaller --distpath dist/icon_test_clean --workpath build/icon_test_clean packaging/pdv_studio.spec
```

成功测试目录 `dist/icon_test_clean/PDV_Studio_v0.1.3`，复制为新目录
`release/PDV_Studio_v0.1.3_iconfix` 后核验 450 个构建文件哈希全部一致。
新目录仅含 `PDV Studio.exe`、`_internal/`、`README.txt`、空 `data/`。
没有复制用户实验数据或临时源 PNG。旧 `v0.1.3` 完整保留。

| 检查 | 结果与证据 |
| --- | --- |
| 源码 `python -m dps_studio.gui`，cwd `D:/` | PASS；`source_desktop/smoke.json`，退出码 0 |
| 源码标题栏/任务栏 | PASS；`source_desktop/titlebar.png`、`taskbar.png` |
| 独立测试包，cwd `D:/` | PASS；`packaged_clean_desktop/smoke.json` |
| 最终 release，cwd `D:/` | PASS；`release_final/smoke.json`，退出码 0 |
| 无 Python/Conda/源码路径依赖 | EXE smoke 移除 PYTHONPATH、QT_PLUGIN_PATH，PATH 仅含 Windows |
| 最终标题栏 | PASS；原生 PrintWindow 截图 `release_final/native_titlebar.png` |
| 最终任务栏 | PASS；桌面截图 `release_final/taskbar.png` |
| Explorer EXE 图标 | Windows Shell 的 SHGetFileInfoW 大/小图标均正确；`release_final/shell_large.png`、`shell_small.png` |
| 无控制台 | PASS；PE subsystem=2，spec console=False |
| Windows 图标缓存 | 未发现 Shell 返回旧图标；未重启 Explorer、未清缓存 |

Explorer 核验是 Shell 提取与渲染，并非逐个查看已打开的 Explorer 窗口缓存。
最初 PrintWindow/client 与屏幕截图存在不含标题栏或被其它窗口遮挡的情况；
最终以 `release_final/native_titlebar.png` 为标题栏验收依据。

最终 EXE SHA-256：`8da705b946c77724a3ab548f8fc29f8d138af4c17c32ceebf696ad6b589df45d`。
旧 EXE SHA-256：`d8e054687c487d9b4eeeac4568d272128054a8f041130143179614358b10beab`。
两者时间与哈希不同，详见 PE 报告。

## 测试、文件与边界

- pytest：627 passed，108 秒。命令 `python -m pytest --basetemp build/icon_pytest_full_20260910 -q`。
- 首次定向 pytest 的系统临时目录出现 WinError 5，已改用仓库新临时目录，完整套件全部通过。
- Ruff：`python -m ruff check .`，PASS。
- mypy：`python -m mypy src`，PASS，80 个 source files。
- `git diff --check`：PASS；仅 Git 的既有 LF→CRLF 提示。
- `git diff -- data/raw`：空；哈希核验 24 个 raw 文件和 452 个旧 release 文件，全部未变。
- `git diff --cached`：空；未 add、commit、push、stash、reset、clean 或切换分支。

本次修改：`packaging/pdv_studio.spec`、`src/dps_studio/gui/app.py`。
本次新增：`src/dps_studio/gui/icons/pdv_studio_master.png`、`pdv_studio.ico`、`README.md`；
`tools/build_app_icon.py`；`tests/unit/test_app_icon_assets.py`；`tests/unit/gui/test_app_icon.py`；
`artifacts/icon_cleanup/` 下诊断图、脚本、日志与报告，以及新的 release 目录。
新增 8 个测试实例，覆盖主体 RGB/不透明性、抗锯齿、RGB 污染/振铃、九帧 ICO、
拒绝覆盖、无主体输入及非 repo cwd 的 source/frozen 图标加载。

最终 git status：上述两个 tracked 文件 M；新增图标目录、两份测试、工具与诊断目录为 ??。
用户原有 `docs/user_manual/` 和 `packaging/release_version.txt` 仍为 ??，未整理。
未修改科学算法、普通 GUI 行为、configs、runtime_paths.py 或原始数据。

Obsidian 日志：`D:/Research/Notes/05项目/dps/2026-09-10_TASK-ICON_PDV-Studio图标替换.md`。
未解决问题：无阻塞项；Explorer 已打开窗口的缓存状态没有逐窗检查。
下一步：用户检查新的 iconfix 目录与视觉预览。本任务到此停止，不推进其他 TASK。
