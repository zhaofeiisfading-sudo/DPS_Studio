# TASK-021B real-data Global Path calibration

Research-only, development / uncalibrated; no Production configuration was modified.

`calibration_summary.csv` has one row per dataset/profile/channel/K/preset.
`synthetic_regression_summary.csv` has the A–H truth metrics for the same grid.
`cost_audits/` contains full per-state DP records for the balanced K=20 view of every stream.
`00_RESULT_SUMMARY/` contains the comparison tables and key plots.

Candidate-vs-NULL margin is best candidate cumulative cost minus NULL cumulative cost.
A negative margin favors a candidate; a positive margin favors NULL.
Manual event references, when inside an input time range, are plot-only diagnostics.
