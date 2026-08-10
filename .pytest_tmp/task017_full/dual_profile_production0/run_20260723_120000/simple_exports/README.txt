DPS Studio simple apparent-velocity exports

This directory contains one independent file for every actual configured profile/channel stream:
- balanced__pdv_channel_1__velocity_time.csv
- balanced__pdv_channel_2__velocity_time.csv
- high_time_resolution__pdv_channel_1__velocity_time.csv
- high_time_resolution__pdv_channel_2__velocity_time.csv

Filename fields identify the configured analysis profile and the independent PDV acquisition channel.
Columns: time_s is absolute STFT frame-center time in seconds; velocity_m_s is unsigned apparent velocity in m/s.
When cross-profile consensus is available, every frame with time_s before it is written as exactly 0 m/s, regardless of its formal diagnostic signal state.
For this run, cross-profile consensus is unavailable; no manual reference is substituted and the formal quality-gated array is copied unchanged.
The complete pre-event zero platform is a plotting convention for direct use in Origin or Excel; it is not a measured velocity.
At and after the consensus time, formal quality-gated apparent velocity is copied exactly and invalid frames remain NaN.
All original STFT frames and times are retained. No row is removed and no value is interpolated, smoothed, bridged, or resampled.
These values have not received a verified LiF correction.
Configured development-calibrated thresholds: peak/background >= 10 dB and peak/competitor >= 3 dB.
Threshold provenance: development-calibrated for the current production record; not an absolute experimental standard.
The detailed apparent_velocity_diagnostics.csv files are the formal reference and are never pre-event zero-filled.
The physical identities of spectral branches near the record tail remain unconfirmed.
Do not directly average the two raw voltage channels or the four velocity curves.
