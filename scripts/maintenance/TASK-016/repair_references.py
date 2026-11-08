"""Apply the reviewed TASK-016 path/import mapping and record changed file hashes."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    plan = json.loads((ROOT / "artifacts/TASK-016/audit/migration-plan.json").read_text(encoding="utf-8"))
    moved = {row["target"]: row["source"] for row in plan["moves"]}
    prior = json.loads((ROOT / "artifacts/TASK-016/audit/reference-repairs.json").read_text(encoding="utf-8"))
    prior_hash = {row["path"]: row["before_sha256"] for row in prior}
    custom = {"src/dps_studio/runtime_paths.py", "src/dps_studio/research/task009_data.py",
              "src/dps_studio/research/task009_runtime.py", "src/dps_studio/research/waveform/data.py"}
    modules = {}
    paths = {row["source"]: row["target"] for row in plan["moves"]}
    for source, target in paths.items():
        if source.startswith(("scripts/", "tools/")) and source.endswith(".py"):
            modules[Path(source).stem] = target[:-3].replace("/", ".")
    changes = []
    candidates = [ROOT / "README.md", ROOT / "pyproject.toml"]
    for folder in ("src", "scripts", "tests", "configs", "docs", ".github", ".githooks"):
        candidates += [path for path in (ROOT / folder).rglob("*") if path.is_file()
                       and path.suffix in {".py", ".ps1", ".bat", ".spec", ".json", ".toml", ".md", ".yml"}]
    for path in candidates:
        relative = path.relative_to(ROOT).as_posix()
        if ("maintenance/TASK-016/" in relative or "/provenance/" in relative
                or "__pycache__" in relative or relative in custom):
            continue
        before = path.read_bytes()
        text = before.decode("utf-8-sig")
        if relative in prior_hash:
            original_path = moved.get(relative, relative)
            blob = subprocess.run(["git", "--no-optional-locks", "show", ":" + original_path],
                                  cwd=ROOT, capture_output=True)
            candidates = [blob.stdout, blob.stdout.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")]
            verified = next((value for value in candidates if digest(value) == prior_hash[relative]), None)
            if blob.returncode == 0 and verified is not None:
                text = verified.decode("utf-8-sig")
            else:
                # Recover only the demonstrated repeated-prefix substitution;
                # never restore an unverified Git version over local work.
                for old, new in paths.items():
                    if "/" not in old:
                        broken = old
                        for sep in ("/", "\\", "\\\\"):
                            broken = broken.replace(old, new.replace("/", sep))
                        text = text.replace(broken, old)
        # Most-specific package names first; numerical implementation bodies are untouched.
        for name in ("common", "catalog", "acmd", "baseband", "clutter_varpro", "dechirp",
                     "gated_stft256", "gated_stft512", "legacy_m0_512", "legacy_m0_768",
                     "matrix_pencil", "stft512", "stft512_wide", "stft768", "time_domain", "varpro"):
            text = text.replace(f"artifacts.research_clean_task8.{name}", f"dps_studio.algorithms.waveform.{name}")
        text = re.sub(r"artifacts\.research_clean_task8\.(\{[^}]+\})\.implementation",
                      r"dps_studio.algorithms.waveform.\1.implementation", text)
        text = text.replace("artifacts.research_clean_task8", "dps_studio.research.waveform")
        text = text.replace("dps_studio.algorithms.task008", "dps_studio.algorithms.waveform")
        text = text.replace("artifacts.research_clean_task13.repro", "scripts.research.task013")
        for n in range(9, 16):
            text = text.replace(f"artifacts.research_clean_task{n}", f"scripts.research.task{n:03}")
        for name, module in modules.items():
            text = re.sub(rf"\b(?:scripts|tools)\.{re.escape(name)}\b", module, text)
            parent = module.rsplit(".", 1)[0]
            text = re.sub(rf"\bfrom (?:scripts|tools) import {re.escape(name)}\b",
                          f"from {parent} import {name}", text)
            text = re.sub(rf"(?m)^(\s*)from {re.escape(name)} import ", rf"\1from {module} import ", text)
            text = re.sub(rf"(?m)^(\s*)import {re.escape(name)} as ", rf"\1import {module} as ", text)
        # Literal file references (including Windows spellings) use the same audited mapping.
        for old, new in sorted(paths.items(), key=lambda pair: len(pair[0]), reverse=True):
            if "/" in old:
                pattern = r"[/\\]+".join(re.escape(part) for part in old.split("/"))
                text = re.sub(pattern, lambda _: new, text)
            else:
                pattern = rf'((?:ROOT|REPOSITORY_ROOT)\s*/\s*[\"\x27]){re.escape(old)}([\"\x27])'
                text = re.sub(pattern, lambda m: m[1] + new + m[2], text)
        for n in range(8, 16):
            text = text.replace(f"artifacts/research_clean_task{n}", f"artifacts/TASK-{n:03}")
            text = text.replace(f"artifacts\\research_clean_task{n}", f"artifacts\\TASK-{n:03}")
        text = text.replace("artifacts/TASK-009/source_data", "data/research/TASK-009/source_data")
        text = text.replace("packaging/windows-constraints.txt", "scripts/build/windows-constraints.txt")
        # Relocate repository-root derivation only where the original expression
        # identified the original root. Unrelated ancestor calculations are retained.
        if relative in moved and path.suffix == ".py":
            old = moved[relative]
            old_depth = len(Path(old).parts) - 1
            new_depth = len(Path(relative).parts) - 1
            text = text.replace(f"Path(__file__).resolve().parents[{old_depth}]",
                                f"Path(__file__).resolve().parents[{new_depth}]")
            match = re.match(r"artifacts/research_clean_task(\d+)/", old)
            if match:
                number = int(match[1])
                artifact = f'Path(__file__).resolve().parents[{new_depth}] / "artifacts/TASK-{number:03}"'
                for symbol in ("OUT", "T9"):
                    text = re.sub(rf"(?m)^{symbol} = Path\(__file__\)(?:\.resolve\(\))?\.parent\s*$",
                                  f"{symbol} = {artifact}", text)
            if relative.startswith("src/dps_studio/research/waveform/"):
                text = text.replace("from .common import ", "from dps_studio.algorithms.waveform.common import ")
                text = text.replace("from .catalog import ", "from dps_studio.algorithms.waveform.catalog import ")
            if relative.startswith("scripts/research/task015/"):
                text = text.replace("ROOT = OUT.parents[1]", f"ROOT = Path(__file__).resolve().parents[{new_depth}]")
        after = text.encode("utf-8")
        if after != before:
            path.write_bytes(after)
            changes.append({"path": relative, "before_sha256": digest(before), "after_sha256": digest(after)})
    report = ROOT / "artifacts/TASK-016/audit/reference-repairs-corrected.json"
    report.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Updated {len(changes)} path/import references; {report}")


if __name__ == "__main__":
    main()
