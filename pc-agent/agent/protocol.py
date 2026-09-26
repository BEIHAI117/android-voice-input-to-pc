"""Wire protocol between the phone and the PC agent.

Framing: one WebSocket text frame per message.

    plain mode   ->  {"t": "...", ...}            (JSON, token auth only)
    encrypt mode ->  {"e": "<base64>"}            (NaCl SecretBox of the JSON)

The encryption key is derived deterministically from the pairing token, so no
extra handshake is needed — whoever holds the token (transmitted out-of-band in
the QR code) can read the traffic.

Message types (see docs/协议.md for the full table):

    phone -> pc : auth, text, typing, cmd, ping
    pc -> phone : auth_ok, auth_fail, ack, cmd_result, pong, error
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

KEY_CONTEXT = b"phonemic-v1|"

try:
    from nacl.secret import SecretBox
    from nacl.utils import random as _nacl_random

    HAS_NACL = True
except Exception:  # pragma: no cover - optional dependency
    SecretBox = None  # type: ignore[assignment]
    HAS_NACL = False


class ProtocolError(Exception):
    pass


def derive_key(token: str) -> bytes:
    return hashlib.sha256(KEY_CONTEXT + token.encode("utf-8")).digest()


def encode(msg: dict[str, Any], token: str, encrypt: bool) -> str:
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if not encrypt:
        return raw.decode("utf-8")
    if not HAS_NACL:
        raise ProtocolError("pynacl is not installed but encrypt=True")
    box = SecretBox(derive_key(token))
    # EncryptedMessage == nonce || ciphertext, which is what SecretBox.decrypt expects.
    sealed = box.encrypt(raw, _nacl_random(24))
    return json.dumps({"e": base64.b64encode(bytes(sealed)).decode("ascii")})


def decode(frame: str, token: str) -> dict[str, Any]:
    try:
        obj = json.loads(frame)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"frame is not JSON: {exc}") from exc

    if isinstance(obj, dict) and "e" in obj:
        if not HAS_NACL:
            raise ProtocolError("encrypted frame but pynacl is not installed")
        try:
            box = SecretBox(derive_key(token))
            raw = box.decrypt(base64.b64decode(obj["e"]))
        except Exception as exc:  # nacl raises several unrelated types
            raise ProtocolError(f"decrypt failed: {exc}") from exc
        try:
            obj = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"plaintext is not JSON: {exc}") from exc

    if not isinstance(obj, dict) or "t" not in obj:
        raise ProtocolError("message must be an object with a 't' field")
    return obj


# ---------------------------------------------------------------- helpers ---


def ok_ack(seq: int, mode: str, chars: int) -> dict[str, Any]:
    return {"t": "ack", "seq": seq, "ok": True, "mode": mode, "chars": chars}


def error(text: str, code: str = "generic") -> dict[str, Any]:
    return {"t": "error", "code": code, "msg": text}
