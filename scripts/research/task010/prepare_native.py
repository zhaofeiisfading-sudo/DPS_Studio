"""Reuse the verified local TASK-009 Origin COM renderer in a new Research file."""
from __future__ import annotations

from scripts.research.task010.audit import OUT, ROOT, sha, write_json


def main() -> None:
    source = ROOT / "artifacts/TASK-009/scripts/render_origin.ps1"
    target = OUT / "scripts/render_origin.ps1"
    script = source.read_text(encoding="utf-8-sig")
    script = script.replace("task9", "task10").replace("T9G", "T10G").replace(
        "T9Leg", "T10Leg").replace("TASK-009", "TASK-010")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8-sig") as stream:
        stream.write(script)
    write_json(OUT / "checks/native_renderer_provenance.json", dict(
        source=source.relative_to(ROOT).as_posix(), source_sha256=sha(source),
        target=target.relative_to(ROOT).as_posix(), target_sha256=sha(target),
        changes="only task/output identifiers; PowerShell7, private hidden Origin COM, numerical readback unchanged"))


if __name__ == "__main__":
    main()
