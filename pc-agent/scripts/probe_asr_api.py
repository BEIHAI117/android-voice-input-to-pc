"""Probe which request shape a "OpenAI-compatible" ASR endpoint actually wants.

Providers routinely expose a model like `mimo-v2.5-asr` while implementing the
route differently from OpenAI's /audio/transcriptions. This tries each plausible
shape and prints the status + body so the right one can be picked.

    python scripts/probe_asr_api.py --wav test_speech.wav \
        --base https://token-plan-cn.xiaomimimo.com/v1 --model mimo-v2.5-asr
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def send(url: str, key: str, body: bytes | None, headers: dict, timeout: int = 120):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")[:600]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:600]
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def multipart(fields: list[tuple[str, str]], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields:
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    for name, filename, data, ctype in files:
        out += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wav", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--model", default="mimo-v2.5-asr")
    p.add_argument("--language", default="zh")
    args = p.parse_args()

    wav = Path(args.wav).read_bytes()
    b64 = base64.b64encode(wav).decode()
    base = args.base.rstrip("/")
    auth = {"Authorization": f"Bearer {args.key}"}
    json_hdr = {"Content-Type": "application/json", **auth}

    cases: list[tuple[str, str, bytes | None, dict]] = []

    # 1. OpenAI /audio/transcriptions (multipart)
    body, ctype = multipart(
        [("model", args.model), ("language", args.language), ("response_format", "json")],
        [("file", "audio.wav", wav, "audio/wav")],
    )
    cases.append(("POST /audio/transcriptions (multipart)", f"{base}/audio/transcriptions", body, {**auth, "Content-Type": ctype}))

    # 2. chat/completions with input_audio content
    cases.append((
        "POST /chat/completions {input_audio}",
        f"{base}/chat/completions",
        json.dumps({
            "model": args.model,
            "messages": [{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}
            ]}],
        }).encode(),
        json_hdr,
    ))

    # 3. chat/completions with a text instruction + input_audio
    cases.append((
        "POST /chat/completions {text + input_audio}",
        f"{base}/chat/completions",
        json.dumps({
            "model": args.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "把这段音频转成文字，只输出转写结果。"},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
            ]}],
        }).encode(),
        json_hdr,
    ))

    # 4. chat/completions with audio_url data URI
    cases.append((
        "POST /chat/completions {audio_url data-uri}",
        f"{base}/chat/completions",
        json.dumps({
            "model": args.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "转写这段音频。"},
                {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + b64}},
            ]}],
        }).encode(),
        json_hdr,
    ))

    # 5. plain audio field on chat/completions
    cases.append((
        "POST /chat/completions {audio field}",
        f"{base}/chat/completions",
        json.dumps({"model": args.model, "audio": {"data": b64, "format": "wav"},
                    "messages": [{"role": "user", "content": "转写这段音频"}]}).encode(),
        json_hdr,
    ))

    # 6. OpenAI /audio/speech-style probe with base64 json body
    body, ctype = multipart(
        [("model", args.model)],
        [("file", "audio.wav", wav, "audio/wav")],
    )
    cases.append(("POST /audio/transcriptions (no lang)", f"{base}/audio/transcriptions", body, {**auth, "Content-Type": ctype}))

    for name, url, body, headers in cases:
        print(f"\n── {name}")
        print(f"   {url}")
        status, text = send(url, args.key, body, headers)
        print(f"   [{status}] {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
