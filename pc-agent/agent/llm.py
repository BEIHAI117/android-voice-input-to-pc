"""Optional L1 layer: map free-form speech to an action using an LLM.

Disabled unless ``llm_base_url`` is configured. Uses an OpenAI-compatible
``/chat/completions`` endpoint (works with OpenAI, DeepSeek, Ollama, vLLM,
anything speaking the same protocol) via urllib so there is no extra
dependency.

The model is constrained to emit exactly one action object from the schema in
agent.commands — the same shapes the rule engine produces — so there is one
executor for both paths.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import Config

SYSTEM_PROMPT = """你是电脑语音助手的意图解析器。把用户的话解析成**一个**动作 JSON，不要输出任何其他内容。

只允许以下 action：
1. {"action":"hotkey","keys":["win","shift","s"]}     键盘快捷键（keys 用小写英文键名）
2. {"action":"launch","target":"..."}                 打开程序/网址（target 用可执行文件名或 URL）
3. {"action":"shell","cmd":"..."}                     执行 shell 命令（Windows）
4. {"action":"text","text":"..."}                     原样输入这段文字
5. {"action":"clipboard","text":"..."}                复制这段文字到剪贴板

如果用户说的只是普通文字内容（要输入到光标处的内容），返回
{"action":"text","text":"<原文>"}。
如果无法解析，返回 {"action":"none"}。
"""


def parse_intent(text: str, cfg: Config, timeout: float = 15.0) -> dict[str, Any] | None:
    if not cfg.llm_base_url:
        return None

    body = {
        "model": cfg.llm_model or "gpt-4o-mini",
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    req = urllib.request.Request(
        cfg.llm_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {cfg.llm_api_key}"} if cfg.llm_api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, OSError):
        return None

    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{"):]
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        action = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    return None if action.get("action") in (None, "none") else action
