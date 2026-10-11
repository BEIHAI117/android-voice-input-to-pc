"""Persistent configuration and trust state for the PhoneMic PC agent.

Everything lives in a per-user data directory so the pairing token stays stable
across restarts (the QR code therefore does not change every launch).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

APP_NAME = "PhoneMic"
PROTOCOL_VERSION = 1

# 中转房间 id 的派生盐。VPS 上的 relay_server.py 用同一公式校验注册者，
# 知道房间 id 但不知道 key 的人无法抢注。
RELAY_SALT = "phonemic-relay-v1"

# Injection modes understood by agent.inject
MODE_CLIPBOARD = "clipboard"  # copy to clipboard + Ctrl+V  (default, best for CJK)
MODE_TYPE = "type"            # SendInput unicode keystrokes (for terminals/SSH/vim)


def data_dir() -> Path:
    # Test/unattended escape hatch: keep a run's token/config out of the real
    # per-user directory.
    override = os.environ.get("PHONEMIC_DATA_DIR")
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p
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
    # 跨局域网中转：手机与 PC 都主动出站连到这台服务器（部署在 VPS 上），
    # 双方都不需要公网 IP。空 = 只用局域网直连。relay_key 只派生房间 id，
    # 不参与手机认证（配对令牌仍是端到端的），泄露它只能占一个空房间。
    relay_url: str = ""
    relay_key: str = field(default_factory=lambda: secrets.token_urlsafe(24))

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


def normalize_relay_url(url: str) -> str:
    """Accept https://http(s) style mistakes and a trailing slash; keep it clean."""
    url = url.strip().rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    return url


def relay_pc_id(cfg: "Config") -> str:
    """The relay room this PC owns. Printed in the QR payload for the phone."""
    digest = hashlib.sha256((RELAY_SALT + "|" + cfg.relay_key).encode("utf-8")).hexdigest()
    return "pm" + digest[:12]


def relay_pc_url(cfg: "Config") -> str:
    """URL the PC agent dials out to (registers the room)."""
    return f"{cfg.relay_url.rstrip('/')}/pc?p={relay_pc_id(cfg)}&k={quote(cfg.relay_key)}"


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
