"""Persistent configuration and trust state for the PhoneMic PC agent.

Everything lives in a per-user data directory so the pairing token stays stable
across restarts (the QR code therefore does not change every launch).
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "PhoneMic"
PROTOCOL_VERSION = 1

# Injection modes understood by agent.inject
MODE_CLIPBOARD = "clipboard"  # copy to clipboard + Ctrl+V  (default, best for CJK)
MODE_TYPE = "type"            # SendInput unicode keystrokes (for terminals/SSH/vim)


def data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON so that a crash mid-write can never corrupt the file.

    These files hold the pairing token; if it is lost the phone has to be
    re-paired, so a truncated write is not an acceptable failure mode. Write to
    a sibling temp file and rename — on Windows os.replace is atomic.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _default_device_name() -> str:
    """What the phone shows on the floating ball for this computer.

    Defaults to the machine's hostname so two desktops on the same LAN are
    distinguishable without any setup. Override in config.json (`device_name`)
    or with ``--name`` when the hostname is unhelpful (often a random OEM
    string like "DESKTOP-4V6F778").
    """
    try:
        name = socket.gethostname().strip()
    except OSError:
        name = ""
    return name or "PhoneMic PC"


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8765
    # The computer's display name on the phone. Edit `device_name` in
    # config.json (path printed at startup) to change it.
    device_name: str = field(default_factory=_default_device_name)
    token: str = ""
    inject_mode: str = MODE_CLIPBOARD
    # Off by default for M0: token auth over a trusted LAN. Flip on once both
    # ends are verified — the scheme is documented in docs/协议.md.
    encrypt: bool = False
    char_delay_ms: int = 0
    paste_delay_ms: int = 80
    dry_run: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    def __post_init__(self) -> None:
        if not self.token:
            self.token = secrets.token_urlsafe(24)

    @property
    def config_path(self) -> Path:
        return data_dir() / "config.json"

    def save(self) -> None:
        _atomic_write_json(self.config_path, asdict(self))

    @classmethod
    def load(cls) -> "Config":
        path = data_dir() / "config.json"
        if not path.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass
class TrustStore:
    """Devices that have been allowed to drive this computer."""

    devices: list = field(default_factory=list)

    @property
    def path(self) -> Path:
        return data_dir() / "trust.json"

    def save(self) -> None:
        _atomic_write_json(self.path, {"devices": self.devices})

    @classmethod
    def load(cls) -> "TrustStore":
        path = data_dir() / "trust.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(devices=raw.get("devices", []))

    def remember(self, device_id: str, name: str) -> None:
        self.devices = [d for d in self.devices if d.get("id") != device_id]
        self.devices.append({"id": device_id, "name": name, "paired_at": _now_iso()})
        self.save()

    def is_known(self, device_id: str) -> bool:
        return any(d.get("id") == device_id for d in self.devices)

    def forget(self, device_id: str) -> None:
        self.devices = [d for d in self.devices if d.get("id") != device_id]
        self.save()


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
