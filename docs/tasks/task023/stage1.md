# TASK-023 Stage 1 verification

The Production shell has four inspector pages with pinned actions and a light workflow strip. Guided ridge re-entry opens the spectrogram for boundary editing. Direct tab changes select the corresponding inspector and leave export preview when the user leaves Review. File drops reuse the existing import settings dialog and worker.

## Verification

The project Python 3.12 environment ran the checks below from the Production checkout on `main` at base `5ae3479`.

| Check | Result |
| --- | --- |
| Ruff on `src/dps_studio/gui` | All checks passed |
| Strict mypy on `src` | Success, 95 source files |
| Full `tests/unit/gui` | 156 passed in 76.48 s |
| Ruff on the new regression module | All checks passed |
| Real-data release workflow smoke | Passed as part of the full GUI suite, including input hash and plotted/exported acceleration agreement |
| Semantic navigation regression | Passed with the existing `transitions == [3]` assertion |
| English catalog | 731 finished translations, 0 unfinished. All 14 newly used MainWindow source strings have English entries. GUI source scan found 0 dynamic `tr()` arguments. |
| Raw files | All 24 paths and SHA-256 hashes matched `artifacts/task023/baseline/raw_sha256.json` |
| Strict repository hygiene | Exit 1. The before and after checks both found five historical release ZIPs under `build/`. Both reported zero unexpected root entries, tracked generated files, duplicate packages and raw copies under artifacts. |

One earlier full-suite run exited with Windows access violation `0xC0000005` during pyqtgraph ROI handle creation in `test_guided_channels_are_independent_and_runs_target_displayed_channel`. The test passed in isolation in 0.64 s and in the complete rerun. The cause was not established. The stack trace is in `artifacts/task023/pytest_stage1.log` and the passing run is in `artifacts/task023/pytest_stage1_repeat.log`.

## Layout and interaction

Native Windows checks at 900×570 and 1024×640 showed all four steps on one row in English and Chinese. At the smaller size the navigation viewport was 868 logical pixels wide. The last step ended at x = 603 in English and x = 412 in Chinese (exclusive right edges). A separate offscreen regression checks every step rectangle and pinned action at both sizes. The native 900×570 English velocity page placed wavelength, window material and observation angle at the same right edge, x = 337 within the inspector.

The four new GUI cases cover both locales, manual and automatic ridge re-entry, pinned actions, review preview exit, import confirmation and cancellation, unsupported drops, export directory opening and the four-file acceleration export receipt. Screenshots of the native shell and loaded inspector pages are under `artifacts/task023/figures/native_*.png`.

## Changed files

- `src/dps_studio/gui/icons.py` and `inspector_widgets.py` provide vector icons, cards, collapsible sections and banners.
- `src/dps_studio/gui/main_window.py`, `styles.py`, `workstation.py`, `analysis_range.py` and `window_preset_editor.py` implement the shell, layout and state changes.
- `src/dps_studio/gui/translations/pdv_studio_en.ts` and `pdv_studio_en.qm` contain the English source and runtime catalog.
- `tests/unit/gui/test_task023_inspector.py` contains the new regressions.
- `docs/tasks/task023/stage1.md` records this verification. Local logs, screenshots, test outputs and caches are under `artifacts/task023/`.
