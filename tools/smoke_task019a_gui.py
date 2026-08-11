"""Exercise TASK-019A through the real offscreen Qt application and raw data."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QMessageBox

from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


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


def _wait_for_analysis(window: MainWindow) -> None:
    loop = QEventLoop()
    failure: list[str] = []
    timed_out = [False]

    def timeout() -> None:
        timed_out[0] = True
        loop.quit()

    def failed(_generation: int, error_type: str, message: str, _detail: str) -> None:
        failure.append(f"{error_type}: {message}")
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(60_000, timeout)
    if not window.run_automatic_analysis():
        raise RuntimeError("GUI rejected the automatic-analysis request.")
    loop.exec()
    if timed_out[0] or failure:
        raise RuntimeError(f"GUI automatic analysis failed: {failure or 'timeout'}")


def _csv_header(path: Path) -> tuple[str, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(next(csv.reader(handle)))


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    repository_root = Path(__file__).resolve().parents[1]
    source = repository_root / "data" / "raw" / "20260630-1.csv"
    output_directory = repository_root / "artifacts" / "task019a" / "gui_smoke"
    output_directory.mkdir(parents=True, exist_ok=False)
    raw_files = sorted(
        path for path in source.parent.iterdir() if path.is_file()
    )
    hashes_before = {path.name: _sha256(path) for path in raw_files}

    app = create_application([])
    QMessageBox.information = staticmethod(  # type: ignore[method-assign]
        lambda *_args, **_kwargs: None
    )
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load(source))
        window.analysis_range_panel.use_full_range()
        app.processEvents()
        _wait_for_analysis(window)
        if window.workflow_state is not WorkflowState.RESULT_READY:
            raise RuntimeError("Real GUI flow did not reach RESULT_READY.")

        channel_name = "pdv_channel_1"
        analysis = window.analysis_session.channel_analyses[channel_name]
        event_reference_s = analysis.stream_event_candidates.primary_candidate_time_s
        if event_reference_s is None:
            raise RuntimeError("Real data did not provide an automatic event candidate.")
        window._adopt_event_candidate(channel_name, event_reference_s)
        app.processEvents()

        session = window.analysis_session
        generation_before = session.generation_id
        guided_generation_before = session.guided_generation_id
        analysis = session.channel_analyses[channel_name]
        upstream_ids = {
            "stft": id(analysis.stft_result),
            "ridge": id(analysis.ridge_result),
            "refined": id(analysis.refined_result),
            "event": id(analysis.stream_event_candidates),
            "quality": id(analysis.signal_detection_result),
        }
        apparent_before = analysis.apparent_velocity_m_s.copy()

        window.workflow_navigation.setCurrentRow(4)
        window.measurement_angle_spin.setValue(15.0)
        app.processEvents()
        step5_stayed = window.workflow_navigation.currentRow() == 4
        window.workflow_navigation.setCurrentRow(5)
        none_index = window.export_window_material_combo.findData("none")
        window.export_window_material_combo.setCurrentIndex(none_index)
        app.processEvents()
        step6_stayed = window.workflow_navigation.currentRow() == 5

        none_result = session.channel_analyses[channel_name]
        none_corrected = none_result.corrected_velocity_m_s.copy()
        lif_index = window.export_window_material_combo.findData("LiF")
        window.export_window_material_combo.setCurrentIndex(lif_index)
        app.processEvents()
        lif_result = session.channel_analyses[channel_name]
        lif_restore_changed_corrected = not np.array_equal(
            lif_result.corrected_velocity_m_s,
            none_corrected,
            equal_nan=True,
        )
        step6_to_step5_synced = window.window_material_combo.currentData() == "LiF"
        window.export_window_material_combo.setCurrentIndex(none_index)
        app.processEvents()

        refreshed = session.channel_analyses[channel_name]
        current_upstream_ids = {
            "stft": id(refreshed.stft_result),
            "ridge": id(refreshed.ridge_result),
            "refined": id(refreshed.refined_result),
            "event": id(refreshed.stream_event_candidates),
            "quality": id(refreshed.signal_detection_result),
        }
        finite = np.isfinite(apparent_before)
        expected = apparent_before[finite] / math.cos(math.radians(15.0))
        if not np.allclose(refreshed.corrected_velocity_m_s[finite], expected):
            raise RuntimeError("None + nonzero angle did not export angle correction.")
        if not np.array_equal(
            np.isnan(refreshed.corrected_velocity_m_s),
            np.isnan(apparent_before),
        ):
            raise RuntimeError("Velocity post-processing changed NaN positions.")

        window.velocity_view.fit_analysis_range()
        window.velocity_view.fit_result_range()
        if not window.velocity_view.plot_widget.plotItem.buttonsHidden:
            raise RuntimeError("Velocity built-in AutoRange button remains enabled.")
        if not window.export_event_time_origin_radio.isChecked():
            raise RuntimeError("Event-relative time is not the GUI export default.")

        export_directory = output_directory / "export"
        export_directory.mkdir()
        window._set_export_output_directory(export_directory)
        if not window._export_current_result():
            raise RuntimeError("Real GUI formal export failed.")
        metadata_path = next(export_directory.glob("*.metadata.json"))
        simple_path = next(
            path
            for path in export_directory.glob("*.csv")
            if not path.name.endswith("_detail.csv")
        )
        detail_path = next(export_directory.glob("*_detail.csv"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        document: dict[str, Any] = {
            "command_semantics": (
                "offscreen QApplication through the same MainWindow entry used by "
                "python -m dps_studio.gui"
            ),
            "source": source.name,
            "result_ready_after_correction": (
                window.workflow_state is WorkflowState.RESULT_READY
            ),
            "step5_stayed": step5_stayed,
            "step6_stayed": step6_stayed,
            "step6_to_step5_synced": step6_to_step5_synced,
            "lif_restore_changed_corrected": lif_restore_changed_corrected,
            "generation_unchanged": session.generation_id == generation_before,
            "guided_generation_unchanged": (
                session.guided_generation_id == guided_generation_before
            ),
            "upstream_object_ids_unchanged": upstream_ids == current_upstream_ids,
            "apparent_velocity_unchanged": bool(
                np.array_equal(
                    refreshed.apparent_velocity_m_s,
                    apparent_before,
                    equal_nan=True,
                )
            ),
            "window_material": metadata["velocity_correction"]["window"][
                "material"
            ],
            "angle_deg": metadata["velocity_correction"]["angle"][
                "angle_deg_display"
            ],
            "time_coordinate": metadata["time_coordinate"],
            "simple_header": _csv_header(simple_path),
            "detail_header": _csv_header(detail_path),
            "velocity_buttons_hidden": (
                window.velocity_view.plot_widget.plotItem.buttonsHidden
            ),
            "other_plot_buttons_unchanged": {
                "spectrogram": not window.spectrogram_view.plot_widget.plotItem.buttonsHidden,
                "ridge": not window.ridge_view.plot_widget.plotItem.buttonsHidden,
            },
        }
    finally:
        window.close()
        app.processEvents()

    hashes_after = {path.name: _sha256(path) for path in raw_files}
    document["raw_sha256_before"] = hashes_before
    document["raw_sha256_after"] = hashes_after
    document["raw_unchanged"] = hashes_before == hashes_after
    document["all_passed"] = all(
        (
            document["result_ready_after_correction"],
            document["step5_stayed"],
            document["step6_stayed"],
            document["step6_to_step5_synced"],
            document["lif_restore_changed_corrected"],
            document["generation_unchanged"],
            document["guided_generation_unchanged"],
            document["upstream_object_ids_unchanged"],
            document["apparent_velocity_unchanged"],
            document["raw_unchanged"],
        )
    )
    (output_directory / "gui_smoke.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0 if document["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
