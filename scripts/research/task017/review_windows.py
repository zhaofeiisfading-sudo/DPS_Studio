"""Manually selected raw-only inspection windows from the viewed overviews."""
from scripts.research.task017.prepare import raw_figure, records

WINDOWS_US = {
    "20201210m_ch1": (138.72, 138.80),
    "20201211m_ch1": (107.71, 107.78),
    "20201214m_ch1": (82.93, 83.00),
    "20221017a_ch1": (87.695, 87.75),
    "20231019-ch1_ch1": (89.39, 89.46),
    "20260607_ch1": (554.63, 554.74),
    "20260607_ch2": (554.63, 554.74),
    "20260630-1_ch1": (746.14, 746.28),
    "20260630-1_ch2": (746.14, 746.28),
    "20260630-2_ch1": (540.16, 540.28),
    "20260630-2_ch2": (540.16, 540.28),
    "20260701_ch1": (656.80, 656.92),
    "20260701_ch2": (656.80, 656.92),
    "ch3_ch1": (183.61, 183.70),
}

if __name__ == "__main__":
    for item in records():
        a, b = WINDOWS_US[item["id"]]
        bounds = (a*1e-6, b*1e-6)
        print(raw_figure(item, bounds, "onset_review"), flush=True)
