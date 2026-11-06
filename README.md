# PDV Studio Research

Windows x64 科研测试版。经典 STFT 与人工分段工作区共用只读输入，正式导出保留时间参考、质量标志、算法来源与修正配置。Research Balanced 默认 W1024/H64。阶段专项结论和已知限制见 [TASK-014](artifacts/research_clean_task14/README.md)。

## Windows 源码运行与自动构建

使用 Python 3.12 x64，从仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -c packaging/windows-constraints.txt -e ".[dev]"
.\.venv\Scripts\python -m dps_studio.gui
.\.venv\Scripts\python -m PyInstaller --workpath build --distpath dist packaging/pdv_research.spec
```

科研复现加装 `.[dev,research]`，并提供本地研究数据索引所列文件。GitHub Actions 的 **Windows Research test build** 支持手动启动和 `v*` 标签启动，检查通过后上传整个 onedir 目录。下载后先完整解压，再运行其中的 EXE。无需复制 Production、配置密钥或提供私有实验数据来构建。

## 继承的流程与历史文档

下列 Production 资料用于追溯历史流程。Research 发布验收以 TASK-014 和当前 Windows 工作流为准。

The formal production pipeline is for an authorized local raw-data file, which is intentionally not included in this repository. After activating the project environment and updating the TOML input path for that local file, run:

```powershell
python scripts\run_demo_pipeline.py --config configs\demo_dual_profile.toml
```

The TOML file is the single production configuration entry for the input path,
column mapping, analysis interval, demonstration wavelength, per-frame quality
parameters, independent event-candidate/consensus settings, plot ranges, and
output root. Every production run analyzes the independent acquisition channels
with both the Balanced and High time resolution profiles.

Successful formal runs are isolated under
`outputs/production_runs/run_<YYYYMMDD_HHMMSS>/`. The run root contains the
profile/channel diagnostic trees, `comparisons/`, `event_consensus.json`, and a
`simple_exports/` directory. Each actual profile/channel stream has exactly one
`<profile>__<channel>__velocity_time.csv` file with the Origin/Excel-ready
columns `time_s` and `velocity_m_s`. Every frame before the cross-profile
consensus time is defined as zero solely for plotting. At and after consensus,
the formal quality-gated apparent velocity is copied exactly, including NaN
gaps; all original STFT frames and times are retained without interpolation,
smoothing, bridging, or resampling. If consensus is unavailable, the formal
array is copied unchanged and the manual reference is not substituted. The
complete per-frame table remains available as
`apparent_velocity_diagnostics.csv`; no duplicate `apparent_velocity.csv` alias
is generated. Its formal `apparent_velocity_m_s` and signal states are never
pre-event zero-filled. Each profile/channel directory also contains the primary
red/blue `apparent_velocity_full_overview.png`, the simple-series
`apparent_velocity_full_time_reviewed.png`, a formal full-time plot, and separate
state diagnostics. `comparisons/threshold_calibration.csv` records the four
approved threshold pairs and deterministic selection. The retained 10 dB
peak/background and 3 dB peak/competitor values are development-calibrated for
this record, not an absolute experimental standard. `outputs/LATEST_RUN.txt` is
updated only after a complete successful formal run.

Numerical workflow:

raw time-voltage data -> validation -> STFT -> peak ridge -> sub-bin refinement
-> spectral quality -> quality-gated unsigned apparent velocity
-> exact MEASURED segments -> channel consensus -> profile consensus

The formal ridge search is 0.05–2.0 GHz. The analysis-band plots display
0–2.0 GHz, while full-band plots use the complete one-sided STFT range from
0 Hz through the actual Nyquist frequency. The configured 1550 nm wavelength
is an unconfirmed demonstration value. No LiF correction, smoothing,
interpolation, channel fusion, or profile fusion is implemented.
`MEASURED` means spectrally qualified under the configured detection rules;
physical branch identity remains `unreviewed`. Event consensus changes metadata
only and does not average or fuse voltage, frequency, or velocity.

Development rules:

- Never overwrite raw data.
- Keep the numerical core independent from the GUI.
- Use SI units internally.
- Store all parameters and manual edits.
- Return NaN and quality flags when no reliable signal exists.


## TASK-009 Research package (2026-11-05)

TASK-008 algorithms and frozen results now have a physical local copy and an independent Research entry.
See [research package](artifacts/research_clean_task9/README.md), [migration report](MIGRATION_REPORT.md), and [paper figure index](FIGURE_INDEX.md).
Publication figures are in `artifacts/research_clean_task9/figures_final/` (10 Origin projects; 13 PDF/SVG figures with source data and Chinese captions).
Real experiments have no Ground Truth; supported curves do not certify physical velocity. Production is outside this task.
