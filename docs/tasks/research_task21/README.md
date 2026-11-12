# research_task21｜Production 双算法加速度与仓库治理

Production 新增独立加速度页。原始差分和可选局部线性拟合保持既有数值，Dechirp 从原始电压估计局部拍频斜率并输出表观加速度。512 点默认窗在三份真实记录分别通过 310/620、621/1,557、326/620 帧；弱信号起跳可能没有任何通过窗。真实记录没有独立加速度真值，不据此宣称更准确。采用 Dechirp 的理由是独立波形证据，代价是缺测、耗时和窗口依赖。

原生 Windows 实测了切页、算法切换、局部缩放、光标和 CSV 导出。三份真实记录的旧科学链路及九份旧 CSV 与 TASK-019 的指纹完全相同。脚本归入 `scripts/build`、`scripts/dev`、`scripts/maintenance` 和本任务的 `scripts/research/research_task21`；正式发布构建入口只在 `release/` 生成验证后的 ZIP。未构建软件。

| 报告 | 内容 |
|---|---|
| [加速度对照](ACCELERATION_COMPARISON.md) | 数学模型、真实原始波形、STFT、峰值、失效与窗敏感性 |
| [GUI 验收](GUI_VALIDATION.md) | 原生截图、切页交互和导出 |
| [仓库治理](REPOSITORY_CLEANUP.md) | 隔离区、发布包、磁盘核对和待决项 |
| [验证](VALIDATION.md) | 数值回归、测试、Git 与 raw 边界 |
