"""WebSocket server: accepts the phone, authenticates it, injects its text."""
from __future__ import annotations

import asyncio
import logging
import socket
import sys
import time
from pathlib import Path
from typing import Any

from . import commands as commands_mod
from . import http_page, inject, llm
from .config import MODE_CLIPBOARD, Config, TrustStore
from .protocol import ProtocolError, decode, encode, error, ok_ack

log = logging.getLogger("phonemic.server")


def lan_ip() -> str:
    """Best-effort LAN address to put in the QR code.

    UDP ``connect`` only picks a route — no packet is ever sent — so pointing it
    at a public address is safe and yields the outbound interface address.
    """
    for probe in (("223.5.5.5", 53), ("8.8.8.8", 80), ("1.1.1.1", 443)):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(probe)
            addr = s.getsockname()[0]
            if not addr.startswith("127."):
                return addr
        except OSError:
            continue
        finally:
            s.close()
    return "127.0.0.1"


def pairing_payload(cfg: Config) -> str:
    return f"phonemic://{lan_ip()}:{cfg.port}?v=1&t={cfg.token}"


class Session:
    """One connected phone."""

    def __init__(self, ws: Any, cfg: Config, trust: TrustStore) -> None:
        self.ws = ws
        self.cfg = cfg
        self.trust = trust
        self.authed = False
        self.device_id = ""
        self.device_name = ""
        self.pending_shell: str | None = None

    async def send(self, msg: dict[str, Any]) -> None:
        await self.ws.send(encode(msg, self.cfg.token, self.cfg.encrypt))

    async def handle(self) -> None:
        async for frame in self.ws:
            try:
                msg = decode(frame, self.cfg.token)
            except ProtocolError as exc:
                log.warning("bad frame from %s: %s", self.ws.remote_address, exc)
                await self.send(error(str(exc), code="bad_frame"))
                continue
            try:
                await self.dispatch(msg)
            except Exception:
                log.exception("handler failed for %r", msg.get("t"))
                await self.send(error("internal error", code="internal"))

    async def dispatch(self, msg: dict[str, Any]) -> None:
        t = msg.get("t")

        if t == "ping":
            await self.send({"t": "pong", "ts": time.time()})
            return

        if t == "auth":
            await self.do_auth(msg)
            return

        if not self.authed:
            await self.send(error("not authenticated", code="unauth"))
            return

        if t == "typing":
            # Partial results are acknowledged only; M0 does not stream them
            # into the caret (that would spam the undo stack).
            await self.send({"t": "ack", "seq": msg.get("seq", 0), "ok": True, "partial": True})
            return

        if t == "text":
            await self.do_text(msg)
            return

        if t == "cmd":
            await self.do_cmd(msg)
            return

        await self.send(error(f"unknown message type {t!r}", code="unknown_type"))

    async def do_auth(self, msg: dict[str, Any]) -> None:
        token = str(msg.get("token", ""))
        if not token or not _const_eq(token, self.cfg.token):
            log.warning("rejected auth from %s", self.ws.remote_address)
            await self.send({"t": "auth_fail", "reason": "bad token"})
            await self.ws.close(code=4401, reason="bad token")
            return

        self.authed = True
        self.device_id = str(msg.get("id", ""))[:64]
        self.device_name = str(msg.get("name", "phone"))[:64]
        if self.device_id and not self.trust.is_known(self.device_id):
            self.trust.remember(self.device_id, self.device_name)
            log.info("new device paired: %s (%s)", self.device_name, self.device_id)

        await self.send(
            {
                "t": "auth_ok",
                "device_name": self.cfg.device_name,
                "inject_mode": self.cfg.inject_mode,
                "encrypt": self.cfg.encrypt,
                "version": 1,
            }
        )
        log.info("authenticated %s", self.device_name or self.ws.remote_address)

    async def do_text(self, msg: dict[str, Any]) -> None:
        text = str(msg.get("text", ""))
        if not text:
            await self.send(ok_ack(int(msg.get("seq", 0)), self.cfg.inject_mode, 0))
            return

        t0 = time.perf_counter()
        used = inject.inject_text(
            text,
            mode=str(msg.get("mode") or self.cfg.inject_mode),
            char_delay_ms=self.cfg.char_delay_ms,
            paste_delay_ms=self.cfg.paste_delay_ms,
            dry_run=self.cfg.dry_run,
        )
        log.info("injected %d chars via %s in %.0f ms", len(text), used, (time.perf_counter() - t0) * 1000)
        await self.send(ok_ack(int(msg.get("seq", 0)), used, len(text)))

    async def do_cmd(self, msg: dict[str, Any]) -> None:
        seq = int(msg.get("seq", 0))
        intent = msg.get("intent")
        args = msg.get("args") or {}

        # Allow the phone to send either a pre-resolved action or raw speech.
        if isinstance(intent, dict):
            action = intent
        elif intent:
            action = {"action": intent, **args}
        else:
            text = str(msg.get("text", ""))
            action = await self.resolve(text)

        if action is None:
            await self.send({"t": "cmd_result", "seq": seq, "ok": False, "detail": "no intent matched"})
            return

        if action.get("action") == "shell" and action.get("confirm", True):
            self.pending_shell = str(action.get("cmd", ""))
            await self.send(
                {
                    "t": "cmd_result",
                    "seq": seq,
                    "ok": False,
                    "needs_confirm": True,
                    "detail": self.pending_shell,
                }
            )
            return

        result = commands_mod.run_action(action, dry_run=self.cfg.dry_run)
        await self.send(
            {
                "t": "cmd_result",
                "seq": seq,
                "ok": True,
                "action": result.action,
                "detail": result.detail,
            }
        )

    async def resolve(self, text: str) -> dict[str, Any] | None:
        matched = commands_mod.find_command(text, commands_mod.load_commands())
        if matched is not None:
            return matched.get("action", {})
        return llm.parse_intent(text, self.cfg)


async def run(cfg: Config) -> None:
    from websockets.asyncio.server import serve

    trust = TrustStore.load()
    commands_mod.load_commands()  # materialise commands.json from the example

    payload = pairing_payload(cfg)
    qr_png = _write_qr(payload)

    # Setup page on port+1: real QR image + APK download for the phone.
    http_port = cfg.port + 1
    httpd = http_page.start(
        host=cfg.host,
        port=http_port,
        qr_png=qr_png,
        apk=_find_apk(),
        payload=payload,
        token=cfg.token,
        pc_name=cfg.device_name,
    )

    ip = lan_ip()
    print()
    print(f"  PhoneMic PC agent  v1  ·  {cfg.device_name}")
    print(f"  listening on ws://{ip}:{cfg.port}   (encrypt={'on' if cfg.encrypt else 'off'})")
    print(f"  inject mode: {cfg.inject_mode}{'   [DRY RUN]' if cfg.dry_run else ''}")
    print()
    if httpd is not None:
        print(f"  ┌──────────────────────────────────────────────────────────┐")
        print(f"  │  手机连上同一个 WiFi，浏览器打开：                          │")
        print(f"  │  http://{ip}:{http_port}{' ' * max(0, 38 - len(ip) - len(str(http_port)))}│")
        print(f"  │  → 可下载安装包 + 二维码                                  │")
        print(f"  └──────────────────────────────────────────────────────────┘")
        print()
    print(f"  pairing payload:  {payload}")
    print(f"  pairing token:    {cfg.token}")
    print()

    _show_qr(payload, qr_png)
    sys.stdout.flush()

    async def handler(ws: Any) -> None:
        session = Session(ws, cfg, trust)
        log.info("connection from %s", getattr(ws, "remote_address", "?"))
        try:
            await session.handle()
        except Exception:
            log.exception("session crashed")
        finally:
            log.info("connection closed")

    async with serve(handler, cfg.host, cfg.port, ping_interval=20, ping_timeout=20):
        await asyncio.Future()  # run until cancelled


def _write_qr(payload: str) -> Path | None:
    """Render the QR to a PNG. Returns the path, or None if qrcode is missing."""
    try:
        import qrcode
    except ImportError:
        return None
    from .config import data_dir

    qr = qrcode.QRCode(border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    path = data_dir() / "pairing-qr.png"
    try:
        qr.make_image(fill_color="black", back_color="white").save(path)
    except Exception:
        return None
    return path


def _show_qr(payload: str, qr_png: Path | None) -> None:
    if qr_png is not None:
        print(f"  QR code (image): {qr_png}")
        # The PNG is the reliable thing to scan; open it so it is one glance away.
        try:
            import os
            import subprocess

            if os.name == "nt":
                os.startfile(str(qr_png))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(qr_png)])
        except Exception:
            pass

    try:
        import qrcode
    except ImportError:
        print("  (install qrcode[pil] to render a QR code)")
        return

    qr = qrcode.QRCode(border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    print()
    print(_render_half_block(qr))
    print()
    print("  ↑ 终端渲染可能仍有变形，扫不出来请扫上面自动打开的图片，或用手机浏览器打开配对页。")
    print()


def _render_half_block(qr, invert: bool = False) -> str:
    """Render a QR code as text at the correct aspect ratio.

    Terminal cells are roughly 2:1 (taller than wide), so printing one glyph
    per module stretches the code sideways and it will not scan. Packing two
    module rows into one cell with the half-block glyphs cancels that out.

    `qrcode`'s own `print_tty` does the same thing but refuses to run when
    stdout is redirected ("Not a tty"), so this is done by hand — it works in
    a log file, a pipe, or a console alike.
    """
    matrix = [[bool(c) != invert for c in row] for row in qr.get_matrix()]
    if len(matrix) % 2:
        matrix.append([False] * len(matrix[0]))

    out: list[str] = []
    for i in range(0, len(matrix), 2):
        top, bottom = matrix[i], matrix[i + 1]
        line = []
        for t, b in zip(top, bottom):
            line.append("█" if (t and b) else "▀" if t else "▄" if b else " ")
        out.append("".join(line))
    return "\n".join(out)


def _find_apk() -> Path | None:
    """Locate the built APK so the setup page can offer it as a download."""
    import glob

    here = Path(__file__).resolve().parent.parent.parent
    for pattern in ("dist/*.apk", "android/app/build/outputs/apk/release/*.apk"):
        hits = sorted(glob.glob(str(here / pattern)), reverse=True)
        hits = [h for h in hits if "unsigned" not in h]
        if hits:
            return Path(hits[0])
    return None


def _const_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
