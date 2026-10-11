#!/usr/bin/env python3
"""PhoneMic 中转自检 —— 同时扮演 PC 与手机两端，验证转发链路。

    python selfcheck.py ws://127.0.0.1:8766
    python selfcheck.py wss://relay.example.com

全绿（5 项 PASS）即部署成功。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sys
import time

try:
    from websockets.asyncio.client import connect
except ImportError:
    sys.exit("缺少依赖：pip install 'websockets>=13'")

SALT = "phonemic-relay-v1"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures.append(name)


async def main(url: str) -> int:
    key = secrets.token_urlsafe(24)
    pc_id = "pm" + hashlib.sha256((SALT + "|" + key).encode()).hexdigest()[:12]
    pc_url = f"{url.rstrip('/')}/pc?p={pc_id}&k={key}"
    phone_url = f"{url.rstrip('/')}/phone?p={pc_id}"

    # 1) 错误的 key 必须被拒绝
    try:
        bad = await connect(f"{url.rstrip('/')}/pc?p={pc_id}&k=wrong", open_timeout=10)
        try:
            await bad.recv()
            check("坏 key 被拒", False, "连接未被关闭")
        except Exception:
            check("坏 key 被拒", True)
    except Exception:
        check("坏 key 被拒", True, "握手阶段即被拒")

    async def run_pc() -> str:
        async with connect(pc_url, open_timeout=10) as ws:
            await ws.send(json.dumps({"t": "auth", "token": "sometoken"}))
            reply = await asyncio.wait_for(ws.recv(), timeout=10)
            return reply

    async def run_phone() -> str:
        t0 = time.perf_counter()
        async with connect(phone_url, open_timeout=10) as ws:
            await ws.send(json.dumps({"t": "auth", "token": "sometoken"}))
            reply = await asyncio.wait_for(ws.recv(), timeout=10)
            dt = (time.perf_counter() - t0) * 1000
            print(f"      往返延迟 {dt:.0f} ms")
            return reply

    pc_task = asyncio.create_task(run_pc())
    await asyncio.sleep(1.0)  # 让 PC 先注册
    phone_task = asyncio.create_task(run_phone())

    try:
        got_pc, got_phone = await asyncio.wait_for(
            asyncio.gather(phone_task, pc_task), timeout=15
        )
        check("PC 注册成功", got_pc == json.dumps({"t": "auth", "token": "sometoken"}),
              f"PC 收到: {got_pc[:80]}")
        check("手机拨号成功", got_phone == json.dumps({"t": "auth", "token": "sometoken"}),
              f"手机收到: {got_phone[:80]}")
    except Exception as exc:
        check("PC 注册成功", False, str(exc)[:120])
        check("手机拨号成功", False, str(exc)[:120])

    # 5) pc 不在线时手机应收到 pc_offline
    try:
        async with connect(f"{url.rstrip('/')}/phone?p=pmdoesnotexist", open_timeout=10) as ws:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=10)
                err = json.loads(frame)
                check("离线房间报 pc_offline", err.get("code") == "pc_offline", frame[:80])
            except Exception:
                check("离线房间报 pc_offline", False, "未收到 error 帧")
    except Exception as exc:
        check("离线房间报 pc_offline", False, str(exc)[:120])

    print()
    if failures:
        print(f"自检失败：{len(failures)} 项未通过 —— 把本脚本完整输出发给排查人。")
        return 1
    print("自检通过：中转转发链路正常。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("用法：python selfcheck.py ws://<host>:<port>")
    raise SystemExit(asyncio.run(main(sys.argv[1])))
