DPS Studio formal production run

Profiles: balanced, high_time_resolution
Independent channels: pdv_channel_1, pdv_channel_2
simple_exports/ contains strict two-column Origin-ready files.
Every pre-consensus simple-export frame is written as plotting zero; post-consensus formal NaN gaps remain NaN.
Each profile/channel apparent_velocity_diagnostics.csv is the complete detailed diagnostic table.
Detailed formal apparent_velocity_m_s is never pre-event zero-filled.
Configured detection thresholds are 10 dB peak/background and 3 dB peak/competitor.
Threshold provenance: development-calibrated for the current production record; not an absolute experimental standard.
comparisons/threshold_calibration.csv records the four approved candidate comparisons and deterministic selection.
No duplicate apparent_velocity.csv compatibility alias is generated.
apparent_velocity_full_overview.png is the primary full-range preview/formal comparison.
apparent_velocity_full_time_reviewed.png is display-only and never changes or exports formal velocity values.
comparisons/ contains cross-stream validation and event diagnostics.
event_consensus.json records event-candidate consensus metadata.
Detailed apparent velocities remain unsigned and unmodified; simple exports use the configured formal corrected velocity. Neither represents profile/channel fusion or physical branch selection.
