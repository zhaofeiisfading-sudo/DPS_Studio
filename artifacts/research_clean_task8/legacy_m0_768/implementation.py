"""Literal historical M0 at Hann 768/640/4096; see 512 implementation."""
from __future__ import annotations

from ..common import Context, Estimate
from ..legacy_m0_512.implementation import run_width

PARAMETERS = dict(window=768, overlap=640, nfft=4096, top_k=20,
                  minimum_frequency_hz=50e6, maximum_frequency_hz=6e9,
                  selection="historical rank-one transition_frequency_hz",
                  fallback="explicit refined-if-finite else discrete-bin; uncalibrated hypothesis")


def run(context: Context) -> Estimate:
    return run_width(context, 768)
