"""中转链路端到端测试：relay 子进程 + PC agent（进程内）+ 模拟手机。

    python scripts/test_relay_e2e.py

覆盖：
1. 中转模式配对 payload 生成且字段齐全（m=relay / p / s / t / n）
2. 手机经中转拨号 → auth_ok → text → ack 全链路
3. PC 未上线时手机拨号收到 pc_offline
4. 二次会话：手机离开后 PC 自动重注册，还能再连

PC agent 在本进程内跑 run()，PHONEMIC_DATA_DIR 指向临时目录，
不会碰真实的 config.json。
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "pc-agent"))

from agent.config import Config, relay_pc_id  # noqa: E402
from agent.protocol import decode, encode  # noqa: E402
from agent.server import pairing_payload  # noqa: E402


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def wait_port(port: int, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            return
        except OSError:
            await asyncio.sleep(0.1)
    raise RuntimeError(f"port {port} never came up")


async def dial_and_drive(relay_port: int, pc_id: str, token: str, text: str) -> dict:
    """模拟手机：拨号 → auth → text，返回收到的最后一帧。"""
    from websockets.asyncio.client import connect

    url = f"ws://127.0.0.1:{relay_port}/phone?p={pc_id}"
    deadline = time.monotonic() + 12
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            async with connect(url, open_timeout=5) as ws:
                await ws.send(
                    encode({"t": "auth", "id": str(uuid.uuid4()), "name": "e2e-phone", "token": token}, token, False)
                )
                ok = decode(await asyncio.wait_for(ws.recv(), 8), token)
                if ok.get("t") != "auth_ok":
                    raise AssertionError(f"expected auth_ok, got {ok}")
                await ws.send(encode({"t": "text", "seq": 1, "text": text}, token, False))
                ack = decode(await asyncio.wait_for(ws.recv(), 8), token)
                return ack
        except Exception as exc:  # PC 可能还没注册上，稍后重试
            last_err = exc
            await asyncio.sleep(0.5)
    raise AssertionError(f"dial failed: {last_err}")


async def expect_offline(relay_port: int, bogus_room: str) -> bool:
    from websockets.asyncio.client import connect

    try:
        async with connect(f"ws://127.0.0.1:{relay_port}/phone?p={bogus_room}", open_timeout=5) as ws:
            frame = await asyncio.wait_for(ws.recv(), 5)
            return json.loads(frame).get("code") == "pc_offline"
    except Exception as exc:
        raise AssertionError(f"expected pc_offline frame, got {exc}")


async def main() -> int:
    from websockets.asyncio.client import connect

    relay_port, agent_port = free_port(), free_port()
    token = "e2e-" + uuid.uuid4().hex[:16]
    cfg = Config(
        token=token,
        device_name="relay-e2e-pc",
        host="127.0.0.1",
        port=agent_port,
        relay_url=f"ws://127.0.0.1:{relay_port}",
        dry_run=True,
    )

    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory(prefix="phonemic-e2e-") as tmp:
        os.environ["PHONEMIC_DATA_DIR"] = tmp
        os.environ["PHONEMIC_QR_AUTOPEN"] = "0"

        # relay 的日志必须落到文件而不是 PIPE：无人读取的 PIPE 写满后会
        # 阻塞 relay 的事件循环（上次调试时就是这么"冻住"的）。
        relay_log = open(Path(tmp) / "relay.log", "w+b")
        relay = subprocess.Popen(
            [sys.executable, str(ROOT / "vps" / "relay_server.py"),
             "--host", "127.0.0.1", "--port", str(relay_port)],
            stdout=relay_log, stderr=subprocess.STDOUT,
        )
        try:
            await wait_port(relay_port)

            # 1) pairing payload（relay 模式）
            payload = pairing_payload(cfg)
            pc_id = relay_pc_id(cfg)
            check(
                "中转配对 payload",
                payload.startswith("phonemic://") and "m=relay" in payload
                and f"p={pc_id}" in payload and f"t={token}" in payload and "s=0" in payload,
                payload,
            )

            # 2) PC 未上线 → pc_offline
            check("离线房间报 pc_offline", await expect_offline(relay_port, pc_id))

            # 3) PC agent 上线（进程内），全链路听写
            from agent.server import run as agent_run
            agent_task = asyncio.create_task(agent_run(cfg))
            ack = await dial_and_drive(relay_port, pc_id, token, "中转链路你好")
            check(
                "中转端到端 auth+text+ack",
                ack.get("t") == "ack" and ack.get("ok") is True and ack.get("chars") == len("中转链路你好"),
                json.dumps(ack, ensure_ascii=False),
            )

            # 4) 第二次会话（PC 已自动重注册）
            ack2 = await dial_and_drive(relay_port, pc_id, token, "第二轮")
            check("二次会话可用", ack2.get("t") == "ack" and ack2.get("ok") is True,
                  json.dumps(ack2, ensure_ascii=False))

            agent_task.cancel()
            try:
                await agent_task
            except asyncio.CancelledError:
                pass
        finally:
            relay.terminate()
            try:
                relay.wait(timeout=5)
            except subprocess.TimeoutExpired:
                relay.kill()
            relay_log.seek(0)
            content = relay_log.read().decode(errors="replace")
            relay_log.close()
            if fails:
                print("---- relay log ----")
                print(content)

    print()
    if fails:
        print(f"测试失败：{len(fails)} 项")
        return 1
    print("中转端到端测试全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
