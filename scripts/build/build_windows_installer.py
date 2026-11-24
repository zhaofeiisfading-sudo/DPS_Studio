"""Build, verify, and publish the PDV Studio per-user Windows x64 installer."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dps_studio import __version__  # noqa: E402
from scripts.build.build_production_release import (  # noqa: E402
    build_environment,
    copy_smoke_input,
    file_hash,
    isolated_environment,
    runtime_files,
    tree_hashes,
    validate_startup_report,
    verify_onedir_directory,
)
from scripts.build.layout import release_paths  # noqa: E402

INSTALLER_NAME = "PDV-Studio-Setup-x64.exe"
APP_ID = "{8D6E4A72-5C39-4E91-9B1A-4D2F7A8C0200}"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
PACKAGE_FILES = (
    "PDV Studio.exe",
    "pdv.exe",
    "THIRD_PARTY_NOTICES.txt",
    "skills/pdv-studio/SKILL.md",
    "launchers/一键分析_1550nm_LiF_0度.bat",
    "launchers/一键分析_1550nm_无窗口_0度.bat",
)
USERDATA_DIRS = ("config", "materials", "presets", "cache", "logs", "temp")
CLI_OUTPUTS = (
    "velocity_raw.csv",
    "velocity_gated.csv",
    "velocity_display.csv",
    "run_summary.json",
    "spectrogram_ridge.png",
)
RUNTIME_DISTRIBUTIONS = (
    "numpy", "scipy", "pandas", "PySide6", "shiboken6", "pyqtgraph", "pydantic",
    "pydantic-core", "pyinstaller", "pyinstaller-hooks-contrib",
)
LICENSE_DISTRIBUTIONS = (
    "numpy", "scipy", "pandas", "pyqtgraph", "pydantic", "pydantic-core", "pyinstaller",
)
SUPPLEMENTAL_LICENSES = (
    "annotated-types", "colorama", "python-dateutil", "six", "typing-extensions",
    "typing-inspection", "tzdata",
)
SILENT_FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


def find_iscc(explicit: Path | None = None) -> Path:
    """Find ISCC in invocation order, including ordinary per-user installations."""
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"ISCC.exe not found: {explicit}")
        return explicit.resolve()

    on_path = shutil.which("ISCC.exe")
    if on_path:
        return Path(on_path).resolve()
    candidates = (
        Path(os.environ["LOCALAPPDATA"]) / "Programs" if os.environ.get("LOCALAPPDATA") else None,
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")),
    )
    for root in candidates:
        if root is not None:
            executable = root / "Inno Setup 6" / "ISCC.exe"
            if executable.is_file():
                return executable.resolve()
    raise FileNotFoundError("Inno Setup 6 ISCC.exe was not found. Provide its path with --iscc.")


def source_provenance(*, allow_dirty: bool) -> dict[str, str | bool]:
    def git(*arguments: str) -> str:
        return subprocess.check_output(
            ["git", "--no-optional-locks", *arguments], cwd=PROJECT_ROOT, text=True,
        ).strip()

    clean = not git("status", "--porcelain", "--untracked-files=all")
    if not clean and not allow_dirty:
        raise RuntimeError("The worktree is dirty. Use --allow-dirty to record a local dirty build.")
    head = git("rev-parse", "HEAD")
    return {"commit_sha": head if clean else f"{head}-dirty", "worktree_clean": clean}


def write_json(path: Path, document: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_logged(
    command: list[str], log_path: Path, *, cwd: Path, env: dict[str, str], timeout: int,
) -> None:
    with log_path.open("x", encoding="utf-8") as log:
        result = subprocess.run(
            command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
        )
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} exited {result.returncode}. See {log_path}")


def check_layout(directory: Path, *, files: tuple[str, ...], dirs: tuple[str, ...]) -> None:
    missing = [name for name in files if not (directory / name).is_file()]
    missing.extend(name for name in dirs if not (directory / name).is_dir())
    if missing:
        raise RuntimeError(f"Required package contents missing under {directory}: {missing}")


def copy_distribution_licenses(distribution: str, destination: Path) -> bool:
    metadata = importlib.metadata.distribution(distribution)
    copied = False
    for path in metadata.files or ():
        if not path.parts[0].endswith(".dist-info"):
            continue
        relative = Path(*path.parts[1:])
        if relative.parts[0] != "licenses" and not relative.name.upper().startswith(
            ("LICENSE", "COPYING", "NOTICE"),
        ):
            continue
        target = destination / distribution / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(metadata.locate_file(path), target)
        copied = True
    return copied


def populate_onedir(directory: Path, info: dict[str, Any]) -> None:
    name = f"PDV Studio {__version__} (Windows x64)"
    (directory / "README.txt").write_text(
        f"{name}\n\n"
        "Open PDV Studio.exe for the desktop application.\n"
        "Run pdv.exe --help for the command-line tools.\n"
        "Keep both executables together with their shared _internal/ directory.\n"
        "The application saves settings and materials in userdata/ beside the executables.\n"
        "Choose a writable installation directory. Back up userdata/ before moving it.\n"
        "See skills/pdv-studio/SKILL.md for CLI examples and THIRD_PARTY_NOTICES.txt for licenses.\n",
        encoding="utf-8",
    )
    shutil.copyfile(
        PROJECT_ROOT / "docs" / f"RELEASE_NOTES_{__version__}.md", directory / "RELEASE_NOTES.md",
    )
    shutil.copyfile(
        PROJECT_ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt", directory / "THIRD_PARTY_NOTICES.txt",
    )
    skill = Path("skills/pdv-studio/SKILL.md")
    (directory / skill).parent.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / ".agents" / skill, directory / skill)
    launchers_dir = directory / "launchers"
    launchers_dir.mkdir(parents=True, exist_ok=True)
    for launcher in sorted((PROJECT_ROOT / "packaging" / "launchers").glob("*.bat")):
        shutil.copyfile(launcher, launchers_dir / launcher.name)
    licenses = directory / "licenses"
    shutil.copytree(PROJECT_ROOT / "packaging" / "licenses", licenses)
    python_license = next(
        (path for name in ("LICENSE_PYTHON.txt", "LICENSE.txt") if
         (path := Path(sys.base_prefix) / name).is_file()),
        None,
    )
    if python_license is None:
        raise FileNotFoundError(f"Python redistribution license missing in {sys.base_prefix}")
    shutil.copyfile(python_license, licenses / "Python.txt")
    for distribution in LICENSE_DISTRIBUTIONS:
        if not copy_distribution_licenses(distribution, licenses):
            raise RuntimeError(f"Redistribution license missing from {distribution} metadata")
    for distribution in SUPPLEMENTAL_LICENSES:
        try:
            copy_distribution_licenses(distribution, licenses)
        except importlib.metadata.PackageNotFoundError:
            continue
    write_json(directory / "BUILD_INFO.json", info)


def smoke_config(defaults: Path) -> dict[str, Any]:
    """Use the explicit import and laboratory conditions of the GUI startup fixture."""
    config = tomllib.loads(defaults.read_text(encoding="utf-8"))
    columns = {"pdv_channel_1": 1, "pdv_channel_2": 2}
    correction = config["velocity_correction"]
    return {
        "time_column": 0,
        "time_unit": "s",
        "voltage_columns": columns,
        "voltage_units": dict.fromkeys(columns, "V"),
        "vacuum_wavelength_m": config["analysis"]["vacuum_wavelength_m"],
        "measurement_angle_rad": correction["measurement_angle_rad"],
        "window_material": correction["window_material"],
        "lif_b1": correction["lif_b1"],
        "lif_b2": correction["lif_b2"],
        "lif_reference_wavelength_m": correction["lif_reference_wavelength_m"],
        "profile": config["analysis"]["default_profile"],
        "delimiter": config["input"]["delimiter"],
        "has_header": config["input"]["has_header"],
        "encoding": config["input"]["encoding"],
    }


def runtime_environment(root: Path) -> dict[str, str]:
    environment = isolated_environment()
    environment.update(TEMP=str(root), TMP=str(root))
    return environment


def cli_smoke(
    directory: Path, source: Path, root: Path, environment: dict[str, str],
    *, startup: dict[str, Any],
) -> dict[str, Any]:
    executable = str(directory / "pdv.exe")
    run_logged(
        [executable, "--version"], root / "cli_version.log", cwd=root, env=environment, timeout=30,
    )
    banner = (root / "cli_version.log").read_text(encoding="utf-8").strip()
    if banner != f"pdv {__version__}":
        raise RuntimeError(f"Unexpected CLI version: {banner}")

    input_hash = file_hash(source)
    preview_path = root / "inspect.json"
    run_logged(
        [executable, "inspect", str(source), "--out", str(preview_path)], root / "cli_inspect.log",
        cwd=root, env=environment, timeout=30,
    )
    preview = read_json(preview_path)
    if preview["source_sha256"] != input_hash or preview["column_count"] < 3:
        raise RuntimeError(f"Unexpected CLI waveform preview in {preview_path}")

    output = root / "cli_results"
    config = root / "smoke_experiment.json"
    write_json(config, smoke_config(directory / "_internal/configs/pdv_studio_defaults.toml"))
    run_logged(
        [executable, "analyze", str(source), "--config", str(config), "--out", str(output)],
        root / "cli_analyze.log", cwd=root, env=environment, timeout=180,
    )
    check_layout(output, files=CLI_OUTPUTS, dirs=())
    summary = read_json(output / "run_summary.json")
    if not (
        summary["source_sha256"] == file_hash(source) == input_hash
        and summary["software_version"] == __version__
    ):
        raise RuntimeError(f"Unexpected CLI result provenance in {output}")
    with (output / "spectrogram_ridge.png").open("rb") as figure:
        if figure.read(8) != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError(f"Invalid CLI figure: {output / 'spectrogram_ridge.png'}")

    import csv
    import numpy as np

    gui_channels = startup["analysis_smoke"]["channels"]
    if list(gui_channels.keys()) != list(summary["channels"]):
        raise RuntimeError("GUI and CLI startup analyses exported different channels")
    with (output / "velocity_raw.csv").open(encoding="utf-8", newline="") as handle:
        cli_rows = list(csv.DictReader(handle))
    parity = {}
    for channel, report in gui_channels.items():
        token = summary["channel_tokens"][channel]
        col = f"{token}_raw_velocity_m_s"
        cli_vals = np.array([float(row[col]) if row[col] != "" else np.nan for row in cli_rows], dtype=np.float64)
        gui_csv = Path(report["continuous_csv"])
        with gui_csv.open(encoding="utf-8", newline="") as handle:
            gui_rows = list(csv.DictReader(handle))
        gui_vals = np.array([float(row["display_velocity_m_s"]) for row in gui_rows], dtype=np.float64)
        if not np.allclose(cli_vals, gui_vals, rtol=0.0, atol=0.0, equal_nan=True):
            raise RuntimeError(f"GUI and CLI raw velocity arrays differ for {channel}: {gui_csv}, {output / 'velocity_raw.csv'}")
        parity[channel] = {"rows": report["continuous_rows"], "sha256": file_hash(gui_csv)}
    return {"version": banner, "input_sha256": input_hash, "continuous_csv_parity": parity,
            "output_sha256": tree_hashes(output)}


def verify_bundle(directory: Path, root: Path, analysis_input: Path) -> dict[str, Any]:
    check_layout(directory, files=PACKAGE_FILES, dirs=("_internal",))
    components = runtime_files(directory)
    hashes = tree_hashes(directory)
    result = verify_onedir_directory(
        directory, analysis_input=analysis_input, verification_root=root,
    )
    environment = runtime_environment(root)
    cli_environment = {**environment, "PDV_STUDIO_USERDATA_DIR": str(root / "cli_userdata")}
    cli = cli_smoke(directory, root / "example.csv", root, cli_environment, startup=result["startup"])
    if hashes != tree_hashes(directory):
        raise RuntimeError(f"GUI or CLI verification changed packaged files under {directory}")
    return {**result, "cli": cli, "runtime_files": components,
            "file_sha256": hashes, "packaged_files_unchanged_after_execution": True}


def installed_registration() -> dict[str, str] | None:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        return None
    with key:
        return {
            name: winreg.QueryValueEx(key, name)[0]
            for name in ("DisplayName", "DisplayVersion", "InstallLocation", "UninstallString")
        }


def appdata_snapshot() -> dict[str, list[str]]:
    snapshots = {}
    for variable in ("APPDATA", "LOCALAPPDATA"):
        for name in ("DPS Studio", "PDV Studio"):
            root = Path(os.environ[variable]) / name
            entries = []
            if root.exists():
                entries.append(".")
                for directory, subdirs, files in root.walk():
                    entries.extend((directory / item).relative_to(root).as_posix()
                                   for item in subdirs + files)
                    subdirs[:] = [item for item in subdirs if not (directory / item).is_junction()]
            snapshots[str(root)] = sorted(entries)
    return snapshots


def verify_registration(directory: Path, uninstaller: Path) -> dict[str, str]:
    record = installed_registration()
    if (
        record is None or record["DisplayName"] != "PDV Studio"
        or record["DisplayVersion"] != __version__
        or Path(record["InstallLocation"]).resolve() != directory
        or record["UninstallString"].strip('"').casefold() != str(uninstaller).casefold()
    ):
        raise RuntimeError(f"Unexpected uninstall registration in HKCU\\{UNINSTALL_KEY}: {record}")
    return record


def wait_for_uninstall(uninstaller: Path, *, purge: bool, timeout: float = 30) -> None:
    """Wait for Inno's detached cleanup process to finish removing its launcher."""
    deadline = time.monotonic() + timeout
    while (
        uninstaller.exists() or installed_registration() is not None
        or (purge and uninstaller.parent.exists())
    ):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Uninstall cleanup did not finish at {uninstaller.parent}")
        time.sleep(0.1)


def verify_installer(
    installer: Path, root: Path, analysis_input: Path, bundle: dict[str, Any],
) -> dict[str, Any]:
    from dps_studio.core.physics.models import LIF_RIGG_2014_1550NM
    from dps_studio.core.physics.window_presets import WindowPresetRepository

    install_dir = root / "中文 空格 安装目录" / "PDV Studio"
    uninstaller = install_dir / "unins000.exe"
    if installed_registration() is not None:
        raise RuntimeError(f"A current-user installation already owns HKCU\\{UNINSTALL_KEY}")
    root.mkdir()
    environment = runtime_environment(root)
    source = copy_smoke_input(analysis_input, root)
    userdata = install_dir / "userdata"
    settings = userdata / "config/settings.ini"
    materials = userdata / "materials/window_presets.json"
    name = "升级保留测试窗口"
    package_hashes = bundle["file_sha256"]

    def install(phase: str) -> dict[str, str]:
        run_logged(
            [str(installer), *SILENT_FLAGS, "/CURRENTUSER", f"/DIR={install_dir}",
             f"/LOG={root / f'{phase}.log'}"],
            root / f"{phase}_process.log", cwd=root, env=environment, timeout=600,
        )
        check_layout(
            install_dir, files=(*PACKAGE_FILES, "unins000.exe"),
            dirs=("_internal", *(f"userdata/{item}" for item in USERDATA_DIRS)),
        )
        if any(file_hash(install_dir / path) != digest for path, digest in package_hashes.items()):
            raise RuntimeError(f"Installed package files differ from the verified onedir: {install_dir}")
        return verify_registration(install_dir, uninstaller)

    def uninstall(phase: str, *, purge: bool) -> None:
        options = ["/PURGEUSERDATA=1"] if purge else []
        run_logged(
            [str(uninstaller), *SILENT_FLAGS, *options, f"/LOG={root / f'{phase}.log'}"],
            root / f"{phase}_process.log", cwd=root, env=environment, timeout=180,
        )
        wait_for_uninstall(uninstaller, purge=purge)

    try:
        registration = install("install")
        before = appdata_snapshot()
        cli_root = root / "installed_cli"
        cli_root.mkdir()
        cli = cli_smoke(install_dir, source, cli_root, environment, startup=bundle["startup"])
        gui_report = root / "installed_gui" / "workflow.json"
        run_logged(
            [str(install_dir / "PDV Studio.exe"), "--workflow-smoke-test", str(gui_report),
             "--workflow-input", str(source), "--workflow-installation-storage"],
            root / "installed_gui.log", cwd=root, env=environment, timeout=120,
        )
        gui = read_json(gui_report)
        validate_startup_report(gui, install_dir, require_analysis=False)
        if gui.get("status") != "PASS" or not gui.get("workflow_complete"):
            raise RuntimeError(f"Installed GUI failed full workflow smoke: {gui_report}")
        check_layout(
            userdata, files=("config/settings.ini", "materials/window_presets.json"),
            dirs=("cache/matplotlib",),
        )
        if "发布验证窗口" not in WindowPresetRepository(materials).load():
            raise RuntimeError("The installed GUI did not persist its saved window preset locally")

        after = appdata_snapshot()
        if before != after:
            raise RuntimeError(f"Application-specific AppData paths changed: {before} -> {after}")
        write_json(root / "appdata_snapshot.json", {"before": before, "after": after})

        repository = WindowPresetRepository(materials)
        repository.save(replace(LIF_RIGG_2014_1550NM, configuration_name=name))
        with settings.open("a", encoding="utf-8") as handle:
            handle.write("\n[InstallerVerification]\ncustomSetting=preserve\n")
        saved = {path: file_hash(path) for path in (settings, materials)}

        def verify_saved_userdata() -> None:
            if any(not path.is_file() or file_hash(path) != sha for path, sha in saved.items()):
                raise RuntimeError("Installer changed the saved settings or material presets")
            if name not in repository.load():
                raise RuntimeError(f"Custom material preset lost: {name}")

        install("upgrade")
        verify_saved_userdata()
        uninstall("uninstall_keep", purge=False)
        removed = ["PDV Studio.exe", "pdv.exe", "_internal", "userdata/cache", "userdata/temp"]
        if installed_registration() is not None or any((install_dir / p).exists() for p in removed):
            raise RuntimeError("Default uninstall left installed runtime, cache, temp, or registry")
        verify_saved_userdata()
        install("reinstall")
        verify_saved_userdata()
        uninstall("uninstall_purge", purge=True)
        if install_dir.exists() or installed_registration() is not None:
            raise RuntimeError(f"Purge uninstall left its installation or registration: {install_dir}")
    except Exception as error:
        if uninstaller.is_file() and installed_registration() is not None:
            try:
                uninstall("failure_cleanup", purge=True)
            except Exception as cleanup_error:
                error.add_note(f"Test-install cleanup failed: {cleanup_error}")
        raise

    return {
        "install_directory": str(install_dir), "registry_key": f"HKCU\\{UNINSTALL_KEY}",
        "registration": registration, "local_userdata_verified": True,
        "appdata_unchanged": True, "installed_cli": cli, "installed_gui": gui,
        "upgrade_preserved_userdata": True, "default_uninstall_preserved_userdata": True,
        "purge_uninstall_removed_installation": True, "preserved_material": name,
        "userdata_sha256": {path.relative_to(userdata).as_posix(): sha for path, sha in saved.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, default=PROJECT_ROOT / "release")
    parser.add_argument("--analysis-smoke-input", type=Path, required=True)
    parser.add_argument("--iscc", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    if (
        sys.platform != "win32" or sys.maxsize <= 2**32
        or platform.machine().upper() not in {"AMD64", "X86_64"}
    ):
        raise RuntimeError("This installer build requires native Windows x64 and 64-bit Python.")
    output_root, release_root = release_paths(PROJECT_ROOT, args.output_root, args.release_root)
    target = release_root / INSTALLER_NAME
    checksum = release_root / f"{INSTALLER_NAME}.sha256"
    for path in (target, checksum, output_root):
        if os.path.lexists(path):
            raise FileExistsError(f"Will not overwrite existing output: {path}")
    if output_root.drive.casefold() == os.environ["SystemDrive"].casefold():
        raise ValueError("Installer verification requires --output-root on a non-system drive.")
    analysis_input = args.analysis_smoke_input.resolve(strict=True)
    if not analysis_input.is_file():
        raise ValueError(f"Analysis smoke input is not a file: {analysis_input}")
    analysis_hash = file_hash(analysis_input)
    iscc = find_iscc(args.iscc)
    provenance = source_provenance(allow_dirty=args.allow_dirty)

    output_root.mkdir(parents=True)
    environment = build_environment()
    environment.update(
        DPS_STUDIO_ONEFILE="0", PYINSTALLER_CONFIG_DIR=str(output_root / "pyinstaller_cache"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = [
        sys.executable, "-B", "-m", "PyInstaller", "--clean", "--noconfirm",
        "--workpath", str(output_root / "work"), "--distpath", str(output_root / "dist"),
        str(PROJECT_ROOT / "packaging" / "pdv_studio.spec"),
    ]
    versions = {name: importlib.metadata.version(name) for name in RUNTIME_DISTRIBUTIONS}
    qt_version = versions["PySide6"]
    info = {
        "release_version": __version__, "platform": "Windows", "architecture": "x64",
        "built_at_utc": datetime.now(UTC).isoformat(), "python_version": platform.python_version(),
        **provenance, "dependency_versions": versions,
        "qt_corresponding_source": {
            "Qt": ("https://download.qt.io/official_releases/qt/"
                   f"{qt_version.rsplit('.', 1)[0]}/{qt_version}/single/"),
            "PySide6 and Shiboken6": (
                "https://download.qt.io/official_releases/QtForPython/pyside6/"
                f"PySide6-{qt_version}-src/"
            ),
        },
    }
    print(f"Building the shared Windows runtime. Log: {output_root / 'build.log'}", flush=True)
    run_logged(command, output_root / "build.log", cwd=PROJECT_ROOT, env=environment, timeout=1200)
    directory = output_root / "dist" / f"PDV_Studio_v{__version__}"
    populate_onedir(directory, info)
    print("Verifying both frozen executables and continuous CSV parity.", flush=True)
    bundle = verify_bundle(directory, output_root / "onedir_verification", analysis_input)
    write_json(output_root / "onedir_verification" / "report.json", bundle)

    staging = output_root / "installer_staging"
    staging.mkdir()
    compile_command = [
        str(iscc), f"/DMyAppVersion={__version__}", f"/DProjectRoot={PROJECT_ROOT}",
        f"/DOnedirSource={directory}", f"/DOutputDir={staging}",
        f"/DOutputBaseFilename={Path(INSTALLER_NAME).stem}",
        str(PROJECT_ROOT / "packaging" / "pdv_studio_installer.iss"),
    ]
    print(f"Compiling Inno Setup installer. Log: {output_root / 'iscc.log'}", flush=True)
    run_logged(
        compile_command, output_root / "iscc.log", cwd=PROJECT_ROOT, env=environment, timeout=1200,
    )
    installer = staging / INSTALLER_NAME
    digest = file_hash(installer)
    print("Verifying per-user install, in-place upgrade, and both uninstall modes.", flush=True)
    installed = verify_installer(
        installer, output_root / "install_verification", analysis_input, bundle,
    )
    write_json(output_root / "install_verification" / "report.json", installed)
    if source_provenance(allow_dirty=args.allow_dirty) != provenance:
        raise RuntimeError("Git HEAD or worktree cleanliness changed during the build")
    if file_hash(analysis_input) != analysis_hash or file_hash(installer) != digest:
        raise RuntimeError("The smoke input or installer changed during verification")
    if os.path.lexists(checksum):
        raise FileExistsError(f"Will not overwrite existing checksum: {checksum}")

    release_root.mkdir(parents=True, exist_ok=True)
    installer.rename(target)  # Windows rename does not overwrite a competing release.
    with checksum.open("x", encoding="ascii") as handle:
        handle.write(f"{digest}  {target.name}\n")
    write_json(output_root / "release_manifest.json", {
        **info, "installer": str(target), "installer_sha256": digest,
        "size_bytes": target.stat().st_size, "onedir_directory": str(directory),
        "build_command": command, "iscc_command": compile_command,
        "analysis_smoke_input_sha256": analysis_hash,
        "verification": {"onedir": bundle, "installer": installed},
    })
    print(f"{target}\nSHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
