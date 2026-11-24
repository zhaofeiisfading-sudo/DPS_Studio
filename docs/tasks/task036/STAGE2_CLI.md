# TASK-036 Stage 2 · Production CLI and agent skill

The `pdv` and `dps-studio` console scripts and `python -m dps_studio` use the same entry point. `inspect` reports a delimited-file preview and verifies the source SHA-256. `analyze` requires seven explicit experimental inputs and accepts JSON, TOML, and command-line overrides. `batch` processes files in sorted order, retains successes when individual files fail, and records each outcome.

The CLI uses the Production signal loader, STFT, automatic ridge and quality workflow, event display configuration, and formal exporter. Resolved analysis boundaries and relative output paths are recorded in `metadata.json`. The CLI stages the report and figures before publishing files with exclusive creation. Output under `data/raw/` is rejected. When acceleration is disabled, the CSV is omitted and the PNG indicates the setting. The agent skill documents the required researcher confirmations and how to interpret low-quality frames.

## Verification

| Check | Result |
| --- | --- |
| Ruff and strict mypy | Passed. Mypy checked 98 source files. |
| Targeted pytest for package, CLI, and runtime paths | 61 passed. |
| CLI and `AnalysisSession` parity | On two synthetic channels with distinct voltage units, LiF correction, a manual reference, an analysis interval, a clamped frequency band, and a local acceleration fit, the simple, detail, and acceleration CSV files matched byte for byte. |
| Qt PNG output | Visually checked the four offscreen figures after fixing the Windows font fallback. Tested app lifetime and rendering with a pre-existing `QCoreApplication`. For a core-only application, axis labels and bounds are retained in PNG metadata. |
| Agent skill | Frontmatter validator passed. |
| Repository hygiene | Zero unexpected root entries, tracked generated files, or raw copies under artifacts. The five historical package placement entries were present at preflight. |

The repository fixture `tests/fixtures/test.csv` has an OLE workbook signature. Its regression test expects the delimited preview to reject it and checks its unchanged SHA-256. Text CSV, tab-delimited DAT, and mixed-whitespace DAT fixtures cover successful inspection. The test outputs are under `artifacts/task036/tmp/pytest_stage2/`. Frozen-mode coverage is limited to runtime-path simulation.

The Git HEAD and index matched preflight. Existing Stage 1 edits were preserved. Validation used synthetic waveforms, with no access to Production raw files.
