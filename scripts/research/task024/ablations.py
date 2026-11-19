"""Run isolated interventions on the frozen TASK-023 M4 call graph.

Function copies bind dependencies in private namespaces. No TASK-023 module
attributes or shared bank arrays are patched, including during an exception.
"""
from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from functools import cached_property, lru_cache
from time import perf_counter
from types import FunctionType
from typing import ParamSpec, TypeVar, cast

import numpy as np
from numpy.typing import NDArray

from scripts.research.task023 import coherent, phase_coherent as m4, pursuit
from scripts.research.task023.coherent import Hypotheses
from scripts.research.task023.common import Channel, Estimate, RawEvaluator, RawEvidence
from scripts.research.task023.waveform import Bool, Float, Int, Quiet, Steps, quiet_model

FULL = "M4_full"
NO_CHIRP = "M4_no_chirp"
NO_STEP = "M4_no_step_rail"
NO_CFAR = "M4_no_cfar"
NO_LOW = "M4_no_lowfreq_floor"
NO_CW = "M4_no_cw_harmonic"
NO_PATH = "M4_no_path_gap"
VARIANTS = (FULL, NO_CHIRP, NO_STEP, NO_CFAR, NO_LOW, NO_CW, NO_PATH)
P = ParamSpec("P")
R = TypeVar("R")


def _bind(fn: Callable[P, R], **overrides: object) -> Callable[P, R]:
    namespace = {**fn.__globals__, **overrides}
    bound = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
    bound.__kwdefaults__ = fn.__kwdefaults__
    return cast(Callable[P, R], bound)


def _time(timing: dict[str, float], stage: str, fn: Callable[[], R]) -> R:
    start = perf_counter()
    value = fn()
    timing[stage] = timing.get(stage, 0.) + perf_counter()-start
    return value


@dataclass(frozen=True)
class _StudyChannel(Channel):
    keep_edges: bool = True
    timing: dict[str, float] | None = None

    @cached_property
    def quiet(self) -> Quiet:
        def build() -> Quiet:
            return quiet_model(self.y, self.fs, self.q, fmax=self.fmax)

        quiet = build() if self.timing is None else _time(self.timing, "quiet_model", build)
        if self.keep_edges:
            return quiet
        return replace(quiet, steps=Steps(np.empty(0, dtype=np.int64), np.empty(0)))


class _NoCfar(m4._VerificationNoise):
    def background_loss(self, frames: Int, hz: Float, duration_ns: float) -> Float:
        return np.zeros_like(hz)


class _NoLowFloor(m4._VerificationNoise):
    def low_frequency_loss(self, hz: Float) -> Float:
        return np.zeros_like(hz)


@lru_cache(maxsize=1)
def _verify_without_low_gate() -> Callable[
    [Channel, RawEvaluator, Hypotheses, Int, Int, Steps, Bool, m4._VerificationNoise],
    m4.Verification,
]:
    """Remove just the sustained-oscillation veto from the frozen verifier.

    Reuse every other gate and its evaluation order. Check the full block's
    statement targets before removal so an upstream rearrangement fails closed.
    """
    fn = m4._verify
    tree = ast.parse(inspect.getsource(fn))
    definition = tree.body[0]
    if not isinstance(definition, ast.FunctionDef):
        raise RuntimeError("Unexpected TASK-023 verifier definition")
    expected = (
        "low = np.flatnonzero(valid & (hz < 250e6))",
        "low_fit = ev.matched(frame[low], hz[low], rate[low], LONGEST_NS)",
        "min_r2 = np.where((hz[low] < 200e6) & ~short_anchor[low], .15, .10)",
        "_, low_positive = _short_cycles(ch, hz[low], rate[low], samples_for_ns(LONGEST_NS, ch.fs))",
        "valid[low] &= (low_positive & (abs(short.phasor[low]) <= 3.*abs(low_fit.phasor))"
        " & (low_fit.r2 >= min_r2) & (low_fit.rho >= .55)"
        " & (low_fit.snr_db - low_loss[low] >= 8.)"
        " & (low_fit.half_snr_db - low_loss[low] >= 4.5))",
    )
    block = [ast.dump(ast.parse(line).body[0]) for line in expected]
    body = [ast.dump(node) for node in definition.body]
    starts = [i for i in range(len(body)) if body[i:i+len(block)] == block]
    if len(starts) != 1:
        raise RuntimeError("TASK-023 sustained-oscillation gate changed. Update the intervention.")
    del definition.body[starts[0]:starts[0]+len(block)]
    namespace = dict(fn.__globals__)
    exec(compile(tree, inspect.getfile(fn), "exec"), namespace)
    return cast(Callable[
        [Channel, RawEvaluator, Hypotheses, Int, Int, Steps, Bool, m4._VerificationNoise],
        m4.Verification,
    ], namespace[fn.__name__])


def _nominate_tone(
    residual: Float, gate: Float, phase_factor: NDArray[np.complex64], rate: Float,
    nfft: int, df: float, band: Int, positive: Bool, previous: Float, *, fmax: float,
) -> tuple[Float, Float]:
    zero = rate == 0.
    return pursuit._nominate(residual, gate, phase_factor[zero], rate[zero], nfft, df,
                             band, positive[zero], previous, fmax=fmax)


def _tone_gaps(ch: Channel, h: Hypotheses, path: Int, near: Bool) -> Hypotheses:
    search = m4._around_gaps(ch, h, path, near)
    # Keep the three frequency offsets with exactly zero rate offset on each side.
    keep = [3, 4, 5, 12, 13, 14]
    return Hypotheses(search.hz[:, keep], search.rate[:, keep], search.score[:, keep],
                      search.rho[:, keep], search.scale_ns[:, keep])


def _without_cw(ch: Channel, h: Hypotheses, valid: Bool) -> tuple[Int, Bool, Bool]:
    null = coherent.off_threshold()
    score = np.where(valid, np.maximum(h.score, null), -np.inf)
    path, jump = coherent.kinematic_path(replace(h, score=score), ch.t[ch.q],
                                         np.ones(len(ch.q), dtype=np.bool_), null,
                                         entry_penalty=.95, persistent_cw=None, jump_cost=3.)
    # Keep observational CW flags for the common readout only.
    cw, _ = m4._persistent_cw(h, valid, fmax=ch.fmax)
    return path, jump, cw


def _greedy(ch: Channel, h: Hypotheses, valid: Bool) -> tuple[Int, Bool, Bool]:
    cw, _ = m4._persistent_cw(h, valid, fmax=ch.fmax)
    rank = np.argmax(np.where(valid, h.score, -np.inf), axis=1)
    return np.where(valid.any(axis=1), rank, -1), np.zeros(len(rank), dtype=np.bool_), cw


def _never_isolate(
    valid: Bool, score: Float, r2: Float, duration: Float, hz: Float, rate: Float, dt: float,
) -> Bool:
    return np.zeros_like(valid)


def _no_gaps(ch: Channel, h: Hypotheses, path: Int, near: Bool) -> Hypotheses:
    return m4._around_gaps(ch, h, np.full_like(path, -1), near)


def _no_rail(y: Float) -> Bool:
    return np.zeros(len(y), dtype=np.bool_)


@dataclass(frozen=True)
class AblationRun:
    estimate: Estimate
    seconds: dict[str, float]
    initial_bank: tuple[Hypotheses, Bool]


def run_variant(
    ch: Channel, variant: str, shared: tuple[Hypotheses, Bool] | None = None,
) -> AblationRun:
    """Run one intervention, accepting shared proposals only for unchanged banks."""
    if variant not in VARIANTS or (shared is not None and variant in (FULL, NO_CHIRP, NO_STEP)):
        raise ValueError(f"Incompatible variant or proposal bank: {variant}")
    timing: dict[str, float] = {}
    channel = _StudyChannel(ch.id, ch.t, ch.y, ch.fs, fmax=ch.fmax,
                            keep_edges=variant != NO_STEP, timing=timing)
    scale_fn = (_bind(coherent._scale_peaks, RATES=np.zeros(1)) if variant == NO_CHIRP
                else coherent._scale_peaks)
    pursue_fn = (_bind(pursuit._pursue, _nominate=_nominate_tone) if variant == NO_CHIRP
                 else pursuit._pursue)
    verify_fn = _verify_without_low_gate() if variant == NO_LOW else m4._verify
    select_fn = {NO_CW: _without_cw, NO_PATH: _greedy}.get(variant, m4._select)
    gap_fn = {NO_CHIRP: _tone_gaps, NO_PATH: _no_gaps}.get(variant, m4._around_gaps)
    noise = {NO_CFAR: _NoCfar, NO_LOW: _NoLowFloor}.get(variant, m4._VerificationNoise)
    bank = shared
    in_gap = False

    def scale(ch: Channel, duration: float) -> Hypotheses:
        return _time(timing, f"_scale_peaks_{duration:g}ns", lambda: scale_fn(ch, duration))

    def pursue(
        ch: Channel, duration: float, rail: Bool, impulse: Float, *, selected: Bool,
        atom_count: int, secondary_gain: float, reject_harmonics: bool,
    ) -> pursuit.PursuitFit:
        return _time(timing, f"_pursue_{duration:g}ns", lambda: pursue_fn(
            ch, duration, rail, impulse, selected=selected, atom_count=atom_count,
            secondary_gain=secondary_gain, reject_harmonics=reject_harmonics,
        ))

    make_bank = _bind(m4._propose, hypotheses=_bind(coherent.hypotheses, _scale_peaks=scale),
                      _pursue=pursue)

    def propose(ch: Channel, ev: RawEvaluator, rail: Bool, near: Bool) -> tuple[Hypotheses, Bool]:
        nonlocal bank
        if bank is None:
            bank = _time(timing, "_propose_total", lambda: make_bank(ch, ev, rail, near))
        return bank

    def verify(
        ch: Channel, ev: RawEvaluator, h: Hypotheses, frame: Int, col: Int,
        edges: Steps, rail: Bool, noise: m4._VerificationNoise,
    ) -> m4.Verification:
        return _time(timing, "_verify_gap" if in_gap else "_verify_initial",
                     lambda: verify_fn(ch, ev, h, frame, col, edges, rail, noise))

    def select(ch: Channel, h: Hypotheses, valid: Bool) -> tuple[Int, Bool, Bool]:
        return _time(timing, "_select_final" if in_gap else "_select_initial",
                     lambda: select_fn(ch, h, valid))

    def gap(ch: Channel, h: Hypotheses, path: Int, near: Bool) -> Hypotheses:
        nonlocal in_gap
        in_gap = True
        return _time(timing, "_around_gaps", lambda: gap_fn(ch, h, path, near))

    class TimedEvaluator(RawEvaluator):
        def evaluate(self, hz: Float, rate: Float) -> RawEvidence:
            evaluate = super().evaluate
            return _time(timing, "RawEvaluator.evaluate", lambda: evaluate(hz, rate))

    engine = _bind(m4.m4_phase_coherent, _propose=propose, _VerificationNoise=noise,
                   RawEvaluator=TimedEvaluator, _verify=verify, _select=select, _around_gaps=gap,
                   rail_mask=_no_rail if variant == NO_STEP else pursuit.rail_mask,
                   _isolated=_never_isolate if variant == NO_PATH else m4._isolated)
    result = _time(timing, "cold_total" if shared is None else "shared_total",
                   lambda: engine(channel))
    assert bank is not None
    return AblationRun(result, timing, bank)


def assert_exact(a: Estimate, b: Estimate) -> None:
    for key in ("sample_index", "candidate_hz", "accepted_hz", "chirp_hz_s"):
        np.testing.assert_array_equal(getattr(a, key), getattr(b, key), err_msg=key)
    for field in fields(RawEvidence):
        np.testing.assert_array_equal(getattr(a.raw, field.name), getattr(b.raw, field.name),
                                      err_msg=field.name)
    assert a.diagnostics.keys() == b.diagnostics.keys()
    for key in a.diagnostics:
        np.testing.assert_array_equal(a.diagnostics[key], b.diagnostics[key], err_msg=key)
