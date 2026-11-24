---
name: pdv-studio
description: Use PDV Studio Production to inspect delimited PDV waveforms, run headless single-file or batch analyses with researcher-confirmed conditions, and interpret the unified 5-file outputs and signal-quality diagnostics.
---

# PDV Studio (v0.2.1)

Run `Get-Command pdv.exe` in PowerShell to locate the CLI on `PATH`. In a standard installation, `<install_dir>\pdv.exe`, `<install_dir>\PDV Studio.exe`, `<install_dir>\launchers\*.bat`, and `<install_dir>\skills\pdv-studio\SKILL.md` are installed together. In a Python environment, `pdv`, `dps-studio`, and `python -m dps_studio` invoke the same CLI. Use `pdv <command> --help` for options.

## 1. Inspect the input

Run `pdv inspect <file>` for a read-only structural preview and SHA-256. Review `column_count`, `delimiter`, `encoding`, `has_header`, and `sample_rows`. Column indices start at zero. Comma, tab, semicolon, and whitespace-delimited `.csv` / `.dat` / `.txt` text files are supported. If the source is an Excel workbook, export it to delimited text while retaining the original.

## 2. Confirm the experiment

Before analysis, confirm `time_unit`, `voltage_units`, `vacuum_wavelength_m`, `measurement_angle_deg`, and `window_material` with the researcher (plus `time_column` and `voltage_columns` unless using `--auto-columns` on a 2–4 column file where col `0` is time and cols `1..N` are `pdv_channel_1..3`). Enter `none` only when the researcher confirms no window correction. Replace every placeholder below with confirmed values before saving `experiment.json`:

```json
{
  "time_column": 0,
  "time_unit": "ns",
  "voltage_columns": {"pdv_channel_1": 1, "pdv_channel_2": 2},
  "voltage_units": {"pdv_channel_1": "mV", "pdv_channel_2": "V"},
  "vacuum_wavelength_m": 1.55e-6,
  "measurement_angle_deg": 0.0,
  "window_material": "LiF"
}
```

Use `measurement_angle_rad` as the config alternative to degrees. A saved window preset or a complete set of `lif_b1`, `lif_b2`, and `lif_reference_wavelength_m` uses the existing Rigg formula.

## 3. Run the analysis

```powershell
# Single file with automatic delimiter, header & 1-3 voltage column mapping (col 0 = time)
pdv analyze "waveforms\shot01.dat" --auto-columns --time-unit s --voltage-units V `
  --wavelength-m 1.55e-6 --angle-deg 0 --window-material LiF --out "results\shot01"

# Single file or directory batch with explicit experiment.json
pdv analyze "waveforms\shot01.csv" --config "experiment.json" --out "results\shot01"
pdv batch "waveforms" --config "experiment.json" --out "results\batch" --pattern "*.csv"
```

Useful optional flags:
- `--time-origin {absolute,event}` and `--event-reference-time-s <seconds>`
- `--no-pre-event-display` (disable pre-event 0 platform in `velocity_display.csv`)
- `--no-auto-band-retry` (disable automatic stepped lower-bound retry `[0.20, 0.35, 0.50]` GHz when default search yields `< 5%` measured due to `peak_at_band_boundary`)
- `--acceleration` (opt-in `acceleration.csv`; acceleration is OFF by default)
- `--full-diagnostics` (opt-in legacy `<tok>_detail.csv`; omitted by default)

If overriding storage with `PDV_STUDIO_USERDATA_DIR`, point it at a separate writable folder — **never** inside the `--out` result directory. Use a fresh non-existing/empty `--out` directory for each run.

## 4. Read the 5 default outputs

Both `pdv analyze` and the desktop GUI export the same 5 files into the result directory (channels are combined column-wise on the full uniform STFT time grid):

- `velocity_raw.csv`: Unfiltered working corrected velocity (`<tok>_raw_velocity_m_s`). Never smoothed or quality-gated.
- `velocity_gated.csv`: Formal quality-gated corrected velocity (`signal_state == measured` and finite). Non-passing frames are written as **empty cells `""`** (never `"nan"`) so OriginPro/Excel import numeric columns cleanly with breaks across gaps.
- `velocity_display.csv`: Ready-to-plot derived curve from measured frames: 3-frame `[1,2,1]/4` interior smoothing preserving segment endpoints, linear bridging across short internal gaps `<= 5` frames only, and traceable pre-event `0` platform (all empty if 0 frames passed).
- `run_summary.json`: Consolidated provenance, source SHA-256, inferred sample rate, `quality` stats, `auto_band_retry` trace, `display_processing` provenance (including `bridged_intervals` and `pre_event_source`), warnings, and `outputs`.
- `spectrogram_ridge.png`: Spectrogram(s) clamped to resolved `[f_min, f_max]` GHz overlaid with dashed `Working ridge` and solid red `Formal gated ridge`, plus measured pass-rate header.

## 5. Review signal quality & warnings

Inspect `run_summary.json` (`quality`, `auto_band_retry`, `warnings`) alongside stdout JSON and `spectrogram_ridge.png` — never assume exit code `0` implies high pass fraction (`stderr` warns if `0` measured frames remain or if inferred sample rate lies outside `[1e8, 1e12]` Hz).

**Iron rules**

- Use PDV Studio's Production CLI/GUI analysis. Never write custom STFT or velocity scripts to replace it.
- Never modify `data/raw/` or use it as an output directory.
- Never upload raw data to an external service.
