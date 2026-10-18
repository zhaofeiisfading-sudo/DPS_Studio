"""TASK005 reproduction refuses to overwrite outputs or process changed raw files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run_denoising_task005.py"),
                           *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False)


def test_existing_unrelated_result_directory_is_not_overwritten(tmp_path: Path) -> None:
    sentinel = tmp_path / "important.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    completed = invoke("--phase", "real", "--work-dir", str(tmp_path))
    assert completed.returncode != 0
    assert "Work directory must be new" in completed.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (tmp_path / "real").exists()


def test_sha_mismatch_stops_before_importing_and_preserves_input(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "20201210m.dat"
    source.write_bytes(b"deliberately changed fixture")
    config = json.loads((ROOT / "configs/research/denoising_task005.json").read_text(encoding="utf-8"))
    config["raw_files"] = config["raw_files"][:1]
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "new_run"
    completed = invoke("--phase", "real", "--work-dir", str(output), "--config", str(config_path),
                       "--raw-root", str(raw))
    assert completed.returncode != 0
    assert "Raw SHA-256 mismatch" in completed.stderr
    assert source.read_bytes() == b"deliberately changed fixture"
    assert list((output / "real").iterdir()) == []
