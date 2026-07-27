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
`simple_exports/` directory. Each simple export has exactly `time_s` and the
formal quality-gated `apparent_velocity_m_s`; all STFT frames and NaN gaps are
retained. The complete 42-column per-frame table remains available as
`apparent_velocity_diagnostics.csv` and the compatibility filename
`apparent_velocity.csv`. `outputs/LATEST_RUN.txt` is updated only after a
complete successful formal run.

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
