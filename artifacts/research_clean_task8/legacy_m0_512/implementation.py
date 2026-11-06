"""Literal historical M0: Top-20 amplitude rank one, discrete fallback explicit."""
from __future__ import annotations

import numpy as np

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import GlobalPathConfig, extract_global_path_candidates
from dps_studio.core.time_frequency import compute_stft

from ..common import Context, Estimate, finish

PARAMETERS = dict(window=512, overlap=384, nfft=4096, top_k=20,
                  minimum_frequency_hz=50e6, maximum_frequency_hz=6e9,
                  selection="historical rank-one transition_frequency_hz",
                  fallback="explicit refined-if-finite else discrete-bin; uncalibrated hypothesis")


def run_width(context: Context, width: int) -> Estimate:
    record = SignalRecord(context.signal.time_s, context.signal.voltage_v)
    stft = compute_stft(record, window_length_samples=width,
                        overlap_samples=width-128, nfft=4096, window_name="hann")
    candidates = extract_global_path_candidates(stft, minimum_frequency_hz=50e6,
                    maximum_frequency_hz=6e9, config=GlobalPathConfig(top_k=20))
    chosen = [frame[0] for frame in candidates.candidates_by_frame]
    select = context.seed_indices if width == 512 else np.arange(len(chosen))
    f = np.asarray([chosen[i].transition_frequency_hz for i in select])
    refined = np.asarray([chosen[i].refined_frequency_hz for i in select])
    discrete = np.asarray([chosen[i].discrete_frequency_hz for i in select])
    result = finish(context, f, mask_before_onset=False,
                    details={"historical_m0_contract": "explicit discrete fallback retained",
                             "all_candidate_values_are_hypotheses": True},
                    extra={"discrete_hz": discrete, "strict_refined_hz": refined})
    energy = np.max(abs(stft.spectrum)[context.band], axis=0)**2
    high = np.flatnonzero(energy > max(float(np.median(energy[:max(3, len(energy)//10)]))*8, 1e-300))
    result.onset_s = float(stft.time_s[high[0]]) if len(high) else None
    return result


def run(context: Context) -> Estimate:
    return run_width(context, 512)
