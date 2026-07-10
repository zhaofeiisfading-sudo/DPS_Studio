# Codex Project Rules

1. Never modify, overwrite, or delete files in data/raw.
2. The core package must not depend on the GUI package.
3. Use SI units for internal calculations.
4. Store apparent velocity and corrected velocity separately.
5. Do not silently interpolate, smooth, or delete data.
6. Return NaN and quality flags when the signal is unreliable.
7. Do not add a formal LiF correction formula until it has been verified.
8. Every task must add tests and run pytest and ruff.
9. Do not perform unrelated large refactors.
10. Stop after completing the requested task.