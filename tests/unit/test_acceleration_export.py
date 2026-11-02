from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from test_formal_result_export import _analyses as formal_analyses, _options as formal_options

from dps_studio.core.export import (
    export_formal_results, ExportTimeOrigin, ResultExportWriteError, ResultAnalysisMode,
    ResultExportOptions,
)
from dps_studio.core.workflow.acceleration import channel_acceleration
from dps_studio.core.workflow import WorkingRidgeSource, PRE_EVENT_DISPLAY_ORIGIN


def _options(path: Path, analyses: dict[str, Any]) -> ResultExportOptions:
    return formal_options(path, mode=ResultAnalysisMode.AUTOMATIC,
                          analyses=analyses, source_path=None)


def _analyses(path: Path) -> dict[str, Any]:
    return formal_analyses(path)["automatic"]


def test_local_fit_export_preserves_raw_columns_and_records_window(tmp_path: Path) -> None:
    analyses = _analyses(tmp_path)
    report = export_formal_results(replace(_options(tmp_path, analyses),
        include_acceleration=True, acceleration_fit_window_s=50e-9))
    for exported in report.exported_channels:
        assert exported.acceleration_csv_path is not None
        with exported.acceleration_csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        analysis = analyses[exported.channel_name]
        detection = analysis.signal_detection_result
        time = analysis.stft_result.time_s
        mask = (time >= detection.analysis_start_time_s) & (time <= detection.analysis_end_time_s)
        for column, window in (("acceleration_m_s2", None),
                               ("local_linear_acceleration_m_s2", 50e-9)):
            np.testing.assert_allclose([float(row[column]) for row in rows],
                channel_acceleration(analysis, window_s=window).acceleration_m_s2[mask],
                equal_nan=True)
        metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
        assert metadata["acceleration_export"]["method"] == "finite_difference_nonuniform_central_3point"
        assert metadata["acceleration_local_fit"]["window_s"] == 50e-9
        assert metadata["acceleration_local_fit"]["method"] == "local_linear_least_squares"


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("quality", [False, True])
def test_optional_csv_preserves_original_files_and_records_si_source(
    tmp_path: Path, relative: bool, quality: bool,
) -> None:
    analyses = _analyses(tmp_path)
    plain = tmp_path / "plain"
    extra = tmp_path / "extra"
    plain.mkdir()
    extra.mkdir()
    options = replace(_options(plain, analyses), quality_passed_only=quality,
                      time_origin=ExportTimeOrigin.EVENT if relative else ExportTimeOrigin.ABSOLUTE)
    first = export_formal_results(options).exported_channels[0]
    second = export_formal_results(replace(options, output_directory=extra,
                                         include_acceleration=True)).exported_channels[0]
    assert first.acceleration_csv_path is None
    assert len(list(plain.glob("*.csv"))) == 2 * len(analyses)
    assert first.csv_path.read_bytes() == second.csv_path.read_bytes()
    assert first.detail_csv_path.read_bytes() == second.detail_csv_path.read_bytes()
    assert second.acceleration_csv_path is not None
    with second.acceleration_csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    analysis = analyses[second.channel_name]
    time_s = analysis.stft_result.time_s
    detection = analysis.signal_detection_result
    mask = (time_s >= detection.analysis_start_time_s) & (time_s <= detection.analysis_end_time_s)
    indices = np.flatnonzero(mask)
    np.testing.assert_allclose([float(row["acceleration_m_s2"]) for row in rows],
                              channel_acceleration(analysis).acceleration_m_s2[mask], equal_nan=True)
    expected_time = time_s[mask] - (detection.manual_event_reference_time_s if relative else 0.)
    key = "time_from_event_s" if relative else "time_s"
    np.testing.assert_allclose([float(row[key]) for row in rows], expected_time)
    for row, index in zip(rows, indices, strict=True):
        assert row["velocity_source"] == "display_velocity_m_s"
        assert row["working_source"] == analysis.working_source[index].value
        assert row["signal_state"] == detection.signal_states[index].value
    metadata = json.loads(second.metadata_path.read_text(encoding="utf-8"))
    acceleration = metadata.pop("acceleration_export")
    assert acceleration["units"] == {"time": "s", "velocity": "m/s", "acceleration": "m/s^2"}
    assert not acceleration["input_is_signed"]
    assert "unsigned" in acceleration["interpretation"]
    assert acceleration["velocity_correction"] == metadata["continuous_velocity_correction"]
    old = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    metadata.pop("exported_at_utc")
    old.pop("exported_at_utc")
    assert metadata == old


def test_known_finite_interpolated_gap_and_platform_are_masked(tmp_path: Path) -> None:
    analysis = _analyses(tmp_path)["pdv_channel_1"]
    index = int(np.flatnonzero(np.isfinite(analysis.plot_velocity_m_s) &
               (analysis.stft_result.time_s > .5e-6))[0])
    sources = list(analysis.working_source)
    sources[index] = WorkingRidgeSource.INTERPOLATED
    changed = replace(analysis, working_source=tuple(sources))
    result = channel_acceleration(changed)
    assert np.isnan(result.acceleration_m_s2[index])
    for i, origin in enumerate(analysis.velocity_origins):
        if origin == PRE_EVENT_DISPLAY_ORIGIN:
            assert np.isnan(result.acceleration_m_s2[i])
    assert changed.plot_velocity_m_s[index] == analysis.plot_velocity_m_s[index]


def test_acceleration_collision_allocates_consistent_group(tmp_path: Path) -> None:
    options = replace(_options(tmp_path, _analyses(tmp_path)), include_acceleration=True)
    first = export_formal_results(options).exported_channels[0]
    assert first.acceleration_csv_path is not None
    before = first.acceleration_csv_path.read_bytes()
    second = export_formal_results(options).exported_channels[0]
    assert second.acceleration_csv_path != first.acceleration_csv_path
    assert first.acceleration_csv_path.read_bytes() == before


def test_acceleration_publication_failure_rolls_back_whole_group(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    import dps_studio.core.export.writer as writer
    options = replace(_options(tmp_path, _analyses(tmp_path)), include_acceleration=True)
    original_link = writer.os.link

    def failing_link(source: Path, target: Path) -> None:
        if target.name.endswith("_acceleration.csv"):
            raise OSError("simulated failure")
        original_link(source, target)

    monkeypatch.setattr(writer.os, "link", failing_link)
    with pytest.raises(ResultExportWriteError, match="simulated failure"):
        export_formal_results(options)
    assert not list(tmp_path.glob("*.metadata.json"))
    assert not list(tmp_path.glob("*_detail.csv"))
    assert not list(tmp_path.glob("*_acceleration.csv"))
