# PDV Studio 0.1.6

- Optional local linear acceleration estimate with a time window in ns. Raw
  finite differences remain the default; velocity reconstruction is unchanged.
- Optional fit columns in acceleration CSV, with method/window/source metadata.
- Acceleration zoom survives correction-parameter refresh; full range remains
  available. Empty estimates show the computed-point count.
- Shorter Chinese/English notices, compact dv/dt axis, wrapped material forms
  and event candidate rows for narrow sidebars.
- Constant-offset and boundary-roundoff safeguards for the optional estimator.

Local fitting can suppress, broaden or move short features; it is not a new
time resolution or a validated physical acceleration. Known gaps remain NaN.
The 50 ns initial window is a user-adjustable display choice, not calibration.

## Original Windows ZIP

Extract the entire directory and keep `_internal`
next to `PDV Studio.exe`. Existing releases and user presets are retained.
Local build provenance and runtime results are in the release manifest.
Remote versions were not checked; no online release or macOS build was made.

## Windows x64 独立版

`PDV_Studio_v0.1.6_Windows_x64.exe` 是本地发布的单文件版，包含 TASK-019 GUI
和 research_task21 独立加速度页。加速度页提供速度差分与 Dechirp，导出可包含各自的
结果与 metadata。旧版 `PDV_Studio_v0.1.6.zip` 对应更早的构建。
