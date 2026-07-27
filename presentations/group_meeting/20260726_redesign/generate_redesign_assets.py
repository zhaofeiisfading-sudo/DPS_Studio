"""Generate presentation-only assets from real DPS Studio data and source text.

This script writes only under presentations/group_meeting/20260726_redesign.
It never modifies source data, project source code, or existing outputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
REAL = ASSETS / "real"
CODE = ASSETS / "code"

RAW = REPO / "data" / "raw" / "20260607.csv"
LATEST_RUN = REPO / "outputs" / "production_runs" / "run_20260724_004901_103968"
CH1_CSV = LATEST_RUN / "balanced" / "pdv_channel_1" / "apparent_velocity.csv"
CH2_CSV = LATEST_RUN / "balanced" / "pdv_channel_2" / "apparent_velocity.csv"
QUALITY_CSV = LATEST_RUN / "balanced" / "quality_summary.csv"
PROFILE_SOURCE = REPO / "src" / "dps_studio" / "core" / "analysis_profiles.py"

EVENT_START_S = 5.54668e-4
WARM_RED = "#9E2A1B"
TEAL = "#167C80"
CHARCOAL = "#252525"
MUTED = "#6A6967"
GRID = "#D9D4CE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei"],
            "font.serif": ["Times New Roman"],
            "mathtext.fontset": "stix",
            "axes.unicode_minus": False,
            "axes.edgecolor": CHARCOAL,
            "axes.labelcolor": CHARCOAL,
            "xtick.color": CHARCOAL,
            "ytick.color": CHARCOAL,
        }
    )


def _raw_voltage_plot() -> dict[str, float]:
    values = np.loadtxt(RAW, delimiter=",", dtype=np.float64)
    time_s = values[:, 0]
    ch1 = values[:, 1]
    ch2 = values[:, 2]
    relative_us = (time_s - EVENT_START_S) * 1e6
    mask = (relative_us >= -0.12) & (relative_us <= 0.28)
    if not np.any(mask):
        raise RuntimeError("No raw samples found in the requested event display window.")

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(13.2, 5.2),
        sharex=True,
        gridspec_kw={"hspace": 0.13},
    )
    for ax, data, color, label in (
        (axes[0], ch1, WARM_RED, "PDV channel 1"),
        (axes[1], ch2, TEAL, "PDV channel 2"),
    ):
        ax.plot(relative_us[mask], data[mask], color=color, linewidth=0.75)
        ax.axvline(0.0, color="#C78926", linewidth=1.2, linestyle=(0, (4, 3)))
        ax.text(
            0.985,
            0.87,
            label,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=15,
            color=CHARCOAL,
            fontfamily="Times New Roman",
        )
        ax.set_ylabel("电压 (V)", fontsize=15)
        ax.grid(True, color=GRID, linewidth=0.55, alpha=0.55)
        ax.tick_params(labelsize=13)
        ax.spines[["top", "right"]].set_visible(False)
    axes[1].set_xlabel("相对事件起点时间 (μs)", fontsize=15)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.97, bottom=0.15)
    path = REAL / "raw_voltage_dual_channel.png"
    fig.savefig(path, dpi=240, facecolor="white")
    plt.close(fig)

    ch1_ptp = float(np.ptp(ch1[mask]))
    ch2_ptp = float(np.ptp(ch2[mask]))
    sample_interval = float(np.median(np.diff(time_s)))
    return {
        "channel_1_peak_to_peak_v": ch1_ptp,
        "channel_2_peak_to_peak_v": ch2_ptp,
        "channel_2_to_channel_1_peak_to_peak_ratio": ch2_ptp / ch1_ptp,
        "representative_sample_interval_s": sample_interval,
        "representative_sample_rate_hz": 1.0 / sample_interval,
    }


def _two_channel_plot() -> dict[str, float]:
    ch1 = pd.read_csv(CH1_CSV)
    ch2 = pd.read_csv(CH2_CSV)
    c1 = ch1.loc[ch1["quality_flag"] == "candidate"].copy()
    c2 = ch2.loc[ch2["quality_flag"] == "candidate"].copy()

    fig, ax = plt.subplots(figsize=(12.5, 5.2))
    ax.plot(
        c1["time_relative_to_event_s"] * 1e6,
        c1["apparent_velocity_m_s"],
        color=WARM_RED,
        linewidth=2.0,
        label="PDV channel 1",
    )
    ax.plot(
        c2["time_relative_to_event_s"] * 1e6,
        c2["apparent_velocity_m_s"],
        color=TEAL,
        linewidth=2.0,
        label="PDV channel 2",
    )
    ax.set_xlabel("相对事件起点时间 (μs)", fontsize=15)
    ax.set_ylabel("无符号表观速度 (m/s)", fontsize=15)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.6)
    ax.tick_params(labelsize=13)
    ax.spines[["top", "right"]].set_visible(False)
    legend = ax.legend(
        loc="best",
        frameon=False,
        fontsize=14,
        prop={"family": "Times New Roman", "size": 14},
    )
    for text in legend.get_texts():
        text.set_color(CHARCOAL)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.97, bottom=0.16)
    path = REAL / "two_channel_latest_candidates.png"
    fig.savefig(path, dpi=240, facecolor="white")
    plt.close(fig)

    quality = pd.read_csv(QUALITY_CSV).set_index("channel_name")
    return {
        "channel_1_first_candidate_m_s": float(c1["apparent_velocity_m_s"].iloc[0]),
        "channel_2_first_candidate_m_s": float(c2["apparent_velocity_m_s"].iloc[0]),
        "channel_1_peak_to_background_db_median": float(
            quality.loc["pdv_channel_1", "peak_to_background_db_median"]
        ),
        "channel_2_peak_to_background_db_median": float(
            quality.loc["pdv_channel_2", "peak_to_background_db_median"]
        ),
        "channel_1_peak_to_competitor_db_median": float(
            quality.loc["pdv_channel_1", "peak_to_competitor_db_median"]
        ),
        "channel_2_peak_to_competitor_db_median": float(
            quality.loc["pdv_channel_2", "peak_to_competitor_db_median"]
        ),
    }


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    font_name = "consolab.ttf" if bold else "consola.ttf"
    path = Path("C:/Windows/Fonts") / font_name
    if not path.exists():
        raise RuntimeError(f"Required Consolas font not found: {path}")
    return ImageFont.truetype(str(path), size=size)


def _code_excerpt() -> None:
    source_lines = PROFILE_SOURCE.read_text(encoding="utf-8").splitlines()
    selected = list(range(136, 146))
    rows = [(number, source_lines[number - 1]) for number in selected]

    width = 1200
    line_height = 52
    top = 92
    bottom = 30
    height = top + line_height * len(rows) + bottom
    image = Image.new("RGB", (width, height), "#1F2428")
    draw = ImageDraw.Draw(image)
    regular = _load_font(42)
    bold = _load_font(42, bold=True)
    small = _load_font(27)
    draw.rectangle((0, 0, width, 66), fill="#15191D")
    draw.text(
        (28, 20),
        "analysis_profiles.py  ·  lines 136–145",
        font=small,
        fill="#B8C0C7",
    )

    for row_index, (line_number, text) in enumerate(rows):
        y = top + row_index * line_height
        draw.text((24, y), f"{line_number:>3}", font=small, fill="#69737D")
        body_x = 104
        stripped = text.lstrip()
        indent = text[: len(text) - len(stripped)]
        draw.text((body_x, y), indent, font=regular, fill="#D7DEE5")
        body_x += int(draw.textlength(indent, font=regular))
        if stripped.startswith(("BALANCED_PROFILE", "HIGH_TIME_RESOLUTION_PROFILE")):
            draw.text((body_x, y), stripped, font=bold, fill="#F2C14E")
        elif any(
            key in stripped
            for key in (
                "window_length_samples",
                "overlap_samples",
                "hop_samples",
                "nfft",
                "minimum_frequency_hz",
                "maximum_frequency_hz",
            )
        ):
            draw.text((body_x, y), stripped, font=regular, fill="#8ED3E6")
        else:
            draw.text((body_x, y), stripped, font=regular, fill="#D7DEE5")

    image.save(CODE / "analysis_profiles_balanced_excerpt.png")


def main() -> None:
    REAL.mkdir(parents=True, exist_ok=False)
    CODE.mkdir(parents=True, exist_ok=False)
    _configure_matplotlib()
    stats = {
        "raw_source": str(RAW),
        "raw_source_sha256": _sha256(RAW),
        "latest_run": str(LATEST_RUN),
        "raw_voltage": _raw_voltage_plot(),
        "two_channel": _two_channel_plot(),
        "code_excerpt_source": str(PROFILE_SOURCE),
        "code_excerpt_lines": ["136-145"],
    }
    _code_excerpt()
    (ASSETS / "asset_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
