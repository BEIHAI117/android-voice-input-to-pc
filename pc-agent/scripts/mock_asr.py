"""Mock OpenAI-compatible transcription endpoint, for end-to-end testing.

Lets the whole "record -> ASR -> send -> inject" path run without a real
microphone or a paid API key. Point the app's cloud ASR Base URL at this
server and it will always recognise the configured phrase.

    python scripts/mock_asr.py --text "你好，这是来自模拟器的测试" --port 8799
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PHRASE = "你好，这是来自模拟器的测试"


class Handler(BaseHTTPRequestHandler):
    phrase = PHRASE

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        boundary = self.headers.get("Content-Type", "")
        print(f"[mock-asr] POST {self.path}  {len(body)} bytes  {boundary[:60]}")

        if self.path.endswith("/audio/transcriptions"):
            payload = json.dumps({"text": self.phrase}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            print(f"[mock-asr] -> 200 {self.phrase!r}")
        else:
            self.send_error(404)

    def log_message(self, *args) -> None:
        pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8799)
    p.add_argument("--text", default=PHRASE)
    args = p.parse_args()

    Handler.phrase = args.text
    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[mock-asr] listening on 0.0.0.0:{args.port}  phrase={args.text!r}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
