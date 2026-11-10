"""Human-readable Codex visual judgements, transcribed AFTER viewing raw PNGs.

These numbers are manual judgements, not an automatic detector or truth data.
No algorithm results have been generated when this file is first executed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.research.task017.prepare import OUT, records

# (boundary in original microseconds, stage beginning there, uncertainty ns, evidence)
PLANS: dict[str, list[tuple[float, str, float, str]]] = {
    "20201210m_ch1": [
        (138.720, "unknown", 5, "Slow DC precursor; no resolved moving beat"),
        (138.7548, "onset", 1.5, "Voltage step and first sustained ~3.7 GHz oscillations"),
        (138.767, "plateau", 4, "Narrow nearly horizontal ~3.7 GHz ridge"),
        (139.220, "decline", 10, "Main ridge bends downward toward ~2.3 GHz"),
        (139.355, "unknown", 8, "Discontinuous lower branch; identity cannot be followed"),
        (139.470, "noise", 15, "Main coherent ridge lost; residual background"),
    ],
    "20201211m_ch1": [
        (107.700, "unknown", 8, "DC excursion before establishment of GHz beat"),
        (107.7382, "onset", 1.5, "Negative impulse and establishment of ~4.8 GHz beat"),
        (107.751, "plateau", 4, "Sustained ~4.8 GHz ridge, background remains strong"),
        (108.270, "decline", 10, "Resolved downward branch"),
        (108.385, "weak_signal", 10, "Weak lower branches and ambiguous handoff"),
        (108.475, "noise", 12, "No sustained main branch"),
    ],
    "20201214m_ch1": [
        (82.910, "unknown", 10, "Large low-frequency baseline structure; no certified zero"),
        (82.9585, "onset", 2, "Bipolar transient followed by ~6.3 GHz oscillations"),
        (82.974, "plateau", 5, "Narrow plateau ABOVE 6 GHz; excluded by fixed baseline band"),
        (83.340, "decline", 10, "~6.3 GHz ridge slopes downward"),
        (83.445, "unknown", 10, "Abrupt branch handoff from ~4.6 to ~2 GHz"),
        (83.485, "decline", 8, "Lower branch continues downward"),
        (83.550, "weak_signal", 12, "Weak low-frequency tail"),
        (83.610, "noise", 15, "No reliable continuous ridge"),
    ],
    "20221017a_ch1": [
        (87.7189, "onset", 1, "Abrupt strong ~4.4 GHz beat above pre-existing ~1.5-2 GHz background"),
        (87.726, "plateau", 3, "Stable narrow ~4.4 GHz line; amplitude decays later"),
        (88.150, "decline", 8, "Continuous downward ridge"),
        (88.245, "weak_signal", 12, "Ridge fades toward background"),
        (88.310, "noise", 15, "No reliable continuing beat"),
    ],
    "20231019-ch1_ch1": [
        (89.4191, "onset", 1.2, "Impulse followed by high-amplitude ~4.1 GHz oscillations"),
        (89.427, "plateau", 3, "Nearly horizontal main branch"),
        (89.610, "acceleration", 12, "Gradual upward drift toward ~4.4 GHz"),
        (89.765, "decline", 10, "Main ridge falls toward ~2.2 GHz"),
        (89.985, "unknown", 8, "Abrupt low-branch handoff; no unique identity"),
        (90.040, "weak_signal", 10, "Weak rising low-frequency tail, ambiguous branch"),
        (90.120, "noise", 15, "No reliable coherent tail"),
    ],
    "20260607_ch1": [
        (554.668, "onset", 2, "Oscillations grow with ~0.7 GHz line and parallel multiples"),
        (554.682, "plateau", 4, "Persistent ~0.7 GHz line plus ~1.4/2.1 GHz components"),
        (555.170, "decline", 12, "All visible parallel ridges bend downward"),
        (555.340, "weak_signal", 12, "Low-frequency tail with poor cycle support"),
        (555.510, "unknown", 12, "Pulse and competing low-frequency branches"),
        (555.660, "noise", 15, "No sustained main ridge"),
    ],
    "20260607_ch2": [
        (554.668, "onset", 2, "Own-channel voltage oscillations establish ~0.7 GHz; upper clipping possible"),
        (554.682, "plateau", 4, "Own-channel narrow line and parallel multiples"),
        (555.170, "decline", 12, "Parallel ridges bend downward"),
        (555.340, "weak_signal", 12, "Low-frequency weak tail"),
        (555.510, "unknown", 12, "Competing residual branches and pulses"),
        (555.660, "noise", 15, "Main line no longer reliable"),
    ],
    "20260630-1_ch1": [
        (746.216, "onset", 2.5, "Voltage leaves background and clips; ~0.55 GHz plus many harmonics"),
        (746.239, "plateau", 5, "Stable fundamental-like line and odd harmonic ladder; target identity unverified"),
        (746.730, "decline", 15, "Harmonic ladder bends downward"),
        (746.915, "weak_signal", 10, "Low-frequency minimum; amplitude dropout"),
        (746.995, "rebound", 12, "Visible line and multiples rise after minimum"),
        (747.110, "weak_signal", 12, "Abrupt fading and very low-frequency tail"),
        (747.245, "noise", 20, "No continuing coherent main branch"),
    ],
    "20260630-1_ch2": [
        (746.216, "onset", 2.5, "Own-channel clipped oscillations and harmonic ladder"),
        (746.239, "plateau", 5, "Own-channel stable ~0.55 GHz branch and harmonics"),
        (746.730, "decline", 15, "Own-channel parallel lines bend downward"),
        (746.915, "weak_signal", 10, "Amplitude minimum, branch support degrades"),
        (746.995, "rebound", 12, "Own-channel low branch rises after minimum"),
        (747.110, "weak_signal", 12, "Fading low-frequency tail"),
        (747.245, "noise", 20, "No reliable continuing main branch"),
    ],
    "20260630-2_ch1": [
        (540.216, "onset", 2, "Strong clipped oscillations and ~0.85 GHz line"),
        (540.234, "plateau", 5, "Horizontal fundamental-like ridge with harmonics"),
        (540.780, "weak_signal", 12, "Amplitude dropout; visible branch continuity uncertain"),
        (540.900, "plateau", 12, "Line reappears at similar frequency; no physical identity proof"),
        (540.970, "decline", 12, "Parallel lines slope downward"),
        (541.105, "plateau", 10, "Short low-frequency shelf, several cycles only"),
        (541.210, "weak_signal", 12, "Fading branch and amplitude modulation"),
        (541.290, "noise", 15, "Motion-like ridge disappears"),
    ],
    "20260630-2_ch2": [
        (540.216, "onset", 2, "Own-channel bipolar transient followed by ~0.85 GHz beat"),
        (540.234, "plateau", 5, "Narrow own-channel line; weaker multiples than ch1"),
        (540.780, "weak_signal", 12, "Amplitude dropout"),
        (540.900, "plateau", 12, "Line re-establishes; identity conditional"),
        (540.970, "decline", 12, "Visible downward bend"),
        (541.105, "plateau", 10, "Short low-frequency shelf"),
        (541.210, "weak_signal", 12, "Fading weak tail"),
        (541.290, "noise", 15, "No reliable coherent ridge"),
    ],
    "20260701_ch1": [
        (656.8455, "onset", 2, "Clipped beat establishes ~0.7 GHz and higher multiples"),
        (656.863, "plateau", 5, "Persistent main line, slight drift; harmonics evolve"),
        (657.630, "decline", 12, "Main and second line bend downward together"),
        (657.735, "weak_signal", 12, "Weak low-frequency terminal shelf"),
        (657.860, "noise", 18, "No continuing narrow main ridge"),
    ],
    "20260701_ch2": [
        (656.8455, "onset", 2, "Own-channel transient and established ~0.7 GHz oscillations"),
        (656.863, "plateau", 5, "Narrow own-channel fundamental-like line"),
        (657.630, "decline", 12, "Own-channel lines turn downward"),
        (657.735, "weak_signal", 12, "Weak terminal shelf"),
        (657.860, "noise", 18, "No continuing narrow line"),
    ],
    "ch3_ch1": [
        (183.646, "onset", 2.5, "Impulse followed by intermittent ~3.6-3.9 GHz oscillations"),
        (183.661, "weak_signal", 6, "Broad intermittent ridge and amplitude fades; no stable platform"),
        (183.800, "unknown", 10, "Abrupt change toward ~1.3 GHz then broadband terminal burst"),
        (183.875, "noise", 10, "Burst ends; no reliable continuous ridge"),
    ],
}


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    plans = {}
    for item in records():
        entries = PLANS[item["id"]]
        initial = "unknown" if item["id"] == "20221017a_ch1" else "stationary"
        starts = [(item["start_s"]*1e6, initial, 0.,
                   "Background label only; NOT measured zero; pre-existing tone possible"), *entries]
        segments = []
        for i, (start, stage, uncertainty, evidence) in enumerate(starts):
            end = starts[i+1][0] if i+1 < len(starts) else item["end_s"]*1e6
            end_unc = starts[i+1][2] if i+1 < len(starts) else 0.
            segments.append({"id": f"s{i:02d}", "start_s": start*1e-6, "end_s": end*1e-6,
                             "stage": stage, "visual_evidence": evidence,
                             "confidence": "medium" if stage in ("unknown", "weak_signal")
                             or item["id"] == "ch3_ch1" else "high",
                             "start_range_s": [(start-uncertainty*.001)*1e-6,
                                               (start+uncertainty*.001)*1e-6],
                             "end_range_s": [(end-end_unc*.001)*1e-6,
                                             (end+end_unc*.001)*1e-6],
                             "physical_branch": "requires experimental confirmation",
                             "stationary_zero_is_measurement": False})
        segments[0]["start_s"] = item["start_s"]
        segments[-1]["end_s"] = item["end_s"]
        plans[item["id"]] = segments
    out = OUT / "data/visual_annotations.json"
    with out.open("x", encoding="utf-8") as handle:
        json.dump({"method": "Codex directly viewed 14 raw overviews and 14 onset PNGs",
                   "algorithm_curves_viewed_before_freeze": False, "plans": plans},
                  handle, ensure_ascii=False, indent=2)
    lock = {"frozen_utc": datetime.now(timezone.utc).isoformat(),
            "annotations_sha256": sha(out), "inventory_sha256": sha(OUT / "data/inventory.json"),
            "raw_review_images": {p.name: sha(p) for p in sorted(
                (OUT / "figures/visual_review").glob("*.png"))},
            "note": "Example screenshots provided no boundaries; all judgements use current raw."}
    with (OUT / "data/visual_freeze.json").open("x", encoding="utf-8") as handle:
        json.dump(lock, handle, ensure_ascii=False, indent=2)
    print(f"Frozen {len(plans)} channel plans; {sum(map(len, plans.values()))} segments.")


if __name__ == "__main__":
    main()
