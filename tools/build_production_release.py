"""Build, verify, ZIP, extract, and smoke-test a fresh Production release.

Never reuses or removes an existing build directory. Runtime collection remains
the PyInstaller hooks' responsibility; no manual DLL copies are performed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dps_studio import __version__  # noqa: E402


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def runtime_files(directory: Path) -> dict[str, list[str]]:
    patterns = {
        "pyside6_extension": "**/PySide6/QtCore.pyd",
        "pyside6_runtime": "**/PySide6/Qt6Core.dll",
        "shiboken_extension": "**/shiboken6/Shiboken.pyd",
        "shiboken_runtime": "**/shiboken6/*shiboken*.dll",
        "qt_windows_platform": "**/qwindows.dll",
        "scipy_ccallback": "**/scipy/_lib/_ccallback_c*.pyd",
    }
    result = {
        name: sorted(str(path.relative_to(directory)) for path in directory.glob(pattern))
        for name, pattern in patterns.items()
    }
    missing = [name for name, files in result.items() if not files]
    if missing:
        raise RuntimeError(f"Release runtime components missing: {missing}")
    return result


def isolated_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "CONDA", "QT", "PYSIDE", "QML", "_PYI_"))
        and key.upper() not in {"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "__PYVENV_LAUNCHER__"}
    }
    windows = Path(environment.get("SYSTEMROOT", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    return environment


def build_environment() -> dict[str, str]:
    environment = isolated_environment()
    environment["PATH"] = os.pathsep.join((
        str(Path(sys.executable).parent), str(Path(sys.prefix) / "Library" / "bin"),
        str(Path(sys.prefix) / "Scripts"), environment["PATH"],
    ))
    return environment


def tree_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): file_hash(path)
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def create_release_zip(directory: Path, archive_path: Path) -> None:
    if archive_path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Release ZIP must be outside its source directory")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in tree_hashes(directory):
            archive.write(directory / name, f"{directory.name}/{name}")


def validate_startup_report(startup: dict, extracted: Path, *, require_analysis: bool) -> None:
    if not (
        startup.get("event_loop_entered") and startup.get("window_visible")
        and startup.get("window_exposed") and startup.get("qt_platform") == "windows"
        and startup.get("version") == startup.get("gui_version") == __version__
    ):
        raise RuntimeError(f"Unexpected startup report: {startup}")
    paths = startup.get("runtime_paths", {})
    required = {"PySide6", "shiboken6", "scipy._lib._ccallback_c", "qwindows.dll",
                "QtCore.pyd", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
                "Shiboken.pyd", "shiboken6.abi3.dll"}
    if not required.issubset(paths):
        raise RuntimeError("Startup did not report all required loaded native runtimes")
    for loaded_path in paths.values():
        if not Path(loaded_path).resolve().is_relative_to(extracted.resolve()):
            raise RuntimeError(f"Runtime loaded outside the extracted release: {loaded_path}")
    if require_analysis:
        analysis = startup.get("analysis_smoke") or {}
        if analysis.get("status") != "PASS" or not analysis.get("input_unchanged"):
            raise RuntimeError(f"Release-side analysis failed: {analysis}")
        if not Path(analysis["core_module"]).resolve().is_relative_to(extracted.resolve()):
            raise RuntimeError("Release-side analysis imported core outside the release")


def verify_release_zip(
    directory: Path, archive_path: Path, *, analysis_input: Path | None = None,
) -> dict:
    extraction_root = Path(tempfile.mkdtemp(prefix="dps_production_release_"))
    if extraction_root.resolve().is_relative_to(PROJECT_ROOT.resolve()) or extraction_root.resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Smoke extraction must be outside the repository and Python environment")
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extraction_root)
    extracted = extraction_root / directory.name
    hashes = tree_hashes(directory)
    if hashes != tree_hashes(extracted):
        raise RuntimeError("ZIP extraction file set or SHA-256 differs from the release directory")
    report_path = extraction_root / "startup.json"
    command = [str(extracted / "PDV Studio.exe"), "--startup-smoke-test", str(report_path)]
    if analysis_input is not None:
        copied_input = extraction_root / "example.csv"
        shutil.copyfile(analysis_input, copied_input)
        if file_hash(copied_input) != file_hash(analysis_input):
            raise RuntimeError("Analysis smoke input copy differs from its source")
        command.extend(("--analysis-smoke-input", str(copied_input)))
    environment = isolated_environment()
    completed = subprocess.run(command, cwd=extraction_root, env=environment, timeout=90,
                               capture_output=True, text=True)
    if not report_path.is_file():
        raise RuntimeError(f"Isolated startup did not produce a report: {completed.returncode}; {completed.stderr}")
    startup = json.loads(report_path.read_text(encoding="utf-8"))
    if completed.returncode != 0:
        raise RuntimeError(f"Isolated startup failed: {completed.returncode}; {startup}")
    validate_startup_report(startup, extracted, require_analysis=analysis_input is not None)
    if hashes != tree_hashes(extracted):
        raise RuntimeError("Running the release changed its packaged files")
    return {
        "zip_path": str(archive_path), "zip_sha256": file_hash(archive_path),
        "extraction_root": str(extraction_root), "startup": startup, "exit_code": completed.returncode,
        "runtime_environment_path": environment["PATH"],
        "zip_extraction_hashes_match": True, "zip_extraction_file_set_match": True,
        "packaged_files_unchanged_after_execution": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--analysis-smoke-input", type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    release_root = args.release_root.resolve() if args.release_root is not None else None
    if release_root is not None:
        for target in (release_root / f"PDV_Studio_v{__version__}", release_root / f"PDV_Studio_v{__version__}.zip"):
            if target.exists():
                raise FileExistsError(f"Will not overwrite existing release: {target}")
    output_root.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--workpath", str(output_root / "work"),
        "--distpath", str(output_root / "dist"),
        str(PROJECT_ROOT / "packaging" / "pdv_studio.spec"),
    ]
    build_env = build_environment()
    with (output_root / "build.log").open("x", encoding="utf-8") as log:
        subprocess.run(command, cwd=PROJECT_ROOT, env=build_env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    directory = output_root / "dist" / f"PDV_Studio_v{__version__}"
    components = runtime_files(directory)
    versions = {
        name: importlib.metadata.version(name)
        for name in ("pyinstaller", "pyinstaller-hooks-contrib", "PySide6", "shiboken6", "scipy", "numpy")
    }
    with (directory / "README.txt").open("x", encoding="utf-8") as handle:
        handle.write(
            f"PDV Studio v{__version__}\n\n"
            "双击 PDV Studio.exe 启动。请保持 _internal 与 EXE 一起移动。\n"
            "本发布包无需安装 Python 或 Conda。\n"
            "默认两列 CSV 导出连续显示曲线；质量筛选需显式勾选，文件名含 quality_passed，时间序列可能有缺口。\n"
        )
    with (directory / "BUILD_INFO.json").open("x", encoding="utf-8") as handle:
        json.dump({"release_version": __version__, "python_version": platform.python_version(),
                   "dependency_versions": versions, "build_path": build_env["PATH"]}, handle, indent=2)
    hashes = tree_hashes(directory)
    archive_path = output_root / f"PDV_Studio_v{__version__}.zip"
    create_release_zip(directory, archive_path)
    build_verification = verify_release_zip(directory, archive_path, analysis_input=args.analysis_smoke_input)
    final_verification = None
    final_directory = None
    if release_root is not None:
        release_root.mkdir(parents=True, exist_ok=True)
        final_directory = release_root / directory.name
        shutil.copytree(directory, final_directory)
        if hashes != tree_hashes(final_directory):
            raise RuntimeError("Release staging differs from the verified build")
        final_archive = release_root / archive_path.name
        create_release_zip(final_directory, final_archive)
        final_verification = verify_release_zip(final_directory, final_archive, analysis_input=args.analysis_smoke_input)
    manifest = {
        "release_version": __version__, "build_command": command,
        "python_version": platform.python_version(),
        "build_path": build_env["PATH"],
        "dependency_versions": versions,
        "runtime_files": components, "file_sha256": hashes,
        "zip_path": str(archive_path), "zip_sha256": file_hash(archive_path),
        "extraction_root": build_verification["extraction_root"], "startup": build_verification["startup"],
        "build_verification": build_verification, "final_release_verification": final_verification,
        "final_release_directory": str(final_directory) if final_directory is not None else None,
        "zip_extraction_hashes_match": True,
    }
    with (output_root / "release_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"release": str(final_directory or directory), "verification": final_verification or build_verification}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
