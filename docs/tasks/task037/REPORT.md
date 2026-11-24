# TASK-037 — Windows v0.2.0 Quick-Start Docs & Release Archive

Created concise user and CLI/Agent guides for PDV Studio Windows `0.2.0` and bundled them with the verified Windows x64 installer into a single distribution archive under `release/`.

## Deliverables

| File | Purpose | Size (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| `docs/USER_QUICK_START.md` | 1–2 screen quick-start card for researchers (install, GUI workflow, import, analysis, export, notes) | 4155 | `d1d7e1d3a8f339152bfee4256ac52c33b277a6816712e46b42f077223ac5822d` |
| `docs/README_for_agent.md` | CLI & Agent quick reference (`pdv.exe`, PATH setup & 3 fallbacks, minimal `inspect`/`analyze`/`batch` examples, output layout) | 6040 | `cb9d700387610b446f03ee29b279c43c81f000677880a251c62645f6604bffc3` |
| `docs/INSTALL_FAQ.md` | Short 5-question installation & usage FAQ | 1822 | `6d738d8050d0bea7d992187d0e55814cdbe6491e335285a6d2f5d4e25f738d06` |
| `release/PDV_Studio_v0.2.0_Windows.zip` | Final distribution bundle (`PDV_Studio_v0.2.0/` containing `PDV-Studio-Setup-x64.exe` + the 3 Markdown docs) | 73568658 | `18d2a1f4aab160a634bd6f163abb6d457326652f1b16dce23094be6e1a57867a` |

## Verified Installer & CLI Facts Reflected

- Checked `packaging/pdv_studio_installer.iss` and `packaging/pdv_studio.spec`: `pdv.exe` and `skills/pdv-studio/SKILL.md` are installed by default alongside `PDV Studio.exe` and `_internal/`. Only `Add command-line tool (pdv) to current user PATH` (`addtopath`) and `Create a desktop shortcut` (`desktopicon`) are optional tasks (both unchecked by default).
- Checked `src/dps_studio/cli.py`, `src/dps_studio/cli_config.py`, `src/dps_studio/gui/main_window.py`, `src/dps_studio/gui/import_dialog.py`, `src/dps_studio/gui/raw_signal_view.py`, and `src/dps_studio/runtime_paths.py` so every command flag, config key, GUI label, and `userdata/` path matches Production code.
- Source installer `release/PDV-Studio-Setup-x64.exe` (`74057655` bytes) retained its exact SHA-256 `15a3efc3083b8a79419bd3f86d4003a81b0a92549e86e8c85dc6f9d3a7fef4ca`.

## Verification

- ZIP check (`zipfile.ZipFile.testzip()` and per-member SHA-256 readback): passed with zero errors; all 4 archive members under `PDV_Studio_v0.2.0/` matched their source files byte for byte.
- Repository hygiene (`D:\miniconda3\envs\dps-studio\python.exe -B scripts/maintenance/check_repo_hygiene.py`): `unexpected_root: 0`, `tracked_generated: 0`, `large_tracked: 0`, `duplicate_packages: 0`, `raw_copies_in_artifacts: 0`, `misplaced_packages: 5` (unchanged preflight historical items).
- Preserved all existing Task 036 uncommitted changes, `data/raw/`, `src/`, `configs/`, `packaging/`, `AGENTS.md`, and `.gitignore`; no Git commit or push performed.
