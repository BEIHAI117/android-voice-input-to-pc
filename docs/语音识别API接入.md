# 语音识别 API 接入 · Xiaomi mimo

已接入并验收。**默认识别引擎是云端识别，开箱即用，无需任何配置。**

## 一、关键发现：它不是 OpenAI 的 audio 接口

服务方说"兼容 OpenAI 接口协议"，但**音频转写根本不走 `/audio/transcriptions`**（404）。
真正的入口是 `chat/completions`，模型直接读 `input_audio`：

```
✅ POST https://token-plan-cn.xiaomimimo.com/v1/chat/completions
{
  "model": "mimo-v2.5-asr",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "input_audio", "input_audio": {"data": "<base64 WAV>", "format": "wav"}}
    ]
  }]
}
→ {"choices":[{"message":{"content":"今天天气不错，我们下午三点开个会讨论一下项目进度。"}}]}
```

网关对请求形态**要求很严**，我逐个踩出来的规则：

| 尝试 | 结果 |
|---|---|
| `POST /audio/transcriptions`（OpenAI 标准） | **404** |
| `chat/completions` + 单个 `input_audio` | ✅ **200，转写完全正确** |
| `chat/completions` + text + `input_audio` | 400 `ASR request must not include text parts; text prompt is injected by the gateway` |
| `chat/completions` + `audio_url`（data URI） | 400 `ASR requires exactly one input_audio part, found: 0` |
| `chat/completions` + 顶层 `audio` 字段 | 400 `ASR request requires a user message with input_audio content` |

即：**必须是一个 `user` 消息、恰好一个 `input_audio`、一个字的 text 都不能带。**

准确率实测（Windows TTS 合成的中文语音）：

```
输入音频："今天天气不错，我们下午三点开个会讨论一下项目进度。"
返回内容："今天天气不错，我们下午三点开个会讨论一下项目进度。"   ← 一字不差
```

## 二、App 端实现

`CloudAsrEngine` 现在**同时支持两种请求形态**，并自动探测：

| 形态 | 路径 | 适用 |
|---|---|---|
| `transcriptions` | `POST {base}/audio/transcriptions` | OpenAI / Groq / 自建 whisper-asr-webservice |
| `chat-audio` | `POST {base}/chat/completions` + `input_audio` | **mimo 网关**、GPT-4o-audio 类 |

`style=auto`（默认）第一次请求时探一下 `/audio/transcriptions`：
返回 **404/405** 就切到 `chat-audio`，其它状态码（401/400/5xx）按真实错误处理、不切换。
结果会缓存，后续请求直接走对的形态。改模型名会重置缓存。

> 想跳过探测，可把 `cloud_style` 设为 `transcriptions` 或 `chat-audio`。

## 三、预置配置（已写入 APK，开箱即用）

| 项 | 值 |
|---|---|
| Base URL | `https://token-plan-cn.xiaomimimo.com/v1` |
| 模型名 | `mimo-v2.5-asr` |
| API Key | `REDACTED` |
| 默认引擎 | 云端识别 |

**⚠️ API Key 是明文编译进 APK 的。** 这是为了你"装上就能用"，但如果要把 APK 发给别人，
请先在设置页里换掉或清空 Key。想改，在 App 设置页直接编辑（Base URL / 模型名 / API Key 三个输入框），
或改 `Settings.kt` 里的 `DEFAULT_CLOUD_*` 常量重新编译。

### 其它可用模型

服务方列出的模型（`GET /v1/models` 实测确认）：

```
mimo-v2.6-pro      mimo-v2.6-flash
mimo-v2.5-pro      mimo-v2.5
mimo-v2.5-asr      ← 当前用于识别
mimo-v2.5-tts      mimo-v2.5-tts-voiceclone
mimo-v2.5-tts-voicedesign
```

换成别的 ASR 模型：设置页「模型名」填对应名字即可。

## 四、验收结果

| 项 | 结果 |
|---|---|
| 请求形态探测 | ✅ `probe: /audio/transcriptions -> 404, using chat-audio` |
| App 调用真实 API 成功 | ✅ `recognised -> ...` |
| WAV 编码正确 | ✅ 10752 samples → 21548 bytes（10752×2 + 44 头，精确） |
| **全链路：长按 → 录音 → mimo API → PC → 记事本光标** | ✅ `read back: '嗯。'` `RESULT: ALL PASS` |
| 识别准确率（真实中文语音） | ✅ 一字不差 |

> 模拟器麦克风是静音，所以端到端那轮 API 返回的是「嗯。」（模型对静音的输出）。
> **准确率是用真实中文语音单独验证的**，不是靠模拟器那一轮。

## 五、接口探测脚本

```bash
cd pc-agent
python scripts/probe_asr_api.py --wav test_speech.wav \
    --base https://token-plan-cn.xiaomimimo.com/v1 \
    --key <你的key> --model mimo-v2.5-asr
```

会把 6 种可能的请求形态各试一遍并打印状态码和响应体，换任何服务方都能用它摸清接口。
