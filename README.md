# DPS Studio

PDV/DPS signal analysis software.

Core workflow:

raw time-voltage data -> validation -> STFT -> ridge extraction -> apparent velocity -> window correction -> export

Development rules:

- Never overwrite raw data.
- Keep the numerical core independent from the GUI.
- Use SI units internally.
- Store all parameters and manual edits.
- Return NaN and quality flags when no reliable signal exists.