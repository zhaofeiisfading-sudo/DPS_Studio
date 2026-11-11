"""Local, bounded votes over observed candidate clusters; no trajectory prior."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class Candidate:
    key: int
    estimator: str
    family: str
    hz: float
    gated: bool
    supported: bool
    priority: tuple[int, int]


def clusters(candidates: Iterable[Candidate], width: float) -> list[list[Candidate]]:
    """No chaining: complete within-cluster frequency span <= width, lower anchor."""
    if not isfinite(width) or width <= 0:
        raise ValueError('Positive finite cluster width required')
    groups: list[list[Candidate]] = []
    for point in sorted(candidates, key=lambda p: (p.hz, p.priority, p.key)):
        if not isfinite(point.hz) or point.hz <= 0:
            raise ValueError('Clusters require legal positive finite frequencies')
        if not groups or point.hz-groups[-1][0].hz > width:
            groups.append([])
        groups[-1].append(point)
    return groups


@dataclass(frozen=True, slots=True)
class Peak:
    cluster: int
    score: float
    mass: float
    voters: int
    eligible: int
    representative: Candidate
    supporters: tuple[str, ...]


def vote(groups: Sequence[Sequence[Candidate]], eligible: Mapping[str, float], *,
         family: bool, require_support: bool = False) -> list[Peak]:
    """Unit budget per voter across distinct clusters; eligibility varies by band."""
    by_voter: dict[str, set[int]] = defaultdict(set)
    presence: list[set[str]] = []
    supported: list[set[str]] = []
    for k, group in enumerate(groups):
        units = set()
        evidence = set()
        for point in group:
            unit = point.family if family else point.estimator
            if unit not in eligible or point.hz > eligible[unit]:
                raise ValueError('Candidate outside voter eligibility')
            units.add(unit)
            if point.supported:
                evidence.add(unit)
            by_voter[unit].add(k)
        presence.append(units)
        supported.append(evidence)
    budgets = Counter({key: len(ks) for key, ks in by_voter.items()})
    peaks = []
    for k, group in enumerate(groups):
        voters = supported[k] if require_support else presence[k]
        selection = [p for p in group if not require_support or p.supported]
        if not selection:
            continue
        rep = min(selection, key=lambda p: (p.priority, p.hz, p.key))
        mass = sum(1/budgets[v] for v in sorted(voters))
        # A cluster straddling an eligibility cutoff may include a restricted
        # voter at its low edge. Include that participant using the lower edge.
        denominator = sum(cap >= group[0].hz for cap in eligible.values())
        peaks.append(Peak(k, mass/denominator, mass, len(voters), denominator, rep,
                          tuple(sorted(voters))))
    return sorted(peaks, key=lambda p: (-p.score, -p.voters, p.representative.priority,
                                        p.representative.hz, p.cluster))
