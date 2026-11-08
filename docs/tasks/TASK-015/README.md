# TASK-015｜人工阶段先验与算法池

**结论：存在阶段专用的条件性收益，尚不支持整体替代传统 STFT。** 任务开始于 2026-11-07，实验和验收跨至 2026-11-08。独立测试 288 条、开发集 72 条；另有边界/误标与时间分辨实验。真实 13 文件、17 路全部诊断，仅报告 Hz 观测。

- 低频目标叠加强固定杂散：原始实值 GLRT/局部杂散投影的支持点 RMSE **0.028 m/s、覆盖 75%**；传统 STFT 全部选错高频支路。低频带 STFT 在该组全部被质量门控拒绝。此收益以低频目标先验和杂散模型成立为条件。
- 无强杂散低频组：相同 75% 覆盖下，低频带 STFT / GLRT 的 RMSE 为 **0.565 / 0.036 m/s**。少周期与 AC 耦合不可观测结果仍为 NaN，不作为实测零速。
- 专项组合总体含缺失失败 **48.05%**，传统 Balanced 为 **45.69%**。误标、漂移杂散及前缀已有目标是保留的失败；不以较低支持点 RMSE 掩盖缺失。

| 阶段 | 自动推荐 | 可手动比较的选项与证据 |
|---|---|---|
| 静止 | STFT + 独立静止先验标识 | 低频带 STFT、低频 GLRT；上列低频收益，误标可全拒绝 |
| 起跳 | STFT | 边界短窗；准确边界和较高 SNR 下有条件收益 |
| 加速 | 既有 Dechirp | 保留历史配置；斜率符号消融未显示额外净收益 |
| 平台 | STFT | 长窗 STFT、长窗正弦精修；弱信号/边界可降低覆盖 |
| 下降、回升 | STFT | 短窗或既有 VarPro；避免默认长窗抹平转折 |
| 弱信号、噪声干扰、未知 | STFT | Clutter VarPro 仅手选；噪声不再直接排除成 NaN |

修改阶段即时同步推荐；之后手动选择会保留至再次改变阶段或主动重置。新增五个手选策略共享一个计算内核。内部观测质量独立于阶段。**低频策略仍遵守用户频带**，若要研究 20–40 MHz，须显式把频带下限调到对应范围（本实验为 5 MHz）；算法不会偷偷放宽。零速先验仅在表观速度图以灰色虚线/“非测量”文字和独立 CSV 字段表示，绝不填入测量数组。

**交付：** [完整对照与失败](COMPARISON.md) · [验证与边界](VALIDATION.md) · [图件说明](FIGURES.md) · [Windows 测试 ZIP](release/PDV_Studio_Research_TASK015_Windows_x64.zip)。ZIP 是未签名 Research 测试版；解压后运行 `PDV Studio Research TASK015.exe`。本轮无提交、push、merge 或 promotion，已有历史测试版保留。

**复现：** 在仓库用 PowerShell 7 执行 `& scripts/research/task015/run.ps1 scripts/research/task015/experiment.py heldout --count 16 --workers 4 --output artifacts/TASK-015/data/replay_new`。输出须选不存在的新目录。开发命令将 `heldout` 改为 `development --count 4`；边界测试增加 `--sensitivity`。`run.ps1` 绑定本机既有 conda 环境，缓存/临时文件均在本任务目录。精确版本见 `data/environment.json`；统计和绘图脚本读取已冻结结果。目录结构：`data/` 数值与验收，`figures/` 四组 PNG/SVG/PDF，`logs/` 完整日志，`disk_governance/` 清理与只读证据，`release/` 一个 ZIP；根层为轻量复现代码和报告。
