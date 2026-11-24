# TASK-036 Stage 1 — Localized runtime storage

Source-mode storage defaults to `artifacts/userdata/`. Frozen storage defaults to `userdata/` next to the executable. An explicit root takes precedence over `PDV_STUDIO_USERDATA_DIR`, which takes precedence over either default. Application resources still resolve through the existing resource helpers.

Startup creates `config/`, `materials/`, `presets/`, `cache/`, `logs/`, and `temp/`. It probes write access to the root and config directory. If storage initialization fails, ordinary GUI startup reports the path and exits with code 2. Qt uses `config/settings.ini` for language and layout preferences, and the window preset editor uses `materials/window_presets.json`. Matplotlib configuration targets `cache/matplotlib/`. Ordinary frozen startup also redirects Python and process temp paths.

With no environment override, both smoke entry points use `userdata/` under the report directory for runtime storage. Their existing report-local `layout.ini` and window preset JSON continue to support isolated verification and restart checks.

## Verification

| Check | Result |
| --- | --- |
| `ruff check src tests` | Passed |
| `mypy --strict src/dps_studio` | Passed for 96 source files |
| Targeted pytest for runtime paths, acceleration presets, and release workflow smoke | 30 passed, including real-waveform plot and export comparisons and an input hash check |
| Offscreen Qt source smoke | Confirmed language and layout persistence in the same INI, both Qt settings scopes under the selected config directory, and report-local storage through both smoke entry points |
| Repository hygiene before and after | Zero unexpected root entries, tracked generated files, or raw copies in artifacts. Five pre-existing package placement entries in both inventories |

Unit tests covered frozen path selection and process temp redirection. The offscreen smoke checks used source mode with the Windows DLL inventory call stubbed. Evidence is under `artifacts/task036/`.

Production Git HEAD and the index matched preflight. Runtime and GUI changes are confined to the requested modules, with regression tests and task records alongside them.
