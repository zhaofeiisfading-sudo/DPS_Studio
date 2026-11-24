# PDV Studio 0.2.1

Release notes for the PDV Studio 0.2.1 Windows release:

- **Unified 5-file export bundle (CLI & Desktop GUI)**: Exports `velocity_raw.csv`, `velocity_gated.csv`, `velocity_display.csv`, `run_summary.json`, and `spectrogram_ridge.png`, retiring legacy `*_detail.csv` and keeping acceleration export opt-in.
- **OriginPro-friendly CSVs and derived display curve**: Non-finite/missing cells export as empty strings (`""`) rather than `"nan"` on the full uniform time grid; `velocity_display.csv` applies endpoint-preserving 3-frame smoothing, short-gap bridging (`<= 5` frames), and traceable pre-event display handling.
- **Smarter CLI defaults (`--auto-columns` & auto low-frequency band retry)**: Automatically detects `.csv`/`.dat` delimiters, headers, and 1–3 voltage channels with `--auto-columns`, and performs single-bundle stepped low-frequency band retry (`[0.20, 0.35, 0.50]` GHz) when boundary peaks suppress formal pass rate.
- **Desktop multi-channel export & one-click launchers**: Desktop review/export defaults to combined multi-channel export (`全部通道（合并导出）`), and two drag-and-drop Windows `.bat` launchers are shipped under `launchers/`.
