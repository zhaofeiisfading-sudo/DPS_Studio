# TASK-009 迁移报告

日期：2026-11-05。范围：TASK-008研究包迁移、入口修复与论文绘图；不进入Production，不改变冻结估计器、参数或既有结论。

## 迁移前的真实状态

| 工作树 | 分支 | HEAD | 初始状态 |
| --- | --- | --- | --- |
| TASK021A源树 | `codex/research_2/global-path-ridge` | `1b88f6ba97b4edda61268a88150aacc6f14d2796` | 12375个跟踪删除、README修改及43项未跟踪；全部保留 |
| RESEARCH_CLEAN目标 | `codex/research_2/global-path-ridge-v2` | `28ab6403d4ed3bec40d4a2836e55ac0805d3235f` | Git原先干净，但artifacts是指向源树的NTFS junction |
| DPS_Studio Production | `main` | 见边界快照 | Git原先干净；不修改 |

目标中“已有”的TASK-008成果实际来自junction，没有独立实体副本。源码、scripts、tests、data/raw均检查了真实位置。最终保护结论及SHA明细见 `checks/boundary_verification.json`；原始现场见 `boundary_before.json` 和 `provenance/junction_probe/boundary_before.json`。

探测初期因未及时识别继承的junction，6个新建TASK-009探测文件落在源树。已将6文件逐一备份到 `provenance/junction_probe/` 并核验SHA；用户明确授权“仅删除这次新建的探测目录”后，核验限定绝对路径、文件数量和备份哈希，仅删除该目录。回执见 `checks/source_probe_cleanup.json`。未删除任何既有TASK-008成果或清理源树其他修改。`checks/migration_summary.json` 中6个probe残留是清理前的状态，不能代替最终边界检查。

## 文件与路径处理

| 来源 | 目标/动作 | 原因与验证 |
| --- | --- | --- |
| 目标原artifacts junction | 保留为 `artifacts/legacy_task021a_link`，目标artifacts改为物理目录 | 仅处理目标reparse point，源目录内容不随之移动 |
| 源TASK-008的12659个文件 | 11121个文件复制到目标同名物理TASK-008目录 | 每个复制文件SHA一致；不改冻结实现、协议、参数、结果、开发负结果与原图 |
| 1538个缓存/重复smoke产物 | 清单列为排除，不从源删除 | 保留源码冻结、原重放比较/环境等证据；排除pycache、临时缓存及重复输入输出副本 |
| 源2个TASK-008测试 | 目标 `tests/unit/test_research_task008*.py` | 原字节复制，不修改测试合同 |
| 源根COMPARISON.md | 目标根COMPARISON.md | 原字节复制；保留研究结论与负结果 |
| 目标已有10个真正原始文件 | 以SHA匹配原逻辑路径，保留原位置和字节 | DAT平铺路径由索引解决，不改raw布局 |
| 源独有ch1/ch2/ch4.csv | 目标TASK-009 `source_data/raw_supplement/` | 仅研究副本，逐SHA一致；不新增或覆盖目标data/raw |
| 新研究代码 | `src/dps_studio/research/task009_runtime.py`、`task009_data.py` | 导入目标本地实现；旧树文件访问守卫；逻辑数据索引 |
| 新入口/测试/绘图 | scripts、tests及TASK-009目录 | 不修改core、GUI、配置或Production；具体路径见根Git状态和迁移清单 |

原始迁移共复制11124个文件、295542774字节（含2测试和COMPARISON，不含后续3个raw补充及新TASK-009文件）。逐文件来源、目标、排除理由与哈希以 `migration_files.csv` 为准。冻结日志和旧README中的绝对路径作为历史来源文本保留，执行应使用TASK-009入口。

## 独立复现与数值合同

168条合成轨迹：12族固定第0条×14方法；42条真实轨迹：20260607第一电压列、ch3坏记录、80 GS/s 20231019 DAT×14方法。运行均开启禁止访问TASK021A的Python审计守卫；时间、候选频率、支持频率、R²与原冻结数组比较，`rtol=1e-11, atol=1e-3`，NaN位置保持。频率的绝对容差单位Hz；本验证证明数值重放一致，不是新精度结论。记录位于 `replays/independent_smoke/replay_comparison.json`、`checks/raw_replay.json`。新CLI另外实际运行20260607的VarPro，输出在 `replays/cli_example/`。

原真实测试14×17=238条方法-流记录全部保留，原harness状态均为OK；OK只表示未抛异常，支持可以为空，真实准确性仍不可知。新接口保留候选、支持、质量标志、假设等效速度与独立校正速度，不把支持当作已验证物理速度。

算法与完整重放无需TASK021A源码。目标其他非TASK-008历史artifacts通过各自junction继续保留原入口，因此不能把本结论扩展为整个历史仓库已完全独立。

## 绘图与QA

10张主图原生Origin OPJU/PDF，3张Matplotlib补充图，均提供SVG和600 dpi PNG。数据只来自冻结结果，真实谱图仅对同SHA原电压以既有512/Hann/4096配置重算可视化。全部方法/全部真实通道保留在总图、补图和来源表；有限点RMSE、全分母失败、覆盖率、原波形级区间和缺失值分别呈现。图注逐一标记固定样例、事后选择及无GT限制。

本机Origin 2021长LabTalk数组曾触发2次进程崩溃；早期PutWorksheet/图层/文本对象与图例行为也出现负结果。失败probe与render版本完整保留。最终改用原生ASCII导入、逐点读回、显式当前曲线、独立手工图例和分段NaN绘制。QA发现并修正了Pencil极低速RMSE被纵轴上界截断、自动图例将缺口分段误列为算法、补充图面板字母越出页面等问题。没有改动数值来改善外观。

Times New Roman按180 mm宽排版；主图约9–10 pt，四边框、向内主次刻度；热图使用cividis。原生PDF未嵌字，成品PDF用本机Ghostscript嵌入字体；SVG由该矢量PDF转换，文本字形成为路径，OPJU保留原生编辑性。补充谱图为声明过的混合矢量/栅格图，不冒充纯矢量谱矩阵。

## 检查记录与限制

运行命令、最终测试/静态检查与PDF QA见 `checks/VALIDATION.md`；不是全仓零失败的报告。全仓首轮1047通过、6失败，保留原日志 `checks/pytest_full_v01.log`：

- 两个deployment launcher测试仍期待Production式conda启动器，与本分支既有Research禁用/转发启动器不一致。
- TASK023F、TASK023G、TASK025的三个历史冻结哈希测试与本分支既有Research源码不一致。
- TASK025校准测试所引用的旧NPZ在原artifact来源中缺失。

这些文件的既有字节与初始快照一致；本次不重构启动器、不改旧冻结期望、不重造缺少的历史NPZ。新增Research代码的相关测试、Ruff、mypy及图件完整性检查单独记录。尚无独立实验真值或仪器波长/通道校准，不能作真实精度排名。建议继续研究可预测杂散模型、局部Chirp/VarPro与多起跳检测，保留完整M0并先解决不足周期可辨识性；不据此promotion。
