# DPS Studio 组会汇报来源映射

## 全局事实基线

- 仓库：`D:\Code\Python_Projects\DPS_Studio`
- 分支 / HEAD：`main` / `11b761fe49550f22e7430f939f2bedb87826c345`
- 工作树：本任务开始前已不干净；PPT 使用“当前工作树已实现”，不声称稳定发布。
- 审计报告：`presentations/PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md`，SHA-256
  `A85B9F983A3074B7E9BE13A65BC2C30FE1A40F25BD48BD1991299134A54E4A67`。
- 模板：`presentations/Sigapore_presentation.pptx`，只用背景/装饰风格。
- 最新真实运行：`outputs/production_runs/run_20260724_004901_103968`。
- 原始数据：`data/raw/20260607.csv`，真实 run manifest 记录 SHA-256
  `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。
- 本轮质量门：
  - 首次直接 `python -m pytest -q`：`270 passed, 1 failed`；失败原因是被测 CLI
    继承 `-q` 并将其视为未知业务参数。
  - 权威重跑：`PYTEST_ADDOPTS='-q -p no:cacheprovider'` 后执行
    `conda run --no-capture-output -n dps-studio python -m pytest`：
    `271 passed in 9.39s`。
  - `conda run --no-capture-output -n dps-studio python -m ruff check . --no-cache`：
    `All checks passed!`。
  - `conda run --no-capture-output -n dps-studio python -m mypy src --cache-dir
    presentations/group_meeting/20260725/_qa_tmp/mypy_cache`：
    `Success: no issues found in 39 source files`。

## 逐页映射

| 页 | 主要结论 | 主要事实来源 | 代码/测试证据 | 图片与生成方式 | 类型 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 当前对象是 PDV 数值工作流，不是已发布 GUI | `README.md`; 当前 Git | `src/dps_studio/gui/__init__.py`; `src/dps_studio/cli.py` | 模板第 1、20 页仅作背景参考；`prompts/slide_01.json` + `image_gen` | 事实 |
| 2 | 软件把原始信号连接到表观速度和后续物理判断 | 审计报告第 7、8、17 节 | `core/io`; `time_frequency`; `ridge`; `physics` | 依据真实调用链重新绘制流程图；不冒充实验图 | 事实 + 示意 |
| 3 | 旧输出缺少完整证据链，不能当物理真值 | 审计报告第 6.3、9.11 节; `data/reference/legacy/README.md` | `scripts/audit_legacy_velocity_reference.py`; `tests/unit/test_legacy_velocity_audit.py` | 因果风险链由 `image_gen` 绘制 | 事实 + 推论 |
| 4 | Python 栈用于数值、配置、测试和未来 GUI | `pyproject.toml`; 本轮质量门 | `tests/`; Ruff; mypy | 技术栈图由 `image_gen` 绘制 | 事实 |
| 5 | 表观速度闭环已打通，修正和 GUI 未实现 | 审计报告第 17 节; 当前源码 | `src/dps_studio/core/workflow/analysis.py`; `scripts/production_outputs.py` | 三态处理链由 `image_gen` 绘制 | 事实 |
| 6 | 输入只读、SI、双通道独立、不静默处理 | `AGENTS.md`; `configs/demo_dual_profile.toml` | `core/io/delimited.py`; `core/models/signal.py`; IO/model tests | `assets/project_outputs/raw_voltage_event.png`; 命令：`conda run --no-capture-output -n dps-studio python presentations/group_meeting/20260725/generate_assets.py` | 事实 |
| 7 | STFT 保留时变频率，NFFT 网格不等于真实分辨率 | 审计报告 9.2、15.7、17.3 | `core/time_frequency/stft.py`; `core/analysis_profiles.py`; `tests/unit/test_stft.py` | `assets/project_outputs/balanced_ch1_stft_ridge.png`，复制自最新真实 run | 事实 |
| 8 | 脊线经显式波长换算无符号表观速度；1550 nm 未确认 | `configs/demo_dual_profile.toml`; manifest | `core/physics/velocity.py`; apparent velocity tests | `assets/project_outputs/balanced_ch1_velocity_event.png`，复制自最新真实 run | 事实 |
| 9 | 双通道独立；质量量不是正式 SNR 或通道选择器 | 审计报告 9.6、9.8; 真实 quality CSV | `core/ridge/spectral_quality.py`; quality/production tests | `assets/project_outputs/quality_diagnostics_summary.png`; 同 `generate_assets.py` 命令 | 事实 + 当前数据观察 |
| 10 | `core.workflow` 与 GUI/绘图/scripts 解耦 | 审计报告第 17.1 节; 当前导入关系 | `core/workflow/*`; `core/__init__.py`; workflow tests | 架构图由 `image_gen` 绘制 | 事实 |
| 11 | 当前工作树闭环可运行，质量门通过但未发布 | 当前 Git; 本轮质量门; 最新 manifest | `tests/`; `scripts/production_outputs.py` | 状态矩阵和数字卡由 `image_gen` 绘制 | 事实 |
| 12 | 两通道同量级是重复性线索，不是准确度证明 | 最新 `quality_summary.csv` 和 manifest | production 输出契约和测试 | `balanced_ch1_velocity_event.png` + `balanced_ch2_velocity_event.png`，严格保留原图 | 事实 + 安全推论 |
| 13 | 能运行不等于科研级可信 | manifest guards; 审计结论; 当前缺失模块 | `ridge/peak.py`; `gui`; `cli.py`; `physics` | 对照图由 `image_gen` 绘制 | 事实 + 归纳 |
| 14 | 非 AI 可信判据优先，修正和 GUI 后置 | 由第 13 页缺口推导；符合 `AGENTS.md` | 计划项尚无实现代码 | 路线图由 `image_gen` 绘制 | 下一阶段计划 |
| 15 | 重点转向可信、可复现、可交付 | 全套事实综合 | 无新增能力声明 | 模板第 20 页只作结尾背景参考；`image_gen` 重建，不保留原文 | 归纳 |

## 真实图片资产

- `assets/project_outputs/raw_voltage_event.png`：当前 raw 的事件窗口，两个通道分图；
  未平滑、未插值、未重采样。
- `assets/project_outputs/balanced_ch1_stft_ridge.png`：最新真实 run，Balanced / 通道 1。
- `assets/project_outputs/balanced_ch1_velocity_event.png`：最新真实 run，Balanced / 通道 1。
- `assets/project_outputs/balanced_ch2_velocity_event.png`：最新真实 run，Balanced / 通道 2。
- `assets/project_outputs/quality_diagnostics_summary.png`：由最新两份质量 CSV 重新绘制；
  标题明确“不是正式 SNR”。
- `assets/project_outputs/balanced_ch1_full_preview_dev.png`：仅留作审计证据，不作为
  正式速度结果使用；manifest 明确其为 quality-unfiltered development preview。

## 禁止性解释

- 不把 `peak_to_background_db` 称为正式 SNR。
- 不把 `display_velocity_m_s=0` 称为起跳前真实测量零速度。
- 不把两通道并列结果称为融合或自动择优。
- 不把 `vacuum_wavelength_m=1.55e-6` 称为已确认实验参数。
- 不把 apparent velocity 称为 LiF 修正后的 true/corrected velocity。
- 不把单个真实数据文件与一次 production run 泛化为科研级普适验证。
