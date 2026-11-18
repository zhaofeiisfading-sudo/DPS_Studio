# Dropdown styling and Windows Research release verification

Final scope: Round 2 polish of the audited dropdown implementation.
Date: 2026-11-13; implementation: Codex; lead: Gemini.
Repository: `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`.
Branch: `codex/research_2/global-path-ridge-v2`.
HEAD: `4eeed35a9e8bea63ba57ba46fdd85f90f92bb729` (unchanged; no commit).

## Final implementation

`src/dps_studio/gui/styles.py` centrally supplies combo/menu QSS, paired light
palette roles, a view-owned popup delegate, automatic configuration of existing
and rebuilt controls, and screen-bounded popup widths. Invalid combo borders in
`main_window.py` remain selector-scoped, and existing interaction-style contracts
are preserved. Scientific code and defaults are unchanged.

Round 2 adds the following:

- A popup row is enabled only when both the paint option's `State_Enabled` and
  the model's `ItemIsEnabled` flag are set. Either disabled condition produces
  white background, `#8a98a3` text, no active fill and no focus bar.
- Closed focus remains white; open combo buttons use `#f4f9fd`, with the accent
  border retained in both states.
- `HoverEnter` immediately resolves the entered model index.
- Wheel bursts schedule one zero-delay update after Qt scrolls. It resolves
  `view.indexAt(viewport.mapFromGlobal(QCursor.pos()))` only inside the viewport,
  clears stale hover outside it, and repaints without synthesizing MouseMove.
- The deferred callback uses the viewport as its QObject context. RuntimeError
  guards handle stale/deleted wrappers in the callback and application event
  filter. This uses Qt's documented [QTimer context overload](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTimer.html).

Round 2 edits `styles.py` and `tests/unit/gui/test_dropdown_styles.py`, and moves
`docs/maintenance/dropdown_styles_round1.md` to this record. The previously
audited changes in `main_window.py`, `scripts/build/build_windows.ps1`,
`scripts/dev/check_gui.py`, and `tests/unit/test_gui_runner.py` are preserved.

## Verification commands and results

Python 3.12.13: `D:\miniconda3\envs\dps-studio\python.exe`; Qt/PySide6 6.11.1.
Source commands use `scripts/dev/run.ps1 -Task DEV`, with bytecode disabled and
all caches/test outputs under `artifacts/DEV/tmp/`. Evidence for this round is
`artifacts/DEV/tmp/dropdown-verification/r2/`.

```powershell
pwsh -File scripts/dev/run.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe -m ruff check src scripts tests
pwsh -File scripts/dev/run.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe -m mypy src/dps_studio/core src/dps_studio/gui
$env:QT_QPA_PLATFORM='offscreen'
pwsh -File scripts/dev/run.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe -m pytest tests/unit/gui/test_dropdown_styles.py -q --junitxml=artifacts/DEV/tmp/dropdown-verification/r2/dropdown-offscreen.xml
$env:QT_QPA_PLATFORM='windows'
pwsh -File scripts/dev/run.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe -m pytest tests/unit/gui/test_dropdown_styles.py -q --junitxml=artifacts/DEV/tmp/dropdown-verification/r2/dropdown-windows.xml
pwsh -File scripts/dev/run.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe -m pytest tests/unit/test_gui_runner.py tests/unit/test_repo_hygiene.py -q --junitxml=artifacts/DEV/tmp/dropdown-verification/r2/unit-maintenance.xml
pwsh -File scripts/dev/run.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe scripts/dev/check_gui.py --timeout-seconds 60
D:\miniconda3\envs\dps-studio\python.exe -B scripts/maintenance/check_repo_hygiene.py --json
```

| Verification | Result | Exit |
|---|---|---:|
| Ruff, `src scripts tests` | All checks passed | 0 |
| Strict mypy, core and GUI | 94 files, no issues | 0 |
| Dropdown tests, offscreen | 30 passed; no failures/errors/skips | 0 |
| Dropdown tests, native Windows | 30 passed; no failures/errors/skips | 0 |
| GUI runner and repository hygiene unit tests | 14 passed | 0 |
| Complete GUI run, all 26 modules | 210 passed; zero failures/errors/skips | 0 |
| Repository hygiene | `findings: []` | 0 |

The dropdown module now has 13 additional parameterized cases. It covers
HoverEnter without a preceding MouseMove, cleared option-enabled state on an
enabled model item, stationary-cursor wheel scrolling with rendered-pixel
checks, and abrupt C++ widget destruction before deferred delivery. Existing
coverage includes selected/hover/disabled/focus colors, keyboard navigation,
menus, dynamic table widgets, style idempotence, validation borders, and long
Chinese/English options at 1024x640, 1280x720 and 1366x768.

Tests exercise Fusion and Windows 11 styles under Light and Dark Qt schemes
on both Qt backends. Enabled row colors have at least 7:1 contrast; muted
disabled text has at least 2.5:1. Highlighted rows contain no pure-white blocks.
Native Windows screenshots were inspected for readable Chinese/Latin text.
The full runner preserves module timeout attempts and isolates their cases;
assertion failures and individual case timeouts remain failures.
The final run used 51 processes: 25 successful module runs and 26 isolated
cases from `test_task012_workspaces` after its 60-second module timeout.
The timeout log and attempts JSON remain alongside the final passing results.

## Final standalone Windows package

```powershell
pwsh -File scripts/build/build_windows.ps1 -Task DEV -Python D:\miniconda3\envs\dps-studio\python.exe -DistDirectory artifacts/DEV/tmp/release_dist -WorkDirectory artifacts/DEV/tmp/build_work
pwsh -File artifacts/DEV/tmp/dropdown-verification/r2/verify_release.ps1
```

Both commands returned 0. The official `scripts/build/specs/pdv_research.spec`
was used without modification. Build DLL lookup stays local to the selected
Python environment; no dependency installation or system PATH change occurred.

Release: `release/PDV_Studio_Research_0.1.0_Windows_x64/`.
Its direct contents are `PDV Studio Research.exe`, `_internal/` and
`RELEASE_NOTES.txt`. Total: 453 files, 241,014,894 bytes; unsigned.
Required Python/Qt runtimes, Windows Qt plugin, `chevron_down.svg`,
`pdv_studio.ico`, `pdv_studio_en.qm` and default TOML are present.

EXE SHA-256:
`1DE40C9DD602BF125C4F2627285951DC91B59D646494000D209977A4C8E9AEEB`.

| New EXE smoke test | Result | Exit | Captured DLL paths |
|---|---|---:|---:|
| `--startup-smoke-test .../r2/startup/report.json` | Windows event loop/window entered; version 0.1.0 | 0 | 218 |
| `--workflow-smoke-test .../r2/workflow-zh/report.json --workflow-input .../r2/workflow-input.csv --workflow-language zh_CN --workflow-width 1366 --workflow-height 768` | Full workflow; input unchanged | 0 | 266 |
| `--workflow-smoke-test .../r2/workflow-en/report.json --workflow-input .../r2/workflow-input.csv --workflow-language en --workflow-width 1024 --workflow-height 640` | Full workflow; input unchanged | 0 | 266 |

Verification runs from the final release directory with isolated settings,
empty PYTHONPATH/PYTHONHOME and Windows-only PATH. All 11 reported Python/Qt
runtime paths are inside the final release. DLL audits found zero Production
or site-packages paths. Smoke JSON, exact launch arguments, native module
inventories, required-resource hashes, screenshots and the complete release
SHA-256 manifest are retained in the Round 2 evidence directory.

## Repository boundary and handoff

All 168 protected files match their Round 2 starting SHA-256 values. The final
comparison and Git snapshot are retained as `protected-after.json` and
`git-status-final.txt` in the Round 2 evidence directory. The index remains empty.
`AGENTS.md` and `.agents/skills/repo-hygiene/SKILL.md` retain their pre-existing
changes. Core, algorithms, research, configs and raw files remain untouched.
No Production write, new task ID, external Obsidian write, dependency
installation, commit, push, merge or worktree cleanup was performed.

Two current Round 2 build directories remain for Gemini to clean before commit:

- `artifacts/DEV/tmp/release_dist/`
- `artifacts/DEV/tmp/build_work/`

Their exact paths and file counts are in `r2/cleanup-targets.json`. The final
release and verification evidence are separate.

Status: Round 2 source, all 210 GUI cases, packaged release and repository
closeout verified. Temporary build scratch awaits Gemini cleanup; commit awaits
separate approval.

