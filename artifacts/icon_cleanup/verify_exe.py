"""Verify PE icon bytes, windowed subsystem, and the bundled runtime asset."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    ico = root / "src/dps_studio/gui/icons/pdv_studio.ico"
    pe = pefile.PE(str(args.exe), fast_load=True)
    pe.parse_data_directories(directories=[2])
    resources = {}
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id not in (3, 14):
            continue
        resources[kind.id] = {}
        for entry in kind.directory.entries:
            data = entry.directory.entries[0].data.struct
            resources[kind.id][entry.id] = pe.get_data(data.OffsetToData, data.Size)
    blob = ico.read_bytes()
    count = struct.unpack_from("<H", blob, 4)[0]
    frames = []
    for i in range(count):
        width, _, _, _, _, bits, size, offset = struct.unpack_from("<BBBBHHII", blob, 6 + i * 16)
        content = blob[offset:offset + size]
        matches = [rid for rid, data in resources[3].items() if data == content]
        frames.append({"size": width or 256, "bits": bits, "resource_ids": matches,
                       "exact_match": bool(matches)})
    old = root / "release/PDV_Studio_v0.1.3/PDV Studio.exe"
    bundled = args.exe.parent / "_internal/dps_studio/gui/icons/pdv_studio.ico"
    report = {
        "exe": str(args.exe), "subsystem": pe.OPTIONAL_HEADER.Subsystem,
        "no_console": pe.OPTIONAL_HEADER.Subsystem == 2,
        "rt_icon_count": len(resources[3]), "rt_group_icon_count": len(resources[14]),
        "frames": frames, "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        "old_exe_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
        "exe_mtime": args.exe.stat().st_mtime, "old_exe_mtime": old.stat().st_mtime,
        "bundled_ico_exact_match": bundled.read_bytes() == blob,
        "external_png_exists": (args.exe.parent / "软件图标.png").exists(),
        "foreign_icu_bundled": (args.exe.parent / "_internal/icuuc.dll").exists(),
    }
    assert all(frame["exact_match"] for frame in frames)
    assert report["no_console"] and report["bundled_ico_exact_match"]
    assert not report["external_png_exists"]
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
