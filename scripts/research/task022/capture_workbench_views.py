"""Capture actual TASK-022 widgets with exact real-data frame/candidate telemetry.

Run through scripts/dev/run.ps1 -Task TASK-022. Defaults to offscreen; set
QT_QPA_PLATFORM=windows for desktop capture. Each invocation creates a new run
directory, retaining earlier captures and never overwriting evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from dps_studio.gui.app import create_application  # noqa: E402
from dps_studio.gui.research_window import ResearchMainWindow  # noqa: E402
from dps_studio.core.physics.window_presets import WindowPresetRepository  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    app = create_application([], language_code="zh_CN")
    if app.platformName() == "offscreen" and os.name == "nt":
        # The offscreen Windows plugin may not enumerate registry-installed fonts.
        # Register existing local font files for this process only.
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisym.ttf", "seguiemj.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        app.setFont(QFont("Microsoft YaHei", 9))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = ROOT / "artifacts/TASK-022/figures" / stamp
    output.mkdir(parents=True, exist_ok=False)
    settings_dir = ROOT / "artifacts/TASK-022/tmp/capture" / stamp
    settings_dir.mkdir(parents=True, exist_ok=False)
    window = ResearchMainWindow(
        settings=QSettings(str(settings_dir / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(settings_dir / "windows.json"),
    )
    window.resize(1600, 960)
    window.show()
    window.mode_combo.setCurrentIndex(2)
    workspace = window.diagnostic_workspace
    captures: list[dict[str, object]] = []

    def capture(label: str, estimator: str = "B1", *, raw: bool = False) -> None:
        workspace.inspector.select_estimator(estimator)
        workspace.inspector.waveform_mode_combo.setCurrentIndex(1 if raw else 0)
        app.processEvents()
        QTest.qWait(100)
        app.processEvents()
        path = output / f"{label}.png"
        if not window.grab().save(str(path)):
            raise OSError(f"Qt grab failed: {path}")
        bundle, ev = workspace.bundle, workspace.inspector.evidence
        assert bundle is not None and ev is not None
        row: dict[str, object] = {
            "png": str(path.relative_to(ROOT)),
            "channel": bundle.channel_name,
            "frame_index": workspace.frame_index,
            "q": ev.sample_index,
            "time_s": ev.time_s,
            "relative_ns": (ev.time_s - bundle.time_s[0]) * 1e9,
            "focus": estimator,
            "waveform_mode": "raw" if raw else "detrended",
            "tone_r2": ev.raw_tone_r2 if math.isfinite(ev.raw_tone_r2) else None,
            "chirp_r2": ev.raw_chirp_r2 if math.isfinite(ev.raw_chirp_r2) else None,
            "stage": bundle.frame_tags.stage[workspace.frame_index],
            "competing": bool(bundle.frame_tags.competing_clusters_mask[workspace.frame_index]),
            "reasons": workspace.inspector.reason_box.toPlainText(),
            "compute_mode": bundle.compute_mode,
            "provenance": bundle.provenance_note,
            "logical_size": [window.width(), window.height()],
        }
        captures.append(row)
        print(f"Captured {path} · q={ev.sample_index} · {estimator}", flush=True)

    try:
        for channel in ("20201210m_ch1", "ch3_ch1", "20260630-1_ch2", "20201214m_ch1"):
            index = next(
                (i for i, p in enumerate(workspace.properties.presets) if p.channel_id == channel),
                None,
            )
            if index is None:
                raise FileNotFoundError(f"Showcase raw preset missing: {channel}")
            workspace.properties.preset_combo.setCurrentIndex(index)
            workspace.properties.prefer_frozen_checkbox.setChecked(True)
            workspace.properties.load_preset_button.click()
            deadline = monotonic() + args.timeout
            while workspace.busy and monotonic() < deadline:
                app.processEvents()
                sleep(0.01)
            app.processEvents()
            if workspace.busy or workspace.bundle is None:
                raise RuntimeError(workspace.properties.stage_label.text())
            bundle = workspace.bundle
            workspace.backdrop_combo.setCurrentIndex(0)
            workspace.filter_combo.setCurrentIndex(0)
            workspace.reset_view()
            if channel == "20201210m_ch1":
                onset = bundle.indices_for_filter("onset")
                workspace.select_frame(onset[0])
                capture("20201210m_dc_onset_global")
                workspace.zoom_local()
                workspace.backdrop_combo.setCurrentIndex(1)
                capture("20201210m_dc_leak_B0_raw", "B0", raw=True)
                workspace.backdrop_combo.setCurrentIndex(0)
                capture("20201210m_onset_B1_detrended")
                decline = bundle.indices_for_filter("decline")
                if decline:
                    workspace.select_frame(decline[len(decline) // 2])
                    workspace.zoom_local()
                    capture("20201210m_decline_B1")
            elif channel == "ch3_ch1":
                workspace.select_sample(42752)
                workspace.zoom_local()
                capture("ch3_onset_q42752_B0", "B0")
                capture("ch3_onset_q42752_dechirp", "dechirp")
                capture("ch3_onset_q42752_dechirp_raw", "dechirp", raw=True)
                decline = bundle.indices_for_filter("decline")
                if decline:
                    workspace.select_frame(decline[len(decline) // 2])
                    workspace.zoom_local()
                    capture("ch3_decline_varpro", "varpro")
            elif channel == "20260630-1_ch2":
                workspace.select_frame(
                    bundle.frame_index_for_time(float(bundle.time_s[0]) + 3254.4e-9)
                )
                workspace.zoom_local()
                capture("20260630_weak_competing_3254p4ns_B1")
                selected = next(
                    (
                        c.estimator
                        for c in bundle.candidates_by_frame[workspace.frame_index]
                        if c.s2_selected
                    ),
                    "dechirp",
                )
                capture("20260630_weak_competing_3254p4ns_S2source", selected)
            else:
                indices = bundle.indices_for_filter("onset")
                workspace.select_frame(indices[-1] if indices else len(bundle.common_times_s) // 2)
                workspace.reset_view()
                capture("20201214m_out_of_band_context", "B0", raw=True)
        (output / "capture_manifest.json").write_text(
            json.dumps(captures, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        print(f"Manifest: {output / 'capture_manifest.json'}", flush=True)
    finally:
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
