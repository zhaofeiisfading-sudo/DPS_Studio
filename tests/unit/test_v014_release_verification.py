"""Release gate regressions for native origin, exact ZIP sets, and real exports."""

from __future__ import annotations

import json
import runpy
import shutil
import zipfile
from pathlib import Path

import pytest

from dps_studio import __version__
from dps_studio.gui.release_smoke import run_analysis_smoke, smoke_options


ROOT = Path(__file__).resolve().parents[2]
BUILD = runpy.run_path(str(ROOT / "tools/build_production_release.py"))


@pytest.mark.parametrize("arguments", [[], ["PDV Studio.exe", "-platform", "windows"]])
def test_ordinary_gui_arguments_do_not_enable_smoke(arguments):
    assert smoke_options(arguments) == (None, None)


@pytest.mark.parametrize("arguments", [
    ["--startup-smoke-test"], ["--startup-smoke-test", "--analysis-smoke-input"],
    ["--analysis-smoke-input", "example.csv"],
])
def test_invalid_smoke_arguments_are_explicit_errors(arguments):
    with pytest.raises(ValueError):
        smoke_options(arguments)


def test_native_runtime_outside_the_extracted_release_blocks_acceptance(tmp_path):
    names = ("PySide6", "shiboken6", "scipy._lib._ccallback_c", "qwindows.dll", "QtCore.pyd",
             "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Shiboken.pyd", "shiboken6.abi3.dll")
    report = {
        "event_loop_entered": True, "window_visible": True, "window_exposed": True,
        "qt_platform": "windows", "version": __version__, "gui_version": __version__,
        "runtime_paths": {name: str(tmp_path / "release" / name) for name in names},
    }
    BUILD["validate_startup_report"](report, tmp_path / "release", require_analysis=False)
    report["runtime_paths"]["qwindows.dll"] = str(tmp_path / "foreign" / "qwindows.dll")
    with pytest.raises(RuntimeError, match="outside the extracted release"):
        BUILD["validate_startup_report"](report, tmp_path / "release", require_analysis=False)


def test_smoke_acceptance_requires_exposed_window_and_loaded_native_runtime(tmp_path):
    with pytest.raises(RuntimeError, match="Unexpected startup report"):
        BUILD["validate_startup_report"]({"event_loop_entered": True}, tmp_path, require_analysis=False)
    report = {
        "event_loop_entered": True, "window_visible": True, "window_exposed": True,
        "qt_platform": "windows", "version": __version__, "gui_version": __version__,
        "runtime_paths": {},
    }
    with pytest.raises(RuntimeError, match="required loaded native runtimes"):
        BUILD["validate_startup_report"](report, tmp_path, require_analysis=False)


@pytest.mark.parametrize("change", ["extra", "missing", "changed"])
def test_zip_verification_rejects_different_file_sets_or_bytes(tmp_path, change):
    directory = tmp_path / "PDV_Studio_example"
    directory.mkdir()
    (directory / "keep.txt").write_text("original", encoding="utf-8")
    (directory / "second.txt").write_text("second", encoding="utf-8")
    archive_path = tmp_path / "example.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"{directory.name}/keep.txt", "changed" if change == "changed" else "original")
        if change != "missing":
            archive.writestr(f"{directory.name}/second.txt", "second")
        if change == "extra":
            archive.writestr(f"{directory.name}/extra.txt", "unexpected")
    with pytest.raises(RuntimeError, match="file set or SHA-256 differs"):
        BUILD["verify_release_zip"](directory, archive_path)


def test_existing_zip_is_not_overwritten(tmp_path):
    directory = tmp_path / "release"
    directory.mkdir()
    (directory / "payload.txt").write_text("payload", encoding="utf-8")
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"historical ZIP remains unchanged")
    with pytest.raises(FileExistsError):
        BUILD["create_release_zip"](directory, archive)
    assert archive.read_bytes() == b"historical ZIP remains unchanged"


def test_real_release_analysis_preserves_both_csv_modes_and_current_version(tmp_path):
    source = tmp_path / "example.csv"
    shutil.copyfile(ROOT / "docs" / "原始数据.csv", source)
    report = run_analysis_smoke(source, tmp_path / "exports")
    assert report["status"] == "PASS"
    assert report["input_unchanged"]
    assert report["sample_count"] == 80000
    for channel in report["channels"].values():
        assert channel["continuous_rows"] > channel["quality_rows"] > 0
        assert channel["continuous_rows"] == channel["detail_rows"]
        assert channel["version"] == __version__
        document = json.loads(Path(channel["metadata_json"]).read_text(encoding="utf-8"))
        assert document["software_version"] == document["dps_studio_version"] == __version__
        assert document["input_provenance"]["original_time_unit"] == "s"
        assert document["input_provenance"]["original_voltage_unit"] == "V"
