"""TASK005: persistent spectral-band hypotheses from untouched Top-20 nodes.

The STFT tube is a derived *evidence* image, never a filtered voltage or an
output frequency. Only original candidate values can enter the returned path.
Support and continuity do not certify target identity or a velocity correction.
All times, frequencies and slopes use seconds, Hz and Hz/s, respectively.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.core.time_frequency import STFTResult

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


def _positive(value: float, name: str, *, zero: bool = False) -> None:
    if not np.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


@dataclass(frozen=True)
class BandSeed:
    """One identity hint; the tolerance does not impose a trajectory."""

    time_s: float
    frequency_hz: float
    frequency_tolerance_hz: float = 100e6

    def __post_init__(self) -> None:
        if not np.isfinite(self.time_s):
            raise ValueError("seed time must be finite")
        _positive(self.frequency_hz, "seed frequency_hz", zero=True)
        _positive(self.frequency_tolerance_hz, "frequency_tolerance_hz")


@dataclass(frozen=True)
class BandConfig:
    """Adjustable research settings; ``dataclasses.asdict`` preserves all fields.

    Tube support counts observed foreground along each straight local orientation.
    Its frequency half-width and the graph tolerance scale with window-limited
    resolution, not the zero-padded FFT bin spacing. The absolute link cap applies
    in addition to the slope gate. No candidate rank or frequency boundary gets
    a preference. Auto ambiguity compares persistence-weighted component scores
    and uses the same relative margin for original peak-magnitude comparability.
    """

    min_candidate_background_db: float = 6.0
    temporal_radius_s: float = 12.8e-9
    orientations_hz_per_s: tuple[float, ...] = (-2e16, -1e16, 0.0, 1e16, 2e16)
    foreground_threshold_db: float = 6.0
    tube_half_width_resolution_factor: float = 0.5
    min_tube_supported_fraction: float = 0.6
    min_fragment_duration_s: float = 32e-9
    max_gap_s: float = 9.6e-9
    max_link_delta_hz: float = 200e6
    max_slope_hz_per_s: float = 2e16
    link_tolerance_resolution_factor: float = 0.5
    frequency_cost_weight: float = 0.3
    gap_cost_weight: float = 0.75
    background_reward_clip_db: float = 24.0
    automatic_min_relative_margin: float = 0.2
    companion_time_tolerance_s: float = 0.05e-9
    companion_frequency_tolerance_resolution_factor: float = 0.5

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name == "orientations_hz_per_s":
                continue
            value = float(getattr(self, item.name))
            _positive(value, item.name, zero=item.name in {
                "min_candidate_background_db", "foreground_threshold_db",
                "frequency_cost_weight", "gap_cost_weight", "automatic_min_relative_margin",
                "companion_time_tolerance_s"})
        if not self.orientations_hz_per_s or not np.isfinite(self.orientations_hz_per_s).all():
            raise ValueError("orientations_hz_per_s must contain finite slopes")
        if self.min_tube_supported_fraction > 1 or self.automatic_min_relative_margin >= 1:
            raise ValueError("support fraction must be <= 1 and automatic margin < 1")


@dataclass(frozen=True, eq=False)
class BandObservations:
    """Detached observations; candidate bin indices are LOCAL to the band grid.

    Candidate column j retains original frame tuple index j, including amplitude
    ordering. Missing candidates use NaN frequency/background and bin index -1.
    A real candidate with unavailable contrast may also have NaN background.
    """

    time_s: FloatArray
    grid_frequency_hz: FloatArray
    magnitude: FloatArray
    candidate_frequency_hz: FloatArray
    candidate_background_db: FloatArray
    candidate_bin_indices: IntArray
    resolution_hz: float

    def __post_init__(self) -> None:
        _positive(self.resolution_hz, "resolution_hz")
        for name in ("time_s", "grid_frequency_hz", "magnitude",
                     "candidate_frequency_hz", "candidate_background_db"):
            array = np.array(getattr(self, name), dtype=np.float64, copy=True)
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        bins_raw = np.asarray(self.candidate_bin_indices)
        if not np.issubdtype(bins_raw.dtype, np.integer):
            raise ValueError("candidate_bin_indices must be integer-valued")
        bins = np.array(bins_raw, dtype=np.int64, copy=True)
        bins.setflags(write=False)
        object.__setattr__(self, "candidate_bin_indices", bins)
        for name in ("time_s", "grid_frequency_hz"):
            axis = getattr(self, name)
            if (axis.ndim != 1 or not axis.size or not np.isfinite(axis).all()
                    or not (np.diff(axis) > 0).all()):
                raise ValueError(f"{name} must be finite, nonempty and strictly increasing")
        if self.grid_frequency_hz[0] < 0:
            raise ValueError("frequency grid must be nonnegative")
        expected = (len(self.grid_frequency_hz), len(self.time_s))
        if self.magnitude.shape != expected or not np.isfinite(self.magnitude).all():
            raise ValueError("magnitude must be finite with shape (frequency, time)")
        if (self.magnitude < 0).any():
            raise ValueError("magnitude must be nonnegative")
        shape = self.candidate_frequency_hz.shape
        if (len(shape) != 2 or shape[0] != len(self.time_s) or shape[1] < 1
                or self.candidate_background_db.shape != shape or bins.shape != shape):
            raise ValueError("candidate arrays must share shape (time, K), K >= 1")
        valid = np.isfinite(self.candidate_frequency_hz)
        if (np.isinf(self.candidate_frequency_hz).any()
                or np.isinf(self.candidate_background_db).any()
                or not np.isnan(self.candidate_background_db[~valid]).all()
                or (bins[~valid] != -1).any() or (bins[valid] < 0).any()
                or (bins[valid] >= len(self.grid_frequency_hz)).any()):
            raise ValueError("invalid candidate padding or bin indices")
        frequencies = self.candidate_frequency_hz[valid]
        if ((frequencies < self.grid_frequency_hz[0]).any()
                or (frequencies > self.grid_frequency_hz[-1]).any()):
            raise ValueError("candidate frequency lies outside the observation band")


@dataclass(frozen=True, eq=False)
class BandResult:
    """Full-domain hypothesis and evidence; invalid nodes have index/fragment -1.

    ``candidate_companion_support`` marks matching original companion peaks. If
    no companion is supplied, finite primary candidates pass this optional mask.
    Eligible/agreed diagnostic counts are before/after applying this mask to the
    primary background-and-tube eligible nodes, respectively.
    """

    time_s: FloatArray
    frequency_hz: FloatArray
    candidate_indices: IntArray
    quality_flags: tuple[str, ...]
    validated_frequency_hz: FloatArray
    mode: str
    seed: BandSeed | None
    score: FloatArray
    tube_support_fraction: FloatArray
    fragment_ids: IntArray
    candidate_score: FloatArray
    candidate_tube_support_fraction: FloatArray
    candidate_fragment_ids: IntArray
    candidate_companion_support: BoolArray
    diagnostics: dict[str, float | int | str]


def make_observations(stft: STFTResult, peaks: RidgeCandidateSet) -> BandObservations:
    """Copy the shared search band and untouched, ordered Top-20 frequencies."""
    if peaks.config.top_k != 20 or not np.array_equal(stft.time_s, peaks.time_s):
        raise ValueError("expected original Top-20 candidates on the shared STFT time axis")
    band = np.flatnonzero((stft.frequency_hz >= peaks.minimum_frequency_hz)
                          & (stft.frequency_hz <= peaks.maximum_frequency_hz))
    if not band.size:
        raise ValueError("candidate band contains no STFT bins")
    shape = (len(peaks.time_s), peaks.config.top_k)
    frequency = np.full(shape, np.nan)
    background = np.full(shape, np.nan)
    bins = np.full(shape, -1, dtype=np.int64)
    for i, frame in enumerate(peaks.candidates_by_frame):
        for j, candidate in enumerate(frame):
            frequency[i, j] = candidate.transition_frequency_hz
            background[i, j] = candidate.peak_to_background_db
            bins[i, j] = candidate.discrete_bin_index - int(band[0])
    return BandObservations(stft.time_s, stft.frequency_hz[band], np.abs(stft.spectrum[band]),
                            frequency, background, bins,
                            stft.sample_rate_hz / stft.window_length_samples)


def _tube_evidence(obs: BandObservations, cfg: BandConfig) -> tuple[FloatArray, FloatArray]:
    """Sample oriented finite tubes; maximize over orientations, never time-fill."""
    tiny = np.finfo(np.float64).tiny
    median = np.median(obs.magnitude, axis=0)
    image_db = 20 * (np.log10(np.maximum(obs.magnitude, tiny))
                     - np.log10(np.maximum(median, tiny)))
    # Frequency dilation is a feature only. Its support is bounded in physical Hz.
    half_width = cfg.tube_half_width_resolution_factor * obs.resolution_hz
    lower = np.searchsorted(obs.grid_frequency_hz, obs.grid_frequency_hz - half_width)
    upper = np.searchsorted(obs.grid_frequency_hz, obs.grid_frequency_hz + half_width, side="right")
    tube_image = np.empty_like(image_db)
    for i, (lo, hi) in enumerate(zip(lower, upper, strict=True)):
        tube_image[i] = np.max(image_db[lo:hi], axis=0)
    support = np.zeros_like(obs.candidate_frequency_hz)
    strength = np.zeros_like(support)
    for i, time in enumerate(obs.time_s):
        radius = cfg.temporal_radius_s * (1 + 1e-12)
        first = int(np.searchsorted(obs.time_s, time - radius))
        last = int(np.searchsorted(obs.time_s, time + radius, side="right"))
        frames = np.arange(first, last)
        delta_t = obs.time_s[frames] - time
        valid = np.isfinite(obs.candidate_frequency_hz[i])
        frequency = obs.candidate_frequency_hz[i, valid]
        best_support = np.zeros(len(frequency))
        best_strength = np.zeros(len(frequency))
        for slope in cfg.orientations_hz_per_s:
            predicted = frequency[:, None] + slope * delta_t
            bins = np.searchsorted(obs.grid_frequency_hz, predicted)
            bins = np.clip(bins, 0, len(obs.grid_frequency_hz) - 1)
            left = np.maximum(bins - 1, 0)
            bins = np.where(abs(obs.grid_frequency_hz[left] - predicted)
                            < abs(obs.grid_frequency_hz[bins] - predicted), left, bins)
            in_band = ((predicted >= obs.grid_frequency_hz[0])
                       & (predicted <= obs.grid_frequency_hz[-1]))
            values = np.where(in_band, tube_image[bins, frames[None, :]], 0.0)
            fraction = np.mean(in_band & (values >= cfg.foreground_threshold_db), axis=1)
            reward = np.mean(np.clip(values, 0, cfg.background_reward_clip_db), axis=1)
            better = (fraction > best_support) | ((fraction == best_support) & (reward > best_strength))
            best_support = np.where(better, fraction, best_support)
            best_strength = np.where(better, reward, best_strength)
        support[i, valid] = best_support
        strength[i, valid] = best_strength
    return support, strength


def _graph(obs: BandObservations, cfg: BandConfig, valid: BoolArray
           ) -> tuple[IntArray, list[tuple[IntArray, IntArray]], int]:
    """Short-gap connected fragments with both absolute and slope link gates."""
    count, width = valid.shape
    parents = np.arange(count * width, dtype=np.int64)
    edges: list[tuple[IntArray, IntArray]] = []

    def root(node: int) -> int:
        while node != parents[node]:
            parents[node] = parents[parents[node]]
            node = int(parents[node])
        return node

    for i in range(count):
        current = np.flatnonzero(valid[i])
        first = int(np.searchsorted(obs.time_s, obs.time_s[i] - cfg.max_gap_s * (1 + 1e-12)))
        for j in range(first, i):
            previous = np.flatnonzero(valid[j])
            limit = min(cfg.max_link_delta_hz, cfg.max_slope_hz_per_s
                        * (obs.time_s[i] - obs.time_s[j])
                        + cfg.link_tolerance_resolution_factor * obs.resolution_hz)
            delta = abs(obs.candidate_frequency_hz[j, previous, None]
                        - obs.candidate_frequency_hz[i, current][None, :])
            a, b = np.nonzero(delta <= limit)
            source, target = j * width + previous[a], i * width + current[b]
            edges.append((source, target))
            for x, y in zip(source, target, strict=True):
                rx, ry = root(int(x)), root(int(y))
                if rx != ry:
                    parents[ry] = rx
    labels = np.full(count * width, -1, dtype=np.int64)
    groups: dict[int, list[int]] = {}
    for node in np.flatnonzero(valid.ravel()):
        groups.setdefault(root(int(node)), []).append(int(node))
    persistent = 0
    for nodes in groups.values():
        indices = np.array(nodes, dtype=np.int64)
        times = obs.time_s[indices // width]
        if np.max(times) - np.min(times) >= cfg.min_fragment_duration_s * (1 - 1e-12):
            labels[indices] = persistent
            persistent += 1
    return labels.reshape(valid.shape), edges, persistent


def _seed_path(obs: BandObservations, cfg: BandConfig, labels: IntArray,
               edges: list[tuple[IntArray, IntArray]], reward: FloatArray,
               anchor: int) -> IntArray:
    """Exact forward/backward DAG optimization through one observed anchor node."""
    width = labels.shape[1]
    flat_frequency = obs.candidate_frequency_hz.ravel()
    component = labels.ravel()[anchor]
    flat_reward = reward.ravel()
    chosen: set[int] = {anchor}
    hop = float(np.median(np.diff(obs.time_s))) if len(obs.time_s) > 1 else cfg.max_gap_s
    for reverse in (False, True):
        total = np.full(labels.size, -np.inf)
        pointer = np.full(labels.size, -1, dtype=np.int64)
        total[anchor] = flat_reward[anchor]
        for sources, targets in reversed(edges) if reverse else edges:
            a_nodes, b_nodes = (targets, sources) if reverse else (sources, targets)
            for a, b in zip(a_nodes, b_nodes, strict=True):
                if labels.ravel()[b] != component or not np.isfinite(total[a]):
                    continue
                dt = abs(obs.time_s[b // width] - obs.time_s[a // width])
                df = abs(flat_frequency[b] - flat_frequency[a]) / obs.resolution_hz
                cost = cfg.frequency_cost_weight * df**2 + cfg.gap_cost_weight * max(0, dt / hop - 1)
                value = total[a] + flat_reward[b] - cost
                if value > total[b]:
                    total[b], pointer[b] = value, a
        node = int(np.argmax(total))
        while node != -1:
            chosen.add(node)
            node = int(pointer[node])
    return np.array(sorted(chosen), dtype=np.int64)


def _internal_branching(obs: BandObservations, cfg: BandConfig, labels: IntArray,
                        component: int) -> tuple[float, int]:
    """Duration of resolved, comparable simultaneous peaks in one component.

    Raw STFT magnitudes are used only for this automatic ambiguity check. The
    existing relative margin excludes window sidelobes from a clear main peak;
    clipped path rewards must not make those sidelobes appear equally strong.
    Both the two-resolution separation and minimum duration reuse existing
    physical scales. These tests do not modify guided selection or its rewards.
    """
    members = labels == component
    bins = np.maximum(obs.candidate_bin_indices, 0)
    amplitude = obs.magnitude[bins, np.arange(len(obs.time_s))[:, None]]
    strongest = np.max(np.where(members, amplitude, 0.0), axis=1)
    comparable = members & (amplitude >= strongest[:, None]
                           * (1 - cfg.automatic_min_relative_margin))
    lower = np.min(np.where(comparable, obs.candidate_frequency_hz, np.inf), axis=1)
    upper = np.max(np.where(comparable, obs.candidate_frequency_hz, -np.inf), axis=1)
    resolved = upper - lower >= 2 * obs.resolution_hz
    runs = np.flatnonzero(np.diff(np.r_[False, resolved, False].astype(np.int8))).reshape(-1, 2)
    duration = max((float(obs.time_s[stop - 1] - obs.time_s[start])
                    for start, stop in runs), default=0.0)
    return duration, int(np.sum(resolved))


def _within_tolerance(left: FloatArray, right: FloatArray, tolerance: float) -> BoolArray:
    """Inclusive bound with coordinate-scale rounding allowance, not extra physics.

    Compare ``abs(left-right) <= tolerance + 4*eps*max(abs(left), abs(right),
    tolerance)`` elementwise. The allowance covers a few coordinate ULPs lost to
    axis construction/subtraction; it is not a relative relaxation of the
    configured physical tolerance. NaN candidate padding remains unmatched.
    """
    scale = np.maximum(np.maximum(abs(left), abs(right)), tolerance)
    allowance = 4 * np.finfo(np.float64).eps * scale
    return np.asarray(abs(left - right) <= tolerance + allowance, dtype=np.bool_)


def _companion_agreement(obs: BandObservations, companion: BandObservations | None,
                         cfg: BandConfig) -> BoolArray:
    """Match original peaks without temporal interpolation or frequency fusion."""
    if companion is None:
        return np.isfinite(obs.candidate_frequency_hz)
    support = np.zeros(obs.candidate_frequency_hz.shape, dtype=np.bool_)
    right = np.clip(np.searchsorted(companion.time_s, obs.time_s), 0, len(companion.time_s) - 1)
    left = np.maximum(right - 1, 0)
    nearest = np.where(abs(companion.time_s[left] - obs.time_s)
                       <= abs(companion.time_s[right] - obs.time_s), left, right)
    tolerance = (cfg.companion_frequency_tolerance_resolution_factor
                 * max(obs.resolution_hz, companion.resolution_hz))
    aligned = _within_tolerance(companion.time_s[nearest], obs.time_s,
                                cfg.companion_time_tolerance_s)
    for i in np.flatnonzero(aligned):
        j = nearest[i]
        eligible = companion.candidate_background_db[j] >= cfg.min_candidate_background_db
        matched = _within_tolerance(obs.candidate_frequency_hz[i, :, None],
                                    companion.candidate_frequency_hz[j, None, :], tolerance)
        support[i] = np.any(matched & eligible[None, :], axis=1)
    return support


def track_band(observations: BandObservations, *, seed: BandSeed | None = None,
               config: BandConfig = BandConfig(),
               companion: BandObservations | None = None) -> BandResult:
    """Return supported original nodes on the entire domain, retaining NaN gaps.

    A guided seed selects a persistent connected component. A long evidence gap
    terminates that identity component: no prediction reconnects the other side.
    Automatic selection abstains when competing persistent components have close
    scores or one winning component contains persistent, resolved peaks of
    comparable original magnitude. Finite output remains an unvalidated band
    hypothesis; an automatic ambiguity check never changes guided selection.
    An optional second STFT of the same waveform supplies an explicit peak
    agreement mask before graph construction. It is not independent validation;
    outputs still use only untouched primary candidate frequencies and indices.
    """
    obs, cfg = observations, config
    if seed is not None and not (obs.time_s[0] <= seed.time_s <= obs.time_s[-1]
            and obs.grid_frequency_hz[0] <= seed.frequency_hz <= obs.grid_frequency_hz[-1]):
        raise ValueError("seed lies outside the observation time/frequency domain")
    support, tube_strength = _tube_evidence(obs, cfg)
    valid = (np.isfinite(obs.candidate_frequency_hz)
             & (obs.candidate_background_db >= cfg.min_candidate_background_db)
             & (support >= cfg.min_tube_supported_fraction))
    eligible_count = int(np.sum(valid))
    companion_support = _companion_agreement(obs, companion, cfg)
    valid = valid & companion_support
    labels, edges, fragment_count = _graph(obs, cfg, valid)
    reward = (1.0 + support + np.clip(obs.candidate_background_db, 0,
               cfg.background_reward_clip_db) / cfg.background_reward_clip_db
              + tube_strength / cfg.background_reward_clip_db)
    anchor, reason = -1, "NO_PERSISTENT_BAND"
    internal_branch_duration, internal_branch_frames = 0.0, 0
    component_scores = np.zeros(fragment_count)
    for fragment in range(fragment_count):
        nodes = labels == fragment
        # Count supported frames once even if a fragment contains multiple nodes.
        frame_reward = np.max(np.where(nodes, reward, 0.0), axis=1)
        component_scores[fragment] = np.sum(frame_reward)
    if seed is not None:
        frame = int(np.argmin(abs(obs.time_s - seed.time_s)))
        options = np.flatnonzero((labels[frame] >= 0)
                    & (abs(obs.candidate_frequency_hz[frame] - seed.frequency_hz)
                       <= seed.frequency_tolerance_hz))
        reason = "SEED_UNSUPPORTED"
        if options.size:
            j = int(options[np.argmin(abs(obs.candidate_frequency_hz[frame, options] - seed.frequency_hz))])
            anchor = frame * labels.shape[1] + j
    elif fragment_count:
        ordered = np.argsort(component_scores)[::-1]
        winner = int(ordered[0])
        ambiguous = (len(ordered) > 1 and component_scores[ordered[1]]
                     >= component_scores[winner] * (1 - cfg.automatic_min_relative_margin))
        internal_branch_duration, internal_branch_frames = _internal_branching(obs, cfg, labels, winner)
        internal_ambiguous = (internal_branch_duration
                              >= cfg.min_fragment_duration_s * (1 - 1e-12))
        if internal_ambiguous:
            reason = "INTERNAL_IDENTITY_AMBIGUOUS"
        elif ambiguous:
            reason = "IDENTITY_AMBIGUOUS"
        if not ambiguous and not internal_ambiguous:
            nodes = np.flatnonzero(labels.ravel() == winner)
            anchor = int(nodes[np.argmax(reward.ravel()[nodes])])
    selected = (_seed_path(obs, cfg, labels, edges, reward, anchor) if anchor >= 0
                else np.empty(0, dtype=np.int64))
    count, width = labels.shape
    frequencies = np.full(count, np.nan)
    indices = np.full(count, -1, dtype=np.int64)
    scores = np.full(count, np.nan)
    tube = np.full(count, np.nan)
    fragments = np.full(count, -1, dtype=np.int64)
    for node in selected:
        i, j = divmod(int(node), width)
        indices[i], frequencies[i] = j, obs.candidate_frequency_hz[i, j]
        scores[i], tube[i], fragments[i] = reward[i, j], support[i, j], labels[i, j]
    # A branching label is a graph fact, not a calibrated identity probability.
    # Annotate the whole selected component even outside its parallel frames.
    component_id = int(labels.ravel()[anchor]) if anchor >= 0 else -1
    component_nodes = (np.sum(labels == component_id, axis=1) if anchor >= 0
                       else np.zeros(count, dtype=np.int64))
    branched = component_nodes >= 2
    finite_flag = "TUBE_SUPPORTED|IDENTITY_UNVALIDATED"
    if companion is not None:
        finite_flag += "|DUAL_WINDOW_AGREEMENT"
    if np.any(branched):
        finite_flag += "|BRANCHED_COMPONENT"
    flags = tuple(finite_flag if j >= 0
                  else ("NO_BAND_OBSERVATION" if anchor >= 0 else reason) for j in indices)
    validated = np.full(count, np.nan)
    arrays = (frequencies, indices, scores, tube, fragments, validated, reward, support, labels,
              companion_support)
    for array in arrays:
        array.setflags(write=False)
    diagnostics: dict[str, float | int | str] = {
        "persistent_fragment_count": fragment_count, "selected_node_count": len(selected),
        "companion_used": int(companion is not None),
        "candidate_eligible_count": eligible_count,
        "candidate_agreed_count": int(np.sum(valid)),
        "selected_fragment_id": component_id,
        "selected_component_max_nodes_per_frame": int(np.max(component_nodes)),
        "selected_component_branch_frame_count": int(np.sum(branched)),
        "selected_path_branch_frame_count": int(np.sum(branched & (indices >= 0))),
        "automatic_internal_branch_duration_s": internal_branch_duration,
        "automatic_internal_branch_frame_count": internal_branch_frames,
        "best_component_score": float(np.max(component_scores)) if fragment_count else 0.0,
        "selection_status": "OBSERVED_HYPOTHESIS" if anchor >= 0 else reason,
    }
    return BandResult(obs.time_s, frequencies, indices, flags, validated,
                      "guided" if seed is not None else "automatic", seed, scores, tube,
                      fragments, reward, support, labels, companion_support, diagnostics)
