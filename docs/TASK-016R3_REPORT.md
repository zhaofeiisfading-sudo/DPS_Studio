# TASK-016R3 Report

## 1. Left workflow hover

`workflowNavigation` is a `QListWidget`. Its selected state is the existing
`QListWidget::item:selected` shared-QSS rule; the light hover feedback remains
the native Windows/Qt item-view behavior (there is no new list-item hover rule).

## 2. Original right-panel feedback

The previous shared `QPushButton` rule only set minimum height and padding, so
ordinary right-panel actions had no unified enabled hover, pressed, focus, or
disabled treatment.

## 3. New hover location

The rules are centralized in `src/dps_studio/gui/styles.py`; no parameter page
uses per-button `setStyleSheet()`.

## 4. Secondary buttons

Enabled `QPushButton` hover uses `#edf0f2` with a restrained neutral border;
pressed uses the slightly deeper `#dfe5e9`. Normal and disabled states are
explicitly retained.

## 5. Primary buttons

Default (primary) buttons remain blue: hover is `#07577f` and pressed is
`#064364`, rather than inheriting the gray secondary hover.

## 6. Pointing cursor

The shared helper applies `PointingHandCursor` to enabled `QPushButton` and
`QToolButton` descendants of the main window, including dynamically-created
event-candidate `QPushButton`s. An enabled-state event filter restores
`ArrowCursor` as soon as an action is disabled.

## 7. Native input cursors

`QComboBox`, `QSpinBox`, `QDoubleSpinBox`, and `QLineEdit` receive no pointer
cursor override. Native Windows/Qt editing, drop-down, and spin-arrow cursor
semantics remain intact.

## 8. Automatic / Guided

No enum, button ID, radio text, button-group mapping, controller/session state,
or run handler changed. `:focus` was added only as a visual rule; existing
checked/unchecked indicator and checked-hover rules remain more explicit than
unchecked hover. The existing TASK-016R2-R switching regression plus the new
initial GUI-state regression keep this mapping covered.

## 9. Left workflow preservation

No `QListWidget` selector or navigation implementation changed. The selected
rule remains `#dceaf4`; no `QListWidget::item:hover` rule was added.

## 10. Language, size, and DPI

Native Windows Qt smoke covered Chinese at 1440×900 and 1280×720; the captured
1280×720 layout remained usable without border-width layout movement. A fresh
English window showed `Automatic` / `Guided` and all checked right-panel button
size hints fit its 340 px panel. The active desktop was DPR 2.0 (not a 125%
DPI session), so 125% was not claimed.

## 11. Modified files

- `src/dps_studio/gui/styles.py`
- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/analysis_range.py`
- `tests/unit/gui/test_task016r3_interaction_styles.py`
- `docs/TASK-016R3_REPORT.md`
- `artifacts/task016r3/`

## 12. pytest

`conda run -n dps-studio python -m pytest` with a fresh independent
`--basetemp` supplied through `PYTEST_ADDOPTS` (forward-slash path): **445
passed**.

## 13. Ruff

`conda run -n dps-studio ruff check .`: passed.

## 14. mypy

`conda run -n dps-studio mypy src`: passed with strict configuration.

## 15. Diff check

`git diff --check`: passed. Git emitted pre-existing permission warnings for
unrelated task-cache directories, but reported no whitespace errors.

## 16. Screenshots and native hover acceptance

The smoke opened a native Windows Qt window, loaded `data/raw/20260607.csv`,
visited Data, Range, STFT, Ridge Automatic, Ridge Guided, and Velocity, and
used real `QCursor.setPos` hover positions verified by `underMouse` before
each capture. Pressed and disabled states were also verified. Evidence:

- `artifacts/task016r3/right_panel_normal_zh.png`
- `artifacts/task016r3/right_panel_hover_zh.png`
- `artifacts/task016r3/right_panel_primary_hover_zh.png`
- `artifacts/task016r3/ridge_mode_hover_zh.png`
- `artifacts/task016r3/layout_1280x720_zh.png`
- `artifacts/task016r3/native_gui_smoke_summary.json`

## 17. Git status

The intended changes are this task's GUI source, GUI test, report, and artifact
directory. The final status also contains one untracked
`CodePython_ProjectsDPS_Studioartifactstask016r3pytest_basetemp_20260804_retry/`
directory created by the failed backslash-form pytest invocation; it contains
only test temporary output and no project source or data. No tracked core,
configuration, script, output, or raw-data file was modified.

## 18. Staged state

`git diff --cached` is empty. No `git add`, commit, or push was performed.

## 19. `data/raw` integrity

Both `git diff -- data/raw` and `git diff --cached -- data/raw` are empty. The
native smoke recorded the same SHA-256 before and after loading
`data/raw/20260607.csv`:
`AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`.
