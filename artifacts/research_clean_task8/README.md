# TASK-008｜PDV 速度重建算法开放探索

研究实验与报告完成；停留在 Research。14 个方法/对照均运行了 **13 个真正原始文件、17 条电压通道**，另完成 96 条新种子主合成测试和 50 条低速随机初相压力测试，共 2282 个正式方法流，执行异常为 0。12 个探索方法先冻结；随后追加两种历史 M0 契约对照，不改变探索参数。开发轮失败另外保留，没有混入最终统计。

有条件的最明确新增收益来自“相干杂散预测＋VarPro”：主分布支持后全分母失败率 8.70%，原 768 点 STFT 为 13.64%，去 DC＋截断 512 点控制为 17.79%。**相对原 768 的配对区间跨零，不能宣布全面胜出。** 低速极限、弱信号漏检、双分量身份与前端未知传递函数仍未解决。

## 📁 阅读入口

| 入口 | 内容 |
| --- | --- |
| [COMPARISON.md](../../COMPARISON.md) | 全部算法、逐真实数据表、合成/压力结果、负结果与四条推荐路线 |
| [冻结协议](PROTOCOL.md) | 物理模型、输入全集、参数开发与新种子分离、分母与成本口径 |
| [主结果图](figures/synthetic_comparison.png) | 各族 RMSE、覆盖和含缺失失败率同时显示 |
| [低速初相压力](figures/low_speed_phase_stress.png) | 不掩盖 15–30 m/s 失败和拒绝输出 |
| [原始文件清单](tables/raw_inventory.csv) | 13 个波形、5 个处理结果及辅助文件的分类、SHA 和采样率 |
| [全部真实诊断](tables/real_diagnostics.csv) | 238 条方法×通道观测记录，真实准确率不可得 |
| [图清单](figure_manifest.csv) | 408 PNG 与对应来源，其中真实图 238 张、固定合成例 168 张；原12方法总图另存 |
| [边界验收](checks/final_boundary_check.json) | raw/Production/Git/既有修改前后核对 |
| [检查记录](checks/validation.json) | 新测试、全仓 pytest、Ruff、mypy 与既有失败区别 |

真实数据没有 Ground Truth，波长与参考频移没有重新标定。真实速度图仅按 **1550 nm 假设给出等效表观速度**，主输出保留 Hz；不计算 LiF 或 corrected velocity，不把无拍频置为实测零速。每个方法的 `accepted_hz` 只是启发式波形支持后的研究假设。

## 🔁 安全复现

PowerShell 7，现有 dps-studio 环境，无新增安装。下列命令从本工作区运行，只向一个**尚不存在**的新目录写入；遇到已有目录会拒绝覆盖：

```powershell
$env:PYTHONPATH='D:\Code\Python_Projects\DPS_Studio_TASK021A\src;D:\Code\Python_Projects\DPS_Studio_TASK021A'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& 'D:\miniconda3\envs\dps-studio\python.exe' -B -m artifacts.research_clean_task8.reproduce --output 'D:\Research\DPS_TASK008_replay_new' --figures
```

快速数值重放可增加 `--smoke`，只运行 12 族第 0 条，并与原冻结输出逐值比较；不把 smoke 当全量验收。源文件如果偏离冻结指纹会停止。原项目 README 已逐字节保存为 [README_before.md](README_before.md)。

## ✅ 验证状态

新增算法契约测试 30 项通过。全仓 pytest 为 913 通过、6 失败；失败集合与任务前相同，涉及历史启动器约定/冻结记录/缺失旧 artifact，未改这些文件。Ruff、mypy 通过；完整日志在 checks。未 stage、commit、push、merge 或 promotion，Production 未修改。
