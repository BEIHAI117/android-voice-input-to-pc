"""Simulate the phone against the PC agent — end-to-end test without a device.

    python scripts/mock_phone.py --token <token> --text "你好，世界"
    python scripts/mock_phone.py --token <token> --cmd "截图"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.protocol import decode, encode  # noqa: E402


async def main() -> int:
    p = argparse.ArgumentParser(description="PhoneMic mock phone client")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", required=True, help="pairing token from the PC agent output")
    p.add_argument("--text", help="text to inject at the caret")
    p.add_argument("--cmd", help="raw speech to resolve as a command")
    p.add_argument("--name", default="mock-phone")
    p.add_argument("--encrypt", action="store_true")
    p.add_argument("--ping", action="store_true")
    args = p.parse_args()

    from websockets.asyncio.client import connect

    url = f"ws://{args.host}:{args.port}"
    async with connect(url, open_timeout=10) as ws:
        await ws.send(
            encode(
                {"t": "auth", "id": str(uuid.uuid4()), "name": args.name, "token": args.token},
                args.token,
                args.encrypt,
            )
        )
        reply = decode(await ws.recv(), args.token)
        print("<<", json.dumps(reply, ensure_ascii=False))
        if reply.get("t") != "auth_ok":
            return 1

        if args.ping:
            await ws.send(encode({"t": "ping"}, args.token, args.encrypt))
            print("<<", json.dumps(decode(await ws.recv(), args.token), ensure_ascii=False))

        if args.text:
            await ws.send(
                encode({"t": "text", "seq": 1, "text": args.text}, args.token, args.encrypt)
            )
            print("<<", json.dumps(decode(await ws.recv(), args.token), ensure_ascii=False))

        if args.cmd:
            await ws.send(
                encode({"t": "cmd", "seq": 2, "text": args.cmd}, args.token, args.encrypt)
            )
            print("<<", json.dumps(decode(await ws.recv(), args.token), ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
