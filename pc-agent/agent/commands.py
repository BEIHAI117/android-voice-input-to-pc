"""L0 command layer: turn recognised text into a desktop action.

Matching is deliberately dumb and predictable — exact / substring match on a
list of trigger phrases from ``commands.json``. Natural-language intent
parsing is a separate, optional layer (agent.llm) that outputs the very same
action objects, so both paths share one executor.

Action schema::

    {"action": "launch",  "target": "https://..."}          # or an exe path
    {"action": "hotkey",  "keys": ["win", "shift", "s"]}
    {"action": "shell",   "cmd": "...", "confirm": true}
    {"action": "text",    "text": "..."}                     # inject literally
    {"action": "clipboard","text": "..."}
"""
from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import data_dir
from .inject import inject_hotkey, inject_text


class CommandError(Exception):
    pass


@dataclass
class CommandResult:
    matched: bool
    name: str = ""
    action: str = ""
    detail: str = ""
    needs_confirm: bool = False


def commands_path() -> Path:
    return data_dir() / "commands.json"


def load_commands() -> list[dict[str, Any]]:
    path = commands_path()
    if not path.exists():
        example = Path(__file__).resolve().parent.parent / "commands.example.json"
        if example.exists():
            from .config import _atomic_write_json

            _atomic_write_json(path, json.loads(example.read_text(encoding="utf-8")))
        else:
            return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("commands", [])


def find_command(text: str, commands: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Longest trigger wins so "打开微信" beats "打开"."""
    stripped = text.strip().rstrip("。！？!.?").lower()
    if not stripped:
        return None
    best: dict[str, Any] | None = None
    best_len = 0
    for cmd in commands:
        for phrase in cmd.get("match", []):
            p = phrase.strip().lower()
            if not p:
                continue
            hit = stripped == p or (cmd.get("contains", False) and p in stripped)
            if hit and len(p) > best_len:
                best, best_len = cmd, len(p)
    return best


def run_action(action: dict[str, Any], dry_run: bool = False) -> CommandResult:
    kind = action.get("action", "")
    if kind == "launch":
        target = action.get("target", "")
        if dry_run:
            return CommandResult(True, action=kind, detail=f"launch {target!r}")
        _launch(target)
        return CommandResult(True, action=kind, detail=f"launched {target}")

    if kind == "hotkey":
        keys = [str(k) for k in action.get("keys", [])]
        if not keys:
            return CommandResult(True, action=kind, detail="no keys")
        inject_hotkey(*keys, dry_run=dry_run)
        return CommandResult(True, action=kind, detail="+".join(keys))

    if kind == "shell":
        cmd = action.get("cmd", "")
        if action.get("confirm", True):
            return CommandResult(True, action=kind, detail=cmd, needs_confirm=True)
        if dry_run:
            return CommandResult(True, action=kind, detail=f"shell {cmd!r}")
        subprocess.Popen(cmd, shell=True)
        return CommandResult(True, action=kind, detail="shell started")

    if kind in ("text", "clipboard"):
        inject_text(
            action.get("text", ""),
            mode="type" if kind == "text" else "clipboard",
            dry_run=dry_run,
        )
        return CommandResult(True, action=kind, detail=f"{len(action.get('text', ''))} chars")

    return CommandResult(True, action=kind, detail=f"unknown action {kind!r}")


def execute(
    text: str,
    commands: list[dict[str, Any]],
    dry_run: bool = False,
) -> CommandResult:
    cmd = find_command(text, commands)
    if cmd is None:
        return CommandResult(matched=False)
    return run_action(cmd.get("action", {}), dry_run=dry_run)


def _launch(target: str) -> None:
    if not target:
        raise CommandError("empty launch target")
    try:
        if "://" in target:  # http/https/file/mailto
            import webbrowser

            webbrowser.open(target)
            return
    except Exception:
        pass
    try:
        subprocess.Popen([target] if Path(target).exists() else shlex.split(target))
    except OSError as exc:
        raise CommandError(f"cannot launch {target!r}: {exc}") from exc
