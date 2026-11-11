"""Numerical voting contracts and real-input lineage for TASK-018."""
from __future__ import annotations

import numpy as np
import pytest

from scripts.research.task017.compare import align
from scripts.research.task017.prepare import load
from scripts.research.task018.inputs import coordinates, inventory
from scripts.research.task018.model import Candidate, clusters, vote


def point(key: int, ghz: float, family: str, *, supported: bool = True) -> Candidate:
    return Candidate(key, f'est{key}', family, ghz*1e9, False, supported, (1, key))


def test_duplicate_family_does_not_amplify_its_vote() -> None:
    original = [point(0, 1., 'STFT'), point(1, 1.02, 'VarPro'), point(2, 4., 'STFT')]
    caps = {'STFT': 6e9, 'VarPro': 6e9}
    extra = [*original, point(3, 1., 'STFT'), point(4, 4., 'STFT')]
    v = vote(clusters(original, 100e6), caps, family=True)
    assert v == vote(clusters(extra, 100e6), caps, family=True)
    assert [(p.mass, p.score) for p in v] == [(1.5, .75), (.5, .25)]
    assert sum(p.mass for p in v) == 2.


def test_secondary_pole_divides_estimator_vote() -> None:
    a = point(0, 1., 'Subspace')
    b = Candidate(2, a.estimator, a.family, 4e9, False, True, (2, 0))
    p = vote(clusters([a, b], 100e6), {a.estimator: 6e9}, family=False)
    assert [x.score for x in p] == [.5, .5]
    assert [x.representative for x in p] == [a, b]


def test_narrow_family_does_not_vote_against_high_frequency() -> None:
    a, b = point(0, .19, 'LowGLRT'), point(1, 5.4, 'STFT')
    cap = {'LowGLRT': 250e6, 'STFT': 6e9, 'VarPro': 6e9}
    p = vote(clusters([a, b], 100e6), cap, family=True)
    assert [(x.representative, x.eligible) for x in p] == [(b, 2), (a, 3)]
    p_no_varpro = vote(clusters([a, b], 100e6), {'LowGLRT': 250e6, 'STFT': 6e9}, family=True)
    assert p_no_varpro[0].score == 1.


def test_group_width_and_raw_constraint_preserve_original_frequencies() -> None:
    a, b, c = point(0, 1., 'A', supported=False), point(1, 1.09, 'B'), point(2, 1.18, 'C')
    groups = clusters([b, c, a], 100e6)
    assert groups == [[a, b], [c]]
    cap = dict.fromkeys(('A', 'B', 'C'), 6e9)
    assert vote(groups, cap, family=True)[0].representative == a
    supported = vote(groups, cap, family=True, require_support=True)
    assert [p.representative for p in supported] == [b, c]
    assert all(0. < p.score <= 1. for p in supported)


def test_empty_and_invalid_candidates() -> None:
    assert not vote(clusters([], 100e6), {}, family=True)
    assert not vote(clusters([point(0, .5, 'A', supported=False)], 100e6), {'A': 6e9},
                    family=True, require_support=True)
    for bad in (np.nan, np.inf, -1.):
        with pytest.raises(ValueError):
            clusters([point(0, bad, 'A')], 100e6)
    with pytest.raises(ValueError):
        vote(clusters([point(0, 1., 'A')], 100e6), {'A': 250e6}, family=True)


def test_exact_real_time_centers_and_units() -> None:
    items, plans = inventory()
    assert len({r['file'] for r in items}) == 10
    onset_n = 0
    for item in items:
        t, _, fs = load(item)
        coords = coordinates(item, t, plans[item['id']])
        q = coords.sample_index.to_numpy()
        idx, ok = align(t[q[1::2]], t, fs, q)
        assert np.array_equal(q[ok], q[1::2])
        assert np.array_equal(t[q[1::2]][idx[ok]], coords.time_s.to_numpy()[ok])
        assert 1e9 < fs < 1e12 and np.all(np.diff(q) == 128)
        assert np.array_equal(coords.time_s, t[q])
        onset_n += int(((coords.stage == 'onset') & coords.primary).sum())
    assert onset_n == 69
