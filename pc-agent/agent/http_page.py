"""Tiny setup page served over HTTP next to the WebSocket port.

Solves two real onboarding problems at once:

* the ASCII QR printed in a terminal is almost never scannable (terminal cells
  are ~2:1, so the code is stretched) — here the phone sees a real PNG;
* getting the APK onto the phone in the first place — it is offered as a
  download link, so no USB / cloud / file-transfer app is needed.

Serves exactly three things and nothing else: the page, the QR PNG, the APK.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PhoneMic 配对</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         margin: 0; padding: 24px; background: #0f1420; color: #e8ecf5; }}
  .card {{ max-width: 520px; margin: 0 auto; background: #1a2233; border-radius: 16px;
          padding: 24px; box-sizing: border-box; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p  {{ color: #9aa7c0; line-height: 1.7; margin: 8px 0; }}
  .qr {{ background: #fff; border-radius: 12px; padding: 16px; text-align: center; margin: 20px 0; }}
  .qr img {{ width: 100%; max-width: 320px; image-rendering: pixelated; }}
  .btn {{ display: block; text-align: center; text-decoration: none; padding: 14px 18px;
         border-radius: 12px; font-weight: 600; margin: 12px 0; }}
  .primary {{ background: #2f6bff; color: #fff; }}
  .ghost {{ background: #243049; color: #cdd8ee; }}
  code {{ background: #243049; padding: 2px 6px; border-radius: 6px; font-size: 13px;
         word-break: break-all; }}
  .step {{ display: flex; gap: 10px; margin: 10px 0; }}
  .num {{ background: #2f6bff; color: #fff; width: 22px; height: 22px; border-radius: 50%;
         flex: 0 0 22px; text-align: center; line-height: 22px; font-size: 13px; }}
</style>
</head>
<body>
<div class="card">
  <h1>PhoneMic 配对</h1>
  <p>电脑 <code>{pc_name}</code> 已就绪。</p>
  <p style="font-size:13px">这个名字会显示在手机悬浮球上。要改名：编辑
  <code>{config_path}</code> 里的 <code>device_name</code> 后重启。</p>

  {apk_block}

  <div class="qr">
    <img src="/qr.png" alt="配对二维码">
  </div>
  <p style="text-align:center">在 <b>手机 App 里点「扫码绑定电脑」</b>，扫上面这个码</p>

  <div class="step"><div class="num">1</div><div>安装并打开 PhoneMic</div></div>
  <div class="step"><div class="num">2</div><div>点「扫码绑定电脑」，对准上方二维码</div></div>
  <div class="step"><div class="num">3</div><div>点「权限与后台引导」，打开 vivo 的几个开关</div></div>
  <div class="step"><div class="num">4</div><div>点「启动悬浮球」，长按说话</div></div>

  <p style="margin-top:20px">扫不了码？在 App 里选「手动输入地址」，填：<br>
  <code>{manual}</code></p>
  <p>配对令牌：<code>{token}</code></p>
</div>
</body>
</html>
"""

APK_BLOCK = """<a class="btn primary" href="/app.apk">⬇ 下载 PhoneMic 安装包 ({size})</a>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    qr_png: Path | None = None
    apk: Path | None = None
    payload: str = ""
    token: str = ""
    pc_name: str = ""
    config_path: str = ""
    manual: str = ""  # manual-entry hint; empty = derive from the client's IP

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._html()
        elif path == "/qr.png":
            self._file(self.qr_png, "image/png")
        elif path == "/app.apk":
            self._file(self.apk, "application/vnd.android.package-archive", download=True)
        else:
            self.send_error(404)

    def _html(self) -> None:
        if self.manual:
            manual = self.manual
        else:
            host, _ = self.client_address[0], self.server.server_address[1]
            port = self.server.server_address[1] - 1  # QR/WS port is http_port - 1
            manual = f"{host}:{port}?t={self.token}"

        if self.apk and self.apk.exists():
            size_mb = self.apk.stat().st_size / 1024 / 1024
            apk_block = APK_BLOCK.format(size=f"{size_mb:.1f} MB")
        else:
            apk_block = (
                '<a class="btn ghost" href="#">安装包未找到 —— 见仓库 dist/ 目录</a>'
            )

        body = PAGE.format(
            pc_name=self.pc_name or "PC",
            config_path=self.config_path or "config.json",
            apk_block=apk_block,
            manual=manual,
            token=self.token or "-",
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path | None, ctype: str, download: bool = False) -> None:
        if path is None or not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # keep the console clean
        pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(
    host: str,
    port: int,
    qr_png: Path | None,
    apk: Path | None,
    payload: str,
    token: str,
    pc_name: str,
    config_path: str = "",
    manual: str = "",
) -> _Server | None:
    handler = type(
        "Handler",
        (_Handler,),
        {
            "qr_png": qr_png,
            "apk": apk,
            "payload": payload,
            "token": token,
            "pc_name": pc_name,
            "config_path": config_path,
            "manual": manual,
        },
    )
    try:
        httpd = _Server((host, port), handler)
    except OSError:
        return None
    threading.Thread(target=httpd.serve_forever, name="phonemic-http", daemon=True).start()
    return httpd
