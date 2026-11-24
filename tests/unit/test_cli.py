from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication, QImage

from dps_studio import __version__, cli
from dps_studio.cli import main
from dps_studio.cli_plots import headless_plot_application, render_bundle_spectrogram_ridge
from dps_studio.core.analysis_profiles import AnalysisParameterOverrides
from dps_studio.core.export import (
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultBundleOptions,
    export_result_bundle,
)
from dps_studio.core.io.delimited import read_delimited_signals
from dps_studio.core.physics.models import (
    LIF_RIGG_2014_1550NM,
    VelocityCorrectionConfig,
    WindowMaterial,
)
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.analysis_adapter import AnalysisRequest, AnalysisRunResult, _AnalysisWorker
from dps_studio.gui.analysis_session import AnalysisRange, AnalysisSession, RidgeSearchRegion
from dps_studio.runtime_paths import USERDATA_ENV_VAR, RuntimeStorageError, window_preset_file_path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = [
    "time_column", "time_unit", "voltage_columns", "voltage_units", "vacuum_wavelength_m",
    "measurement_angle_deg", "window_material",
]
PLOTS = ("spectrogram", "ridge", "velocity", "acceleration")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _local_userdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(USERDATA_ENV_VAR, str(tmp_path / "userdata"))
    # Register both variables with monkeypatch before runtime storage changes them.
    for key in ("MPLCONFIGDIR", "QT_SETTINGS_PATH"):
        monkeypatch.setenv(key, str(tmp_path / "before"))


@pytest.fixture
def experiment() -> dict:
    return {
        "time_column": 0, "time_unit": "ns", "voltage_columns": 1, "voltage_units": "mV",
        "vacuum_wavelength_m": 1.55e-6, "measurement_angle_deg": 13.0, "window_material": "LiF",
        "window_length_samples": 128, "overlap_samples": 96, "nfft": 512,
    }


def _config(directory: Path, experiment: dict) -> Path:
    path = directory / "experiment.json"
    path.write_text(json.dumps(experiment), encoding="utf-8")
    return path


def _signal(path: Path) -> Path:
    time_ns = np.arange(4096, dtype=float) * 0.25
    phase = 2 * np.pi * (0.36 * time_ns + 0.00023 * time_ns**2)
    secondary_phase = 2 * np.pi * (0.50 * time_ns + 0.00012 * time_ns**2)
    signal = 800 * np.sin(phase) * (time_ns >= 220)
    second_signal = 0.5 * np.sin(secondary_phase) * (time_ns >= 220)
    np.savetxt(path, np.column_stack((1000 + time_ns, signal, second_signal)), delimiter=",",
               header="time,signal_1,signal_2", comments="")
    return path


def test_no_arguments() -> None:
    assert main([]) == 0


@pytest.mark.parametrize("program", ["pdv", "pdv.exe", "dps-studio"])
def test_version(program: str, monkeypatch: pytest.MonkeyPatch,
                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", [program])
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out == f"{Path(program).stem} {__version__}\n"


def test_module_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    process = subprocess.run(
        [sys.executable, "-B", "-m", "dps_studio", "--help"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    assert "{inspect,analyze,batch}" in process.stdout
    assert "" == process.stderr


def test_headless_qt_fonts_and_lifetime() -> None:
    current = QCoreApplication.instance()
    with headless_plot_application():
        assert isinstance(QCoreApplication.instance(), QGuiApplication)
        font = QFontMetricsF(QFont())
        assert all(font.inFont(character) for character in "Time 0123 (Hz)")
    assert QCoreApplication.instance() is current


@pytest.mark.parametrize("command", ["inspect", "analyze", "batch"])
def test_subcommand_help(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main([command, "--help"])
    assert raised.value.code == 0
    assert command in capsys.readouterr().out


@pytest.mark.parametrize("command", ["inspect", "analyze", "batch"])
@pytest.mark.parametrize("frozen", [False, True])
def test_runtime_storage_error(
    command: str, frozen: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    initialize = Mock(side_effect=RuntimeStorageError("blocked userdata"))
    monkeypatch.setattr(cli, "initialize_runtime_storage", initialize)
    args = [command, str(tmp_path / "input")]
    if command != "inspect":
        args += ["--config", str(tmp_path / "config.json"), "--out", str(tmp_path / "out")]
    assert main(args) == 2
    initialize.assert_called_once_with(redirect_process_temp=frozen)
    assert "blocked userdata" in capsys.readouterr().err


@pytest.mark.parametrize(("delimiter", "detected", "suffix"), [
    (",", ",", ".csv"), ("\t", "\t", ".dat"), ("  \t ", "whitespace", ".dat"),
])
def test_inspect_text(
    delimiter: str, detected: str, suffix: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / f"sample{suffix}"
    source.write_text("\n".join(delimiter.join(row) for row in [
        ("time", "probe"), ("0", "10"), ("1", "20"), ("2", "30"), ("3", "40"),
    ]) + "\n", encoding="utf-8")
    before = _sha256(source)
    output = tmp_path / "inspect.json"
    assert main(["inspect", str(source), "--max-rows", "2", "--out", str(output)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document == _read_json(output)
    assert document["command"] == "inspect"
    assert document["software_version"] == __version__
    assert document["source_path"] == str(source)
    assert document["source_sha256"] == _sha256(source) == before
    assert document["input_unchanged"] is True
    assert document["size_bytes"] == source.stat().st_size
    assert document["column_count"] == 2
    assert document["delimiter"] == detected
    assert document["encoding"] == "utf-8"
    assert document["has_header"] is True
    assert document["header"] == ["time", "probe"]
    assert document["sample_rows"] == [["0", "10"], ["1", "20"]]
    assert document["required_experiment_parameters"] == REQUIRED
    assert "profile" in document["optional_analysis_parameters"]


def test_inspect_repository_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    source = ROOT / "tests/fixtures/test.csv"
    before = _sha256(source)
    assert source.read_bytes().startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    assert main(["inspect", str(source)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "decode" in captured.err or "binary" in captured.err
    assert _sha256(source) == before


@pytest.mark.parametrize("missing", REQUIRED)
def test_analyze_requires_each_experimental_field(
    missing: str, experiment: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    del experiment[missing]
    config = _config(tmp_path, experiment)
    output = tmp_path / "output"
    assert main(["analyze", "unopened.csv", "--config", str(config), "--out", str(output)]) == 2
    assert f"Missing required experimental parameters: {missing}" in capsys.readouterr().err
    assert not output.exists()


def test_analyze_lists_all_missing_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", "unopened.csv", "--out", str(tmp_path / "output")]) == 2
    assert ", ".join(REQUIRED) in capsys.readouterr().err


@pytest.mark.parametrize(("overrides", "message"), [
    ({"profile": "unknown"}, "Unknown profile"),
    ({"analysis_start_time_s": 0.0}, "common input range"),
    ({"event_reference_time_s": 0.0}, "Event reference time"),
    ({"voltage_units": {"another_channel": "V"}}, "every selected channel"),
    ({"window_material": "absent"}, "Unknown window preset"),
    ({"lif_b1": 0.8}, "Explicit window coefficients require"),
    ({"include_acceleration": False, "acceleration_fit_window_s": 5e-8}, "fit window"),
])
def test_invalid_analysis_options(
    overrides: dict, message: str, experiment: dict, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _signal(tmp_path / "input.csv")
    config = _config(tmp_path, experiment | overrides)
    output = tmp_path / "output"
    assert main(["analyze", str(source), "--config", str(config), "--out", str(output)]) == 2
    assert message in capsys.readouterr().err
    assert not output.exists()


def _session_exports(source: Path, output: Path, fit_window: float) -> tuple:
    """Run the GUI's session and worker with the selections used by the CLI test."""
    base = load_workflow_config(ROOT / "configs/pdv_studio_defaults.toml", repository_root=ROOT)
    session = AnalysisSession()
    session.set_workflow_configuration(base, profile=base.analysis.default_profile)
    records = read_delimited_signals(
        source, time_column=0, voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        has_header=True, time_scale=1e-9, original_time_unit="ns",
        voltage_scales={"pdv_channel_1": 1e-3, "pdv_channel_2": 1.0},
        original_voltage_units={"pdv_channel_1": "mV", "pdv_channel_2": "V"},
    ).records
    session.load_records(source_path=source, records=records)
    analysis_range = AnalysisRange(1.10e-6, 1.90e-6)
    session.set_analysis_range(analysis_range)
    session.set_analysis_overrides(AnalysisParameterOverrides(
        window_length_samples=128, overlap_samples=96, nfft=512,
        minimum_frequency_hz=1.2e8, maximum_frequency_hz=9e9,
    ))
    session.set_velocity_correction_config(VelocityCorrectionConfig(
        window_material=WindowMaterial.LIF, measurement_angle_rad=math.radians(13),
    ))
    session.set_event_reference_time_s(1.22e-6)
    configuration = session.run_configuration
    assert configuration is not None
    completed: list[AnalysisRunResult] = []
    failures: list[str] = []

    def run(request: AnalysisRequest) -> AnalysisRunResult:
        worker = _AnalysisWorker(request)
        worker.signals.finished.connect(completed.append)
        worker.signals.failed.connect(lambda _id, _kind, _message, trace: failures.append(trace))
        worker.run()
        assert not failures, failures
        return completed.pop()

    from dps_studio.gui.analysis_adapter import AnalysisResultSource

    stfts = run(AnalysisRequest(
        session.generation_id, session.records, analysis_range,
        configuration, result_source=AnalysisResultSource.SPECTROGRAM,
    )).stft_results
    assert session.accept_stft_results(generation_id=session.generation_id, stft_results=stfts)
    default_region = session.ensure_default_ridge_search_region()
    region = RidgeSearchRegion(
        analysis_range.start_time_s, analysis_range.end_time_s,
        default_region.frequency_min_hz, default_region.frequency_max_hz,
    )
    session.set_ridge_search_region(region)
    result = run(AnalysisRequest(
        session.generation_id, session.records, analysis_range, configuration,
        stft_results=stfts, ridge_search_region=region,
    ))
    assert session.accept_results(
        generation_id=result.generation_id, analyses=result.channel_analyses,
        ridge_search_region=result.ridge_search_region,
    )
    output.mkdir()
    bounds = {
        name: (region.frequency_min_hz, region.frequency_max_hz)
        for name in session.automatic_channel_analyses
    }
    report = export_result_bundle(
        ResultBundleOptions(
            output_directory=output,
            analysis_mode=ResultAnalysisMode.AUTOMATIC,
            channel_analyses=session.automatic_channel_analyses,
            time_origin=ExportTimeOrigin.ABSOLUTE,
            source_path=source,
            analysis_profile_name=configuration.parameters.provenance_name,
            pre_event_display_enabled=configuration.enable_pre_event_display,
            pre_event_display_velocity_m_s=configuration.pre_event_display_velocity_m_s,
            event_reference_source=session.event_reference_source,
            event_time_source=session.event_time_source.value,
            include_acceleration=True,
            acceleration_fit_window_s=fit_window,
            spectrogram_renderer=lambda dst: render_bundle_spectrogram_ridge(
                session.automatic_channel_analyses,
                dst,
                channel_frequency_bounds_hz=bounds,
            ),
        )
    )
    return report, region


def _read_csv_dict(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_analyze_exports_exact_gui_session_results(tmp_path: Path, experiment: dict) -> None:
    source = _signal(tmp_path / "signal.csv")
    before = _sha256(source)
    config = _config(tmp_path, experiment | {
        "analysis_start_time_s": 1.10e-6, "analysis_end_time_s": 1.90e-6,
        "event_reference_time_s": 1.22e-6, "acceleration_fit_window_s": 5e-8,
        "minimum_frequency_hz": 1.2e8, "maximum_frequency_hz": 9e9,
        "voltage_columns": {"pdv_channel_1": 1, "pdv_channel_2": 2},
        "voltage_units": {"pdv_channel_1": "mV", "pdv_channel_2": "V"},
        "include_acceleration": True,
    })
    output = tmp_path / "analyzed"
    assert main(["analyze", str(source), "--config", str(config), "--out", str(output)]) == 0
    assert {p.name for p in output.iterdir()} == {
        "velocity_raw.csv",
        "velocity_gated.csv",
        "velocity_display.csv",
        "run_summary.json",
        "spectrogram_ridge.png",
        "acceleration.csv",
    }
    summary = _read_json(output / "run_summary.json")
    assert summary["source_sha256"] == _sha256(source) == before
    assert summary["input_unchanged"] is True
    assert summary["experimental_conditions"]["voltage_units"] == {
        "pdv_channel_1": "mV", "pdv_channel_2": "V",
    }
    assert summary["experimental_conditions"]["window_model"]["b1"] == LIF_RIGG_2014_1550NM.b1
    quality = summary["quality"]
    gui_report, region = _session_exports(source, tmp_path / "session", 5e-8)
    assert summary["analysis_parameters"]["ridge_search_region"] == {
        key: getattr(region, key) for key in (
            "time_start_s", "time_end_s", "frequency_min_hz", "frequency_max_hz",
        )
    }
    for csv_name in ("velocity_raw.csv", "velocity_gated.csv", "velocity_display.csv", "acceleration.csv"):
        assert (output / csv_name).read_bytes() == (gui_report.output_directory / csv_name).read_bytes()
    for name in gui_report.channel_names:
        assert quality[name]["measured"] > 0
        assert quality[name]["outside_analysis_window"] > 0
        assert quality[name]["median_peak_to_background_db"] > 0
        assert quality[name]["max_peak_to_background_db"] >= quality[name]["median_peak_to_background_db"]
        assert quality[name]["measured_fraction"] == quality[name]["measured"] / quality[name]["total_frames"]
    image = QImage(str(output / "spectrogram_ridge.png"))
    assert image.width() >= 1000 and image.height() >= 1000
    assert image.text("Axes") and image.text("Scale") and image.text("Traces")


def test_toml_flags_override_config(tmp_path: Path) -> None:
    source = _signal(tmp_path / "signal.csv")
    config = tmp_path / "experiment.toml"
    config.write_text(
        'time_column = 0\ntime_unit = "ns"\nvoltage_units = "V"\nvoltage_columns = 1\n'
        'vacuum_wavelength_m = 1.55e-6\nmeasurement_angle_rad = 0.2\nwindow_material = "none"\n'
        'window_length_samples = 128\noverlap_samples = 96\nnfft = 512\nhas_header = false\n',
        encoding="utf-8",
    )
    output = tmp_path / "out"
    assert main([
        "analyze", str(source), "--config", str(config), "--out", str(output),
        "--angle-deg", "0", "--has-header", "--no-acceleration", "--no-pre-event-display",
        "--voltage-columns", "probe_a=1,probe_b=2", "--voltage-units", "probe_a=mV,probe_b=V",
        "--min-freq-hz", "3e9", "--max-freq-hz", "4e9",
    ]) == 0
    summary = _read_json(output / "run_summary.json")
    assert summary["experimental_conditions"]["measurement_angle_rad"] == 0
    assert summary["experimental_conditions"]["window_material"] == "none"
    assert summary["experimental_conditions"]["voltage_units"] == {"probe_a": "mV", "probe_b": "V"}
    assert summary["input_format"]["has_header"] is True
    parameters = summary["analysis_parameters"]
    assert parameters["include_acceleration"] is False
    region = parameters["ridge_search_region"]
    assert region["frequency_min_hz"] == 0.0
    assert region["frequency_max_hz"] == pytest.approx(2e9)
    assert region["time_start_s"] > parameters["analysis_start_time_s"]
    assert region["time_end_s"] < parameters["analysis_end_time_s"]
    assert summary["auto_band_retry"]["enabled"] is False
    assert summary["auto_band_retry"]["reason"] == "explicit_minimum_frequency_hz"
    assert summary["display_processing"]["probe_a"]["pre_event_enabled"] is False
    assert not (output / "acceleration.csv").exists()
    assert not list(output.glob("*_detail.csv"))


def test_analyze_flags_with_existing_core_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    source = _signal(tmp_path / "signal.csv")
    output = tmp_path / "out"
    process = subprocess.run([
        sys.executable, "-B", "-c",
        "from PySide6.QtCore import QCoreApplication; import sys; "
        "from dps_studio.cli import main; app = QCoreApplication([]); "
        "status = main(sys.argv[1:]); assert QCoreApplication.instance() is app; "
        "assert 'matplotlib' not in sys.modules; raise SystemExit(status)",
        "analyze", str(source), "--out", str(output), "--time-column", "0", "--time-unit", "ns",
        "--voltage-columns", "1", "--voltage-units", "mV", "--wavelength-m", "1.55e-6",
        "--angle-deg", "0", "--window-material", "none", "--window-length", "128",
        "--overlap", "96", "--nfft", "512",
    ], capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert {p.name for p in output.iterdir()} == {
        "velocity_raw.csv",
        "velocity_gated.csv",
        "velocity_display.csv",
        "run_summary.json",
        "spectrogram_ridge.png",
    }
    image = QImage(str(output / "spectrogram_ridge.png"))
    assert not image.isNull() and image.text("Axes")


@pytest.mark.parametrize("saved", [True, False])
def test_custom_window_and_radians(saved: bool, experiment: dict, tmp_path: Path) -> None:
    from dataclasses import replace

    name = "Calibrated window"
    if saved:
        WindowPresetRepository(window_preset_file_path()).save(replace(
            LIF_RIGG_2014_1550NM, configuration_name=name, b1=0.8, b2=1.0,
        ))
    else:
        experiment.update(lif_b1=0.8, lif_b2=1.0, lif_reference_wavelength_m=1.55e-6)
    del experiment["measurement_angle_deg"]
    experiment.update(window_material=name, measurement_angle_rad=0.1)
    source = _signal(tmp_path / "signal.csv")
    config = _config(tmp_path, experiment)
    output = tmp_path / "out"
    assert main(["analyze", str(source), "--config", str(config), "--out", str(output)]) == 0
    conditions = _read_json(output / "run_summary.json")["experimental_conditions"]
    assert conditions["measurement_angle_rad"] == 0.1
    assert conditions["window_model"]["configuration_name"] == name
    assert conditions["window_model"]["b1"] == 0.8
    assert conditions["window_model"]["b2"] == 1.0


def test_output_collisions_and_protected_raw(
    tmp_path: Path, experiment: dict, capsys: pytest.CaptureFixture[str],
) -> None:
    source = _signal(tmp_path / "signal.csv")
    config = _config(tmp_path, experiment)
    before = _sha256(source)
    assert main(["inspect", str(source), "--out", str(source)]) == 2
    assert _sha256(source) == before
    raw = tmp_path / "data/raw"
    assert main(["inspect", str(source), "--out", str(raw / "inspect.json")]) == 2
    assert main(["analyze", str(source), "--config", str(config), "--out", str(raw)]) == 2
    assert not raw.exists()
    assert "data/raw" in capsys.readouterr().err
    output = tmp_path / "results"
    output.mkdir()
    existing = output / "velocity_raw.csv"
    existing.write_bytes(b"previous result\n")
    assert main(["analyze", str(source), "--config", str(config), "--out", str(output)]) == 2
    assert list(output.iterdir()) == [existing]
    assert existing.read_bytes() == b"previous result\n"
    assert _sha256(source) == before


def test_source_hash_mismatch_prevents_publish(
    tmp_path: Path, experiment: dict, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _signal(tmp_path / "signal.csv")
    config = _config(tmp_path, experiment)
    monkeypatch.setattr(cli, "_sha256", Mock(side_effect=["before", "after"]))
    output = tmp_path / "output"
    assert main(["analyze", str(source), "--config", str(config), "--out", str(output)]) == 2
    assert "Input changed during processing" in capsys.readouterr().err
    assert not list(output.iterdir())


@pytest.mark.parametrize("bad_file", [False, True])
def test_batch(tmp_path: Path, experiment: dict, bad_file: bool) -> None:
    directory = tmp_path / "signals"
    directory.mkdir()
    sources = [_signal(directory / filename) for filename in ("z-last.dat", "a-first.dat")]
    if bad_file:
        (directory / "bad.dat").write_text("invalid waveform", encoding="utf-8")
    (directory / "ignored.csv").write_text("ignored", encoding="utf-8")
    hashes = {source: _sha256(source) for source in sources}
    config = _config(tmp_path, experiment)
    output = tmp_path / "batch"
    assert main(["batch", str(directory), "--config", str(config), "--out", str(output),
                 "--pattern", "*.dat"]) == int(bad_file)
    summary = _read_json(output / "batch_summary.json")
    assert summary["total"] == 2 + int(bad_file)
    assert summary["failed"] == int(bad_file)
    assert summary["succeeded"] == 2
    assert [Path(item["source_path"]).stem for item in summary["results"]] == (
        ["a-first", "bad", "z-last"] if bad_file else ["a-first", "z-last"]
    )
    assert [item["status"] for item in summary["results"]] == (
        ["ok", "failed", "ok"] if bad_file else ["ok", "ok"]
    )
    for source, before in hashes.items():
        run_summary = _read_json(output / source.stem / "run_summary.json")
        assert run_summary["source_sha256"] == before == _sha256(source)
        assert (output / source.stem / "velocity_raw.csv").is_file()
        assert (output / source.stem / "velocity_display.csv").is_file()


def test_auto_columns_csv_and_whitespace_dat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    sample_rate_hz = 20.0e9
    time_s = np.arange(4096, dtype=np.float64) / sample_rate_hz
    active = time_s >= 40.0e-9
    ch1 = np.where(active, np.sin(2.0 * np.pi * 1.1e9 * time_s), 0.0)
    ch2 = np.where(active, 0.8 * np.sin(2.0 * np.pi * 1.4e9 * time_s), 0.0)

    csv_src = tmp_path / "two_col.csv"
    np.savetxt(csv_src, np.column_stack((time_s, ch1)), delimiter=",")
    csv_out = tmp_path / "csv_out"
    assert main([
        "analyze", str(csv_src), "--auto-columns", "--time-unit", "s",
        "--voltage-units", "V", "--wavelength-m", "1.55e-6", "--angle-deg", "0",
        "--window-material", "LiF", "--out", str(csv_out),
    ]) == 0
    stdout_doc = json.loads(capsys.readouterr().out)
    assert list(stdout_doc["channels"]) == ["pdv_channel_1"]
    assert {p.name for p in csv_out.iterdir()} == {
        "velocity_raw.csv",
        "velocity_gated.csv",
        "velocity_display.csv",
        "run_summary.json",
        "spectrogram_ridge.png",
    }

    dat_src = tmp_path / "three_col.dat"
    np.savetxt(dat_src, np.column_stack((time_s, ch1, ch2)), delimiter=" ")
    dat_out = tmp_path / "dat_out"
    assert main([
        "analyze", str(dat_src), "--auto-columns", "--time-unit", "s",
        "--voltage-units", "V", "--wavelength-m", "1.55e-6", "--angle-deg", "0",
        "--window-material", "LiF", "--out", str(dat_out),
    ]) == 0
    dat_stdout = json.loads(capsys.readouterr().out)
    assert list(dat_stdout["channels"]) == ["pdv_channel_1", "pdv_channel_2"]
    gated_rows = _read_csv_dict(dat_out / "velocity_gated.csv")
    assert set(gated_rows[0]) == {"time_s", "ch1_gated_velocity_m_s", "ch2_gated_velocity_m_s"}
    assert "nan" not in (dat_out / "velocity_gated.csv").read_text(encoding="utf-8").lower()


def test_auto_columns_rejects_excess_columns_and_explicit_conflict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    five_col = tmp_path / "five_col.dat"
    five_col.write_text("0 1 2 3 4\n1 2 3 4 5\n2 3 4 5 6\n", encoding="utf-8")
    assert main([
        "analyze", str(five_col), "--auto-columns", "--time-unit", "s",
        "--voltage-units", "V", "--wavelength-m", "1.55e-6", "--angle-deg", "0",
        "--window-material", "LiF", "--out", str(tmp_path / "out5"),
    ]) == 2
    assert "2 to 4 columns" in capsys.readouterr().err

    assert main([
        "analyze", str(five_col), "--auto-columns", "--time-column", "0", "--time-unit", "s",
        "--voltage-units", "V", "--wavelength-m", "1.55e-6", "--angle-deg", "0",
        "--window-material", "LiF", "--out", str(tmp_path / "out_conflict"),
    ]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_sample_rate_out_of_range_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    time_ms = np.arange(2048, dtype=np.float64) * 0.25  # treated as ms -> 4 kHz sample rate
    sig = np.sin(2.0 * np.pi * 0.1 * time_ms)
    source = tmp_path / "slow.csv"
    np.savetxt(source, np.column_stack((time_ms, sig)), delimiter=",")
    output = tmp_path / "out"
    assert main([
        "analyze", str(source), "--auto-columns", "--time-unit", "ms",
        "--voltage-units", "V", "--wavelength-m", "1.55e-6", "--angle-deg", "0",
        "--window-material", "none", "--out", str(output),
    ]) == 0
    captured = capsys.readouterr()
    assert "Inferred sample rate" in captured.err
    summary = _read_json(output / "run_summary.json")
    assert any("Inferred sample rate" in item for item in summary["warnings"])


def test_auto_band_retry_recovers_higher_beat_in_single_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    sample_rate_hz = 20.0e9
    time_s = np.arange(8192, dtype=np.float64) / sample_rate_hz
    # Strong 25 MHz low-frequency clutter peaking on the 50 MHz boundary + real 1.5 GHz beat after 60 ns
    low_bias = 5.0 * np.sin(2.0 * np.pi * 0.025e9 * time_s)
    beat = np.where(time_s >= 60.0e-9, 1.0 * np.sin(2.0 * np.pi * 1.5e9 * time_s), 0.0)
    source = tmp_path / "low_bias.dat"
    np.savetxt(source, np.column_stack((time_s, low_bias + beat)), delimiter=" ")

    retried_out = tmp_path / "retried_out"
    assert main([
        "analyze", str(source), "--auto-columns", "--time-unit", "s",
        "--voltage-units", "V", "--wavelength-m", "1.55e-6", "--angle-deg", "0",
        "--window-material", "LiF", "--out", str(retried_out),
    ]) == 0
    assert {p.name for p in retried_out.iterdir()} == {
        "velocity_raw.csv",
        "velocity_gated.csv",
        "velocity_display.csv",
        "run_summary.json",
        "spectrogram_ridge.png",
    }
    summary = _read_json(retried_out / "run_summary.json")
    retry_ch = summary["auto_band_retry"]["channels"]["pdv_channel_1"]
    assert retry_ch["triggered"] is True
    assert retry_ch["accepted"] is True
    assert retry_ch["baseline_measured_fraction"] < 0.05
    assert retry_ch["final_measured_fraction"] >= 0.15
    assert retry_ch["selected_min_freq_hz"] in (0.20e9, 0.35e9, 0.50e9)

    no_retry_out = tmp_path / "no_retry_out"
    assert main([
        "analyze", str(source), "--auto-columns", "--no-auto-band-retry",
        "--time-unit", "s", "--voltage-units", "V", "--wavelength-m", "1.55e-6",
        "--angle-deg", "0", "--window-material", "LiF", "--out", str(no_retry_out),
    ]) == 0
    err_text = capsys.readouterr().err
    assert "0/" in err_text or "0 measured" in err_text
    no_retry_summary = _read_json(no_retry_out / "run_summary.json")
    assert no_retry_summary["auto_band_retry"]["enabled"] is False
    assert no_retry_summary["quality"]["pdv_channel_1"]["measured_fraction"] < 0.05

