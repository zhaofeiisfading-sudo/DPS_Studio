# TASK-023 Hotfix strict typing verification

- Renamed the two drop-event variables and annotated the Path.stat test double. Test behavior and assertions are unchanged.
- Strict mypy passed for src and the four requested GUI test files, with 100 source files checked. Ruff passed for the same paths.
