"""Portable failure-gate tests; they do not claim a native macOS build."""

from __future__ import annotations

import copy
import json
import plistlib
import runpy
import shutil
import stat
import sys
from pathlib import Path

import pytest

from dps_studio import __version__
from dps_studio.gui import release_smoke
from dps_studio.gui.release_smoke_macos import finish_report, match_loaded_image
from dps_studio.release.portable_reference import capture_snapshot, compare_snapshots, lf_text_hash
from tools import build_macos_release as mac
from tools.build_macos_icon import ICONSET_SIZES, generate_icon


ROOT = Path(__file__).resolve().parents[2]


def valid_startup(tmp_path: Path) -> tuple[dict, Path]:
    app = tmp_path / "PDV Studio.app"
    app.mkdir()
    paths = {}
    for key in mac.REQUIRED_RUNTIME_KEYS:
        path = app / key
        path.write_bytes(b"fixture: gate test, not a native binary")
        paths[key] = str(path)
    report = {
        "application_created": True, "main_window_created": True,
        "event_loop_entered": True, "window_visible": True,
        "normal_exit": True, "exit_code": 0, "architecture": "arm64",
        "window_exposed": True, "qt_platform": "cocoa", "version": __version__,
        "gui_version": __version__, "runtime_paths": paths,
        "analysis_smoke": {"status": "PASS", "input_unchanged": True,
                           "core_module": str(app / "core/analysis.py")},
    }
    return report, app


@pytest.mark.parametrize(("key", "value"), [
    ("qt_platform", "offscreen"), ("qt_platform", "minimal"), ("normal_exit", False),
    ("main_window_created", False), ("event_loop_entered", False), ("window_visible", False),
    ("application_created", False),
    ("exit_code", 1), ("architecture", "x86_64"), ("version", "foreign-version"),
])
def test_native_acceptance_rejects_lifecycle_platform_architecture(tmp_path, key, value):
    report, app = valid_startup(tmp_path)
    report[key] = value
    with pytest.raises(RuntimeError):
        mac.validate_startup_report(report, app)


def test_cocoa_exposure_is_reported_but_not_fabricated(tmp_path):
    report, app = valid_startup(tmp_path)
    report["window_exposed"] = False
    mac.validate_startup_report(report, app)


@pytest.mark.parametrize("runtime", sorted(mac.REQUIRED_RUNTIME_KEYS))
def test_each_runtime_must_load_inside_the_extracted_app(tmp_path, runtime):
    report, app = valid_startup(tmp_path)
    report["runtime_paths"][runtime] = str(tmp_path / "conda-env" / runtime)
    with pytest.raises(RuntimeError, match="outside app bundle"):
        mac.validate_startup_report(report, app)


def test_missing_loaded_image_blocks_release(tmp_path):
    report, app = valid_startup(tmp_path)
    del report["runtime_paths"]["Cocoa_plugin_image"]
    with pytest.raises(RuntimeError, match="images missing"):
        mac.validate_startup_report(report, app)


def test_dyld_probe_requires_an_actually_loaded_image(tmp_path):
    native = str(tmp_path / "_ccallback_c.so")
    with pytest.raises(RuntimeError, match="not loaded"):
        match_loaded_image(native, [])
    assert match_loaded_image(native, [str(Path(native).resolve())]) == str(Path(native).resolve())


def test_minimal_darwin_dispatch_preserves_windows_probe(monkeypatch):
    from dps_studio.gui import release_smoke_macos

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(release_smoke_macos, "loaded_runtime_paths", lambda: {"Cocoa": "native"})
    assert release_smoke.loaded_runtime_paths() == {"Cocoa": "native"}
    source = (ROOT / "src/dps_studio/gui/release_smoke.py").read_text(encoding="utf-8")
    assert 'ctypes.WinDLL("kernel32"' in source
    assert '"qwindows.dll"' in source


def test_report_records_exit_only_after_event_loop_returns(tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{"event_loop_entered": true}', encoding="utf-8")
    finish_report(path, 1)
    report = json.loads(path.read_text())
    assert report["normal_exit"] is False
    assert report["exit_code"] == 1


def test_smoke_environment_scrubs_injection_and_forces_cocoa(monkeypatch):
    for key in ("PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "QT_PLUGIN_PATH",
                "QT_QPA_PLATFORM_PLUGIN_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
                "DYLD_INSERT_LIBRARIES", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__", "_PYI_HOME_DIR"):
        monkeypatch.setenv(key, "/foreign")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    environment = mac.isolated_environment()
    assert environment["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert environment["QT_QPA_PLATFORM"] == "cocoa"
    assert "/foreign" not in environment.values()


@pytest.mark.parametrize("dependency", [
    "/opt/homebrew/lib/libQt6Core.dylib", "/Users/runner/miniforge3/lib/libpython.dylib",
    "/Users/runner/work/DPS_Studio/lib.dylib", "relative/lib.dylib", "/usr/library/lib.dylib",
    "@rpath", "@rpathwrong/lib.dylib",
])
def test_external_or_ambiguous_install_names_are_rejected(dependency):
    with pytest.raises(RuntimeError, match="dependency/rpath"):
        mac.validate_install_path(dependency)


@pytest.mark.parametrize("dependency", [
    "/System/Library/Frameworks/AppKit.framework/AppKit", "/usr/lib/libSystem.B.dylib",
    "@rpath/QtCore", "@loader_path/../Frameworks/Python", "@executable_path/../Frameworks",
    "@loader_path",
])
def test_approved_install_names_are_accepted(dependency):
    mac.validate_install_path(dependency)


def test_otool_parsers_keep_dependency_and_runpath_spaces():
    output = "binary:\n\t@rpath/PDV Studio.dylib (compatibility version 1.0.0, current version 1.0.0)\n"
    assert mac.parse_dependencies(output) == ["@rpath/PDV Studio.dylib"]
    output = "Load command 1\n cmd LC_RPATH\n cmdsize 48\n path @loader_path/../Frameworks (offset 12)\n"
    assert mac.parse_rpaths(output) == ["@loader_path/../Frameworks"]


def test_bundle_manifest_detects_file_bytes_and_keeps_file_type_mode(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    nested = app / "Contents"
    nested.mkdir()
    payload = nested / "payload"
    payload.write_bytes(b"before")
    before = mac.bundle_manifest(app)
    assert before["Contents"]["kind"] == "directory"
    assert before["Contents/payload"]["kind"] == "file"
    assert before["Contents/payload"]["mode"] == stat.S_IMODE(payload.stat().st_mode)
    payload.write_bytes(b"after")
    assert mac.bundle_manifest(app) != before


def miniature_bundle(tmp_path: Path) -> tuple[Path, list[Path]]:
    app = tmp_path / "PDV Studio.app"
    binaries = [
        app / "Contents/MacOS/PDV Studio", app / "Contents/Frameworks/Python",
        *[app / f"Contents/Frameworks/{name}.framework/Versions/A/{name}"
          for name in ("QtCore", "QtGui", "QtWidgets")],
        app / "Contents/Frameworks/shiboken6/Shiboken.abi3.so",
        app / "Contents/Frameworks/scipy/_lib/_ccallback_c.so",
        app / "Contents/Frameworks/PySide6/Qt/plugins/platforms/libqcocoa.dylib",
    ]
    for path in binaries:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xcf\xfa\xed\xfe" + b"gate fixture")
        path.chmod(0o755)
    resources = app / "Contents/Resources"
    resources.mkdir()
    for name in ("pdv_studio_defaults.toml", "pdv_studio_en.qm", "pdv_studio.ico"):
        (resources / name).write_bytes(b"gate fixture")
    (resources / "pdv_studio.icns").write_bytes(b"icnsgate fixture")
    with (app / "Contents/Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": "com.dpsstudio.pdvstudio",
                      "CFBundleVersion": __version__, "CFBundleShortVersionString": __version__,
                      "CFBundleExecutable": "PDV Studio", "CFBundleIconFile": "pdv_studio.icns"}, handle)
    return app, binaries


@pytest.mark.parametrize("failure", ["x86_64_only", "external_dependency", "external_rpath", "missing_target"])
def test_mach_o_gate_rejects_architecture_and_dependency_failures(tmp_path, monkeypatch, failure):
    app, _ = miniature_bundle(tmp_path)

    def output(command, log=None, **kwargs):
        if command[0].endswith("file"):
            return "Mach-O 64-bit executable arm64"
        if command[0].endswith("lipo"):
            return "x86_64" if failure == "x86_64_only" else "arm64"
        if "-L" in command:
            if failure == "external_dependency":
                return "binary:\n\t/opt/homebrew/lib/libfoo.dylib (compatibility version 1)\n"
            if failure == "missing_target":
                return "binary:\n\t@rpath/missing.dylib (compatibility version 1)\n"
            return "binary:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1)\n"
        if failure == "external_rpath":
            return "cmd LC_RPATH\n path /Users/runner/miniforge3/lib (offset 12)\n"
        return ""

    monkeypatch.setattr(mac, "command_output", output)
    with pytest.raises(RuntimeError):
        mac.audit_mach_o(app, tmp_path / "audit.txt")


def test_existing_output_is_never_deleted_or_reused(tmp_path, monkeypatch):
    output = tmp_path / "release"
    output.mkdir()
    historical = output / "history"
    historical.write_bytes(b"do not overwrite")
    monkeypatch.setattr(mac, "require_native_environment", lambda: None)
    with pytest.raises(FileExistsError):
        mac.build_release(output, tmp_path / "source.csv", tmp_path / "reference.json")
    assert historical.read_bytes() == b"do not overwrite"


def test_mac_entry_rejects_other_platform_before_creating_output(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="native macOS arm64"):
        mac.build_release(tmp_path / "new", tmp_path / "source", tmp_path / "reference")
    assert not (tmp_path / "new").exists()


def test_icon_generator_requires_native_iconutil_without_touching_master(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.build_macos_icon.platform.system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="iconutil"):
        generate_icon(tmp_path / "master", tmp_path / "icon.icns", tmp_path / "icon.iconset")
    assert not list(tmp_path.iterdir())
    assert set(ICONSET_SIZES.values()) == {16, 32, 64, 128, 256, 512, 1024}


def test_macos_spec_uses_bundle_arm64_and_single_version_source(tmp_path, monkeypatch):
    calls = {}

    def constructor(name):
        def create(*args, **kwargs):
            calls[name] = kwargs
            return type("BuildFixture", (), {"pure": [], "scripts": [], "binaries": [], "datas": []})()
        return create

    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"icns")
    monkeypatch.setenv("DPS_MACOS_ICON", str(icon))
    runpy.run_path(str(ROOT / "packaging/pdv_studio_macos.spec"), init_globals={
        "SPECPATH": str(ROOT / "packaging"),
        **{name: constructor(name) for name in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")},
    })
    assert calls["EXE"]["target_arch"] == "arm64"
    assert calls["EXE"]["console"] is False
    assert calls["BUNDLE"]["name"] == "PDV Studio.app"
    assert calls["BUNDLE"]["version"] == __version__
    assert calls["BUNDLE"]["info_plist"]["CFBundleVersion"] == __version__


def small_snapshot():
    return {"channels": {"channel": {
        "vectors": {"refined_frequency_hz": [None, 450e6, 450e6]},
        "ridge_bins": [[12, 3]], "quality_flags": [["candidate", 3]],
        "nan_masks": {"refined_frequency_hz": [[True, 1], [False, 2]]},
        "event_selection": {"primary_segment_id": "segment_1"},
        "frame_count": 3,
    }}, "export_schema": {"continuous": {"rows": 3, "columns": ["time_s", "velocity_m_s"]}}}


def test_numerical_contract_accepts_roundoff_with_audited_tolerance():
    expected = small_snapshot()
    actual = copy.deepcopy(expected)
    actual["channels"]["channel"]["vectors"]["refined_frequency_hz"][1] += 0.01
    report = compare_snapshots(expected, actual)
    assert report["status"] == "PASS"
    assert report["metrics"]["snapshot.channels.channel.vectors.refined_frequency_hz"]["max_abs_difference"] > 0


@pytest.mark.parametrize(("key", "value"), [
    ("ridge_bins", [[13, 3]]), ("quality_flags", [["no_allowed_bins", 3]]),
    ("nan_masks", {"refined_frequency_hz": [[False, 3]]}),
    ("event_selection", {"primary_segment_id": "segment_2"}), ("frame_count", 4),
    ("vectors", {"refined_frequency_hz": [0.0, 450e6, 450e6]}),
    ("vectors", {"refined_frequency_hz": [None, 450e6 + 10, 450e6]}),
])
def test_numerical_contract_never_relaxes_discrete_decisions(tmp_path, key, value):
    expected = small_snapshot()
    actual = copy.deepcopy(expected)
    actual["channels"]["channel"][key] = value
    assert compare_snapshots(expected, actual)["status"] == "FAIL"


def test_schema_change_blocks_numerical_acceptance():
    expected = small_snapshot()
    actual = copy.deepcopy(expected)
    actual["export_schema"]["continuous"]["columns"].append("extra")
    report = compare_snapshots(expected, actual)
    assert report["status"] == "FAIL"
    assert report["schema_equality"] is False


def test_line_ending_hash_accepts_only_crlf_lf_difference(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.write_bytes(b"time,voltage\r\n1,2\r\n")
    right.write_bytes(b"time,voltage\n1,2\n")
    assert lf_text_hash(left) == lf_text_hash(right)
    right.write_bytes(b"time,voltage\n1,3\n")
    assert lf_text_hash(left) != lf_text_hash(right)


def test_portable_selection_is_explicit_and_full_suite_retains_raw_tests():
    contract = runpy.run_path(str(ROOT / "tests/conftest.py"))
    for nodeid in contract["REAL_DATA_TESTS"]:
        assert contract["portable_exclusion"](nodeid)
    assert contract["portable_exclusion"]("tests/unit/test_stft.py::test_synthetic") is None
    assert len(contract["REAL_DATA_TESTS"]) == 4


def test_public_scientific_chain_matches_windows_reference(tmp_path):
    reference = json.loads((ROOT / "tests/reference/macos_portable_reference_v014.json").read_text())
    actual = capture_snapshot(ROOT / "docs/原始数据.csv", tmp_path / "exports")
    report = compare_snapshots(reference, actual)
    assert report["status"] == "PASS", report["failures"]
    assert report["nan_mask_equality"] and report["quality_flag_equality"]
    assert report["ridge_bin_equality"] and report["event_selection_equality"]
    assert report["row_count_equality"] and report["schema_equality"]


@pytest.mark.parametrize("change", ["bytes", "mode", "missing"])
def test_archive_gate_rejects_ditto_roundtrip_damage(tmp_path, monkeypatch, change):
    app, binaries = miniature_bundle(tmp_path)
    archive = tmp_path / "release.zip"
    extraction = tmp_path / "extracted"

    def fake_ditto(command, log=None, **kwargs):
        assert "--sequesterRsrc" not in command
        if "-c" in command:
            archive.write_bytes(b"mock archive, never a release artifact")
        else:
            shutil.copytree(app, extraction / app.name)
            payload = extraction / app.name / binaries[0].relative_to(app)
            if change == "bytes":
                payload.write_bytes(b"corrupt")
            elif change == "mode":
                payload.chmod(0o444)
            else:
                payload.unlink()
        return ""

    monkeypatch.setattr(mac, "command_output", fake_ditto)
    with pytest.raises(RuntimeError, match="roundtrip changed"):
        mac.archive_roundtrip(app, archive, extraction)


def test_archive_gate_does_not_overwrite_previous_archive(tmp_path):
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"previous release")
    with pytest.raises(FileExistsError):
        mac.archive_roundtrip(tmp_path / "app", archive, tmp_path / "extracted")
    assert archive.read_bytes() == b"previous release"


def test_codesign_gate_rejects_unexpected_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(mac, "command_output", lambda *args, **kwargs: "Authority=Developer ID Application")
    with pytest.raises(RuntimeError, match="ad-hoc signing"):
        mac.verify_codesign(tmp_path / "app", tmp_path / "audit")


def test_final_codesign_failure_must_not_be_hidden_by_resigning(tmp_path, monkeypatch):
    commands = []

    def failure(command, *args, **kwargs):
        commands.append(command)
        raise RuntimeError("signature invalid after archive roundtrip")

    monkeypatch.setattr(mac, "command_output", failure)
    with pytest.raises(RuntimeError, match="signature invalid"):
        mac.verify_codesign(tmp_path / "app", tmp_path / "audit")
    assert len(commands) == 1
    assert "--sign" not in commands[0]


def test_initial_signing_fallback_is_verified_and_reported_as_ad_hoc(tmp_path, monkeypatch):
    commands = []

    def command_output(command, *args, **kwargs):
        commands.append(command)
        if len(commands) == 1:
            raise RuntimeError("PyInstaller bundle signature needs repair")
        return "Signature=adhoc" if "-dv" in command else ""

    monkeypatch.setattr(mac, "command_output", command_output)
    report = mac.verify_codesign(tmp_path / "app", tmp_path / "audit", allow_signing=True)
    assert report == {"codesign": "AD_HOC", "verification": "PASS", "notarization": "NOT_PERFORMED"}
    assert "--sign" in commands[1] and commands[1][-2] == "-"
    assert "--verify" in commands[2]
