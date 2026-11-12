"""Build and smoke-test a fresh Production Windows EXE or onedir ZIP.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from dps_studio import __version__  # noqa: E402
from scripts.build.layout import release_paths  # noqa: E402


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


def committed_source() -> str:
    """Require a reviewable, clean commit rather than an ambiguous work tree."""
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True)
    if status.strip():
        raise RuntimeError("Commit release changes before building; work tree is not clean")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()


def verify_gui_workflow(
    executable: Path, runtime_root: Path, root: Path, source: Path,
    environment: dict[str, str],
) -> list[dict[str, Any]]:
    """Exercise the actual frozen executable, then restart its isolated settings."""
    reports = []
    for language, scale, width, height in (
        ("zh_CN", "1", 1366, 768), ("en", "1.25", 1366, 768),
        ("zh_CN", "1.5", 1440, 900), ("en", "2", 1024, 640),
    ):
        case = root / f"workflow_{language}_{scale}"
        case.mkdir()
        report_path = case / "workflow.json"
        command = [str(executable), "--workflow-smoke-test", str(report_path),
                   "--workflow-input", str(source), "--workflow-language", language,
                   "--workflow-width", str(width), "--workflow-height", str(height)]
        if scale != "1":
            command.append("--workflow-layout-only")
        environment = environment.copy()
        # Use reproducible effective DPRs independent of this monitor's native 200%.
        environment["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        environment["QT_FONT_DPI"] = "96"
        environment["QT_SCALE_FACTOR"] = scale
        subprocess.run(command, cwd=root, env=environment, check=True, timeout=90)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_startup_report(report, runtime_root, require_analysis=False)
        if report.get("status") != "PASS" or not report.get("frozen"):
            raise RuntimeError(f"Frozen GUI verification failed: {report}")
        if abs(report["device_pixel_ratio"] - float(scale)) > .01:
            raise RuntimeError(f"Requested GUI scale was not applied: {report}")
        reports.append(report)
        if scale == "1":
            restart_path = case / "restart.json"
            subprocess.run([str(executable), "--workflow-smoke-test",
                            str(restart_path), "--workflow-restart"],
                           cwd=root, env=environment, check=True, timeout=30)
            restart = json.loads(restart_path.read_text(encoding="utf-8"))
            validate_startup_report(restart, runtime_root, require_analysis=False)
            if not restart.get("restart_parameters_recovered"):
                raise RuntimeError(f"Saved window preset did not survive restart: {restart}")
            reports.append(restart)
    return reports


def create_release_zip(directory: Path, archive_path: Path) -> None:
    if archive_path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Release ZIP must be outside its source directory")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in tree_hashes(directory):
            archive.write(directory / name, f"{directory.name}/{name}")


def validate_startup_report(
    startup: dict[str, Any], extracted: Path, *, require_analysis: bool,
) -> None:
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
    workflow_smoke: bool = False,
) -> dict[str, Any]:
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
    workflows = []
    if workflow_smoke:
        if analysis_input is None:
            raise ValueError("Workflow smoke requires an analysis input")
        workflows = verify_gui_workflow(
            extracted / "PDV Studio.exe", extracted, extraction_root, copied_input, environment,
        )
    if hashes != tree_hashes(extracted):
        raise RuntimeError("Running the release changed its packaged files")
    return {
        "zip_path": str(archive_path), "zip_sha256": file_hash(archive_path),
        "extraction_root": str(extraction_root), "startup": startup, "exit_code": completed.returncode,
        "runtime_environment_path": environment["PATH"],
        "zip_extraction_hashes_match": True, "zip_extraction_file_set_match": True,
        "packaged_files_unchanged_after_execution": True,
        "gui_workflows": workflows,
    }


def verify_onefile(
    executable: Path, evidence: Path, source: Path,
) -> dict[str, Any]:
    """Launch the native onefile build and prove its bundled dependencies and workflow."""
    evidence.mkdir()
    runtime_root = evidence / "runtime"
    runtime_root.mkdir()
    environment = isolated_environment()
    environment.update(TEMP=str(runtime_root), TMP=str(runtime_root))
    executable_hash = file_hash(executable)
    source_hash = file_hash(source)
    report_path = evidence / "startup.json"
    completed = subprocess.run(
        [str(executable), "--startup-smoke-test", str(report_path),
         "--analysis-smoke-input", str(source)],
        cwd=evidence, env=environment, timeout=90, capture_output=True, text=True,
    )
    if completed.returncode or not report_path.is_file():
        raise RuntimeError(f"Onefile startup failed: {completed.returncode}; {completed.stderr}")
    startup = json.loads(report_path.read_text(encoding="utf-8"))
    validate_startup_report(startup, runtime_root, require_analysis=True)
    workflows = verify_gui_workflow(executable, runtime_root, evidence, source, environment)
    if not workflows[0].get("dechirp_plot_and_export_match") or not workflows[0].get("icon_loaded"):
        raise RuntimeError("Onefile Dechirp or application icon verification did not complete.")
    if any(runtime_root.glob("_MEI*")):
        raise RuntimeError("Onefile runtime extraction remained after the processes exited.")
    if file_hash(executable) != executable_hash or file_hash(source) != source_hash:
        raise RuntimeError("Verification changed the executable or smoke input.")
    return {
        "sha256": executable_hash, "size_bytes": executable.stat().st_size,
        "input_sha256": source_hash, "startup": startup, "exit_code": completed.returncode,
        "gui_workflows": workflows, "runtime_environment_path": environment["PATH"],
        "onefile_runtime_cleaned_after_exit": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, default=PROJECT_ROOT / "release")
    parser.add_argument("--analysis-smoke-input", type=Path)
    parser.add_argument("--workflow-smoke", action="store_true")
    parser.add_argument("--onefile", action="store_true",
                        help="Build and verify a single Windows x64 executable.")
    args = parser.parse_args()
    commit_sha = committed_source()
    built_at = datetime.now(UTC).isoformat()
    if (args.workflow_smoke or args.onefile) and args.analysis_smoke_input is None:
        raise ValueError("Workflow and onefile builds require --analysis-smoke-input")
    analysis_input = (args.analysis_smoke_input.resolve(strict=True)
                      if args.analysis_smoke_input is not None else None)
    output_root, release_root = release_paths(PROJECT_ROOT, args.output_root, args.release_root)
    if args.onefile and (
        sys.platform != "win32" or sys.maxsize <= 2**32
        or platform.machine().upper() not in {"AMD64", "X86_64"}
    ):
        raise RuntimeError("Onefile builds require a native Windows x64 environment.")
    name = f"PDV_Studio_v{__version__}"
    archive_path = release_root / (f"{name}_Windows_x64.exe" if args.onefile else f"{name}.zip")
    if archive_path.exists():
        raise FileExistsError(f"Will not overwrite existing release: {archive_path}")
    output_root.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--workpath", str(output_root / "work"),
        "--distpath", str(output_root / "dist"),
        str(PROJECT_ROOT / "packaging" / "pdv_studio.spec"),
    ]
    build_env = build_environment()
    build_env["DPS_STUDIO_ONEFILE"] = "1" if args.onefile else "0"
    build_env["PYINSTALLER_CONFIG_DIR"] = str(output_root / "pyinstaller_cache")
    with (output_root / "build.log").open("x", encoding="utf-8") as log:
        subprocess.run(command, cwd=PROJECT_ROOT, env=build_env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    versions = {
        name: importlib.metadata.version(name)
        for name in ("pyinstaller", "pyinstaller-hooks-contrib", "PySide6", "shiboken6", "scipy", "numpy")
    }
    if args.onefile:
        assert analysis_input is not None
        executable = output_root / "dist" / "PDV Studio.exe"
        verification = verify_onefile(executable, output_root / "verification", analysis_input)
        if committed_source() != commit_sha:
            raise RuntimeError("Source changed during release build")
        release_root.mkdir(parents=True, exist_ok=True)
        # Windows rename fails if the destination exists, including a competing release.
        executable.rename(archive_path)
        manifest: dict[str, Any] = {
            "release_version": __version__, "platform": "Windows", "architecture": "x64",
            "format": "PyInstaller onefile", "exe": str(archive_path), "commit_sha": commit_sha,
            "built_at_utc": built_at, "python_version": platform.python_version(),
            "dependency_versions": versions, "build_command": command,
            "verification": verification,
        }
        with (output_root / "release_manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
        print(json.dumps({"release": str(archive_path), "sha256": verification["sha256"]}))
        return 0

    directory = output_root / "dist" / name
    components = runtime_files(directory)
    with (directory / "README.txt").open("x", encoding="utf-8") as handle:
        handle.write(
            f"PDV Studio v{__version__}\n\n"
            "双击 PDV Studio.exe 启动。请保持 _internal 与 EXE 一起移动。\n"
            "本发布包无需安装 Python 或 Conda。\n"
            "默认两列 CSV 导出连续显示曲线；质量筛选需显式勾选，文件名含 quality_passed，时间序列可能有缺口。\n"
            "加速度页可切换速度差分和 Dechirp；复核页可额外导出加速度 CSV。\n"
            "材料参数区可命名、保存并重新选择自定义窗口配置。\n"
            f"构建来源：{commit_sha}；远端版本未核验；本包未进行代码签名。\n"
        )
    shutil.copyfile(PROJECT_ROOT / "docs" / f"RELEASE_NOTES_{__version__}.md",
                    directory / "RELEASE_NOTES.md")
    with (directory / "BUILD_INFO.json").open("x", encoding="utf-8") as handle:
        json.dump({"release_version": __version__, "python_version": platform.python_version(),
                   "dependency_versions": versions, "commit_sha": commit_sha,
                   "built_at_utc": built_at, "signing": "NOT_SIGNED",
                   "remote_version_verified": False}, handle, indent=2)
    hashes = tree_hashes(directory)
    release_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".candidate-", dir=release_root) as staging:
        candidate = Path(staging) / archive_path.name
        create_release_zip(directory, candidate)
        verification = verify_release_zip(
            directory, candidate, analysis_input=analysis_input,
            workflow_smoke=args.workflow_smoke,
        )
        if committed_source() != commit_sha:
            raise RuntimeError("Source changed during release build")
        # Publish exactly the verified bytes without overwriting an existing archive.
        os.link(candidate, archive_path)
    verification["zip_path"] = str(archive_path)
    manifest = {
        "release_version": __version__, "build_command": command,
        "commit_sha": commit_sha, "built_at_utc": built_at,
        "python_version": platform.python_version(),
        "build_path": build_env["PATH"],
        "dependency_versions": versions,
        "runtime_files": components, "file_sha256": hashes,
        "zip_path": str(archive_path), "zip_sha256": file_hash(archive_path),
        "extraction_root": verification["extraction_root"], "startup": verification["startup"],
        "build_verification": verification, "final_release_verification": verification,
        "final_release_directory": str(release_root),
        "zip_extraction_hashes_match": True,
    }
    with (output_root / "release_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"release": str(archive_path), "verification": verification}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
