# 历史 M0 基准契约补充核验

## 🔎 发现与处理

初始 12 方法评价中，stft512/stft768 调用正式 peak＋sub-bin API，细化失败保留 NaN；离散峰另存。复核历史 Research 的 `RidgeCandidate.transition_frequency_hz` 时发现 M0 使用 refined-if-finite、否则 discrete 的明确候选契约。这两个输出通道不能混称。

因此在未更改任何探索估计器、生成器、种子或质量参数的前提下，额外实际运行 `legacy_m0_512` 和 `legacy_m0_768`：直接调用原 Top-20 API，取 rank 1 的 transition_frequency_hz。全部 96＋50 合成和 13 文件/17 真实通道再次遍历。注册指纹见 baseline_audit_registration.json；这项核验是在查看原主结果后追加的对照，不能称为盲预注册。

原 12 方法的冻结源码、指标和轨迹不覆盖；汇总的 `all_*_metrics.csv` 合并原结果与两个补充对照。旧 12 方法汇总/总图另存为 `*_12method`。任何差异必须以新的完整对照表为准，不把细化失败的 NaN 当作算法无信息的物理证明。

## 🧪 可复核细节

- 两个基准实现单独存放，所有通道独立图、参数、轨迹和指标齐全。
- 新增单测验证强 DC 边界时，旧 M0 保留离散候选、严格 refined 为 NaN；不把离散回退当作可靠测量。
- 初次核验包装器遇到已有输入不变性日志的 exclusive-write 冲突，日志保留；改用 baseline_fresh / baseline_phase_stress / baseline_real 独立阶段，没有覆盖旧文件。这是包装器文件命名错误，不是估计器异常。
- 参考调用仍计算 Top-20 元数据，耗时不能解读为最优化的裸 strongest-only 内核成本。
