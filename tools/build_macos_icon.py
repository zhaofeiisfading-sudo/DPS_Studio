"""Reproduce the approved PNG as a macOS ICNS using Apple's iconutil."""

from __future__ import annotations

import argparse
import platform
import subprocess
from pathlib import Path

from PIL import Image


ICONSET_SIZES = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}


def generate_icon(master: Path, output: Path, iconset: Path) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("ICNS generation requires macOS iconutil")
    if output.exists() or iconset.exists():
        raise FileExistsError("ICNS and iconset destinations must be new")
    with Image.open(master) as image:
        if image.size != (1254, 1254) or image.mode != "RGBA":
            raise ValueError("Approved icon must be the 1254x1254 RGBA master")
        iconset.mkdir(parents=True)
        for name, size in ICONSET_SIZES.items():
            image.resize((size, size), Image.Resampling.LANCZOS).save(iconset / name)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/usr/bin/iconutil", "-c", "icns", "-o", str(output), str(iconset)], check=True)
    with Image.open(output) as icon:
        if icon.format != "ICNS" or icon.size != (1024, 1024):
            raise RuntimeError("iconutil output is not a full-size ICNS")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=root / "src/dps_studio/gui/icons/pdv_studio.icns")
    parser.add_argument("--iconset", type=Path, required=True)
    args = parser.parse_args()
    generate_icon(root / "src/dps_studio/gui/icons/pdv_studio_master.png", args.output, args.iconset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
