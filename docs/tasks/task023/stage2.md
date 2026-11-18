# Production TASK-023 Stage 2 sign-off

Stage 2 polish passed on Windows in the Production `main` checkout at `5ae3479`. The window, test, and translation changes are local.

## Visual verification

- At 1366×768 and 1440×900, both locales show the full captions for `全部通道` or `All channels`, `pdv_channel_1`, `Viridis`, and the acceleration method, including `Direct Dechirp`. The English ridge inspector also shows `Continuity-assisted`. The capture script checked each visible `PlotSelector` against the text Qt paints. [Native screenshots](../../../artifacts/task023/figures/stage2_polish/)
- Plot actions have bordered secondary-button styling. Native tests confirmed labeled acceleration actions and a single-line crosshair readout at 1280, 1366 and 1440 logical pixels. The toolbar reduces readout spacing before wrapping it, and the 900×570 and 1024×640 tests verify that the acceleration controls stay within the toolbar and do not overlap. [English Dechirp at 1366×768](../../../artifacts/task023/figures/stage2_polish/en/1366x768/09_dechirp.png)
- The ridge footer shows the full quality and working-point source counts, including `STRONGEST_REFINED_FALLBACK`. The spectrogram definition wraps, and the import column summary shows a chevron that updates with its expanded state. [Narrow ridge](../../../artifacts/task023/figures/stage2_polish/en/900x570/05_ridge.png) · [Expanded column summary](../../../artifacts/task023/figures/stage2_polish/en/1366x768/02b_column_summary.png)

The evidence contains 60 PNGs across the two locales and three client sizes, including welcome, import, raw signal, spectrogram, ridge, velocity, acceleration, comparison and Dechirp. The 1366×768 and 900×570 images use Windows client-area capture. The frameless 1440×900 client uses a widget capture on the same native Windows platform to include the full client beyond the taskbar work area. PNGs retain the display's 2× pixel ratio.

## ROI lifecycle

Closing or clearing the spectrogram while editing could call `cancel_drawing()` and construct another `PolyLineROI` just before the plot discarded it. The controller now restores the confirmed constraint without rebuilding the retiring overlay. It cancels pending refreshes, disconnects ROI and fill signals, clears the retiring ROI's hover and drag targets, and defers QObject deletion. Drag callbacks update the constraint immediately and defer overlay reconstruction until the mouse event returns. The crosshair filter checks that its graphics and label are still valid during hide events.

The focused regression closes out a draft with a queued overlay refresh and checks that the old ROI is destroyed. Native mouse checks passed for waveform boundary drag, spectrogram frequency and time boundary drags, rectangle drag, and manual corridor clicks. The historical access violation's exact native cause remains unconfirmed. [Native mouse log](../../../artifacts/task023/native_stage2_polish_mouse.log)

## Verification results

| Check | Result |
| --- | --- |
| Ruff on `src`, `tests`, `scripts/build` and `scripts/maintenance` | Passed |
| Strict mypy on `src` and the three specified GUI test modules | 0 errors across 99 source files |
| Full GUI suite, run 1 | 164 passed in 102.10 s, exit code 0 |
| Full GUI suite, run 2 | 164 passed in 97.54 s, exit code 0 |
| Native Windows desktop regression | 2 passed, both locales |
| Qt English catalog | `pyside6-lupdate` found 584 existing GUI sources and 0 new sources. `pyside6-lrelease` compiled 749 finished translations and 0 unfinished. |
| Real-data workflow | `20260607.csv` produced 310 finite Dechirp estimates across 620 frames. Each capture compared the displayed Y array with the fit output after conversion to `10⁹ m/s²`. The full GUI suite also passed its existing scientific display and export regressions. |
| Raw data and repository | All 24 raw paths and SHA-256 hashes matched the before-run and Stage 2 snapshots. The protected source and configuration paths had a clean Git status, and the index was empty. |
| Repository hygiene | Exit code 0. The before and after checks found the same 39 historical cache directories and five release archives under `build/`, with zero unexpected root entries, tracked generated files, duplicate packages, or raw copies under `artifacts/`. |

Both complete GUI runs used `D:\miniconda3\envs\dps-studio\python.exe -B` and finished without `0xC0000005`. [Run 1](../../../artifacts/task023/pytest_stage2_polish_1.log) · [Run 2](../../../artifacts/task023/pytest_stage2_polish_2.log) · [Ruff](../../../artifacts/task023/ruff_stage2_polish.log) · [Mypy](../../../artifacts/task023/mypy_stage2_polish.log) · [Hygiene](../../../artifacts/task023/hygiene_stage2_polish.log)

## Files changed in this pass

- `src/dps_studio/gui/plot_chrome.py`, `styles.py`, and `acceleration_view.py` size selectors against Qt's text field, adapt toolbar spacing and the crosshair HUD, style actions, and space the acceleration settings grid.
- `src/dps_studio/gui/result_views.py`, `import_dialog.py`, and `ridge_corridor.py` wrap plot footers, style the column-summary toggle, and manage overlay teardown.
- `src/dps_studio/gui/translations/pdv_studio_en.ts` and `.qm` use the shorter English acceleration captions `Settings` and `Fit Y`. The fit action's tooltip describes the visible time range.
- `tests/unit/gui/test_task023_plot_workspace.py`, `test_task023_inspector.py`, and `conftest.py` cover the regressions, dispose their window trees, and route Qt test settings to the test temp directory.
