# Production TASK-023 Stage 3

Production `main` was verified at base `5ae3479dccd4d1c1c563edf64a5bca61d7430704` with the Stage 1–2 changes present. The version is `0.2.0`. [Chinese release notes](../../RELEASE_NOTES_0.2.0.md)

## Windows onedir release

`--onedir-folder` requires native Windows x64 and an analysis input. The builder checks that the target is absent, then uses the existing onedir spec. It adds the runtime guide, release notes and build provenance before verifying the collected folder.

The verifier copies the input to a temporary directory outside the repository and Python environment. It checks native startup and real-data analysis, then runs the GUI workflow and requires the Dechirp plot/export comparison and icon check to pass. File paths and SHA-256 hashes must match before and after execution. After a second clean-commit check, the builder moves the verified folder into `release/PDV_Studio_v0.2.0_Windows_x64/` and writes `release_manifest.json` to the build output directory. The onedir path publishes one folder, including the EXE and `_internal/`.

## Preparation checks

| Check | Result |
| --- | --- |
| Ruff on `src`, `tests`, `scripts/build` and `scripts/maintenance` | Passed. [Log](../../../artifacts/task023/logs/stage3_ruff.log) |
| Strict mypy on `src` and the three requested GUI test files | 99 source files passed. [Log](../../../artifacts/task023/logs/stage3_mypy.log) |
| Full pytest suite | 841 passed in 141.06 s. This includes the About dialog and real-data release analysis/export version checks, and mocked release tests for argument validation, publication, GUI gates and changes to package files. [Log](../../../artifacts/task023/logs/stage3_pytest.log) |
| Windows spec and version source | Stubbed build constructors confirmed file/product version `0.2.0`, onedir collection name `PDV_Studio_v0.2.0` and the shared `release_smoke.py` version. Searches of maintained source, build inputs and tests found no hardcoded `0.1.7`. [Log](../../../artifacts/task023/logs/stage3_version.log) |
| English translations | Qt extraction found 584 existing sources and 0 new ones. Recompiling the maintained catalog produced 749 finished and 0 unfinished entries. The compiled QM matched the existing file byte for byte. [Extraction](../../../artifacts/task023/logs/stage3_lupdate.log) · [Compilation](../../../artifacts/task023/logs/stage3_lrelease.log) |
| Git and raw data | The index was empty. All 24 raw paths and SHA-256 hashes matched the TASK-023 baseline. Core, configuration and `AGENTS.md` had no Git changes. [Raw hashes](../../../artifacts/task023/logs/stage3_raw_sha256.json) |

The repository hygiene check exited 0 with zero unexpected root entries, tracked generated files, duplicate packages and raw copies under artifacts. Strict mode exited 1 before and after because of the same five historical ZIPs under `build/`. A simulated onedir layout produced zero misplaced or duplicate packages. The nested `PDV Studio.exe` is outside the standalone package naming rule, and the large-file threshold only adds entries to the inventory. [Baseline](../../../artifacts/task023/logs/stage3_hygiene_before.log) · [Final check](../../../artifacts/task023/logs/stage3_hygiene_after.log) · [Strict check](../../../artifacts/task023/logs/stage3_hygiene_after_strict.log) · [Onedir fixture](../../../artifacts/task023/logs/stage3_onedir_hygiene_fixture.log)

The ZIP integrity fixtures use a synthetic project and extraction area inside pytest's task temp tree. This keeps their file-set and hash assertions independent of the host temp location.

## Build handoff

Gemini can run the following from Production after reviewing and committing the changes. Run from a Windows desktop session with the system temp directory outside the checkout and the Python environment.

```powershell
& 'D:/miniconda3/envs/dps-studio/python.exe' -B scripts/build/build_production_release.py `
  --onedir-folder --output-root build/task023_windows_x64 `
  --analysis-smoke-input data/raw/20260607.csv
```

Stage 3 preparation ended before any commit or PyInstaller run. The physical release folder and frozen-executable verification remain pending the build.
