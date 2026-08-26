# DPS Studio Research Worktree

`DPS_Studio_TASK021A` is the Research worktree for TASK-021A Global Candidate-Path Ridge Tracking. The Production worktree is `DPS_Studio`.

Use [run_research_global_path.bat](run_research_global_path.bat) as the main real-data Research entry point. With no arguments it opens a file picker for raw data, creates a timestamped `run_*_<source>/00_RESULT_SUMMARY` directory under `artifacts/task021a_global_path/`, and writes candidate-path figures plus CSV/JSON comparisons. It never runs the A-H synthetic benchmark implicitly. The launcher uses the `dps-studio` Conda environment while forcing this worktree's `src` directory ahead of any installed package.

To run the synthetic evidence independently, invoke `scripts/run_task021a_global_path_research.py --mode benchmark --output-directory <new-empty-directory>` with the Research `src` directory first on `PYTHONPATH`. The real-data mode is the default and requires `--raw-data <selected-file>`.

Use [run_research_gui.bat](run_research_gui.bat) only for the existing Research-worktree GUI. The GUI does not integrate Global Path; Global Path remains an opt-in research script/API. The legacy `run_pdv_studio_gui.bat` entry point displays the same warning and delegates to this safe GUI launcher.

Do not use Production-worktree launchers to test Research algorithms. Do not modify `data/raw`; `artifacts` are reproducible Research outputs and remain untracked.
