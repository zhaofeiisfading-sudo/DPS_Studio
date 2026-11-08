"""Registry: legacy adapters retain context; explicit strategies isolate boundaries."""
from __future__ import annotations

import importlib
from functools import partial
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

import numpy as np

from dps_studio.core.physics import (
    VelocityCorrectionConfig, WindowMaterial, apply_velocity_corrections, velocity_correction_metadata,
)
from dps_studio.core.workflow import analyze_configuration

from .models import BeatEstimate, EstimatorRequest, Segment, SegmentedResult, validate_plan
from .strategies import STRATEGIES, estimate_strategy


class Estimator(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def label(self) -> str: ...

    def estimate(self, request: EstimatorRequest) -> BeatEstimate: ...


@dataclass(frozen=True)
class FunctionEstimator:
    id: str
    label: str
    function: Callable[[EstimatorRequest], BeatEstimate]

    def estimate(self, request: EstimatorRequest) -> BeatEstimate:
        return self.function(request)


class AlgorithmPool:
    """One registry shared by the editor and execution layer; no GUI imports."""

    def __init__(self) -> None:
        self._algorithms: dict[str, Estimator] = {}

    def register(self, estimator: Estimator) -> None:
        if not estimator.id or estimator.id in self._algorithms:
            raise ValueError("An estimator needs a unique nonempty identifier")
        self._algorithms[estimator.id] = estimator

    @property
    def algorithms(self) -> tuple[Estimator, ...]:
        return tuple(self._algorithms.values())

    def estimate(self, name: str, request: EstimatorRequest) -> BeatEstimate:
        result = self._algorithms[name].estimate(request)
        if not isinstance(result, BeatEstimate) or result.algorithm != name:
            raise ValueError("Estimator violated its result/provenance contract")
        return result


def _stft(request: EstimatorRequest) -> BeatEstimate:
    options = dict(request.workflow_options)
    # These are shared physical postprocessing inputs, never estimator duties.
    options.pop("velocity_correction_config", None)
    options.pop("assume_pre_event_zero_for_display", None)
    options.pop("pre_event_display_velocity_m_s", None)
    analysis = analyze_configuration(
        {"channel": request.record}, **options,
        analysis_start_time_s=request.start_s, analysis_end_time_s=request.end_s,
        vacuum_wavelength_m=request.wavelength_m, assume_pre_event_zero_for_display=False,
        velocity_correction_config=VelocityCorrectionConfig(window_material=WindowMaterial.NONE),
    )["channel"]
    frequency = analysis.refined_velocity_m_s * (2 / request.wavelength_m)
    return BeatEstimate(
        analysis.stft_result.time_s, frequency, analysis.working_frequency_hz,
        tuple(state.value for state in analysis.signal_detection_result.signal_states),
        "stft", "Production 677a22df formal STFT/quality workflow",
        int(options["window_length_samples"]),
        {"workflow_options": options, "accepted": "formal detection; no display zero filling"},
    )


def _frozen(name: str, request: EstimatorRequest) -> BeatEstimate:
    from dps_studio.algorithms.waveform.common import Context, Signal

    # The whole record retains the original quiet prefix, absolute phase and
    # window support. Artificial segment boundaries never enter the estimator.
    context = Context(Signal(np.array(request.record.time_s),
                             np.array(request.record.voltage_v)))
    module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
    result = module.run(context)
    frequency = np.array(result.accepted_hz, dtype=np.float64)
    flags = [str(flag) for flag in result.flags]
    minimum = float(request.workflow_options["minimum_frequency_hz"])
    maximum = min(float(request.workflow_options["maximum_frequency_hz"]),
                  request.record.nyquist_frequency_hz)
    outside = np.isfinite(frequency) & ((frequency < minimum) | (frequency > maximum))
    frequency[outside] = np.nan
    for index in np.flatnonzero(outside):
        flags[index] += "|OUTSIDE_USER_FREQUENCY_BAND"
    return BeatEstimate(
        np.asarray(context.time_s), frequency, np.asarray(result.frequency_hz), tuple(flags),
        name, f"TASK-008 frozen {name}; TASK-009 local migration", 512,
        {"parameters": module.PARAMETERS, "diagnostics": result.details,
         "native_hop_samples": 128, "native_support": "full original record",
         "user_frequency_band_hz": [minimum, maximum],
         "limits": "quiet-prefix/event heuristic; real branch identity unvalidated",
         "native_diagnostics": {key: np.asarray(value).tolist()
                                for key, value in result.extra.items()}},
    )


def _unobservable(request: EstimatorRequest) -> BeatEstimate:
    width = int(request.workflow_options["window_length_samples"])
    hop = width - int(request.workflow_options["overlap_samples"])
    centers = np.arange(width // 2, len(request.record.time_s) - (width - width // 2) + 1, hop)
    time = np.asarray(request.record.time_s[centers])
    return BeatEstimate(time, np.full(len(time), np.nan), np.full(len(time), np.nan),
                        ("UNOBSERVABLE_NOT_ZERO",) * len(time), "unobservable",
                        "explicit operator exclusion", width)


def default_pool() -> AlgorithmPool:
    pool = AlgorithmPool()
    pool.register(FunctionEstimator("stft", "STFT", _stft))
    for name, label in (("dechirp", "Dechirp"), ("varpro", "VarPro"),
                        ("clutter_varpro", "Clutter VarPro")):
        pool.register(FunctionEstimator(name, label, partial(_frozen, name)))
    for name, label in (("stft_short", "短窗瞬态 STFT（边界约束）"),
                        ("stft_long", "长窗平台 STFT（边界约束）"),
                        ("stft_low", "低频带 STFT（研究）"),
                        ("low_glrt", "低频 GLRT / 杂散投影（研究）"),
                        ("tone_refine", "长窗正弦精修（研究）")):
        pool.register(FunctionEstimator(name, label, partial(estimate_strategy, name=name)))
    pool.register(FunctionEstimator("unobservable", "不估计（NaN）", _unobservable))
    return pool


def analyze_segments(
    request: EstimatorRequest, segments: tuple[Segment, ...], *,
    correction_config: VelocityCorrectionConfig, pool: AlgorithmPool | None = None,
    progress: Callable[[str], None] | None = None,
) -> SegmentedResult:
    validate_plan(segments, request.start_s, request.end_s)
    registry = default_pool() if pool is None else pool
    cache: dict[str, BeatEstimate | Exception] = {}
    times, frequencies, candidates = [], [], []
    segment_ids: list[str] = []
    algorithm_ids: list[str] = []
    quality: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        name = segment.algorithm
        cache_key = f"{name}:{segment.id}" if name in STRATEGIES else name
        if cache_key not in cache:
            if progress is not None:
                progress(name)
            try:
                scoped = replace(request, segment=segment) if name in STRATEGIES else request
                cache[cache_key] = registry.estimate(name, scoped)
            except Exception as exc:
                cache[cache_key] = exc
        entry = cache[cache_key]
        error: str | None = None
        if isinstance(entry, Exception):
            error = f"{type(entry).__name__}: {entry}"
            base = _unobservable(request)
            estimate = BeatEstimate(base.time_s, base.frequency_hz, base.candidate_frequency_hz,
                                    ("ALGORITHM_ERROR",) * len(base.time_s), name,
                                    "failed algorithm; no fallback", base.support_samples)
        else:
            estimate = entry
        last = segment_index == len(segments) - 1
        selected = ((estimate.time_s >= segment.start_s)
                    & ((estimate.time_s <= segment.end_s) if last
                       else (estimate.time_s < segment.end_s)))
        indices = np.flatnonzero(selected)
        selected_time = estimate.time_s[selected]
        times.append(selected_time)
        frequencies.append(estimate.frequency_hz[selected])
        candidates.append(estimate.candidate_frequency_hz[selected])
        segment_ids.extend([segment.id] * len(indices))
        algorithm_ids.extend([name] * len(indices))
        half_support = estimate.support_samples / (2 * request.record.sample_rate_hz)
        for index in indices:
            flag = estimate.quality[index]
            t = estimate.time_s[index]
            if estimate.details.get("support_policy") not in ("clip", "one_sided") and (
                    (segment_index > 0 and t - half_support < segment.start_s)
                    or (not last and t + half_support >= segment.end_s)):
                flag += "|BOUNDARY_CONTEXT"
            if segment.stage == "stationary" and "OPERATOR_STATIONARY_PRIOR" not in flag:
                flag += "|OPERATOR_STATIONARY_PRIOR_NOT_MEASUREMENT"
            quality.append(flag)
        diagnostics.append({"id": segment.id, "algorithm": name, "source": estimate.source,
                            "frames": len(indices), "error": error,
                            "support_samples": estimate.support_samples,
                            "details": dict(estimate.details)})
    time = np.concatenate(times)
    frequency = np.concatenate(frequencies)
    candidate = np.concatenate(candidates)
    apparent = frequency * (request.wavelength_m / 2)
    corrections = apply_velocity_corrections(
        apparent, config=correction_config, vacuum_wavelength_m=request.wavelength_m)
    return SegmentedResult(
        time, frequency, candidate, apparent,
        corrections.angle_corrected_apparent_velocity_m_s, corrections.corrected_velocity_m_s,
        tuple(segment_ids), tuple(algorithm_ids), tuple(quality), segments,
        request.wavelength_m, correction_config,
        {"schema": "pdv-manual-segments/1", "mode": "research_test_segmented",
         "interval_ownership": "[start,end); final endpoint inclusive",
         "boundary_policy": "legacy retains context; explicit TASK-015 strategies clip; never interpolate",
         "branch_identity": "OPERATOR_SELECTED_UNVALIDATED",
         "raw_processing": "no resampling/smoothing/zero filling",
         "algorithms": diagnostics, "workflow_options": dict(request.workflow_options),
         "physical_correction": velocity_correction_metadata(corrections)},
    )
