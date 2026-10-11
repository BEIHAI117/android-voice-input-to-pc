#!/usr/bin/env python3
"""PhoneMic 中转服务器（部署在 VPS 上）。

在手机与 PC agent 之间转发 WebSocket 帧：两端都**主动出站**连到这里，
所以双方都不需要公网 IP、不需要开路由器端口。本服务器不解析业务消息、
看不到配对令牌 —— 手机与 PC 之间的 auth 认证端到端进行。

用法：

    pip install "websockets>=13"
    python relay_server.py                    # 监听 0.0.0.0:8766
    python relay_server.py --port 443 \
        --tls-cert /etc/letsencrypt/live/x/fullchain.pem \
        --tls-key  /etc/letsencrypt/live/x/privkey.pem   # 直接上 wss
    python relay_server.py --host 127.0.0.1   # 挂在 nginx/caddy 后面时

自检（同时扮演 PC 与手机两端，验证转发链路）：

    python selfcheck.py ws://127.0.0.1:8766

协议（详见仓库 docs/协议.md 第 8 节）：

    PC   →  ws(s)://<host>/<path>/pc?p=<pc_id>&k=<relay_key>   注册房间
    手机 →  ws(s)://<host>/<path>/phone?p=<pc_id>              拨号进入

pc_id 由 relay_key 派生（两端各算一遍，服务器只做校验），
知道 pc_id 但不知道 key 的人无法抢注房间。一个房间同时最多一对
PC/手机；手机先到而 PC 不在线时，服务器回一条 error 帧后关闭。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import ssl
import sys
from typing import Any
from urllib.parse import parse_qs

try:
    from websockets.asyncio.server import serve
except ImportError:
    sys.exit("缺少依赖：pip install 'websockets>=13'")

log = logging.getLogger("phonemic.relay")

# 与 PC agent（agent/config.py）保持一致：pc_id = "pm" + sha256(SALT|key)[:12]
SALT = "phonemic-relay-v1"

# 私有关闭码（4000-4999 为应用可用区间）
CLOSE_BAD_REGISTER = 4401  # key 与 pc_id 不匹配，或参数缺失
CLOSE_SUPERSEDED = 4402    # 同一 pc_id 被新连接顶替


def pc_id_for(key: str) -> str:
    return "pm" + hashlib.sha256((SALT + "|" + key).encode("utf-8")).hexdigest()[:12]


class Room:
    """一个 pc_id 对应一间房：最多一个 PC 注册者、一个手机。"""

    def __init__(self, pc_id: str) -> None:
        self.pc_id = pc_id
        self.pc: Any = None
        self.phone: Any = None


class Relay:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    # ------------------------------------------------------------- intake ---

    async def handle(self, ws: Any) -> None:
        path = ""
        try:
            path = ws.request.path  # websockets>=13 asyncio API
        except AttributeError:
            path = getattr(ws, "path", "")
        base, _, query = path.partition("?")
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}

        if base.endswith("/pc"):
            await self._register(ws, params.get("p", ""), params.get("k", ""))
        elif base.endswith("/phone"):
            await self._dial(ws, params.get("p", ""))
        else:
            await ws.close(1008, "unknown path")
            return

    async def _register(self, ws: Any, pc_id: str, key: str) -> None:
        if not pc_id or not key or pc_id != pc_id_for(key):
            log.warning("register refused: bad key/pc_id")
            await ws.close(CLOSE_BAD_REGISTER, "bad key")
            return

        room = self.rooms.setdefault(pc_id, Room(pc_id))
        old = room.pc
        if old is not None:
            log.info("pc %s: kicking stale registration", pc_id)
            room.pc = None
            await _close_quietly(old, CLOSE_SUPERSEDED, "superseded")

        room.pc = ws
        log.info("pc %s: registered", pc_id)
        try:
            # websockets 禁止两个协程同时读一条连接：这里不 iter 帧（那是
            # 配对后 pump 的职责），只挂起等这条连接关闭。
            await ws.wait_closed()
        finally:
            if room.pc is ws:
                room.pc = None
                log.info("pc %s: unregistered", pc_id)
            if room.phone is not None:
                await _close_quietly(room.phone, 1000, "pc left")
            _gc(self.rooms, pc_id)

    async def _dial(self, ws: Any, pc_id: str) -> None:
        room = self.rooms.get(pc_id)
        if room is None or room.pc is None:
            log.info("phone -> %s: pc not online", pc_id or "?")
            await _send_error(ws, "pc_offline", "电脑未连接中转服务器")
            await ws.close(1000, "pc offline")
            return
        if room.phone is not None:
            log.info("phone -> %s: room busy", pc_id)
            await _send_error(ws, "busy", "该电脑已有会话进行中")
            await ws.close(1000, "busy")
            return

        room.phone = ws
        pc_ws = room.pc
        log.info("phone -> %s: paired", pc_id)
        left, right = ws, pc_ws
        try:
            await asyncio.gather(_pump(left, right), _pump(right, left))
        finally:
            if room.phone is ws:
                room.phone = None
                log.info("phone -> %s: left", pc_id)
            # 只关当初配对的那条 PC 连接：若它已被新注册顶替，别误杀新会话
            if room.pc is pc_ws:
                await _close_quietly(room.pc, 1000, "phone left")
            _gc(self.rooms, pc_id)


async def _pump(src: Any, dst: Any) -> None:
    """把 src 收到的每一帧原样转给 dst，不动内容、不看明文。"""
    try:
        async for frame in src:
            await dst.send(frame)
    except Exception as exc:  # 对端先断 / 网络抖动，属正常路径
        log.debug("pump ended: %s", exc)
    finally:
        await _close_quietly(dst, 1000, "upstream closed")


async def _close_quietly(ws: Any, code: int, reason: str) -> None:
    try:
        await ws.close(code, reason)
    except Exception:
        pass


def _send_error(ws: Any, code: str, msg: str) -> Any:
    import json

    return ws.send(json.dumps({"t": "error", "code": code, "msg": msg}, ensure_ascii=False))


def _gc(rooms: dict[str, Room], pc_id: str) -> None:
    room = rooms.get(pc_id)
    if room is not None and room.pc is None and room.phone is None:
        del rooms[pc_id]


async def run(args: argparse.Namespace) -> None:
    tls: ssl.SSLContext | None = None
    if args.tls_cert or args.tls_key:
        if not (args.tls_cert and args.tls_key):
            sys.exit("--tls-cert 与 --tls-key 必须同时给出")
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.tls_cert, args.tls_key)

    relay = Relay()
    async with serve(relay.handle, args.host, args.port, ssl=tls, ping_interval=20, ping_timeout=20):
        scheme = "wss" if tls else "ws"
        where = f"{args.host}:{args.port}"
        print(f"PhoneMic relay listening on {scheme}://{where}")
        print(f"  pc  endpoint:  {scheme}://{where}/pc?p=<pc_id>&k=<relay_key>")
        print(f"  phone  path:   {scheme}://{where}/phone?p=<pc_id>")
        await asyncio.Future()  # run forever


def main() -> int:
    p = argparse.ArgumentParser(description="PhoneMic VPS relay")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--tls-cert", help="PEM 证书链（直接对外 wss 时用）")
    p.add_argument("--tls-key", help="PEM 私钥")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
