"""Run TASK-018B offscreen GUI smoke checks on three real raw shots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState
from assess_task018a_continuity import _sha256


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
    QTimer.singleShot(30_000, timed_out)
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


def _smoke_source(
    app: QApplication,
    source: Path,
    export_directory: Path,
    configuration_path: Path,
    repository_root: Path,
) -> dict[str, object]:
    export_directory.mkdir()
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load(source))
        window.set_analysis_configuration(
            load_workflow_config(
                configuration_path,
                repository_root=repository_root,
            )
        )
        window.analysis_range_panel.use_full_range()
        app.processEvents()
        _wait(window, window.run_automatic_analysis)
        if window.workflow_state is not WorkflowState.RESULT_READY:
            raise RuntimeError("Automatic GUI result did not reach RESULT_READY.")
        analyses = window.analysis_session.channel_analyses
        channel_name = "pdv_channel_1"
        analysis = analyses[channel_name]
        primary_s = analysis.stream_event_candidates.primary_candidate_time_s
        compatibility_s = (
            analysis.signal_detection_result.detected_event_candidate_time_s
        )
        if primary_s is None:
            raise RuntimeError(f"{source.name} channel 1 has no real primary candidate.")
        button = window.analysis_range_panel.candidate_buttons.get(channel_name)
        if button is None:
            raise RuntimeError("GUI did not expose the robust primary adoption action.")
        button.click()
        app.processEvents()
        if window.analysis_session.event_reference_time_s != primary_s:
            raise RuntimeError("GUI adoption did not use the event-level primary.")
        if not str(window.analysis_session.event_reference_source).startswith(
            "user_adopted:automatic_primary"
        ):
            raise RuntimeError("GUI adoption provenance is not explicit.")
        finite_velocity_count = int(
            np.count_nonzero(
                np.isfinite(analysis.signal_detection_result.apparent_velocity_m_s)
            )
        )
        if finite_velocity_count == 0:
            raise RuntimeError("Automatic GUI result has no finite formal velocity.")

        window._set_export_output_directory(export_directory)
        automatic_index = window.export_mode_combo.findData("automatic")
        channel_index = window.export_channel_combo.findData(channel_name)
        if automatic_index < 0 or channel_index < 0:
            raise RuntimeError("Automatic GUI export selection is unavailable.")
        window.export_mode_combo.setCurrentIndex(automatic_index)
        window.export_channel_combo.setCurrentIndex(channel_index)
        if not window._export_current_result():
            raise RuntimeError("GUI export failed.")
        metadata_paths = tuple(export_directory.glob("*.metadata.json"))
        files = sorted(path.name for path in export_directory.iterdir() if path.is_file())
        if len(files) != 3 or len(metadata_paths) != 1:
            raise RuntimeError("GUI export did not produce exactly one three-file group.")
        metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
        if metadata["automatic_event_candidate_time_s"] != primary_s:
            raise RuntimeError("GUI metadata primary candidate does not match the model.")
        if metadata["compatibility_event_candidate_time_s"] != compatibility_s:
            raise RuntimeError("GUI metadata compatibility candidate is inconsistent.")
        if metadata["event_reference_time_s"] != primary_s:
            raise RuntimeError("GUI metadata adopted reference is inconsistent.")

        coarse = analysis.ridge_result.frequency_hz
        stft = analysis.stft_result
        constraint = RidgeCorridorConstraint(
            control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
            control_frequencies_hz=np.asarray([coarse[3], coarse[-4]]),
            half_width_hz=100.0e6,
        )
        window.guided_mode_radio.click()
        window._ridge_constraint_changed(channel_name, constraint)
        app.processEvents()
        _wait(window, window.run_guided_analysis)
        guided = window.analysis_session.guided_channel_analyses[channel_name]
        if window.workflow_state is not WorkflowState.RESULT_READY:
            raise RuntimeError("Guided GUI result did not reach RESULT_READY.")
        if guided.local_peak_candidates is not None or (
            guided.experimental_reselection_result is not None
        ):
            raise RuntimeError("Automatic candidate diagnostics leaked into Guided.")
        return {
            "source": source.name,
            "automatic_result_ready": True,
            "primary_candidate_time_s": primary_s,
            "compatibility_candidate_time_s": compatibility_s,
            "compatibility_is_default": False,
            "explicit_adoption_required": True,
            "adopted_reference_time_s": window.analysis_session.event_reference_time_s,
            "event_reference_source": window.analysis_session.event_reference_source,
            "finite_formal_velocity_count": finite_velocity_count,
            "guided_result_ready": True,
            "guided_candidate_diagnostics_absent": True,
            "export_files": files,
            "export_metadata_json_count": len(metadata_paths),
            "metadata_schema": metadata["export_schema_version"],
            "metadata_event_fields_present": all(
                field in metadata
                for field in (
                    "automatic_event_candidate_time_s",
                    "compatibility_event_candidate_time_s",
                    "event_reference_time_s",
                    "event_reference_source",
                )
            ),
        }
    finally:
        window.close()
        app.processEvents()


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    repository_root = Path(__file__).resolve().parents[1]
    raw_directory = repository_root / "data" / "raw"
    output_directory = repository_root / "artifacts" / "task018b" / "gui_smoke_run"
    output_directory.mkdir(parents=True, exist_ok=False)
    names = ("20260607.csv", "20260701.csv", "20260630-1.csv")
    sources = [raw_directory / name for name in names]
    raw_files = sorted(path for path in raw_directory.iterdir() if path.is_file())
    hashes_before = {path.name: _sha256(path) for path in raw_files}
    app = create_application([])
    QMessageBox.information = staticmethod(lambda *_args, **_kwargs: None)  # type: ignore[method-assign]
    results = [
        _smoke_source(
            app,
            source,
            output_directory / source.stem,
            repository_root / "configs" / "pdv_studio_defaults.toml",
            repository_root,
        )
        for source in sources
    ]
    hashes_after = {path.name: _sha256(path) for path in raw_files}
    if hashes_before != hashes_after:
        raise RuntimeError("A raw SHA-256 changed during GUI smoke testing.")
    document = {
        "command_semantics": "offscreen QApplication using the python -m dps_studio.gui MainWindow",
        "sources": results,
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
