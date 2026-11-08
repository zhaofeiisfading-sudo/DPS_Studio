# Boundary sensitivity expansion

The first 84 perturbations used held-out indices 0–3. Because the held-out design crosses frequency with SNR using index//4, those four indices all have −8 dB. This is a valid low-SNR stress stratum, but is insufficient to assess boundary dependence over the requested SNR range. It is retained in data/sensitivity/ and is not pooled twice.

Without changing any estimator parameters or selection rules, data/sensitivity_v02/ expands to indices 0–15: all four SNR levels, 3 transient families, 6 boundary offsets plus one wrong-stage condition, 336 paired perturbations. Each perturbation reuses its matching main held-out waveform deliberately; it is a repeated-measures sensitivity study, not 336 independent signals. Report timing conditional on successful detections alongside misses and missing-inclusive failure. Do not tune a default from these expanded sensitivity outcomes.
