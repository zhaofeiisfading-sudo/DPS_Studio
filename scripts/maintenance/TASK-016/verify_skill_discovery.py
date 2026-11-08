"""Verify real Codex skills/list discovery without starting a model or chat."""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("Codex CLI is unavailable; discovery was not verified")
    process = subprocess.Popen([executable, "app-server", "--stdio"], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    assert process.stdout and process.stdin

    def reader() -> None:
        assert process.stdout
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    threading.Thread(target=reader, daemon=True).start()

    def send(value: dict[str, Any]) -> None:
        assert process.stdin
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    def response(identifier: int) -> dict[str, Any]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            message = messages.get(timeout=max(.1, deadline - time.monotonic()))
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message["result"]
        raise TimeoutError("Codex skills/list did not return")

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "repo_hygiene_check", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True},
        }})
        response(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "skills/list", "params": {"cwds": [str(ROOT)], "forceReload": True}})
        result = response(2)
        skills = [skill for group in result["data"] for skill in group["skills"]
                  if skill["name"] == "repo-hygiene"]
        expected = ROOT / ".agents/skills/repo-hygiene/SKILL.md"
        selected = next(skill for skill in skills if Path(skill["path"]).resolve() == expected)
        if not selected.get("enabled", True):
            raise RuntimeError("Repository skill is disabled")
        proof = {"method": "Codex app-server skills/list", "forceReload": True,
                 "model_or_chat_started": False, "skill": selected}
        destination = ROOT / "artifacts/TASK-016/validation/skill-discovery.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(proof, ensure_ascii=False, indent=2))
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
