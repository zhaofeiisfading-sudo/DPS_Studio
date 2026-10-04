"""Read historical release evidence and run the documented Production example."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dps_studio import __version__  # noqa: E402
from dps_studio.core.export import (  # noqa: E402
    ResultAnalysisMode, ResultExportOptions, export_formal_results,
)
from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.core.workflow import analyze_profile, load_workflow_config  # noqa: E402


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def historical_zip_evidence() -> dict[str, object]:
    archive_path = ROOT / "release" / "PDV_Studio_v0.1.3_iconfix.zip"
    if not archive_path.is_file():
        return {"status": "UNKNOWN / MISSING EVIDENCE"}
    with zipfile.ZipFile(archive_path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        components = {
            name: [item.filename for item in files if token.lower() in item.filename.lower()]
            for name, token in {
                "shiboken": "shiboken6.abi3.dll", "qt_platform": "qwindows.dll",
                "scipy_ccallback": "_ccallback_c", "icu": "icuuc.dll",
            }.items()
        }
        differences = []
        release = ROOT / "release" / "PDV_Studio_v0.1.3_iconfix"
        for item in files:
            # Archive layouts may include a top-level release folder or its contents.
            relative = Path(item.filename)
            if relative.parts[0] == release.name:
                relative = Path(*relative.parts[1:])
            current = release / relative
            with archive.open(item) as handle:
                archived_hash = hashlib.file_digest(handle, "sha256").hexdigest()
            if not current.is_file() or sha256(current) != archived_hash:
                differences.append(item.filename)
    return {
        "archive": str(archive_path), "archive_sha256": sha256(archive_path),
        "file_count": len(files), "runtime_members": components,
        "differences_from_current_release_directory": differences,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "docs" / "原始数据.csv"
    before = sha256(source)
    config = load_workflow_config(ROOT / "configs" / "pdv_studio_defaults.toml", repository_root=ROOT)
    loaded = read_delimited_signals(
        source, time_column=0, voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        original_time_unit="s", original_voltage_units={"pdv_channel_1": "V", "pdv_channel_2": "V"},
    )
    analyses = analyze_profile(
        loaded.records, profile=config.analysis.default_profile,
        analysis_start_time_s=max(record.start_time_s for record in loaded.records.values()),
        analysis_end_time_s=min(record.end_time_s for record in loaded.records.values()),
        vacuum_wavelength_m=config.analysis.vacuum_wavelength_m,
        detection_config=config.quality.signal_detection, event_candidate_config=config.event_candidate,
        automatic_ridge_selection_config=config.automatic_ridge_selection,
        velocity_correction_config=config.velocity_correction,
        background_guard_window_scale=config.quality.background_guard_window_scale,
        minimum_background_bin_count=config.quality.minimum_background_bin_count,
    )
    options = ResultExportOptions(output, ResultAnalysisMode.AUTOMATIC, analyses,
                                  analysis_profile_name=config.analysis.default_profile.profile_id.value)
    continuous = export_formal_results(options)
    filtered = export_formal_results(replace(options, quality_passed_only=True))
    channels = {}
    for first, second in zip(continuous.exported_channels, filtered.exported_channels, strict=True):
        schema, simple = rows(first.csv_path)
        filtered_schema, quality_rows = rows(second.csv_path)
        _, detail = rows(first.detail_csv_path)
        document = json.loads(first.metadata_path.read_text(encoding="utf-8"))
        assert len(schema) == len(filtered_schema) == 2
        assert document["dps_studio_version"] == __version__
        assert document["input_provenance"]["original_time_unit"] == "s"
        channels[first.channel_name] = {
            "continuous_csv": str(first.csv_path), "quality_csv": str(second.csv_path),
            "csv_columns": schema, "quality_csv_columns": filtered_schema,
            "continuous_rows": len(simple), "quality_rows": len(quality_rows),
            "finite_display_but_not_measured": int(sum(
                row["signal_state"] != "measured" and np.isfinite(float(row["display_velocity_m_s"]))
                for row in detail
            )),
            "candidate_time_s": document["automatic_event_candidate_time_s"],
            "event_reference_time_s": document["event_reference_time_s"],
            "version": document["dps_studio_version"], "input_provenance": document["input_provenance"],
        }
    after = sha256(source)
    assert before == after
    evidence = {
        "source": str(source), "source_sha256_before": before, "source_sha256_after": after,
        "sample_count": loaded.row_count, "profile": options.analysis_profile_name,
        "external_two_shots": "NOT REPRODUCED DUE TO MISSING INPUT DATA",
        "historical_zip": historical_zip_evidence(), "channels": channels,
    }
    with (output / "audit_evidence.json").open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
