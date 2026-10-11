# PhoneMic · 手机悬浮球语音输入到电脑

> **长按手机上的悬浮球说话，松手后文字直接落在电脑当前光标处** —— 不用碰键盘，纯局域网直连，不经过任何云端；跨网络也可以走你自己的 VPS 中转。
>
> *Hold a floating ball on your phone, speak, release — the text appears at your PC's caret. Android voice typing to a Windows machine over the LAN, no cloud relay; across networks it goes through your own VPS relay.*

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![platform](https://img.shields.io/badge/platform-Android%20%7C%20Windows-3E7BFF.svg)
![version](https://img.shields.io/badge/version-0.4.0-22a06b.svg)
![protocol](https://img.shields.io/badge/protocol-v1-e2518c.svg)
![language](https://img.shields.io/badge/Kotlin-1F77B4?logo=kotlin&logoColor=white)

---

## English

**PhoneMic** turns your Android phone into a wireless microphone-plus-keyboard for your PC.

- Long-press the overlay ball, dictate, release — the recognised text is injected at the caret on your Windows machine
- Everything travels over your **local network** (WebSocket + token pairing); audio is discarded right after recognition
- **Multiple PCs**: bind several desktops, single-tap the ball to switch which one receives your dictation (its name is printed inside the ball)
- **Cross-network dictation (optional)**: phone and PC both dial out to a tiny relay on your own VPS — dictation works on mobile data or across offices, without a public IP on either side
- Speech recognition: Android's built-in recognizer (default, zero config), any OpenAI-compatible cloud endpoint, or sherpa-onnx offline
- PC side also runs **voice commands** — "截图" → `Win+Shift+S`, "打开记事本" → launch an app, with confirm-before-execution for dangerous `shell` actions

Getting started: run `python -m agent` on the PC, install the APK on the phone, scan the QR, grant three permissions, hold and talk. Full steps below (Chinese).

---

## 为什么做这个

写代码、回消息、记笔记的时候，很多输入其实**用说的比用打的快**，但：

- 手机上的输入法不能往电脑里打字；
- 传统"手机当电脑麦克风"的方案要在电脑上装一堆东西，还要处理采样率、降噪、回声；
- 云端中转的方案，语音要先上传到别人的服务器。

PhoneMic 把这件事拆到最简单：**手机只负责"听懂"，电脑只负责"敲进去"**，中间走你自己家的局域网。

- 手机端：录音 → 识别成文字 → 通过 WebSocket 发出去
- 电脑端：收到文字 → 粘贴 + `Ctrl+V`（或逐字按键）送到当前光标

音频在手机上识别完就丢弃，**不落盘、不上传到作者的任何服务器**（云端识别是你自己选的服务商）。

## 功能特性

| | |
|---|---|
| 🎙️ **悬浮球长按听写** | 长按 0.5 秒开始，松手发送，气泡实时显示中间结果 |
| 🖥️ **多电脑切换** | 一台手机绑定局域网里的多台电脑，**单击悬浮球**循环切换，球内显示当前目标 |
| 📡 **纯局域网直连** | WebSocket + 配对令牌，不经过任何中转服务器 |
| 🌍 **跨网中转（可选）** | 手机与电脑都主动连**你自己 VPS** 上的中转（`vps/`），跨 WiFi / 走流量照样听写；令牌认证仍端到端 |
| 🔌 **三种识别引擎** | 系统识别（默认，零配置）/ 云端识别（OpenAI 兼容，自带 Key）/ sherpa-onnx 离线接入点 |
| 🎯 **注入到光标处** | 默认剪贴板 + `Ctrl+V`（中文最可靠），可切成真实逐字按键（终端 / SSH / vim） |
| 🗣️ **语音命令** | 说"截图""锁屏""打开记事本"直接执行动作，危险命令先在手机上二次确认 |
| 🧩 **断线不丢字** | 没连上时说的话会排队，握手成功自动补发，不会弹"发送失败"就丢掉 |
| 🔒 **令牌鉴权** | 扫码配对（令牌跨重启不变），常量时间比较，已配对设备记录在 `trust.json` |

## 手势速查

| 操作 | 效果 |
|---|---|
| **长按**悬浮球（0.5 秒） | 开始录音，气泡显示"正在聆听…" |
| **松手** | 结束识别，文本发送到当前电脑的光标处 |
| **单击**悬浮球 | 切换到下一台已绑定的电脑（球内名字跟着变） |
| **拖动** | 移动悬浮球 |
| **双击** | 打开设置页 |
| 说"截图""打开记事本"… | 走命令层，执行动作而不是输入文字 |

> 悬浮球固定 **56dp**，电脑名压在图标内部（不会额外占屏幕）；`●` 表示已连上，`○` 表示未连上。

---

## 快速开始

### 0. 你需要准备

- 一台 **Windows** 电脑（跑 PC Agent）+ **Python 3.10+**
- 一台 **Android 8.0+** 手机
- 两者连在**同一个 WiFi**（重要，见排查）
- 手机可以自己编译 APK，也可以直接装 Release 里下载的包

### 1. 电脑端：起 PC Agent

```bash
git clone <this-repo>
cd <repo>/pc-agent
pip install -r requirements.txt
python -m agent
```

或者双击仓库根目录的 `启动PC端.bat`（Windows）。

启动后终端会打出局域网地址，**并自动弹出配对二维码图片**：

```
  PhoneMic PC agent  v1  ·  客厅电脑
  listening on ws://192.168.1.42:8765

  本机名：客厅电脑
    改名：编辑 C:\Users\你\AppData\Local\PhoneMic\config.json 里的 "device_name" 后重启

  ┌──────────────────────────────────────────────────────────┐
  │  手机连上同一个 WiFi，浏览器打开：                        │
  │  http://192.168.1.42:8766                                │
  │  → 可下载安装包 + 二维码                                 │
  └──────────────────────────────────────────────────────────┘
```

> **手机浏览器打开 `http://<电脑IP>:8766>`** 一个网址搞定两件事：下载 APK + 扫配对二维码。不用数据线。

常用参数：

| 参数 | 作用 |
|---|---|
| `--name "书房台式机"` | 电脑名（显示在手机悬浮球上），同时写进 `config.json` |
| `--dry-run` | 不碰键盘/剪贴板，只打印要注入的内容（调试用） |
| `--mode type` | 用真实按键逐字输入（终端 / SSH / vim）。默认 `clipboard` |
| `--encrypt` | 开启 NaCl 端到端加密载荷 |
| `--port 8765` | 改端口（配对网页固定在 `端口+1`） |
| `-v` | 调试日志 |

配置与数据都在 `%LOCALAPPDATA%\PhoneMic\`（`config.json` / `commands.json` / `trust.json` / `agent.log`），详见 [pc-agent/README.md](pc-agent/README.md)。

### 2. 手机端：装 App

**方式 A —— 直接装编译好的**：仓库 `dist/` 目录里有 `PhoneMic-v0.4.0.apk`，传到手机（微信/QQ 发文件、数据线、`adb install` 都行）点击安装。

> 包名 `com.phonemic.app`，versionName 0.4.0 (versionCode 8)，minSdk 26 / targetSdk 35。
> **APK 不内置任何 API Key** —— 默认用系统识别，不需要配置就能用。

**方式 B —— 自己编译**（不需要 Android Studio）：

工具链装在 `D:\android-toolchain`（便携版 JDK 17 + Android SDK 35 + Gradle 8.9）：

```bash
./build-apk.sh           # 有 keystore 就出 release，没有则自动回退成 debug 并提示如何生成
./build-apk.sh debug     # 明确要 debug
```

> 没有签名密钥时脚本不会报错退出，而是回退出一个 **debug APK**（可直接安装，只是用 Android 调试签名）。
> 想要自己的发布签名：`keytool -genkeypair -v -keystore android/phonemic-release.keystore -alias phonemic -keyalg RSA -keysize 2048 -validity 10000`

### 3. 绑定 + 开权限

1. 点 **「扫码绑定电脑」**，扫 PC 端的二维码（也可以用「手动输入地址」）
2. 点 **「权限与后台引导」**，把下面几项打开：
   - **悬浮窗**（悬浮球必须显示在其他应用之上）
   - **麦克风**（长按说话）
   - 后台保活（vivo/OriginOS 见 [docs/OriginOS6-适配清单.md](docs/OriginOS6-适配清单.md)）
3. 点 **「启动悬浮球」**

### 4. 试一句

长按悬浮球 → 说话 → 松手。识别结果应该直接出现在电脑上当前的输入光标处。
连不上就点 **「测试电脑连接」**，它会告诉你差在哪一环。

---

## 多电脑切换（一台手机 ↔ 多台电脑）

每台电脑就是一个独立的 PC Agent 实例，各自跑、各自出一个二维码：

```bash
# 台式机 A
python -m agent --name "台式机A"
# 台式机 B
python -m agent --name "台式机B"
```

手机侧**分别扫两台的二维码**（或手动输入地址），绑定列表在设置页里可见 —— 点选切换、长按删除。

之后**不用再打开设置页**：单击悬浮球即可在电脑之间循环切换，球内名字即时变化，
旧连接断开、对新电脑重新握手，语音只会发到当前这一台。

约定：

- 每台电脑有**各自的配对令牌**，互不通用
- `auth_ok` 会把 PC 端配置的 `device_name` 回填到手机侧，所以改了电脑名重连就会同步
- 切换时**还没发出去的听写会跟着走**，不会因为切了目标就丢字
- 不配置 `device_name` 时默认取主机名，两台机器开箱就能区分

---

## 跨网听写（VPS 中转，可选）

局域网直连要求手机和电脑在同一个 WiFi。想**在外面用流量、跨办公室**继续听写，
可以在自己的 VPS 上跑一个 ~200 行的中转（`vps/relay_server.py`）：

```
手机(任意网络) ──ws/wss──> VPS 中转 <──ws/wss── PC agent(任意网络)
```

- 两端都**主动出站**连接中转：手机、电脑都不需要公网 IP，不用开路由器端口
- 中转只按房间转发 WebSocket 帧，**不解析内容、看不到配对令牌**，令牌认证与
  （可选的）NaCl 加密照旧端到端
- 一台 VPS 可以同时服务多台电脑（每台一个房间 id，由各自的 key 派生）
- 电脑端开启：`python -m agent --relay wss://你的域名:8766`（写进 config.json，
  之后普通启动即生效），二维码自动变成中转地址，手机照常扫码
- 部署步骤见 [vps/部署对接文档.md](vps/部署对接文档.md)（发给 VPS 操作员即可照做）

不配置 `--relay` 时一切照旧（局域网直连），两种模式可共存：同一台电脑在
局域网里走直连，在外面走中转。

---

## 语音识别怎么选

在 App 设置里切换：

| 方式 | 说明 | 需要联网 | 需要配置 |
|---|---|---|---|
| **系统识别**（默认） | Android 自带 `SpeechRecognizer`，vivo 上通常是端侧引擎 | 否 | **无** |
| **云端识别** | 上传 WAV 到任意 OpenAI 兼容端点 | 是 | Base URL + **自己的 API Key** + 模型名 |
| **本地离线识别** | sherpa-onnx，完全离线 | 否 | 需手动接入 AAR + 中文模型 |

> **App 不内置任何 API Key。** 编译进二进制的密钥等同于公开的密钥，
> 所以 `Settings.kt` 里 `DEFAULT_CLOUD_KEY` 恒为空；想用云端识别就在设置页填自己的 Key。
> 没填就切到云端时，App 会在**开始录音之前**提示，而不是让你说完再吃一个 401。
> 云端请求形态（`/audio/transcriptions` 与 `chat/completions + input_audio` 两种方言的自动探测）见
> [docs/语音识别API接入.md](docs/语音识别API接入.md)。

> sherpa-onnx 的 Android 产物不发 Maven Central，只在 GitHub Releases 提供 AAR，
> 必须手动放进 `app/libs/`。为了保证工程能直接编译，这里做成明确报错的桩，而不是假装可用。

## PC 端注入方式

| 模式 | 机制 | 适用 |
|---|---|---|
| `clipboard`（默认） | 复制到剪贴板 + `Ctrl+V`，1.5 秒后恢复原剪贴板 | **中文首选**，所有输入框都可靠 |
| `type` | Win32 `SendInput` + `KEYEVENTF_UNICODE` 逐字输入，支持完整 UTF-16 | 终端、SSH、vim、远控软件里 `Ctrl+V` 被吞的场景 |

## 语音命令（操作电脑，不只是打字）

`%LOCALAPPDATA%\PhoneMic\commands.json` 把语音映射到动作，**最长匹配优先**：

```json
{
  "commands": [
    { "name": "截图",       "match": ["截图"],       "action": {"action": "hotkey", "keys": ["win","shift","s"]} },
    { "name": "锁屏",       "match": ["锁屏"],       "action": {"action": "shell", "cmd": "rundll32.exe user32.dll,LockWorkStation", "confirm": false} },
    { "name": "打开记事本", "match": ["打开记事本"], "action": {"action": "launch", "target": "notepad.exe"} }
  ]
}
```

动作类型：`hotkey` / `launch` / `shell` / `text` / `clipboard`。
`shell` 默认 `confirm: true`，会在**手机端先请求确认**再执行。

可选 **LLM 意图解析**（`agent/llm.py`）：配好 `llm_base_url` + `llm_api_key` 后，
规则表匹配不到的会交给 LLM 解析成同一个动作 schema。默认关闭。

---

## 架构

```
┌──────────── Android ────────────┐          ┌──────────── Windows ───────────┐
│  FloatBallService (前台服务)     │  WebSocket│  agent/server.py              │
│   └ 长按 → AudioRecorder 录音    │ ════════> │   └ auth → text/cmd 分发       │
│   └ ASR: 系统 / 云端 / sherpa    │  ws://    │  agent/inject.py               │
│   └ PcClient: 排队 + 重连 + 切换 │  :8765    │   └ 剪贴板+Ctrl+V / SendInput  │
│   └ 悬浮球显示当前目标电脑名      │           │  agent/commands.py → 动作执行  │
│  Settings: 多电脑列表 + 当前目标  │           │  config.json / trust.json      │
│  （中转模式下 PcClient 连 VPS）   │           │  （--relay 出站连 VPS 中转）    │
└─────────────────────────────────┘           └────────────────────────────────┘
```

- 手机主动连接电脑，电脑不反向连接；ping/pong 保活 20s，断线指数退避重连
- 协议是一帧一条 JSON 文本帧，**[docs/协议.md](docs/协议.md) 是唯一权威**
- 两端实现：`android/.../net/Protocol.kt` ↔ `pc-agent/agent/protocol.py`，改动需同步三处

---

## 排查

**App 里先点「测试电脑连接」**，它会做 TCP + HTTP 探测并给出结论。按命中率排序：

| 现象 | 原因 / 处理 |
|---|---|
| 连接超时 | 手机和电脑**不在同一个 WiFi**（手机很可能走的是流量）；或一个在 5GHz 一个在 2.4GHz、访客网络、路由器开了 AP 隔离 |
| 连接被拒绝 | 电脑上的 PhoneMic 没在运行；或 **Windows 防火墙拦了 python.exe 入站**（放行专用网络即可） |
| 找不到主机 | 配对地址写错了；电脑 IP 变了要重新扫码 |
| 球在但一直 `○` 没连上 | 杀掉 App 重开让它重新握手；确认 PC Agent 窗口还在 |
| 长按没反应 | 悬浮窗权限没给；vivo/OriginOS 还要开后台弹出界面、自启动、电池不限制（[适配清单](docs/OriginOS6-适配清单.md)） |
| 后台没多久就断 | 电池优化把常驻服务杀了；把 PhoneMic 加进白名单并在最近任务里加锁 |
| 云端识别报错 | 设置页没填 API Key（本项目不内置 Key），或 Base URL/模型名不对 |
| 说完了电脑上没字 | 看 PC 端日志 `%LOCALAPPDATA%\PhoneMic\agent.log`，`injected N chars` 说明已经注入，可能是焦点不在你想要的输入框里 |

## 安全与隐私

- 默认**只监听局域网**，不暴露公网；跨网模式走的是你自己的 VPS 中转（两端主动出站，中转看不到明文令牌）
- 配对必须扫码（二维码内含 `IP:PORT` + 配对令牌），令牌用 `hmac.compare_digest` **常量时间**比较
- 已配对设备记在 `trust.json`，可随时删除
- `shell` 类动作默认要手机端**二次确认**
- **音频不落盘**：识别完立即丢弃 PCM
- 端到端加密（NaCl SecretBox，密钥由配对令牌派生）已实现，**默认关闭** —— 两端都验证后再开
- **不内置任何第三方 API Key**

## 已知限制

1. **sherpa-onnx 未接入** —— 是一个明确报错的接入点（需手动放 AAR + 中文模型）
2. **端到端加密默认关闭**
3. **流式上屏未启用** —— 协议里有 `typing` 消息，但默认整句发送（逐句注入会污染撤销栈）
4. **跨网中转需要自备一台 VPS** —— 见 `vps/`，手机与电脑各自主动出站，无需公网 IP
5. **PC Agent 仅 Windows** —— 注入引擎已抽象，macOS/Linux 用 enigo 重写即可
6. **手机端 UI/权限适配以 vivo OriginOS 6 为主**，其它机型未逐一实测

## 项目结构

```
Phone_mic/
├─ dist/                编译好的 APK（直接装）
├─ android/             Android App（Kotlin：悬浮球 + 录音 + 识别 + 传输）
├─ pc-agent/            PC Agent（Python：WebSocket 服务 + 注入引擎 + 命令层）
├─ vps/                 跨网中转服务器 + 自检脚本 + 部署对接文档（部署到你自己的 VPS）
├─ build-apk.sh         命令行重新编译 APK（不需要 Android Studio）
├─ 启动PC端.bat          Windows 一键启动 PC Agent
└─ docs/
   ├─ 协议.md                  手机 ↔ 电脑通信协议（唯一权威）
   ├─ 语音识别API接入.md        云端识别的两种请求形态与实测规则
   ├─ OriginOS6-适配清单.md     vivo 上必须手动开的开关
   ├─ 异常退出影响分析.md
   ├─ 模拟器调试报告.md         端到端验收记录
   ├─ 方案-v0.1-架构调研.md     开源项目调研 + 架构提案
   └─ （协议.md §8）中转端点与配对格式
```

## 验证结果（本机实测）

| 测试 | 结果 |
|---|---|
| 协议：auth / text / cmd / ping | ✅ 5 项全过 |
| 非法令牌必须被拒 | ✅ `auth_fail` |
| 加密往返 + 错误密钥必须拒绝 | ✅ |
| **真实注入**（记事本当靶子，WM_GETTEXT 读回） | ✅ 3/3 全过，剪贴板与逐字模式均正确落地（含中文） |
| **多电脑切换**（同机两份 agent，8775/8785） | ✅ 两次单击，两端日志同秒交替断开/连接并认证 |
| 悬浮球窗口尺寸 | ✅ 精确 56dp×56dp，电脑名在圆内、无外溢 |

复现：

```bash
cd pc-agent
python scripts/mock_phone.py --token <令牌> --text "你好，世界"
python scripts/test_inject_real.py        # 需在真实桌面会话运行
```

模拟器测不了的部分（需要真机验证）：真实语音识别质量、vivo/OriginOS 后台白名单、
局域网直连（模拟器走 NAT）、电池优化对常驻服务的影响。

## License

[MIT](LICENSE) © BEIHAI117

欢迎提 Issue / PR。协议改动请同时更新 `docs/协议.md` 与两端实现。
