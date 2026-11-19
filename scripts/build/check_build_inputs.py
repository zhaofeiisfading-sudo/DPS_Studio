"""Evaluate PyInstaller spec inputs with inert stubs; never build an executable."""
from __future__ import annotations

import argparse
import ast
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = ROOT / "scripts/build/specs/pdv_research.spec"


def _check_comparison(hidden: list[str], excluded: list[str]) -> None:
    always_forbidden = ("matplotlib", "scripts", "dps_studio.research")
    if not {"matplotlib", "dps_studio.research"}.issubset(excluded):
        raise ValueError("Research comparison requires the existing analysis exclusions")
    for package in ("dps_studio.core.stft_m4", "dps_studio.gui.comparison"):
        base = ROOT / "src" / package.replace(".", "/")
        sources = sorted(base.glob("*.py"))
        if not sources:
            raise ValueError(f"Missing comparison package: {base}")
        forbidden: tuple[str, ...] = always_forbidden
        if package.startswith("dps_studio.core"):
            forbidden += ("PySide6", "pyqtgraph", "dps_studio.gui")
        for source in sources:
            if source.stem != "__init__" and f"{package}.{source.stem}" not in hidden:
                raise ValueError(f"Comparison module is missing from build inputs: {source}")
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
                else:
                    continue
                if any(name == prefix or name.startswith(prefix + ".")
                       for name in names for prefix in forbidden):
                    raise ValueError(f"Forbidden dependency in {source.name}:{node.lineno}")


def validate_spec(spec: Path) -> dict[str, Any]:
    resources: list[str] = []
    entries: list[str] = []
    hidden: list[str] = []
    excluded: list[str] = []

    def require(path: str) -> None:
        item = Path(path).resolve()
        if not item.is_file() or not item.is_relative_to(ROOT):
            raise ValueError(f"Missing or external build input: {item}")

    class Analysis:
        def __init__(self, scripts: list[str], **options: Any) -> None:
            for item in scripts:
                require(item)
                entries.append(item)
            for source, _destination in options.get("datas", []):
                require(source)
                resources.append(source)
            hidden.extend(options.get("hiddenimports", []))
            excluded.extend(options.get("excludes", []))
            self.scripts = scripts
            self.pure: list[str] = []
            self.binaries: list[tuple[str, str, str]] = []
            self.datas = options.get("datas", [])

    def collect_submodules(package: str) -> list[str]:
        base = ROOT / "src" / package.replace(".", "/")
        if not base.is_dir():
            raise ValueError(f"Missing dynamic-import package: {base}")
        return [".".join(path.relative_to(ROOT / "src").with_suffix("").parts)
                for path in sorted(base.rglob("*.py")) if path.name != "__init__.py"]

    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = collect_submodules  # type: ignore[attr-defined]
    names = ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks")
    saved = {name: sys.modules.get(name) for name in names}
    try:
        for name in names:
            sys.modules[name] = hooks if name.endswith(".hooks") else ModuleType(name)
        runpy.run_path(str(spec), init_globals={
            "SPECPATH": str(spec.parent), "Analysis": Analysis,
            "PYZ": lambda *a, **kw: None, "EXE": lambda *a, **kw: None,
            "COLLECT": lambda *a, **kw: None,
        })
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    if not entries or not resources or not hidden:
        raise ValueError("Spec must include an entry point, resources and dynamic algorithms")
    if spec.name == DEFAULT_SPEC.name:
        _check_comparison(hidden, excluded)
    return {"spec": str(spec), "entries": entries, "resources": resources,
            "hidden_imports": hidden, "built": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()
    print(json.dumps(validate_spec(args.spec.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
