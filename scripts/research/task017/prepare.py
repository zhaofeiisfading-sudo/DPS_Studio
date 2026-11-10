"""Inventory unique files and plot raw-only evidence before visual annotation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import stft  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/TASK-017"


def records() -> list[dict[str, Any]]:
    value = json.loads((OUT / "data/inventory.json").read_text(encoding="utf-8"))["channels"]
    return cast(list[dict[str, Any]], value)


def load(item: dict[str, Any]) -> tuple[Any, Any, float]:
    array = np.loadtxt(ROOT / item["file"], delimiter=",", ndmin=2)
    return array[:, 0], array[:, item["column"]], float(item["sample_rate_hz"])


def spectrum(t: Any, y: Any, fs: float, width: int, hop: int = 128) -> tuple[Any, Any, Any]:
    f, relative, z = stft(y, fs=fs, window="hann", nperseg=width, noverlap=width-hop,
                          nfft=4096, detrend=False, boundary=None, padded=False)
    return f, t[0] + relative, np.abs(z)**2


def raw_figure(item: dict[str, Any], bounds: tuple[float, float] | None = None,
               tag: str = "overview") -> Path:
    t, y, fs = load(item)
    a, b = (t[0], t[-1]) if bounds is None else bounds
    fig, axs = plt.subplots(4, 1, figsize=(15, 11), sharex=True,
                            gridspec_kw={"height_ratios": [1, 1.6, 2, 2]})
    visible = np.flatnonzero((t >= a) & (t <= b))
    # Plot envelope extrema, not a decimated voltage pretending to preserve oscillations.
    block = max(1, len(visible)//4000)
    selected = y[visible[:len(visible)//block*block]].reshape(-1, block)
    tt = t[visible[:len(selected)*block:block]]*1e6
    if block == 1:
        axs[0].plot(tt, selected[:, 0], color="#3c637b", linewidth=.6)
    else:
        axs[0].fill_between(tt, selected.min(axis=1), selected.max(axis=1), color="#3c637b")
    axs[0].set_ylabel("Voltage (V)*")
    for ax, width, high in zip(axs[1:], (1024, 1024, 256), (fs/2, 6e9, 6e9), strict=True):
        f, times, power = spectrum(t, y, fs, width, 64 if bounds else 128)
        keep_f = (f <= high)
        keep_t = (times >= a-width/fs) & (times <= b+width/fs)
        band = power[keep_f][:, keep_t]
        db = 10*np.log10(np.maximum(band, 1e-30)/max(float(power.max()), 1e-30))
        ax.pcolormesh(times[keep_t]*1e6, f[keep_f]/1e9, db, vmin=-65, vmax=0,
                      shading="auto", cmap="viridis", rasterized=True)
        ax.set_ylabel("Beat frequency (GHz)")
        ax.text(.005, .97, f"Hann {width} samples / {width/fs*1e9:.2f} ns; no detrending",
                transform=ax.transAxes, va="top", color="white", fontsize=9,
                bbox={"facecolor": "black", "alpha": .5, "edgecolor": "none"})
        ax.set_ylim(0, high/1e9)
    axs[-1].set_xlim(a*1e6, b*1e6)
    axs[-1].set_xlabel("Original absolute time (microseconds)")
    for ax in axs:
        ax.ticklabel_format(axis="x", useOffset=False, style="plain")
    fig.suptitle(f"{item['id']} | RAW evidence only | wavelength UNCONFIRMED\n"
                 "*Inherited headerless mapping: numeric seconds / volts; no physical zero prior",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, .95))
    base = OUT / "figures/visual_review" / f"{item['id']}__{tag}"
    if base.with_suffix(".png").exists():
        raise FileExistsError(base)
    fig.savefig(base.with_suffix(".png"), dpi=140)
    fig.savefig(base.with_suffix(".svg"))
    plt.close(fig)
    return base.with_suffix(".png")


def inventory() -> None:
    index = json.loads((ROOT / "configs/research/task009_data_index.json").read_text(
        encoding="utf-8"))
    old = [r for r in index["records"] if r["kind"] == "RAW"]
    channels, files, excluded = [], [], []
    for path in sorted((ROOT / "data/raw").rglob("*")):
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            sha = hashlib.file_digest(handle, "sha256").hexdigest()
        if "result" in path.name.lower() or path.suffix.lower() not in (".csv", ".dat"):
            excluded.append({"file": path.relative_to(ROOT).as_posix(), "sha256": sha,
                             "reason": "processed result or auxiliary"})
            continue
        data = np.loadtxt(path, delimiter=",", ndmin=2)
        if not np.isfinite(data).all() or data.shape[1] < 2:
            raise ValueError(f"Nonfinite or invalid raw: {path}")
        steps = np.diff(data[:, 0])
        fs = 1/float(np.median(steps))
        jitter = float(np.max(abs(steps-np.median(steps)))/np.median(steps))
        if not np.all(steps > 0) or jitter > 1e-5:
            raise ValueError(f"Nonuniform time; no resampling allowed: {path}")
        matches = [r for r in old if r["sha256"] == sha]
        if not matches:
            raise ValueError(f"Unit provenance missing: {path}")
        row = {"file": path.relative_to(ROOT).as_posix(), "sha256": sha,
               "bytes": path.stat().st_size, "samples": len(data),
               "channels": data.shape[1]-1, "start_s": float(data[0, 0]),
               "end_s": float(data[-1, 0]), "sample_rate_hz": fs,
               "max_relative_step_jitter": jitter,
               "time_scale_to_s": 1., "voltage_scale_to_v": 1.,
               "unit_basis": matches[0]["time_unit_basis"],
               "unit_status": "INHERITED_CONFIG_MAPPING_HEADERLESS_NOT_NEW_CALIBRATION",
               "wavelength_m": matches[0].get("wavelength_m"),
               "angle_deg": None, "window_correction": "NOT_CONFIGURED",
               "historical_logical_paths": [r["path"] for r in matches]}
        files.append(row)
        for column in range(1, data.shape[1]):
            channels.append({**row, "id": f"{path.stem}_ch{column}", "column": column,
                             "voltage_rms_v": float(np.std(data[:, column]))})
    OUT.joinpath("data").mkdir(parents=True, exist_ok=True)
    OUT.joinpath("figures/visual_review").mkdir(parents=True, exist_ok=True)
    with (OUT / "data/inventory.json").open("x", encoding="utf-8") as handle:
        json.dump({"files": files, "channels": channels, "excluded": excluded,
                   "historical_raw_rows": len(old),
                   "historical_stream_rows": sum(r["channels"] for r in old),
                   "current_unique_files": len(files), "current_unique_channels": len(channels)},
                  handle, ensure_ascii=False, indent=2)
    print(f"Unique raw files: {len(files)}; channels: {len(channels)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "overview", "zoom"))
    parser.add_argument("--id")
    parser.add_argument("--start-us", type=float)
    parser.add_argument("--end-us", type=float)
    parser.add_argument("--tag", default="zoom")
    args = parser.parse_args()
    if args.mode == "inventory":
        inventory()
    else:
        for item in records():
            if args.id and args.id != item["id"]:
                continue
            bounds = (args.start_us*1e-6, args.end_us*1e-6) if args.mode == "zoom" else None
            print(raw_figure(item, bounds, args.tag if bounds else "overview"), flush=True)


if __name__ == "__main__":
    main()
