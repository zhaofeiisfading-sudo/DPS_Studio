"""Exercise the hygiene audit against a disposable Git index."""

from __future__ import annotations

import subprocess
import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.maintenance.check_repo_hygiene import audit


def test_hygiene_distinguishes_local_evidence_from_mistaken_index_entries(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    paths = (
        "data/raw/.gitkeep", "data/raw/wave.csv", "artifacts/run.csv",
        "artifacts/local.csv", "release/package.zip", "scripts/__pycache__/old.pyc",
        "misplaced.txt",
    )
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--", *paths[:3], paths[4]], check=True,
    )
    index = tmp_path / ".git" / "index"
    before = index.read_bytes()
    report = audit(tmp_path, large_bytes=4)
    assert report["tracked_generated"] == ["artifacts/run.csv", "data/raw/wave.csv",
                                          "release/package.zip"]
    assert report["unexpected_root"] == ["misplaced.txt"]
    assert report["caches"] == ["scripts/__pycache__"]
    assert "artifacts/local.csv" in report["large_local"]
    assert "artifacts/local.csv" not in report["large_tracked"]
    assert index.read_bytes() == before


def test_hygiene_detects_archive_duplicates_and_raw_copies(tmp_path: Path) -> None:
    with TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w") as zip_file:
            zip_file.writestr("example.txt", "sample release payload")
        archive = stream.getvalue()
        examples = {
            "release/PDV_Studio_v0.1.6.zip": archive,
            "build/attempt/PDV_Studio_v0.1.6.zip": archive,
            "build/PDV_Studio_test_placeholder.zip": b"not an archive",
            "artifacts/example/copy.csv": b"private raw",
            "data/raw/original.csv": b"private raw",
            "artifacts/example/different.csv": b"other value",
            "dist/leftover.txt": b"stray output",
        }
        for name, content in examples.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        report = audit(root, large_bytes=1024)
        assert report["unexpected_root"] == ["dist"]
        assert report["misplaced_packages"] == ["build/attempt/PDV_Studio_v0.1.6.zip"]
        assert report["duplicate_packages"] == [
            "build/attempt/PDV_Studio_v0.1.6.zip = release/PDV_Studio_v0.1.6.zip",
        ]
        assert report["raw_copies_in_artifacts"] == ["artifacts/example/copy.csv"]
