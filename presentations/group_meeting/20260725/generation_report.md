# DPS Studio 组会汇报生成报告（原生可编辑版）

## 1. 最终交付

- PPTX：`D:\Code\Python_Projects\DPS_Studio\presentations\group_meeting\20260725\DPS_Studio_组会汇报_20260725.pptx`
- PDF 预览：`D:\Code\Python_Projects\DPS_Studio\presentations\group_meeting\20260725\DPS_Studio_组会汇报_20260725_preview.pdf`
- 页数：15
- 版式：16:9，10.0 × 5.625 in
- 演讲备注：15/15 页非空
- PowerPoint 实际渲染：15/15 页，位于 `rendered_slides\`
- 可编辑性：全套文字、卡片、箭头、流程图和路线图均为原生 PowerPoint 对象；第 8、9、12 页共有 4 个原生图表。
- 位图范围：仅第 6 页原始电压图和第 7 页 STFT/脊线热图为项目真实图像，不存在“整页铺图”。

SHA-256：

- PPTX：`225BA3525D3948F909ECDD3887FD50808F0416D5A8F2D1CF2F4DCC1085956E2A`
- PDF：`8AE5368A7E5E31AE3D56075142CF169A59EE4773F9A7BC53471EC2514657F0AB`

## 2. 内容结构

1. 从原始 PDV 信号到可追溯的表观速度
2. 速度曲线与后续物理判断
3. 旧流程的证据链风险
4. Python 重建的工程价值
5. 已实现、正在完善和尚未实现的能力边界
6. 只读输入、SI 单位和显式列映射
7. STFT 与可追踪时频脊线
8. 拍频轨迹到无符号表观速度
9. 双通道独立分析与描述性质量
10. core/workflow 与 GUI 解耦
11. 当前工作树完成度与质量门
12. 双通道真实速度结果及可信边界
13. 工程可运行与科研可用的差距
14. 下一阶段依赖路线
15. 可信、可复现、可交付

完整逐页提纲见 `presentation_outline.md`，事实来源和页级映射见 `source_map.md`。

## 3. 使用的项目事实与素材

- 当前仓库 `HEAD`：`11b761f`（`feat: add analysis profiles and production output modes`）。
- 当前工作树原本即为 dirty；汇报明确标注“当前工作树能力不等于稳定发布”。
- 项目审计报告：`presentations\PROJECT_STRUCTURE_AND_PARAMETER_AUDIT.md`，SHA-256 为 `A85B9F983A3074B7E9BE13A65BC2C30FE1A40F25BD48BD1991299134A54E4A67`。
- 用户模板：`presentations\Sigapore_presentation.pptx`，仅抽象使用白色留白、砖红标题、浅米灰几何装饰和细红底边；未保留原模板正文、校徽、四川大学文字、作者、页码或论文内容。
- 原始数据：`data\raw\20260607.csv`，只读使用；任务结束时 SHA-256 仍为 `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`。
- 最近真实 production run：`outputs\production_runs\run_20260724_004901_103968`。
- 真实图像包括：双通道原始电压、Balanced 通道 1 STFT/脊线、双通道事件速度、最近真实 run 的描述性谱质量统计。
- 新生成的分析图：`assets\project_outputs\raw_voltage_event.png` 与 `assets\project_outputs\quality_diagnostics_summary.png`；生成过程未平滑、未插值、未重采样，也未覆盖原始数据。

## 4. 科研边界

- `λ = 1.55 μm` / `1550 nm` 仅是当前配置中的未确认演示值，不作为已核验实验参数。
- 当前正式数值链只到无符号表观速度；未实现 LiF 修正、折射率修正、`corrected velocity` 或有符号速度。
- 两通道独立分析；未实现自动择优、平均或融合。
- 峰—背景和峰—竞争峰的 dB 量仅为描述性谱质量，不是正式 SNR，也没有 GOOD/BAD 自动阈值。
- `PRE_EVENT` 核心速度保持 NaN；显示零与事件起点附近的 bridge 只用于显示，不代表测量或时间插值。
- 全时段 preview 是 quality-unfiltered development preview，不是正式低速测量。
- GUI、完整 CLI、集成测试、打包、跨机器部署和最终用户验收均未完成。

## 5. 生成与修正

- 最终 PPTX 由 `generate_editable_deck.js` 使用 PptxGenJS 生成，正文不是图像后端输出。
- 文字、页眉页脚、卡片、箭头、时间线、工作流、状态条和总结页均为可在 PowerPoint 中直接选择、修改和移动的原生对象。
- 第 8、9、12 页的数据图使用原生 PowerPoint chart；其数据系列、坐标轴、颜色和字号均可继续编辑。
- 第 6 页原始双通道电压图与第 7 页 STFT/脊线热图保留为位图，因为它们承载真实密集科学数据；两图均来自本项目素材，并非生成式整页图。
- 旧的整页图片版已保留为 `_qa_tmp\DPS_Studio_组会汇报_20260725_图片版备份.pptx`，不再占用最终交付路径。
- 生成初版曾发现线段负宽高和紧凑卡片文本框高度过小，可能导致 PowerPoint 修复文件；已统一规范为正向几何尺寸，最终 XML 中负尺寸对象为 0。
- 独立视觉 QA 后完成多轮 fix-and-verify：缩小长标题、释放第 3/4/5 页拥挤区域、精简第 8/12 页轴标签、修正第 10/11 页工作流标注、重构第 14 页路线图，并复核第 15 页收束页。
- 最终文件已由本机 PowerPoint 实际打开并导出 15 页 PDF 与 1920 × 1080 PNG；整套 montage 无裁切、重叠、模板残留或 logo。

## 6. 验证结果

最终权威质量门：

```text
pytest: 271 passed in 10.52s
ruff: All checks passed!
mypy: Success: no issues found in 39 source files
git diff --check: passed
generate_editable_deck.js: node --check passed
```

补充结构检查：

```text
PPT slides: 15
PPT size: 10.0 × 5.625 in
Native text/shapes: present on all 15 slides
Native charts: slide 8 = 1, slide 9 = 1, slide 12 = 2
Pictures: slide 6 = 1, slide 7 = 1, all other slides = 0
Embedded media parts: 2
Non-empty notes: 15/15
Negative geometry extents: 0
PDF pages: 15
PDF page size: 720 × 405 pt
Rendered PNGs: 15
```

验证使用 `PYTEST_ADDOPTS='-q -p no:cacheprovider'` 与隔离的 `TEMP/TMP`，避免 pytest 参数被 CLI 测试误读。PowerPoint 首次 PDF 导出调用因 COM 枚举绑定差异失败，但演示文稿当时已成功打开；随后使用 PowerPoint `SaveAs PDF` 完成导出，该问题不涉及 PPTX 内容或兼容性。

## 7. 主要执行命令

```powershell
conda run --no-capture-output -n dps-studio python -m pytest
conda run --no-capture-output -n dps-studio python -m ruff check . --no-cache
conda run --no-capture-output -n dps-studio python -m mypy src --cache-dir presentations/group_meeting/20260725/_qa_tmp/mypy_cache_editable_final_v6

C:\Users\89484\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe `
  presentations\group_meeting\20260725\generate_editable_deck.js

C:\Users\89484\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe `
  --check presentations\group_meeting\20260725\generate_editable_deck.js

git diff --check
git status --short
```

PowerPoint COM 实际打开最终 PPTX，导出 PDF 与 1920 × 1080 PNG；只关闭本次打开的演示文稿。

## 8. 新增文件范围

本任务只在 `presentations\group_meeting\20260725\` 下新增/更新汇报产物，未修改 `data\raw`、`src`、`scripts`、`tests`、`configs`、`docs` 或既有项目结果。

主要文件：

- `DPS_Studio_组会汇报_20260725.pptx`
- `DPS_Studio_组会汇报_20260725_preview.pdf`
- `presentation_outline.md`
- `outline.md`
- `source_map.md`
- `generation_report.md`
- `speech.md`
- `deck_spec.json`
- `slide_jobs.json`
- `slide_run_state.json`
- `generate_assets.py`
- `generate_editable_deck.js`：最终原生可编辑 PPTX 的生成源文件
- `assets\`：模板只读渲染、真实项目图和来源副本
- `origin_image\`：旧图片方案的母图，仅作为过程记录
- `rendered_slides\`：15 张最终可编辑版经 PowerPoint 实际导出的预览图
- `prompts\`：样稿与 15 页生成任务
- `_qa_tmp\`：旧图片版备份、可编辑版多轮渲染、montage、缓存与验证副本

没有执行 `git add`、`git commit` 或 `git push`。
