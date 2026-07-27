# DPS Studio

PDV/DPS signal analysis software.

Formal production entry point:

```powershell
D:\miniconda3\envs\dps-studio\python.exe scripts\run_demo_pipeline.py --config configs\demo_dual_profile.toml
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
