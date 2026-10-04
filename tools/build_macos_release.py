"""macOS-only internal release: arm64, ad-hoc signed, Cocoa, ditto roundtrip.

The output root must not already exist. No prior release is removed or reused.
Every native gate runs on macOS; tests can exercise parsers on other platforms.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from dps_studio import __version__  # noqa: E402
from dps_studio.release.portable_reference import (  # noqa: E402
    compare_snapshots, dependency_versions, file_hash, lf_text_hash, reference_environment,
)
from tools.build_macos_icon import generate_icon  # noqa: E402


SYSTEM_PREFIXES = ("/System/Library/", "/usr/lib/")
REQUIRED_RUNTIME_KEYS = frozenset({
    "PySide6", "shiboken6", "SciPy", "QtCore_extension_image", "QtCore_framework_image",
    "Cocoa_plugin_image", "shiboken_extension_image", "SciPy_native_image",
})
MACH_O_MAGIC = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def write_json(path: Path, document: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def command_output(command: list[str], log: Path | None = None, **kwargs: Any) -> str:
    result: subprocess.CompletedProcess[str] = subprocess.run(
        command, text=True, capture_output=True, **kwargs,
    )
    output = result.stdout + result.stderr
    if log is not None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {command!r}\nexit={result.returncode}\n{output}\n")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command!r}\n{output}")
    return output


def require_native_environment() -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("Release requires native macOS arm64 Python; Rosetta is forbidden")
    if command_output(["/usr/bin/uname", "-m"]).strip() != "arm64":
        raise RuntimeError("Host uname -m is not arm64")
    if platform.python_version() != "3.12.13":
        raise RuntimeError("Release requires the audited Python 3.12.13")


def check_constraints() -> dict[str, str]:
    import importlib.metadata

    versions = {}
    for line in (ROOT / "packaging/macos-arm64-constraints.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==")
        actual = importlib.metadata.version(name)
        if actual != version:
            raise RuntimeError(f"Pinned dependency mismatch: {name} expected {version}, got {actual}")
        versions[name] = actual
    return versions


def isolated_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith((
            "PYTHON", "CONDA", "QT", "PYSIDE", "QML", "DYLD", "LD_", "_PYI_", "PYINSTALLER",
        )) and key.upper() not in {
            "VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "__PYVENV_LAUNCHER__", "DPS_MACOS_ICON",
        }
    }
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    environment["QT_QPA_PLATFORM"] = "cocoa"
    return environment


def bundle_manifest(app: Path) -> dict[str, dict[str, Any]]:
    """Record lstat semantics without following framework directory symlinks."""
    app = app.resolve()
    entries: dict[str, dict[str, Any]] = {
        ".": {"kind": "directory", "mode": stat.S_IMODE(app.lstat().st_mode)},
    }
    for directory, names, files in os.walk(app, followlinks=False):
        for name in sorted(names + files):
            path = Path(directory) / name
            info = path.lstat()
            entry: dict[str, Any] = {"mode": stat.S_IMODE(info.st_mode)}
            if stat.S_ISLNK(info.st_mode):
                target = path.resolve(strict=True)
                if not target.is_relative_to(app):
                    raise RuntimeError(f"Bundle symlink escapes app: {path}")
                entry.update(kind="symlink", target=os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                entry["kind"] = "directory"
            elif stat.S_ISREG(info.st_mode):
                entry.update(kind="file", sha256=file_hash(path), size=info.st_size)
            else:
                raise RuntimeError(f"Unsupported bundle file type: {path}")
            entries[path.relative_to(app).as_posix()] = entry
    return dict(sorted(entries.items()))


def verify_bundle(app: Path) -> Path:
    with (app / "Contents/Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    if info.get("CFBundleIdentifier") != "com.dpsstudio.pdvstudio":
        raise RuntimeError("Unexpected bundle identifier")
    if info.get("CFBundleVersion") != __version__ or info.get("CFBundleShortVersionString") != __version__:
        raise RuntimeError("Bundle version differs from single source of truth")
    executable = app / "Contents/MacOS" / str(info["CFBundleExecutable"])
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("App executable missing or not executable")
    icon = app / "Contents/Resources" / info["CFBundleIconFile"]
    with icon.open("rb") as handle:
        if handle.read(4) != b"icns":
            raise RuntimeError("Bundle icon is not ICNS")
    for pattern in ("**/pdv_studio_defaults.toml", "**/pdv_studio_en.qm", "**/pdv_studio.ico"):
        if not list(app.glob(pattern)):
            raise RuntimeError(f"Missing runtime resource: {pattern}")
    bundle_manifest(app)
    return executable


def parse_dependencies(output: str) -> list[str]:
    return [line.strip().split(" (", 1)[0] for line in output.splitlines()
            if line[:1].isspace() and " (compatibility version" in line]


def parse_rpaths(output: str) -> list[str]:
    paths = []
    in_rpath = False
    for line in output.splitlines():
        value = line.strip()
        if value.startswith("cmd "):
            in_rpath = value == "cmd LC_RPATH"
        elif in_rpath and value.startswith("path "):
            paths.append(value[5:].rsplit(" (offset ", 1)[0])
            in_rpath = False
    return paths


def validate_install_path(value: str) -> None:
    if value.startswith(SYSTEM_PREFIXES):
        return
    if value.startswith(("@rpath/", "@loader_path/", "@executable_path/")):
        return
    if value in {"@loader_path", "@executable_path"}:
        return
    raise RuntimeError(f"External or invalid Mach-O dependency/rpath: {value}")


def expand_loader_path(value: str, binary: Path, executable: Path) -> Path:
    return Path(value.replace("@loader_path", str(binary.parent))
                .replace("@executable_path", str(executable.parent)))


def audit_mach_o(app: Path, log: Path) -> dict[str, Any]:
    executable = verify_bundle(app)
    app = app.resolve()
    audit: dict[Path, dict[str, Any]] = {}
    categories: set[str] = set()
    for path in sorted(app.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(4) not in MACH_O_MAGIC:
                continue
        description = command_output(["/usr/bin/file", str(path)], log)
        architectures = command_output(["/usr/bin/lipo", "-archs", str(path)], log).strip().split()
        if "arm64" not in architectures:
            raise RuntimeError(f"Native binary lacks arm64: {path}: {architectures}")
        dependencies = parse_dependencies(command_output(
            ["/usr/bin/otool", "-arch", "arm64", "-L", str(path)], log,
        ))
        rpaths = parse_rpaths(command_output(
            ["/usr/bin/otool", "-arch", "arm64", "-l", str(path)], log,
        ))
        for value in dependencies + rpaths:
            validate_install_path(value)
        audit[path] = {"architectures": architectures, "file": description.strip(),
                       "dependencies": dependencies, "rpaths": rpaths}
        relative = path.relative_to(app).as_posix()
        if path == executable:
            categories.add("executable")
        if path.name == "Python" or path.name.startswith("libpython3.12"):
            categories.add("python")
        for name in ("QtCore", "QtGui", "QtWidgets"):
            if path.name == name or path.name.startswith(f"libQt6{name[2:]}"):
                categories.add(name)
        if "shiboken6/" in relative and path.suffix == ".so":
            categories.add("shiboken")
        if "scipy/" in relative and path.suffix == ".so":
            categories.add("scipy")
        if path.name == "libqcocoa.dylib":
            categories.add("cocoa")
    required = {"executable", "python", "QtCore", "QtGui", "QtWidgets", "shiboken", "scipy", "cocoa"}
    if missing := required - categories:
        raise RuntimeError(f"Required Mach-O runtime categories missing: {missing}")
    # PyInstaller relocates all collected libraries to Frameworks. Resolve each
    # @rpath against actual bundle runpaths; every target must exist locally.
    runpaths = [expand_loader_path(value, binary, executable)
                for binary, record in audit.items() for value in record["rpaths"]
                if not value.startswith("@rpath")]
    for binary, record in audit.items():
        for value in record["dependencies"]:
            if value.startswith(SYSTEM_PREFIXES):
                continue
            if value.startswith("@rpath/"):
                candidates = [root / value[7:] for root in runpaths]
            else:
                candidates = [expand_loader_path(value, binary, executable)]
            if not any(path.exists() and path.resolve().is_relative_to(app) for path in candidates):
                raise RuntimeError(f"Unresolved bundle dependency: {binary}: {value}")
        for value in record["rpaths"]:
            if value.startswith(SYSTEM_PREFIXES):
                continue
            if value.startswith("@rpath"):
                raise RuntimeError(f"Recursive @rpath is not an accepted runpath: {binary}: {value}")
            if not expand_loader_path(value, binary, executable).resolve().is_relative_to(app):
                raise RuntimeError(f"Runpath escapes bundle: {binary}: {value}")
    return {"status": "PASS", "native_binary_count": len(audit), "categories": sorted(categories),
            "binaries": {path.relative_to(app).as_posix(): item for path, item in audit.items()}}


def verify_codesign(app: Path, log: Path, *, allow_signing: bool = False) -> dict[str, str]:
    try:
        command_output(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], log)
    except RuntimeError:
        if not allow_signing:
            raise
        command_output(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)], log)
        command_output(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], log)
    details = command_output(["/usr/bin/codesign", "-dv", "--verbose=4", str(app)], log)
    if "Signature=adhoc" not in details:
        raise RuntimeError("Internal release requires actual ad-hoc signing")
    return {"codesign": "AD_HOC", "verification": "PASS", "notarization": "NOT_PERFORMED"}


def archive_roundtrip(app: Path, archive: Path, extracted_root: Path) -> Path:
    if archive.exists() or extracted_root.exists():
        raise FileExistsError("Archive and extraction destinations must be fresh")
    if archive.resolve().is_relative_to(app.resolve()):
        raise ValueError("ZIP must be outside app bundle")
    before = bundle_manifest(app)
    # Current Apple DTS guidance advises against --sequesterRsrc for software
    # distribution: https://developer.apple.com/forums/thread/775923
    command_output(["/usr/bin/ditto", "-c", "-k", "--keepParent",
                    str(app), str(archive)])
    extracted_root.mkdir()
    command_output(["/usr/bin/ditto", "-x", "-k", str(archive), str(extracted_root)])
    extracted = extracted_root / app.name
    if before != bundle_manifest(extracted):
        raise RuntimeError("ZIP roundtrip changed file type/mode/link target/SHA-256")
    verify_bundle(extracted)
    return extracted


def validate_startup_report(report: dict[str, Any], app: Path) -> None:
    if not all(report.get(key) is True for key in (
        "application_created", "main_window_created", "event_loop_entered", "window_visible", "normal_exit",
    )) or report.get("qt_platform") != "cocoa" or report.get("exit_code") != 0:
        raise RuntimeError("NATIVE_GUI_NOT_VERIFIED: native Cocoa lifecycle failed")
    if report.get("architecture") != "arm64":
        raise RuntimeError("Runtime architecture is not arm64")
    if report.get("version") != __version__ or report.get("gui_version") != __version__:
        raise RuntimeError("Runtime version differs")
    paths = report.get("runtime_paths", {})
    if not REQUIRED_RUNTIME_KEYS.issubset(paths):
        raise RuntimeError("Required loaded native images missing")
    for key, value in paths.items():
        path = Path(value).resolve()
        if not path.is_relative_to(app.resolve()):
            raise RuntimeError(f"Runtime loaded outside app bundle: {key}: {path}")
        if key.endswith("_image") and not path.is_file():
            raise RuntimeError(f"Loaded image does not exist: {key}: {path}")
    analysis = report.get("analysis_smoke") or {}
    if analysis.get("status") != "PASS" or not analysis.get("input_unchanged"):
        raise RuntimeError("Release scientific smoke failed")
    if not Path(analysis["core_module"]).resolve().is_relative_to(app.resolve()):
        raise RuntimeError("Scientific core loaded outside app bundle")


def run_native_smoke(app: Path, evidence: Path, source: Path) -> dict[str, Any]:
    executable = verify_bundle(app)
    runtime_root = evidence / "isolated_runtime"
    runtime_root.mkdir()
    report_path = runtime_root / "startup.json"
    command = [str(executable), "--startup-smoke-test", str(report_path),
               "--analysis-smoke-input", str(source)]
    report: dict[str, Any] = {"status": "NATIVE_GUI_NOT_VERIFIED", "command": command}
    try:
        result = subprocess.run(command, cwd=runtime_root, env=isolated_environment(),
                                capture_output=True, text=True, timeout=180)
        report.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        if report_path.exists():
            report.update(json.loads(report_path.read_text(encoding="utf-8")))
        if result.returncode != 0:
            raise RuntimeError(f"Cocoa process exit={result.returncode}: {result.stderr}")
        validate_startup_report(report, app)
        report["status"] = "PASS"
        return report
    except Exception as exc:
        report.update(status="NATIVE_GUI_NOT_VERIFIED", failure=f"{type(exc).__name__}: {exc}")
        raise RuntimeError(f"NATIVE_GUI_NOT_VERIFIED: {exc}") from exc
    finally:
        write_json(evidence / "startup_smoke.json", report)


def build_release(output: Path, source: Path, reference_path: Path) -> None:
    require_native_environment()
    output = output.resolve()
    if output.exists():
        raise FileExistsError("Output root must be new; no existing files are deleted")
    if output == ROOT or ROOT.is_relative_to(output) or output.is_relative_to(ROOT / "data"):
        raise ValueError("Unsafe output root")
    output.mkdir(parents=True)
    evidence = output / "evidence"
    evidence.mkdir()
    manifest: dict[str, Any] = {
        "status": "MACOS INTERNAL RELEASE BLOCKED", "release_version": __version__,
        "codesign": "NOT_VERIFIED", "notarization": "NOT_PERFORMED",
        "native_gui": "NATIVE_GUI_NOT_VERIFIED",
        "workflow_run": os.environ.get("GITHUB_RUN_ID"),
        "workflow_url": (f"https://github.com/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/"
                         f"{os.environ.get('GITHUB_RUN_ID')}"),
        "commit": command_output(["git", "rev-parse", "HEAD"], cwd=ROOT).strip(),
        "full_local_real_data_suite": "NOT_VERIFIED_BY_MACOS_PUBLIC_CI",
    }
    raw_before = {path.relative_to(ROOT).as_posix(): file_hash(path)
                  for path in sorted((ROOT / "data/raw").rglob("*")) if path.is_file()}
    try:
        versions = check_constraints()
        write_json(evidence / "dependency_versions.json", versions)
        write_json(evidence / "environment.json", {
            **reference_environment(), "macos_version": command_output(["/usr/bin/sw_vers"]),
            "uname_m": command_output(["/usr/bin/uname", "-m"]).strip(),
            "python_executable": sys.executable, "conda_prefix": sys.prefix,
            "runner": os.environ.get("RUNNER_NAME"), "runner_os": os.environ.get("RUNNER_OS"),
            "runner_arch": os.environ.get("RUNNER_ARCH"),
            "runtime_environment": {
                "PATH": isolated_environment()["PATH"], "QT_QPA_PLATFORM": "cocoa",
                "injection_variables": "PYTHON*/CONDA*/QT*/DYLD*/LD_*/PYSIDE*/QML*/_PYI_*/VIRTUAL_ENV removed",
            },
        })
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        if reference["environment"]["platform"] != "Windows":
            raise RuntimeError("Numerical reference is not from Windows Production")
        if reference["environment"]["dependencies"] != dependency_versions():
            raise RuntimeError("Mac dependencies differ from Windows reference")
        if reference["environment"]["python"] != platform.python_version():
            raise RuntimeError("Mac Python differs from Windows reference")
        for relative, digest in reference["scientific_source_sha256_lf"].items():
            if lf_text_hash(ROOT / relative) != digest:
                raise RuntimeError(f"Scientific source changed since Windows reference: {relative}")
        icon = evidence / "icon/pdv_studio.icns"
        master = ROOT / "src/dps_studio/gui/icons/pdv_studio_master.png"
        master_sha = file_hash(master)
        generate_icon(master, icon, output / "icon/pdv_studio.iconset")
        if master_sha != file_hash(master):
            raise RuntimeError("Icon generator modified the approved master")
        write_json(evidence / "icon_generation.json", {
            "master": "src/dps_studio/gui/icons/pdv_studio_master.png", "master_sha256": master_sha,
            "output_sha256": file_hash(icon), "generator": "tools/build_macos_icon.py",
            "native_command": ["/usr/bin/iconutil", "-c", "icns", "-o", str(icon),
                               str(output / "icon/pdv_studio.iconset")],
            "master_unchanged": True,
        })
        environment = dict(os.environ)
        environment["DPS_MACOS_ICON"] = str(icon)
        command_output([
            sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
            "--distpath", str(output / "dist"), "--workpath", str(output / "work"),
            str(ROOT / "packaging/pdv_studio_macos.spec"),
        ], evidence / "pyinstaller_build.txt", cwd=ROOT, env=environment)
        app = output / "dist/PDV Studio.app"
        verify_bundle(app)
        manifest["mach_o"] = audit_mach_o(app, evidence / "mach_o_audit.txt")
        manifest.update(verify_codesign(app, evidence / "codesign_audit.txt", allow_signing=True))
        archive = output / f"PDV_Studio_v{__version__}_macos_arm64.zip"
        extracted = archive_roundtrip(app, archive, output / "extracted")
        manifest["archive_roundtrip"] = "PASS"
        manifest["final_mach_o"] = audit_mach_o(extracted, evidence / "mach_o_audit.txt")
        verify_codesign(extracted, evidence / "codesign_audit.txt")
        manifest["final_codesign"] = "PASS"
        source_sha = file_hash(source)
        # The already tracked public example is read directly, never copied from data/raw.
        startup = run_native_smoke(extracted, evidence, source)
        manifest["native_gui"] = "PASS"
        analysis = startup["analysis_smoke"]
        numerical = compare_snapshots(reference, analysis["numerical_snapshot"])
        numerical.update(input_sha256=source_sha, windows_reference_sha256=file_hash(reference_path),
                         windows_production_commit=reference["production_commit"],
                         scientific_smoke="PASS", release_runtime_app=str(extracted))
        write_json(evidence / "analysis_regression.json", numerical)
        if numerical["status"] != "PASS":
            raise RuntimeError(f"Numerical regression failed; investigate decisions: {numerical['failures']}")
        if source_sha != file_hash(source):
            raise RuntimeError("Final scientific smoke changed public input")
        if bundle_manifest(app) != bundle_manifest(extracted):
            raise RuntimeError("Final smoke modified the signed bundle")
        verify_codesign(extracted, evidence / "codesign_audit.txt")
        manifest.update(status="MACOS INTERNAL RELEASE PASS", native_gui="PASS",
                        window_exposed=startup["window_exposed"],
                        app=str(app), extracted_app=str(extracted), archive=str(archive),
                        zip_sha256=file_hash(archive), icon_sha256=file_hash(icon))
        write_json(evidence / "hash_manifest.json", {
            "zip": {archive.name: file_hash(archive)}, "app": bundle_manifest(app),
            "extracted_app": bundle_manifest(extracted), "input_sha256": source_sha,
            "raw_before": raw_before,
        })
    except Exception as exc:
        manifest.update(status="MACOS INTERNAL RELEASE BLOCKED", failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        raw_after = {path.relative_to(ROOT).as_posix(): file_hash(path)
                     for path in sorted((ROOT / "data/raw").rglob("*")) if path.is_file()}
        manifest["raw_unchanged"] = raw_before == raw_after
        if not manifest["raw_unchanged"]:
            manifest["status"] = "MACOS INTERNAL RELEASE BLOCKED"
        write_json(evidence / "build_manifest.json", manifest)
        if not manifest["raw_unchanged"]:
            raise RuntimeError("Raw hashes changed during release")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--analysis-input", type=Path, default=ROOT / "docs/原始数据.csv")
    parser.add_argument("--reference", type=Path,
                        default=ROOT / "tests/reference/macos_portable_reference_v014.json")
    args = parser.parse_args()
    build_release(args.output_root, args.analysis_input, args.reference)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
