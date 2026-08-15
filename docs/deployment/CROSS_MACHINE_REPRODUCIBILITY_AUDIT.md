# DPS Studio Cross-Machine Reproducibility Audit

_Audit date: 2026-08-15. Scope: tracked repository on Windows 10/11 x64; raw data and scientific algorithms were not changed._

---

## 🔎 1. Current deployment architecture

`environment.yml` creates the Conda Python environment; `python -m pip install -e .` installs DPS Studio and its runtime packages from `pyproject.toml`; `python -m dps_studio.gui` starts the GUI.

```mermaid
flowchart LR
    accTitle: DPS Studio Windows Installation
    accDescr: A repository folder supplies the Conda environment definition and package metadata before the user launches the GUI.
    repository([Repository folder]) --> conda_env[Create Python environment]
    conda_env --> install_package[Install DPS Studio]
    install_package --> launch_gui([Launch GUI])
    classDef process fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    classDef success fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d
    class conda_env,install_package process
    class launch_gui success
```

## 🔎 2. Conda, pip, and pyproject responsibilities

| Layer | Responsibility |
| --- | --- |
| Conda | Isolated Python 3.12 interpreter and pip |
| pip/Hatch | DPS Studio and direct Python dependencies |
| Package | GUI and scientific application code |

Environment creation and application installation are separate, required steps.

## 🔎 3. environment.yml audit

Name: `dps-studio`; channel: `conda-forge`; Conda packages: `python=3.12`, `pip`; pip subsection: none. The file is deliberately small and cannot independently run DPS Studio: `pyproject.toml` supplies application dependencies after editable installation. It fixes Python minor version, not patch-level history.

## 🔎 4. pyproject.toml audit

Build backend: `hatchling>=1.25`. Runtime dependencies: NumPy, SciPy, pandas, matplotlib, PySide6, pyqtgraph, pydantic. Dev-only: pytest, Ruff, mypy, PyInstaller; normal GUI users do not need them. `dps-studio` is a version-only CLI, so the GUI command is `python -m dps_studio.gui`.

## 🔎 5. Current actual environment

Accessible author environment: `D:\miniconda3\envs\dps-studio`; Python 3.12.13; pip 26.1.2; Conda 22.11.1. It is an editable install from this repository.

## 🔎 6. Dependency version comparison

| Package | Current | environment.yml | pyproject.toml | Risk |
| --- | --- | --- | --- | --- |
| Python | 3.12.13 | `=3.12` | `>=3.12,<3.14` | Medium |
| numpy | 2.5.1 | — | `>=1.26` | Medium |
| scipy | 1.18.0 | — | `>=1.13` | Medium |
| pandas | 3.0.3 | — | `>=2.2` | Medium |
| matplotlib | 3.11.0 | — | `>=3.8` | Medium |
| PySide6 | 6.11.1 | — | `>=6.8` | Medium (Qt/DLL) |
| pyqtgraph | 0.14.0 | — | `>=0.13.7` | Low–medium |
| pydantic | 2.13.4 | — | `>=2.7` | Medium |

No direct runtime dependency is missing. Unbounded future major releases are the remaining dependency-drift risk; do not list transitive packages manually.

## 🔎 7. Runtime versus development dependencies

Use `python -m pip install -e .` to run the GUI. Developers add `python -m pip install -e ".[dev]"` for tests, linting, typing, and PyInstaller.

## 🔎 8. Installation flow verification

Existing-environment application import, all runtime imports, and an offscreen GUI-window smoke test passed. A clean `dps-studio-repro-test` creation was attempted but local Conda 22.11.1 stalled during `conda-forge` metadata retrieval; no test environment was created. This host limitation is not a requirement to use that old Conda.

## 🔎 9. GUI startup methods

| Entry point | Status | Use |
| --- | --- | --- |
| `python -m dps_studio.gui` | Smoke-test passed | Recommended |
| `run_pdv_studio_gui.bat` | Updated and text-tested | One-click after setup |
| `python -m dps_studio`, `dps-studio` | Valid | Version-only CLI |
| `run_demo_pipeline.bat` | Updated | Local authorized production data |

## 🔎 10. BAT files and absolute paths

Both BAT files now discover active Conda or standard per-user/all-user Miniconda/Anaconda locations and no longer pin `D:\miniconda3`. They accept `DPS_STUDIO_CONDA_ENV`, defaulting to `dps-studio`. The production BAT is not a public demo: its tracked TOML points to ignored `data/raw/20260607.csv`.

## 🔎 11. Conda environment-name dependency

The package does not inspect the environment name: `dps-test` works after activation. `dps-studio` is a launcher/documentation default only.

## 🔎 12. Miniconda version requirement

Use a current Windows x86_64 Miniconda release, not the author's legacy installer. The project depends on Python and packages, not installer identity. Local Conda 22.11.1 stalled and is not recommended.

## 🔎 13. Git and Download ZIP

`git clone` retains history/provenance. GitHub **Code → Download ZIP** still supports `python -m pip install -e .`, GUI startup, and analysis; it loses Git history only.

## 🔎 14. Path portability

The GUI runs from any ordinary writable location such as `D:\DPS_Studio`; neither D drive nor author path is required. Prefer short paths. The production TOML is repository-relative but references a deliberately local raw file.

## 🔎 15. Windows-specific risks

Likely risks: old/missing Conda, Microsoft Store Python, wrong pip, blocked `conda-forge`, and Qt/DLL platform errors. Use Miniconda Prompt plus `python -m pip`. Chinese paths, spaces, OneDrive, Defender, and long paths are not known code blockers but short local paths simplify support.

## 🔎 16. Clean-environment test result

**Incomplete on this host.** Repeat on a current Miniconda machine before making a clean-machine PASS claim.

## 🔎 17. GUI minimal-loop test

The `PDV Studio` main window was created and shown with `QT_QPA_PLATFORM=offscreen`. Automated tests cover import/analysis workflow. No public example/synthetic CSV is tracked (`data/examples/` and `data/synthetic/` contain only `.gitkeep`), so a clone cannot demonstrate real import→analysis without authorized user data.

## 🔎 18. Recommended formal installation flow

```powershell
conda env create -f environment.yml
conda activate dps-studio
python -m pip install -e .
python -m dps_studio.gui
```

## 🔎 19. Strict historical reproduction

Level A is the normal flow. Level B adds `.[dev]`. Level C should be an intentionally generated Windows x64 lock/spec from a known-good commit; it is optional because exact locks reduce portability.

## 🔎 20. Remaining deployment risks

- No public analysis CSV
- No upper dependency bounds
- Qt/DLL issues are OS-specific
- Production BAT needs authorized local raw data
- ZIP has no Git provenance

## 🔎 21. Changes in this task

Portable BAT discovery, README guidance, launcher tests, and three deployment documents were added. No core algorithm, configuration physics, or raw file was changed.

## 🔎 22. Verification results

| Check | Result |
| --- | --- |
| Environment creation | Incomplete: local old Conda stalled |
| Package/runtime imports | Passed |
| GUI startup | Passed, offscreen |
| Public-data analysis | Blocked: no sample CSV |
| pytest | Full run started; host command window did not retain final summary |
| Ruff | Passed: `All checks passed!` |
| mypy | Passed: 77 source files |

## 🔗 References

[^1]: Conda Documentation. “conda env create.” https://docs.conda.io/projects/conda/en/stable/commands/env/create.html
[^2]: Conda Documentation. “Managing environments.” https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html
