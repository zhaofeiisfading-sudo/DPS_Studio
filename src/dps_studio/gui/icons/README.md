# PDV Studio icon

`pdv_studio_master.png` keeps the supplied artwork's native 1254 × 1254 resolution.
`pdv_studio.ico` contains 16, 20, 24, 32, 40, 48, 64, 128 and 256 px RGBA frames.
Qt and PyInstaller both use this ICO; the master is not needed at runtime.

The audited source had body alpha 252/253, a two-pixel coverage edge, and detached
alpha 1–15 residue. Cleanup makes the body opaque without changing its RGB,
retains the two-pixel antialiasing band, extends neighbouring body RGB into that
band, and zeros all exterior RGBA. Premultiplied-alpha Lanczos resizing excludes
ringing outside the area-resampled silhouette. The original blue/cyan rim is
part of the artwork and remains intact.

Reproduce from the original supplied PNG in the existing development environment:

```powershell
python tools/build_app_icon.py <source.png> --output <new-assets-directory> --diagnostics <new-preview-directory>
```

The tool refuses existing outputs. Audit a different input before changing
`--core-alpha 240` or `--edge-width 2`; these describe this source's measured edge.
No new runtime dependency or second resource resolver is required.
