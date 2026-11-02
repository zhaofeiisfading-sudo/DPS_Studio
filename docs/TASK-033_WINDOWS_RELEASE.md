# TASK-033：加速度审查与 Windows 本地发布

日期：2026-11-02；Production：`D:\Code\Python_Projects\DPS_Studio`。

## Git 与版本依据

开始时 main 工作区、暂存区干净，HEAD 为 `e979088b417b45a2962ba910f3bafd7f6ef3c284`，本地跟踪引用显示 ahead 1。该提交已经包含 TASK-032 的 21 个文件及 TASK-031 报告，不重复提交、不拆分、不改写历史。

TASK-031 报告的新增内容记录 macOS run 2 的成功验收。本地 macOS ZIP SHA-256 为 `4601f4a68b02569c14f9f8a73a332909c3b55a4afd8d217d8e5d310238695ffa`，与报告一致；本次未联网重验 CI。报告保持原样。

源码 `src/dps_studio/__init__.py` 原为 0.1.4，是 Hatch、GUI、导出及 Windows spec 的版本来源。本地存在 0.1.0–0.1.4 和 0.1.3_iconfix 发布目录，无本地 tag，也没有明确语义化版本升级规则；本次沿用补丁序列为 0.1.5。**远端版本未核验**。开发环境旧 editable 发行元数据为 0.1.4，离线刷新因缺少 hatchling 未执行成功；PyInstaller 直接读取本仓库源码版本，不使用该旧元数据决定产品版本。

历史 Windows 0.1.4 ZIP 实际为 99,521,610 bytes、SHA-256 `1197a8283150720d5a18b9b26a8475652feb91025f7131e42bdb09690f15edfd`，与早期 TASK-030 记录大小不同；当前目录包含后加的说明材料。本次不重写历史说明，不覆盖该包，以实际文件为准。

## 审查与修复

加速度共享入口使用 `plot_velocity_m_s` 与 `stft_result.time_s`，主图、导出和修正参数更新保持一致。差分按有效连续段执行，端点单边、两点共用割线、单点 NaN。无拍频、分析区间外、插值、无可用频点及显示平台不跨越求导；低质量但有限的工作速度仍保留，随结果输出原始质量来源。没有发现需要改动科学公式的问题。

窗口库内置项只读，修改后标记自定义，保存/另存/重命名显式执行；原子写入、重名冲突和损坏文件处理已有针对性测试。本次进一步通过 GUI 实际保存中文配置、恢复内置、重新选中自定义、导出与进程重启验证。

1366×768 下复现事件参考选项宽度仅 59–60 像素，而完整文字需要 75–99 像素。改为标签独占一行、三个选项纵向排列，并按字体保留高度；英文标签缩短为 Automatic。未重构其他界面。

`docs/原始数据.csv` 为现有示例，两通道各 80,000 点，SHA-256 `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。源码 GUI 全流程输出各 620 个时间点，时间步长约 3.200000001 ns；内置参数下峰值为 +9.0135980933×10¹¹ 与 −9.8337636601×10¹¹ m/s²，独立非均匀三点/单边差分一致，最大绝对浮点差分别 6.104×10⁻⁵、3.052×10⁻⁵ m/s²。峰处状态均为 ambiguous_peak。此结果仅验证求导与输入一致，不证明真实物理峰值。无平滑、删点、插值或限幅。

## 发布门槛与证据

新增翻译/窄窗口布局回归、示例完整 GUI 流程回归及脏工作区构建拒绝测试。发布前运行完整 pytest、Ruff、strict mypy 与 git diff --check。逐项暂存本任务文件后单独提交；完整 SHA 由构建脚本写入 BUILD_INFO 和发布 manifest。

首次全量测试为 781 passed / 1 failed：历史 macOS 数值基线版本为 0.1.4，只有软件版本字段与 0.1.5 不符。测试改为独立断言当前版本，再在内存中对齐历史快照的软件版本字段；所有数值、NaN、质量决策、行数和 schema 比较继续执行。历史基线文件与生产比较器未改动。默认 pytest 临时目录曾遇到访问权限错误，改用全新独立 basetemp，不改变该旧目录权限或内容。

最终全量检查：**782 passed in 104.99s**（未使用 portable deselection）；Ruff **All checks passed**；strict mypy **89 source files，无问题**；git diff --check 通过。测试使用独立 QSettings INI 位置。

构建沿用 PyInstaller onedir ZIP；要求干净提交、独立输出目录、独立 PyInstaller cache，拒绝已有发布路径。候选及最终 ZIP 均重新解压到仓库与 Conda 之外，清除开发环境路径后运行实际 EXE，核对全部文件哈希、实际原生 DLL 来源与版本。GUI 验证包含中英文、100%/125%/150%/200% 的有效 Qt DPR；它是进程级缩放测试，不修改系统显示设置。中文 100% 执行完整数据与配置流程及独立进程重启，其余执行布局验证。所有烟雾配置注入独立 INI/JSON，避免写入日常配置。

发布命令（提交通过检查后执行）：

```powershell
& 'D:/miniconda3/envs/dps-studio/python.exe' tools/build_production_release.py --output-root build/task033_release_v015 --release-root release --analysis-smoke-input docs/原始数据.csv --workflow-smoke
```

最终构建结果见 `build/task033_release_v015/release_manifest.json`；测试和数据保护证据保存在 `build/task033/`。最终 ZIP 路径、大小、哈希、提交、签名和实际 EXE 验证结果写入 Obsidian `2026-11-02_TASK-033_加速度功能审查与Windows发布.md`。该仓库文档记录可复核的发布流程，不能替代最终 manifest 的成功结果。

无 tag、fetch、push、GitHub Release、代理变更或 macOS 构建；不修改 raw、历史发布文件或 TASK-031。
