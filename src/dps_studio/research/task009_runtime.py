"""Local Research entry for the byte-preserved TASK-008 algorithms.

No Production imports or writes. The old worktree is denied at the file-access
boundary during replay, proving that the migrated implementation is independent.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.algorithms import waveform
from dps_studio.runtime_paths import application_resource_root

ROOT = application_resource_root()
TASK8 = Path(waveform.__file__).resolve().parent
PROTOCOL = ROOT/"docs/tasks/TASK-008/PROTOCOL.md"
TASK9 = ROOT/"artifacts/TASK-009"
OLD_ROOT = ROOT.parent/"DPS_Studio_TASK021A"


def assert_local() -> None:
    import dps_studio
    package = Path(dps_studio.__file__).resolve().parent
    if TASK8.is_junction() or not TASK8.resolve().is_relative_to(package):
        raise RuntimeError("Waveform algorithms must be part of the installed Research package")
    if not (TASK8/"common.py").is_file():
        raise RuntimeError("Packaged waveform algorithms missing")


def source_guard(event: str, args: tuple[Any, ...]) -> None:
    if event not in ("open", "os.listdir", "os.scandir") or not args:
        return
    raw = args[0]
    if not isinstance(raw, (str, bytes, Path)):
        return
    try:
        path = Path(raw.decode() if isinstance(raw, bytes) else raw).resolve()
    except (ValueError, OSError):
        return
    if path.is_relative_to(OLD_ROOT):
        raise RuntimeError(f"TASK-009 old-worktree access denied: {path}")


def provenance() -> dict[str, Any]:
    import dps_studio
    from dps_studio.algorithms.waveform import common
    from dps_studio.algorithms.waveform.catalog import METHODS
    return dict(target_root=str(ROOT), frozen_root=str(TASK8.resolve()),
        dps_studio_source=str(Path(dps_studio.__file__).resolve()),
        algorithm_common_source=str(Path(common.__file__).resolve()), methods=list(METHODS),
        old_source_file_access="DENIED", physical_local_package=True)


def run_raw(path: Path, column: int, names: list[str], output: Path) -> None:
    from dps_studio.algorithms.waveform.common import Context, Signal, WAVELENGTH_M
    from dps_studio.research.waveform.runner import write_json
    assert_local()
    matrix = np.loadtxt(path, delimiter=",", ndmin=2)
    if not 0 < column < matrix.shape[1]:
        raise ValueError("Voltage column must be a positive available column index")
    signal = Signal(np.array(matrix[:, 0]), np.array(matrix[:, column]), path.stem)
    context = Context(signal)
    output = output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/"artifacts"):
        raise ValueError("Output must be a new directory inside Research artifacts")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"provenance.json", {**provenance(), "raw_path": str(path.resolve()),
        "voltage_column": column, "real_ground_truth": "UNAVAILABLE",
        "equivalent_velocity_assumed_wavelength_m": WAVELENGTH_M})
    for name in names:
        module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
        result = module.run(context)
        folder = output/name
        folder.mkdir()
        arrays: dict[str, Any] = dict(time_s=context.time_s, frequency_hz=result.frequency_hz,
            supported_hz=result.accepted_hz, equivalent_velocity_m_s=result.frequency_hz*WAVELENGTH_M/2,
            corrected_velocity_m_s=np.full(len(context.time_s), np.nan), flags=result.flags,
            **result.extra)
        with (folder/"trajectory.npz").open("xb") as handle:
            np.savez_compressed(handle, **arrays)
        write_json(folder/"parameters.json", module.PARAMETERS)
        write_json(folder/"diagnostics.json", result.details)
    print(json.dumps(dict(output=str(output), methods=names, frames=len(context.time_s)),
                     ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("list", "replay", "run"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--full", action="store_true", help="96+50 synthetics and every raw channel")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--voltage-column", type=int, default=1)
    parser.add_argument("--method", default="varpro", help="Frozen method identifier or all")
    args = parser.parse_args()
    assert_local()
    sys.addaudithook(source_guard)
    from dps_studio.algorithms.waveform.catalog import METHODS
    if args.mode == "list":
        print(json.dumps(provenance(), ensure_ascii=False, indent=2))
        return
    if args.output is None:
        parser.error("--output is required and must not exist")
    destination = args.output.resolve()
    if not destination.is_relative_to(ROOT/"artifacts") or destination.exists():
        parser.error("Output must be a new directory inside Research artifacts")
    if args.mode == "replay":
        from dps_studio.research.task009_data import install
        install()
        module = importlib.import_module("dps_studio.research.waveform.reproduce")
        sys.argv = ["task009-replay", "--output", str(destination)]
        if not args.full:
            sys.argv.append("--smoke")
        module.main()
        with (destination/"task009_independence.json").open("x", encoding="utf-8") as handle:
            json.dump(provenance(), handle, ensure_ascii=False, indent=2)
    else:
        if args.input is None:
            parser.error("--input is required for run")
        names = list(METHODS) if args.method == "all" else [args.method]
        if not all(name in METHODS for name in names):
            parser.error("Unknown frozen method")
        run_raw(args.input.resolve(), args.voltage_column, names, destination)


if __name__ == "__main__":
    main()
