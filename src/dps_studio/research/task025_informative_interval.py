"""GT-blind scheduling statistics. Frozen TASK-024 E1 is called, not redefined."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import numpy as np
from numpy.typing import NDArray

from dps_studio.research import task023h_raw_evidence as e

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True)
class SupportStatistics:
    e1: FloatArray
    analytic_rms_v: FloatArray
    quality: tuple[str, ...]


def strongest_support(raw_time_s: FloatArray, voltage_v: FloatArray,
                      frame_time_s: FloatArray, strongest_hz: FloatArray,
                      stft_window_s: float) -> SupportStatistics:
    """Exact historical strongest-local constant-frequency evidence protocol."""
    if frame_time_s.shape != strongest_hz.shape or not np.all(np.isfinite(strongest_hz)):
        raise ValueError('Expected finite complete strongest trajectory')
    analytic = e.analytic_signal(raw_time_s, voltage_v)
    scores, rms, flags = [], [], []
    for center, frequency in zip(frame_time_s, strongest_hz, strict=True):
        left = int(np.searchsorted(raw_time_s, center-stft_window_s/2, side='left'))
        right = int(np.searchsorted(raw_time_s, center+stft_window_s/2, side='left'))
        value = e.demodulated_evidence(raw_time_s[left:right], analytic[left:right],
            np.full(right-left, frequency), stft_window_s)
        scores.append(value.E1)
        rms.append(value.amplitude_rms_v)
        flags.append(value.quality)
    return SupportStatistics(np.asarray(scores), np.asarray(rms), tuple(flags))


def calibration_threshold(calibration_values: FloatArray,
                          calibration_target_present: BoolArray,
                          *, split: str) -> float:
    """Only a calibration caller may select the shared .995-recall threshold."""
    if split != 'CALIBRATION':
        raise ValueError('Threshold selection is CALIBRATION only')
    if calibration_values.shape != calibration_target_present.shape:
        raise ValueError('Calibration labels/values must match')
    positives = calibration_values[calibration_target_present]
    if not len(positives):
        raise ValueError('No calibration target frames')
    required = ceil(.995 * len(positives))
    finite = np.sort(positives[np.isfinite(positives)])
    if len(finite) < required:
        raise ValueError('NOT SUPPORTED: calibration finite recall below .995')
    # Any higher observed value would exclude at least one of the required values.
    return float(finite[len(finite)-required])


def runs(mask: BoolArray) -> tuple[tuple[int, int], ...]:
    """Half-open runs, including boundary runs and an empty input."""
    changes = np.diff(np.r_[False, mask, False].astype(int))
    return tuple((int(a), int(b)) for a, b in zip(np.flatnonzero(changes == 1),
                 np.flatnonzero(changes == -1), strict=True))


def informative_mask(time_s: FloatArray, values: FloatArray,
                     threshold: float) -> tuple[BoolArray, BoolArray]:
    """Frozen four-frame persistence followed by physical 16 ns context union."""
    if (values.shape != time_s.shape or values.ndim != 1 or
        not np.isfinite(threshold) or not np.all(np.isfinite(time_s)) or
        np.any(np.diff(time_s) <= 0)):
        raise ValueError('Invalid frame grid/statistic/threshold')
    supported = np.isfinite(values) & (values >= threshold)
    active = np.zeros(len(values), dtype=bool)
    for first, stop in runs(supported):
        if stop-first >= 4:
            active |= (time_s >= time_s[first]-16e-9) & (time_s <= time_s[stop-1]+16e-9)
    return supported, active


def complete_output(strongest_hz: FloatArray, proposed_hz: FloatArray,
                    active: BoolArray) -> FloatArray:
    """Keep complete finite baseline; permit proposed values only inside intervals."""
    if (strongest_hz.shape != proposed_hz.shape or active.shape != strongest_hz.shape
        or strongest_hz.ndim != 1 or not np.all(np.isfinite(strongest_hz))
        or not np.all(np.isfinite(proposed_hz[active]))):
        raise ValueError('A complete finite output is required; no filling missing values')
    result = strongest_hz.copy()
    result[active] = proposed_hz[active]
    return result
