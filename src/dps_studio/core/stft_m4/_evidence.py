"""Shared raw-waveform fits and per-frame verification inputs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from scipy.fft import next_fast_len  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation.strategies import baseline, fit_tone

from .models import MatchedEvidence, RawEvidence
from .waveform import (
    FLOOR, WINDOW_NS, Bool, Float, Int, Quiet, Steps, center_power, centers, chirp_phase, coherence,
    complete, detrend, offsets, quadrature, quadrature_stats, quiet_model, same_side_weights,
    samples_for_ns, split_half_coherence,
)


@dataclass(frozen=True)
class Channel:
    record: SignalRecord
    fmin: float
    fmax: float
    check: Callable[[], None]
    update: Callable[[int, str], None]

    @cached_property
    def t(self) -> Float:
        return self.record.time_s

    @cached_property
    def y(self) -> Float:
        return self.record.voltage_v

    @property
    def fs(self) -> float:
        return self.record.sample_rate_hz

    @cached_property
    def q(self) -> Int:
        return centers(len(self.y))

    @cached_property
    def quiet(self) -> Quiet:
        return quiet_model(self.y, self.fs, self.q, fmin=self.fmin, fmax=self.fmax, check=self.check)

    @cached_property
    def b1_frequency(self) -> Float:
        axis = np.fft.rfftfreq(4096, 1 / self.fs)
        return axis[(axis >= self.fmin) & (axis <= self.fmax)]

    def coherent_grid(self, width: int) -> tuple[int, Int, Float]:
        nfft = int(next_fast_len(max(width, round(self.fs/19.5e6))))
        bins = np.arange(int(np.ceil(self.fmin*nfft/self.fs)),
                         int(np.floor(self.fmax*nfft/self.fs))+1, dtype=np.int64)
        return nfft, bins, np.asarray(bins*self.fs/nfft)

    @cached_property
    def coherent_frequency(self) -> Float:
        # The longest scale gives the reference sampling for the M4 raster.
        return self.coherent_grid(samples_for_ns(WINDOW_NS[-1], self.fs))[2]


@dataclass(frozen=True, slots=True)
class _PreparedFrame:
    voltage: Float
    weights: Float
    residual: Float
    left_residual: Float
    right_residual: Float


class RawEvaluator:
    """Use identical original-voltage conventions for B1, M4 and matched STFT."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    @cached_property
    def local_snr_db(self) -> Float:
        ch = self.channel
        power = center_power(ch.y, ch.q, samples_for_ns(6.4, ch.fs), ch.quiet.steps, ch.check)
        return np.asarray(10*np.log10(np.maximum(power, FLOOR) / ch.quiet.noise_power_v2))

    def _prepare(
        self, q: Int, steps: Steps, width: int, degree: int, usable: Bool | None,
    ) -> _PreparedFrame:
        ch = self.channel
        indices = q[:, None] + offsets(width)
        w = same_side_weights(q, width, steps, len(ch.y))
        if usable is not None:
            w *= usable[indices]
        y = ch.y[indices]
        half = width // 2
        return _PreparedFrame(
            y, w, detrend(y, w, degree),
            detrend(y[:, :half], w[:, :half], degree),
            detrend(y[:, half:], w[:, half:], degree),
        )

    def matched(
        self, frames: Int, hz: Float, rate: Float, duration_ns: float, *,
        steps: Steps | None = None, usable_samples: Bool | None = None,
        progress: tuple[int, int] | None = None,
    ) -> MatchedEvidence:
        """Share frame-invariant voltage, masks and projections across chirps."""
        ch = self.channel
        width = samples_for_ns(duration_ns, ch.fs)
        half = width // 2
        degree = 2 if duration_ns >= 25.6 else 1
        q = ch.q[frames]
        legal = complete(q, len(ch.y), width) & np.isfinite(hz) & np.isfinite(rate)
        valid = np.flatnonzero(legal)
        phasor = np.full(len(frames), np.nan + 1j*np.nan)
        r2, snr_db, half_snr_db, rho, left_db, right_db = (
            np.full(len(frames), np.nan) for _ in range(6)
        )
        sample = offsets(width) / ch.fs
        steps = ch.quiet.steps if steps is None else steps
        # Verification enumerates nominees in frame order. Group them by
        # unique center before gathering, then keep the batch working set bounded.
        unique, inverse = np.unique(q[valid], return_inverse=True)
        groups = np.argsort(inverse, kind="stable")
        boundaries = np.searchsorted(inverse[groups], np.arange(len(unique)+1))
        last_percent = -1
        for start in range(0, len(unique), 16):
            ch.check()
            stop = min(start+16, len(unique))
            if progress is not None:
                first, last = progress
                percent = first+(last-first)*stop//len(unique)
                if percent > max(first, last_percent):
                    ch.update(percent, f"M4 原波形门控 · {duration_ns:g} ns")
                    last_percent = percent
            prepared = self._prepare(unique[start:stop], steps, width, degree, usable_samples)
            selection = groups[boundaries[start]:boundaries[stop]]
            for begin in range(0, len(selection), 64):
                ch.check()
                take = selection[begin:begin+64]
                ok = valid[take]
                rows = inverse[take] - start
                y, w = prepared.voltage[rows], prepared.weights[rows]
                phase = chirp_phase(sample, hz[ok, None], rate[ok, None])
                bed = 2*np.interp(hz[ok], ch.quiet.frequency_hz, ch.quiet.floor_v2)
                phasor[ok], r2[ok], power = quadrature_stats(
                    y, phase, w, degree, residual=prepared.residual[rows],
                )
                zl, _, pl = quadrature_stats(
                    y[:, :half], phase[:, :half], w[:, :half], degree,
                    residual=prepared.left_residual[rows],
                )
                zr, _, pr = quadrature_stats(
                    y[:, half:], phase[:, half:], w[:, half:], degree,
                    residual=prepared.right_residual[rows],
                )
                left = w[:, :half].sum(axis=1) >= half//4
                right = w[:, half:].sum(axis=1) >= half//4
                snr_db[ok] = 10*np.log10(np.maximum(power/bed, FLOOR))
                left_db[ok] = np.where(left, 10*np.log10(np.maximum(pl/bed, FLOOR)), -np.inf)
                right_db[ok] = np.where(right, 10*np.log10(np.maximum(pr/bed, FLOOR)), -np.inf)
                half_snr_db[ok] = np.where(
                    left & right, 10*np.log10(np.maximum(np.minimum(pl, pr)/bed, FLOOR)), -np.inf,
                )
                rho[ok] = np.where(left & right, coherence(zl, zr), np.nan)
        return MatchedEvidence(phasor, r2, snr_db, half_snr_db, rho, left_db, right_db)

    def evaluate(self, hz: Float, rate: Float) -> RawEvidence:
        ch = self.channel
        if hz.shape != ch.q.shape or rate.shape != ch.q.shape:
            raise ValueError("Hypotheses must match the comparison center grid")
        legal = np.isfinite(hz) & (hz >= ch.fmin) & (hz <= ch.fmax)
        rate = np.where(np.isfinite(rate), rate, 0.)
        short = samples_for_ns(6.4, ch.fs)
        long = samples_for_ns(25.6, ch.fs)
        tone, chirp, long_chirp, rho = (np.full(len(hz), np.nan) for _ in range(4))
        short_rows = np.flatnonzero(legal & complete(ch.q, len(ch.y), short))
        sample = offsets(short)
        tau = sample / ch.fs
        if short == 256:
            # Preserve the 40 GS/s TASK-023 legacy 256-sample SVD fit.
            null = baseline(tau, 1)
            for number, i in enumerate(short_rows):
                if number % 16 == 0:
                    ch.check()
                y = ch.y[ch.q[i] + sample]
                tone[i] = fit_tone(tau, y, hz[i], null)[0]
                chirp[i] = fit_tone(tau, y, hz[i], null, rate[i])[0]
        else:
            for start in range(0, len(short_rows), 64):
                ch.check()
                use = short_rows[start:start+64]
                y = ch.y[ch.q[use, None] + sample]
                _, tone[use] = quadrature(y, chirp_phase(tau, hz[use, None], 0.))
                _, chirp[use] = quadrature(y, chirp_phase(tau, hz[use, None], rate[use, None]))
        long_rows = np.flatnonzero(legal & complete(ch.q, len(ch.y), long))
        sample = offsets(long)
        tau = sample / ch.fs
        for start in range(0, len(long_rows), 64):
            ch.check()
            use = long_rows[start:start+64]
            y = ch.y[ch.q[use, None] + sample]
            phase = chirp_phase(tau, hz[use, None], rate[use, None])
            _, long_chirp[use] = quadrature(y, phase, degree=2)
            rho[use] = split_half_coherence(y, phase, degree=2)
        return RawEvidence(tone, chirp, long_chirp, rho, self.local_snr_db)
