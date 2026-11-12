# research_task21｜验收与边界

| 检查 | 结果 |
|---|---|
| 完整 pytest | 809 通过；新增卫生判别的最终定向复测 2 通过 |
| GUI pytest | 147 通过；包含独立页、旧局部拟合、失效清空、切页与中英文尺寸检查 |
| Ruff / mypy strict | 通过；严格类型检查 99 个源码文件 |
| 原生 Windows GUI | 两次成功显示并捕获原生窗口；最终图件见 `artifacts/research_task21/native_final/` |
| Dechirp 数学和真实数据 | 正、负及零斜率，绝对时间偏置、SI 换算、弱信号、双音和阶跃；三份真实记录三种窗长 |
| raw | 24 个路径和 SHA-256 前后一致；无 raw staged/unstaged diff |
| 旧链路 | 三份记录的 STFT 复系数/网格、速度数组、NaN 掩码、15° 与无窗口、LiF、自定义 b1=0.82 的结果及旧差分/拟合指纹一致 |
| 导出 | 9 份旧 CSV 内容和列完全一致；3 份旧 metadata 仅导出时间不同；新 Dechirp 列、状态与核心结果逐点一致 |
| 仓库卫生 | Git 生成物检查通过；严格模式发现空 `dist`、历史包和副本，清单见 [治理报告](REPOSITORY_CLEANUP.md) |

早期一次完整测试在 Windows/Qt 图元构造中出现原生异常；单独 GUI 和非 GUI 两组均通过，随后完整复跑未重现。结果见 `artifacts/research_task21/audit/{regression,gui_final,core_final,ruff,mypy}.txt`。数值对照由 TASK-019 的 `figures/production` 基线复核，机器证据见 `artifacts/research_task21/legacy_parity/parity.json`。

Production 仍在 `main`，HEAD `677a22df`，领先 `origin/main` 1 个既有提交。开始时 1,081 条历史生成文件的索引移除全部保留，其工作副本在本轮均存在。与 TASK-019 和本轮相关的其他修改还在工作区。用户确认了永久清理，自动审批阻止执行；清理验收未完成，未新增暂存或本地提交。未推送、未构建、未写入 Research。
