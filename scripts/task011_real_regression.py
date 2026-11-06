"""All 13 local raw files / 17 streams: independent reference and integrated runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task11"


def reference() -> None:
    production = ROOT.parent / "DPS_Studio"
    selected = list((production / "src/dps_studio/core").rglob("*.py"))
    selected += [production / "src/dps_studio/__init__.py"]
    records = []
    for source in selected:
        if "__pycache__" in source.parts:
            continue
        target = ARTIFACT / "production_reference" / source.relative_to(production)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise RuntimeError(f"Reference conflict: {target}")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        records.append({"path": source.relative_to(production).as_posix(),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    with (ARTIFACT / "production_reference/source_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2)


def run(mode: str, output: Path) -> None:
    import numpy as np

    from dps_studio.core.io import read_delimited_signals
    from dps_studio.core.workflow import analyze_configuration, load_workflow_config

    configuration = load_workflow_config(ROOT / "configs/pdv_studio_defaults.toml", repository_root=ROOT)
    profile = configuration.analysis.default_profile
    index = json.loads((ROOT / "artifacts/research_clean_task9/data_index.json").read_text(encoding="utf-8"))
    rows = [row for row in index["records"] if row["kind"] == "RAW"]
    report: list[dict[str, Any]] = []
    for row in rows:
        source = ROOT / row["local_path"]
        loaded = read_delimited_signals(source, time_column=0, delimiter=",",
            voltage_columns={f"ch{column}": column for column in range(1, row["channels"] + 1)})
        assert len(loaded.records) == row["channels"]
        for channel, record in loaded.records.items():
            key = f"{source.stem}_{channel}"
            options: dict[str, Any] = dict(window_length_samples=profile.window_length_samples,
                overlap_samples=profile.overlap_samples, nfft=profile.nfft,
                window_name=profile.window_name, minimum_frequency_hz=profile.minimum_frequency_hz,
                maximum_frequency_hz=min(profile.maximum_frequency_hz, record.nyquist_frequency_hz),
                detection_config=configuration.quality.signal_detection,
                event_candidate_config=configuration.event_candidate,
                automatic_ridge_selection_config=configuration.automatic_ridge_selection,
                background_guard_window_scale=configuration.quality.background_guard_window_scale,
                minimum_background_bin_count=configuration.quality.minimum_background_bin_count)
            start, end = float(record.start_time_s), float(record.end_time_s)
            if mode == "manual":
                from dps_studio.core.segmentation import EstimatorRequest, Segment, analyze_segments
                from dps_studio.core.segmentation.export import export_segmented_results

                edges = [start + fraction * (end - start) for fraction in (0, .25, .5, .75, 1)]
                segments = tuple(Segment(str(i), edges[i], edges[i + 1], algorithm=name)
                    for i, name in enumerate(("stft", "dechirp", "varpro", "clutter_varpro")))
                result = analyze_segments(
                    EstimatorRequest(record, start, end, configuration.analysis.vacuum_wavelength_m, options),
                    segments, correction_config=configuration.velocity_correction)
                paths = export_segmented_results({channel: result}, output / f"{key}_export", source_path=source)
                from csv import DictReader

                with paths[0].open(encoding="utf-8-sig", newline="") as handle:
                    exported = list(DictReader(handle))
                np.testing.assert_array_equal([float(r["absolute_time_s"]) for r in exported], result.time_s)
                np.testing.assert_array_equal([float(r["frequency_hz"]) for r in exported], result.frequency_hz)
                np.testing.assert_array_equal([float(r["corrected_velocity_m_s"]) for r in exported],
                                              result.corrected_velocity_m_s)
                assert np.all(np.diff(result.time_s) > 0)
                errors = [part["error"] for part in result.metadata["algorithms"]]
                assert not any(errors), errors
                report.append(dict(key=key, frames=len(result.time_s), valid=int(result.valid.sum()),
                    algorithms=[dict(id=part["algorithm"], frames=part["frames"], error=part["error"])
                                for part in result.metadata["algorithms"]],
                    export_roundtrip=True, physical_truth="UNAVAILABLE", wavelength_m=1550e-9))
            else:
                analysis = analyze_configuration({channel: record}, **options,
                    vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
                    analysis_start_time_s=start, analysis_end_time_s=end,
                    velocity_correction_config=configuration.velocity_correction,
                    assume_pre_event_zero_for_display=configuration.plot.assume_pre_event_zero_for_display,
                    pre_event_display_velocity_m_s=configuration.plot.pre_event_display_velocity_m_s)[channel]
                arrays: dict[str, Any] = dict(time_s=analysis.stft_result.time_s,
                    spectrum=analysis.stft_result.spectrum,
                    coarse_hz=analysis.ridge_result.frequency_hz,
                    refined_hz=analysis.refined_result.refined_frequency_hz,
                    formal_apparent=analysis.refined_velocity_m_s,
                    formal_corrected=analysis.velocity_correction_result.corrected_velocity_m_s,
                    working_hz=analysis.working_frequency_hz,
                    working_corrected=analysis.working_velocity_correction_result.corrected_velocity_m_s,
                    displayed=analysis.display_velocity_m_s)
                np.savez_compressed(output / f"{key}.npz", **arrays)
                hashes = {name: hashlib.sha256(value.tobytes()).hexdigest() for name, value in arrays.items()}
                flags = {"quality": [state.value for state in analysis.signal_detection_result.signal_states],
                         "working_source": [state.value for state in analysis.working_source],
                         "velocity_origins": analysis.velocity_origins}
                report.append(dict(key=key, samples=record.sample_count,
                    frames=len(analysis.stft_result.time_s), array_hashes=hashes, flags=flags))
            print(f"{mode}: {key} completed", flush=True)
    import dps_studio

    with (output / "report.json").open("x", encoding="utf-8") as handle:
        json.dump({"mode": mode, "module_path": dps_studio.__file__, "raw_files": len(rows),
                   "streams": len(report), "results": report}, handle, indent=2)


def compare(output: Path) -> None:
    import numpy as np

    baseline = ARTIFACT / "checks/real_reference_v2"
    current = ARTIFACT / "checks/real_current"
    first = json.loads((baseline / "report.json").read_text(encoding="utf-8"))
    second = json.loads((current / "report.json").read_text(encoding="utf-8"))
    results = []
    for left, right in zip(first["results"], second["results"], strict=True):
        assert left == right, f"Classic Production parity failed: {left['key']}"
        with np.load(baseline / f"{left['key']}.npz") as old, np.load(current / f"{left['key']}.npz") as new:
            for name in old.files:
                np.testing.assert_array_equal(old[name], new[name])
        results.append({"key": left["key"], "exact_arrays": len(left["array_hashes"]),
                        "flags_exact": True})
    with (output / "report.json").open("x", encoding="utf-8") as handle:
        json.dump({"passed": True, "raw_files": first["raw_files"], "streams": len(results),
                   "results": results, "reference_module": first["module_path"],
                   "integrated_module": second["module_path"]}, handle, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "reference", "current", "manual", "compare"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        reference()
        return
    if args.output is None:
        parser.error("--output required")
    output = args.output.resolve()
    if not output.is_relative_to(ARTIFACT):
        raise ValueError("Output outside TASK-011 artifact")
    output.mkdir(parents=True, exist_ok=False)
    source = ARTIFACT / "production_reference/src" if args.mode == "reference" else ROOT / "src"
    sys.path.insert(0, str(source))
    if args.mode == "compare":
        compare(output)
    else:
        run(args.mode, output)


if __name__ == "__main__":
    main()
