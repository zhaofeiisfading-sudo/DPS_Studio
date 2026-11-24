# TASK-036 Stage 3 · Windows x64 installer

PDV Studio 0.2.0 was built with Python 3.12.13, PyInstaller 6.21.0, and Inno Setup 6.7.3.
The package contains the x64 GUI and console executables, a shared `_internal/` runtime,
the CLI skill, and third-party license notices and texts. The local build was made with
`--allow-dirty`. The recorded source is `c03edbb639f0e8652f873563e06b6a6426ebf10d-dirty`.

- [Installer](../../../release/PDV-Studio-Setup-x64.exe) · 74,057,655 bytes · Authenticode status `NotSigned`
- [SHA-256 file](../../../release/PDV-Studio-Setup-x64.exe.sha256) · `15a3efc3083b8a79419bd3f86d4003a81b0a92549e86e8c85dc6f9d3a7fef4ca`
- [Release manifest](../../../build/task036_windows_installer/release_manifest.json)
- [Onedir verification](../../../build/task036_windows_installer/onedir_verification/report.json) and [installed verification](../../../build/task036_windows_installer/install_verification/report.json)

| Check | Result |
| --- | --- |
| Frozen onedir | The x64 GUI and console executables started with the isolated runtime environment. The GUI passed at 100%, 125%, 150%, and 200% scaling in Chinese and English, including a full workflow and restart preset recovery. All 491 packaged files retained their SHA-256. |
| Real-waveform export | The balanced profile processed 80,000 samples from a copied `20260607.csv`. The two continuous velocity CSVs matched the GUI and CLI byte for byte, with 620 rows per channel. The CLI also generated metadata, quality data, and all four PNGs. |
| Current-user install | The installer ran on `D:\` in a path containing `中文 空格 安装目录` and created the expected HKCU uninstall registration. Installed CLI and GUI runs populated `userdata/config/settings.ini`, `userdata/materials/window_presets.json`, and `userdata/cache/matplotlib/`. All four AppData snapshots were empty before and after execution. |
| Upgrade and uninstall | The custom setting and `升级保留测试窗口` retained identical file hashes after upgrade and a default silent uninstall. Default uninstall removed the binaries, registry entry, cache, and temp. The reinstall and purge removed the entire test installation directory. |
| Protected directory | Silent setup rejected a fresh path under `C:\Program Files` under a medium-integrity token with exit code 1. Setup left the target path and HKCU uninstall key absent. |
| Tests and hygiene | 102 targeted pytest tests passed. Ruff passed, and strict mypy passed for 98 source files. The staging directory is empty after publication. Hygiene reports zero duplicate packages and the same five misplaced historical ZIPs from preflight. |

The first verification attempt observed Inno Setup's detached uninstall cleanup before it
finished. The build now waits for removal to complete, and the full pipeline passed on rerun.
The live test used both optional tasks in their default unchecked state. Purge removes the
installed payload and `userdata/`, then removes the application directory when it is empty.

The smoke waveform, scientific defaults, Git index, and 911 pre-existing release files
matched their preflight SHA-256. The protected core and configuration paths had no Git
diff. Git HEAD and the index remained at their preflight state.
