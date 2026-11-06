# TASK-014 验收

2026-11-06 开始，2026-11-07 完成本地验收。Windows x64，Python 3.12。GitHub 云端 **尚未远端验证**。

| 检查 | 结果 | 记录 |
|---|---|---|
| 合成与真实 | 48 个种子与 TASK-013 的 180 个开发及独立测试种子无交集。13 文件、17 路，51 行实测诊断。独立重跑后四张表全部非成本字段逐值一致 | checks/reproduction.json、synthetic.csv、real.csv、summary.csv、low_paired.csv |
| core 与研究 | 经 TASK-009 数据适配器运行全部非 GUI 单元测试，1150 通过、5 项历史检查失败；之后新增的低平台精修及失败标志测试 2 项通过 | checks/all_core.log、checks/models.log |
| GUI | 24 个测试模块共 179 项断言用例通过；其中一个模块曾在断言通过后异常退出。修正两个独立绘图控件的测试所有权后，复测 8/8 次 exit=0；涉及事件、导出、显示和样式的最终联合回归 26 项通过 | checks/gui_modules.txt、checks/owned_tests.txt、checks/final_gui.log |
| 事件导出 | 自动候选只在用户采纳后生效，手动时刻同样生效。测试跨工作区、导出第二通道，比较简表的绝对/相对时间及 metadata；Guided 也检查确认时间、来源与时间列；没有对应结果的通道不可导出 | test_task014_export.py、test_task017_result_export.py、checks/gui_export.log |
| 静态检查 | 全部变更的 Python 文件过 Ruff；严格 mypy 对 core/GUI 的 93 个文件通过，四个专项研究/回放模块通过（第三方无类型库与旧研究导入静默跟随） | checks/ruff_changed.log、checks/ci_gate.log、checks/mypy_study.log |
| 干净安装与构建 | 在仓库下新建隔离 venv，按 Windows 精确约束安装 dev，pip check 通过；Ruff、mypy、与工作流一致的 64 项 pytest 通过。PyInstaller 以相对 spec 路径构建。无需私有数据、凭据和 Production 文件 | checks/ci_install.log、checks/ci_gate.log、checks/ci_build.log |
| 原生冻结程序 | Windows 平台，QApplication 窗口可见，模块路径都在 onedir 包内。20260607 双通道端到端，经典/人工分段、角度投影、LiF 开关、加速度、正式导出及读回、5 轮工作区切换、三种窗口尺寸均通过 | checks/portable_acceptance/report.json 和同目录截图 |
| 分发包 | 452 个文件，240,819,753 字节；ZIP 95,754,364 字节。压缩包逐成员 SHA-256 与已运行包相同，完整解压到新目录后独立启动，事件循环进入、窗口可见且已暴露 | checks/package.json、checks/zip_startup.json |
| 构建边界 | CI 只读 contents 权限，支持 workflow_dispatch 与 v* 标签；干净安装后检查、打包、启动，再上传 onedir 产物。机器之间不需要共享路径。PyInstaller 日志含可选 pyqtgraph.opengl / scipy.special._cdflib 警告，已用实际冻结流程检验所需功能 | .github/workflows/windows-research.yml、packaging/pdv_research.spec |

## 历史检查和诊断过程

初轮直接运行 `pytest tests/unit` 为 1317 通过、17 失败；这一轮跨越了旧预设测试迁移，不能作为最终结果。随后固定历史研究窗，修复实际导出刷新，按新默认更新预设断言，按 Research 真实入口验证 launcher，TASK-008 原始清单使用 TASK-009 适配器。未把新默认的第 1015 帧解释为旧网格的第 1015 帧。按历史网格运行的 TASK-018C 和 TASK-028 精确回放通过。

最终非 GUI 失败明细：

| 历史测试 | 实际失败条件 |
|---|---|
| TASK-023A fixed_upstream_and_raw_guardrails | 老清单固定 stft.py 和 candidates.py 的源码字节。本次候选实现有意改变，且任务起点的两文件也未匹配老清单。与本次起点逐候选比较见 checks/candidate_parity.json |
| TASK-023F frozen_e4_constants_and_no_production_writes | 旧快照中 Production 文件的固定摘要与现有 Production 不符；本轮前后 Production 工作树 Git 状态与 .git 字节核对一致 |
| TASK-023G frozen_f_source_production_and_raw_hashes | 旧清单的 task023f_audit.py 指纹与现有已签出内容不符，该文件当前字节与起点对应 CRLF 文件一致 |
| TASK-025 frozen_original_source_and_config_hashes | 老清单的 configs/pdv_studio_defaults.toml 摘要不同；该配置未在本轮改动 |
| TASK-025 calibration_provenance_excludes_held_out_and_is_immutable | 旧归档缺少 streams/T25_CORE_amplitude_exchange_08_balanced.npz |

没有改写冻结清单或填造缺失归档。一次混合 Qt 测试进程在 finished 信号处理中异常终止；同一事件模块单独重跑 6 项通过。另一个显示测试模块曾出现 Windows 0xc0000374 退出码，显式释放测试自己创建的两个独立视图后 8 次连续重跑正常。这些分别记录在 related.log、event_tests.log、display_retest.txt、owned_tests.txt 和 final_gui.log。普通 EXE 运行与测试进程的退出情况分别验收。

## Git 与数据边界

Research 起点 301689a97e96e8b2285c5b13e0134ad73cffc5dc，分支 codex/research_2/global-path-ridge-v2，独立 .git。Production 为 main / 677a22df0566f8403786a0b4d8eac11ff55bcf4f。前后逐文件核对 data/raw 的 11 项（含 .gitkeep）、补充 raw 的 3 项，以及 Production .git 的 115 项（约 6.50 GB），包括内容 SHA-256、字节数和 mtime。另以 git --no-optional-locks 比较 Production 分支、HEAD 和 porcelain 状态。此项覆盖工作树 Git 状态，未对 Production 整个工作目录逐文件宣称内容哈希。

证据在 checks/before.json、after.json、boundaries.json。最终包内已检查没有匹配原始输入的文件，CSV 只见 PyQtGraph 自带色图表。忽略规则保留生成物、本机试验数据、EXE、DLL、ZIP 和图件在 Git 外；本次只允许 TASK-014 根层的小型 .md/.py 进入版本控制。未推送、未发标签、未改远端历史、未 promotion。

ZIP SHA-256 为 `e92dfe026eb9d0c191c393e69a77ee1c7ffa83aeeb02922e89eaa63f8966e1fd`，包内主 EXE SHA-256 为 `37dde67827534aac0db3544ac07ca3657d4d096b04190dc9348654a792ea5cb6`。发布的是未签名研究测试版。
