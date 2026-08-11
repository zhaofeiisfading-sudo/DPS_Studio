"""Exercise TASK-018C modes and windows through the real offscreen GUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _wait(window: MainWindow, launch: Any) -> None:
    loop = QEventLoop()
    state: dict[str, object] = {"timeout": False, "error": None}

    def timed_out() -> None:
        state["timeout"] = True
        loop.quit()

    def failed(_generation: int, error_type: str, message: str, _detail: str) -> None:
        state["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(45_000, timed_out)
    if not launch():
        raise RuntimeError("GUI analysis launch was rejected.")
    loop.exec()
    if state["timeout"] or state["error"] is not None:
        raise RuntimeError(f"GUI analysis failed: {state}")


def _load(source: Path) -> object:
    return DataImportController().load(
        SignalLoadRequest(
            path=source,
            time_column=0,
            channels=(
                ChannelImportSpec("pdv_channel_1", 1, 1.0),
                ChannelImportSpec("pdv_channel_2", 2, 1.0),
            ),
            delimiter=",",
            has_header=False,
            encoding="utf-8",
            time_scale=1.0,
        )
    )


def _select(window: MainWindow, combo_name: str, value: str) -> None:
    combo = getattr(window, combo_name)
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f"GUI option is unavailable: {combo_name}={value}.")
    combo.setCurrentIndex(index)
    QApplication.processEvents()


def _export(
    window: MainWindow,
    directory: Path,
    *,
    channel_name: str = "pdv_channel_2",
) -> dict[str, object]:
    directory.mkdir()
    window._set_export_output_directory(directory)
    mode_index = window.export_mode_combo.findData("automatic")
    channel_index = window.export_channel_combo.findData(channel_name)
    if mode_index < 0 or channel_index < 0:
        raise RuntimeError("Current Automatic GUI export selection is unavailable.")
    window.export_mode_combo.setCurrentIndex(mode_index)
    window.export_channel_combo.setCurrentIndex(channel_index)
    if not window._export_current_result():
        raise RuntimeError("GUI export failed.")
    metadata_paths = list(directory.glob("*.metadata.json"))
    files = sorted(path.name for path in directory.iterdir() if path.is_file())
    if len(files) != 3 or len(metadata_paths) != 1:
        raise RuntimeError("GUI export did not produce one three-file group.")
    metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
    return {
        "files": files,
        "metadata_json_count": 1,
        "schema": metadata["export_schema_version"],
        "window_name": metadata["stft_configuration"]["window_name"],
        "automatic_ridge_selection": metadata["automatic_ridge_selection"],
        "automatic_event_candidate_time_s": metadata[
            "automatic_event_candidate_time_s"
        ],
        "compatibility_event_candidate_time_s": metadata[
            "compatibility_event_candidate_time_s"
        ],
    }


def _scenario(
    window: MainWindow,
    output_directory: Path,
    *,
    name: str,
    window_name: str,
    mode: str,
    reuse_stft: bool,
) -> dict[str, object]:
    _select(window, "window_name_combo", window_name)
    _select(window, "automatic_ridge_extraction_combo", mode)
    launch = (
        window.run_staged_automatic_analysis
        if reuse_stft and window.analysis_session.stft_valid
        else window.run_automatic_analysis
    )
    _wait(window, launch)
    if window.workflow_state is not WorkflowState.RESULT_READY:
        raise RuntimeError(f"{name} did not reach RESULT_READY.")
    analysis = window.analysis_session.channel_analyses["pdv_channel_2"]
    frame = 1015
    result = {
        "scenario": name,
        "window_name": analysis.stft_result.window_name,
        "mode": analysis.automatic_ridge_selection_result.config.mode.value,
        "frame_1015_frequency_hz": float(
            analysis.refined_result.refined_frequency_hz[frame]
        ),
        "frame_1015_velocity_m_s": (
            float(analysis.refined_velocity_m_s[frame])
            if np.isfinite(analysis.refined_velocity_m_s[frame])
            else None
        ),
        "frame_1015_origin": (
            analysis.automatic_ridge_selection_result.origins[frame].value
        ),
        "reselection_count": len(
            analysis.automatic_ridge_selection_result.reselected_frame_indices
        ),
        "automatic_event_candidate_time_s": (
            analysis.stream_event_candidates.primary_candidate_time_s
        ),
        "compatibility_event_candidate_time_s": (
            analysis.signal_detection_result.detected_event_candidate_time_s
        ),
    }
    result["export"] = _export(window, output_directory / name)
    return result


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    repository_root = Path(__file__).resolve().parents[1]
    source = repository_root / "data" / "raw" / "20260630-1.csv"
    output_directory = repository_root / "artifacts" / "task018c" / "gui_smoke"
    output_directory.mkdir(parents=True, exist_ok=False)
    raw_directory = source.parent
    raw_files = sorted(path for path in raw_directory.iterdir() if path.is_file())
    hashes_before = {path.name: _sha256(path) for path in raw_files}
    app = create_application([])
    QMessageBox.information = staticmethod(  # type: ignore[method-assign]
        lambda *_args, **_kwargs: None
    )
    window = MainWindow(translation_manager=translation_manager())
    scenarios: list[dict[str, object]] = []
    try:
        window.set_loaded_result(_load(source))
        window.analysis_range_panel.use_full_range()
        app.processEvents()
        scenarios.append(
            _scenario(
                window,
                output_directory,
                name="hann_continuity",
                window_name="hann",
                mode="continuity_assisted",
                reuse_stft=False,
            )
        )
        if scenarios[-1]["frame_1015_origin"] != (
            "continuity_assisted_alternative"
        ):
            raise RuntimeError("Hann continuity did not formally rescue frame 1015.")
        scenarios.append(
            _scenario(
                window,
                output_directory,
                name="hann_legacy",
                window_name="hann",
                mode="legacy_strongest_peak",
                reuse_stft=True,
            )
        )
        if scenarios[-1]["frame_1015_origin"] != "strongest_peak":
            raise RuntimeError("Hann legacy did not restore strongest-peak behavior.")
        scenarios.append(
            _scenario(
                window,
                output_directory,
                name="blackmanharris_continuity",
                window_name="blackmanharris",
                mode="continuity_assisted",
                reuse_stft=False,
            )
        )
        scenarios.append(
            _scenario(
                window,
                output_directory,
                name="hamming_continuity",
                window_name="hamming",
                mode="continuity_assisted",
                reuse_stft=False,
            )
        )

        analysis = window.analysis_session.channel_analyses["pdv_channel_1"]
        stft = analysis.stft_result
        coarse = analysis.ridge_result.frequency_hz
        constraint = RidgeCorridorConstraint(
            control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
            control_frequencies_hz=np.asarray([coarse[3], coarse[-4]]),
            half_width_hz=100.0e6,
        )
        window.guided_mode_radio.click()
        window._ridge_constraint_changed("pdv_channel_1", constraint)
        app.processEvents()
        _wait(window, window.run_guided_analysis)
        guided = window.analysis_session.guided_channel_analyses["pdv_channel_1"]
        guided_result = {
            "window_name": guided.stft_result.window_name,
            "result_ready": window.workflow_state is WorkflowState.RESULT_READY,
            "local_peak_candidates_absent": guided.local_peak_candidates is None,
            "experimental_reselection_absent": (
                guided.experimental_reselection_result is None
            ),
            "finite_velocity_count": int(
                np.count_nonzero(np.isfinite(guided.refined_velocity_m_s))
            ),
        }
        if not all(
            (
                guided_result["result_ready"],
                guided_result["local_peak_candidates_absent"],
                guided_result["experimental_reselection_absent"],
            )
        ):
            raise RuntimeError("Guided regression smoke failed.")
    finally:
        window.close()
        app.processEvents()
    hashes_after = {path.name: _sha256(path) for path in raw_files}
    if hashes_before != hashes_after:
        raise RuntimeError("A data/raw SHA-256 changed during GUI smoke testing.")
    document = {
        "command_semantics": (
            "offscreen QApplication using the python -m dps_studio.gui MainWindow"
        ),
        "source": source.name,
        "scenarios": scenarios,
        "guided": guided_result,
        "all_passed": True,
        "raw_sha256_before": hashes_before,
        "raw_sha256_after": hashes_after,
        "raw_unchanged": True,
    }
    (output_directory / "gui_smoke.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(document, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
