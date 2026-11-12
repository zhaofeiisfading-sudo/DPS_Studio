# DPS Studio

PDV/DPS signal analysis software.

For a new Windows computer, follow the [beginner installation guide](docs/deployment/WINDOWS_BEGINNER_INSTALL_GUIDE.md). A shorter version is available in [Quick Start for Windows](docs/deployment/QUICK_START_WINDOWS.md).

The GUI entry point after installation is:

```powershell
python -m dps_studio.gui
```

Open a CSV, DAT or TXT file and confirm the column and source unit mappings.
Set the analysis interval on the waveform or in the parameter pane. **快速分析**
computes the STFT and opens the ridge search region for review. The **分析** menu
also offers a full automatic run. Use **视图 → 诊断与数据** to show sampling,
quality and log details. The velocity page holds window and angle corrections;
the export page shows the selected velocity result and opens the directory
picker on the first export.

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
is an unconfirmed demonstration value. These demonstration exports describe
apparent velocity. The desktop GUI additionally supports the existing separable
observation-angle and LiF window corrections. Smoothing, interpolation,
channel fusion, and profile fusion are not applied by this workflow.
`MEASURED` means spectrally qualified under the configured detection rules;
physical branch identity remains `unreviewed`. Event consensus changes metadata
only and does not average or fuse voltage, frequency, or velocity.

Open the **加速度曲线** tab alongside the velocity plot. **速度差分** computes the
time derivative of the final displayed speed. **Dechirp 直接估计** fits the
local beat frequency and its slope in the raw voltage near the selected ridge.
It reports apparent acceleration; angle and window corrections only apply to
the speed used by the difference method. Gaps and rejected waveform fits remain
blank. In Review/Export, the acceleration CSV can include separately named
Dechirp and local fit columns with quality and settings in metadata. The
velocity tables keep their original columns. Under **材料参数…**, edit the fixed window
formula coefficients, name the custom set, and use **保存修改** or **另存为新配置…**.
Saved sets appear in **窗口配置** on the next launch. The built-in LiF remains intact.
See [TASK-032](docs/TASK-032_ACCELERATION_WINDOW_PRESETS.md) for numerical rules,
local configuration paths, compatibility and validation limits.

Acceleration defaults to **原始差分**. In **算法设置**, select **局部线性拟合** for an optional
least-squares slope over a full-width time window (shown in ns; initial value
50 ns). The velocity and original derivative remain unchanged. Known gaps are
not bridged; fewer than three points produces NaN. **全部结果** restores the
full displayed range after zooming. In Review/Export, the separate **附加局部拟合列**
checkbox adds named fit columns alongside the raw derivative, using the window
shown on that checkbox. Metadata records both methods and their corrections.
See [TASK-034](docs/TASK-034_UI_ACCELERATION.md) for validation and limitations.

See [AGENTS.md](AGENTS.md) for development rules and
[research_TASK19](docs/tasks/research_TASK19/README.md) for the workstation change.
Manual release entry points live in [scripts/build](scripts/build/). Build from a clean
commit in the Production Python environment. Use a new `build/<name>/` directory for
intermediates. The Windows onefile builder verifies startup and the GUI workflow on
the supplied local waveform before publishing the versioned x64 EXE in `release/`.

```powershell
python scripts/build/build_production_release.py --onefile --output-root build/windows_release --analysis-smoke-input data/raw/20260607.csv
```

The macOS build gate requires an explicit approved input and its matching Windows numerical
reference. The hosted macOS workflow runs the portable tests without those inputs.
Run `python scripts/maintenance/check_repo_hygiene.py --strict` to inspect the
checkout and Git index without modifying them.
