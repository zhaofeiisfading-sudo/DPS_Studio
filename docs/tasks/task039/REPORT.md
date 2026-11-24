# TASK-039 Software updates and user feedback

Implemented both Help menu workflows in Production on `main` at `c03edbb639f0e8652f873563e06b6a6426ebf10d`.

## Update workflow

- The Releases API request uses the coordinates verified against `origin`. Numeric comparison selects the highest formal release targeting `main`. Startup checks run asynchronously and show an action in the status bar when a newer version exists.
- Downloads require HTTPS on an approved GitHub host at every hop and an authoritative SHA-256 from the API digest or matching checksum asset. The updater reuses verified installers from `userdata/cache/updates/<version>`, serializes competing transfers for that version, and promotes a partial file only after verification.
- Setup starts after confirmation and a fresh hash check. The frozen launcher requests the exact current installation directory and per-user mode. The existing Inno configuration already defaults to per-user installation and excludes userdata from packaged file replacement. [Inno Setup command-line parameters](https://jrsoftware.org/inno-setup/documentation/topic_setupcmdline.htm)

## Feedback workflow

- Users can prepare a GitHub issue draft or copy Markdown for offline use. The diagnostics checkbox starts off and includes only the five documented fields when enabled. Long drafts use the clipboard and a title-only link.
- The URL helper supports prefilled category labels. The public dialog puts the category in the Markdown body so users without repository label permissions can open the draft. The live repository has Issues enabled and currently has `bug` and `enhancement` labels. [GitHub issue query parameters](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue#creating-an-issue-from-a-url-query)

## Changed files

| Change | Paths |
| --- | --- |
| New services | `src/dps_studio/updates.py`, `src/dps_studio/feedback.py` |
| New dialogs | `src/dps_studio/gui/update_dialog.py`, `src/dps_studio/gui/feedback_dialog.py` |
| GUI integration | `src/dps_studio/gui/main_window.py` |
| English translations | `src/dps_studio/gui/translations/pdv_studio_en.ts`, `src/dps_studio/gui/translations/pdv_studio_en.qm` |
| New regressions | `tests/unit/test_updates.py`, `tests/unit/test_feedback.py`, `tests/unit/gui/test_update_and_feedback_dialogs.py` |
| Closeout | `docs/tasks/task039/REPORT.md`, `D:/Research/Notes/05项目/dps/2026-11-21_TASK-039_软件更新与意见反馈.md` |

## Verification

| Check | Result |
| --- | --- |
| Ruff for `src` and `tests` | Passed |
| Strict mypy | Passed for 102 source files |
| TASK-039 pytest | 88 passed (61 update service, 7 feedback service, 20 GUI) |
| Full pytest | 1,028 passed, including existing GUI, CLI, runtime-path and real-data tests. The final button styling was verified in the focused GUI run. |
| Small-screen geometry at 200% Qt scaling | 2 passed, one per language. Reviewed both dialogs at 2× with the Windows UI font loaded into the offscreen Qt process. |
| English translation resource | Qt lrelease compiled 796 finished catalog entries. Every new dialog string has an English translation. |
| Packaging and CLI | PyInstaller's module graph for `packaging/pdv_studio.spec` reaches all four modules from the GUI entry and includes the Qt translation resource. The CLI module graph excludes them and the GUI package. A fresh CLI `--version` process loaded neither GUI nor Qt. |
| Live GitHub check | The Releases request succeeded and returned no qualifying formal release at verification time. Download and installer invocation were exercised with fixtures. |

Test logs, 2× layout captures, and the repository hygiene inventory are under `artifacts/task039/`. Stage 2 covers the official installer build, release publication, and a packaged in-place upgrade with an authoritative installer checksum.

The 24 raw files matched their baseline hashes. Of the 33 files with prior TASK-036–038 work, 32 matched byte for byte. The prior settings-path edit in `main_window.py` was retained alongside the new menu and worker integration. The protected source and documentation paths and Git index had zero changes.

Strict hygiene exited with the same five historical ZIPs in `build/` reported during preflight. The final scan reported zero unexpected root items, generated index entries, duplicate packages, and raw copies in task artifacts. See `artifacts/task039/codex_hygiene_final.json`.
