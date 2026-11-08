# TASK-001: Raw signal data model

Implement SignalRecord only. Do not implement GUI, STFT, filtering, or file readers.

Requirements:

- time_s and voltage_v are one-dimensional NumPy arrays.
- The arrays have equal length and contain at least two samples.
- Time is strictly increasing.
- Reject NaN and Inf.
- Compute sample interval, sample rate, and Nyquist frequency.
- Check approximately uniform sampling.
- Do not mutate input arrays.
- Add complete unit tests.
- Run pytest, ruff, and mypy.