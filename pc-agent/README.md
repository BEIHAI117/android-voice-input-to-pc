# PhoneMic PC Agent

接收手机发来的识别文本，注入到当前输入光标处。

## 安装与运行

```bash
pip install -r requirements.txt
python -m agent
```

启动后终端会显示局域网地址，**并自动弹出二维码图片**：

```
listening on ws://192.168.1.3:8765

  ┌────────────────────────────────────────────────┐
  │  手机连上同一个 WiFi，浏览器打开：                │
  │  http://192.168.1.3:8766                        │
  │  → 可下载安装包 + 二维码                         │
  └────────────────────────────────────────────────┘
```

**手机浏览器打开 `http://<电脑IP>:8766`** 是最快的路径：那个页面上既有可下载的
PhoneMic 安装包，也有可扫描的二维码图片，还有扫不了码时可以手动输入的地址。

> 为什么不直接扫终端里的二维码？终端字符是 2:1 竖长的，渲染出来会被拉变形。
> 所以这里自己用半块字符（`▀█▄`）按 2:1 反向压缩以求近似正方形，但不同字体、
> 不同缩放下仍可能失真。**真正可靠的是自动弹出的 PNG 图片和网页上的图**。

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--dry-run` | 只打印要注入的内容，完全不动键盘和剪贴板 |
| `--mode clipboard\|type` | 注入方式。`clipboard` = 剪贴板 + Ctrl+V（默认，中文可靠）；`type` = 真实按键逐字输入 |
| `--encrypt` / `--no-encrypt` | 载荷加密开关（默认关） |
| `--host` / `--port` | 监听地址 / 端口（默认 `0.0.0.0:8765`） |
| `--name` | 显示在手机上的设备名 |
| `--relay wss://…` | **跨网中转**：出站连 VPS 上的中转服务器（如 `wss://relay.example.com:8766`），二维码自动变为中转地址；留空 = 纯局域网。部署见 [vps/部署对接文档.md](../vps/部署对接文档.md) |
| `--relay-key` | 中转房间密钥（默认自动生成并保存在 config.json，无需手填） |
| `--no-relay` | 停用中转，回到局域网直连 |
| `-v` | 调试日志 |

## 文件

| 文件 | 作用 |
|---|---|
| `agent/server.py` | WebSocket 服务、鉴权、消息分发 |
| `agent/inject.py` | 注入引擎（剪贴板 / SendInput 逐字） |
| `agent/commands.py` | `commands.json` 规则匹配 + 动作执行 |
| `agent/llm.py` | 可选 LLM 意图解析（需配置 Base URL） |
| `agent/protocol.py` | 协议编解码 + NaCl 加密 |
| `scripts/mock_phone.py` | 模拟手机，无真机时做端到端联调 |
| `scripts/test_inject_real.py` | 真实注入验收测试（开记事本当靶子） |

## 配置文件

存在 `%LOCALAPPDATA%\PhoneMic\`：

| 文件 | 作用 |
|---|---|
| `config.json` | 端口、**电脑显示名 `device_name`**、注入模式、配对令牌（跨重启保留，二维码不变） |
| `commands.json` | 语音 → 动作映射，首次运行从 `commands.example.json` 复制 |
| `trust.json` | 已配对设备 |
| `pairing-qr.png` | 配对二维码图片 |

### 电脑叫什么名字

手机悬浮球上显示的就是这个名字。改法两选一：

```bash
# 1) 持久：改 config.json 里的 device_name 后重启
#    %LOCALAPPDATA%\PhoneMic\config.json  →  "device_name": "客厅电脑"

# 2) 临时：启动时加参数（会写回 config.json）
python -m agent --name "书房台式机"
```

**不配置时默认取电脑的主机名**，所以同一局域网里的两台机器开箱就能区分。
多台电脑 = 各自跑一份 agent、各自出一个二维码，手机扫码绑定多次，
**单击悬浮球**即可在它们之间切换（见根目录 README「多电脑切换」）。

## 注入方式怎么选

- **中文、绝大多数输入框** → `clipboard`。它是剪贴板 + `Ctrl+V`，对任何语言都可靠，注入后 1.5 秒自动恢复你原来的剪贴板内容。
- **终端 / SSH / vim / 远程桌面** → `type`。这些地方 `Ctrl+V` 会被吞掉或有别的含义，所以要用 Win32 `SendInput` + `KEYEVENTF_UNICODE` 真的敲键。实测对中文、emoji、生僻字都正确。

可以随时 `--mode` 切换，也可以在协议里按次指定（`text` 消息带 `mode` 字段）。

## 测试

```bash
# 协议联调（先起 agent，再用 mock 手机打）
python -m agent --dry-run
python scripts/mock_phone.py --token <令牌> --text "你好，世界"
python scripts/mock_phone.py --token <令牌> --cmd "截图"

# 真实注入验收（会开一个记事本当靶子，跑完自动关）
python scripts/test_inject_real.py
```

> `test_inject_real.py` 需要在**真实桌面会话**里跑，并且进程完整性级别不能低于目标窗口，
> 否则 Windows UIPI 会静默丢弃合成按键。

## LLM 意图解析（可选）

默认关闭。配置后，`commands.json` 匹配不到的语音会交给 LLM 解析成同一个动作 schema：

```python
# %LOCALAPPDATA%\PhoneMic\config.json
{
  "llm_base_url": "https://api.openai.com/v1",
  "llm_api_key": "sk-...",
  "llm_model": "gpt-4o-mini"
}
```

任何 OpenAI 兼容端点都行（DeepSeek / Ollama / vLLM …）。只用标准库 `urllib`，无额外依赖。

## 安全注意

- 默认只监听局域网。**不要**把它直接暴露到公网。
- 配对令牌就是全部的凭证，泄露即等于把键盘交出去。令牌在二维码和 `config.json` 里，注意别截图外传。
- `shell` 类动作默认 `confirm: true`，需要手机端二次确认才执行。
- 如果要跨网使用，优先用官方中转方案（`--relay`，部署见 `vps/`），两端主动出站、不开入站端口；中转链路上建议两端同时开 `--encrypt`
