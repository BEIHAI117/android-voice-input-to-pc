# PhoneMic · 手机悬浮球 → 电脑光标语音输入

长按手机悬浮球说话，松手后识别结果**直接落到绑定电脑的当前输入光标处**，用于去键盘化输入与简单语音操作电脑。

- 平台：Android（首发适配 vivo **OriginOS 6**）+ Windows PC Agent
- 隐私：默认**纯局域网**，不经过任何云端；音频识别完即丢弃
- 状态：PC Agent 已在本机跑通并验收；Android 端为完整源码，需在 Android Studio 编译

---

## 目录

```
Phone_mic/
├─ dist/               编译好的 APK（直接装）
├─ android/            Android App（Kotlin，悬浮球 + 录音 + 识别 + 传输）
├─ pc-agent/           PC Agent（Python，WebSocket 服务 + 注入引擎 + 命令层）
├─ build-apk.sh        命令行重新编译 APK
├─ docs/
│  ├─ 方案-v0.1-架构调研.md    开源项目调研 + 架构提案
│  ├─ 协议.md                  手机 ↔ 电脑 通信协议
│  └─ OriginOS6-适配清单.md    vivo 上必须手动开的开关
└─ README.md
```

---

## 快速开始

### 1. 起 PC Agent（Windows）

```bash
cd pc-agent
pip install -r requirements.txt
python -m agent
```

启动后终端会打出局域网地址，**同时自动弹出配对二维码图片**：

```
listening on ws://192.168.1.3:8765

  ┌────────────────────────────────────────────────┐
  │  手机连上同一个 WiFi，浏览器打开：                │
  │  http://192.168.1.3:8766                        │
  │  → 可下载安装包 + 二维码                         │
  └────────────────────────────────────────────────┘
```

> **手机浏览器打开 `http://<电脑IP>:8766`** 这一个网址就能搞定两件事：
> 下载 PhoneMic 安装包 + 拿到配对二维码。不用数据线、不用传文件。

常用参数：

| 参数 | 作用 |
|---|---|
| `--dry-run` | 不碰键盘/剪贴板，只打印要注入的内容（调试用） |
| `--mode type` | 用真实按键逐字输入（终端 / SSH / vim 场景）。默认 `clipboard`（剪贴板 + Ctrl+V） |
| `--encrypt` | 开启 NaCl 端到端加密载荷 |
| `--port 8765` | 改端口（配对网页固定在 `端口+1`） |
| `-v` | 调试日志 |

配置与命令表存在 `%LOCALAPPDATA%\PhoneMic\`（`config.json` / `commands.json` / `trust.json`）。

### 2. 安装 Android App

**已经编译好了，直接装：**

```
dist/PhoneMic-v0.2.0.apk
```

传到手机（微信/QQ 发文件、数据线、`adb install` 都行）点击安装即可。
包名 `com.phonemic.app`，versionName 0.2.0 (versionCode 4)，minSdk 26 / targetSdk 35，发布签名（CN=PhoneMic）。

> 相机权限来自扫码配对用的 zxing 库；其余权限见 `docs/OriginOS6-适配清单.md`。

首次启动后的三步：

1. 点「扫码绑定电脑」，扫 PC 端打印的二维码
2. 点「权限与后台引导」，按提示打开 vivo 的几个开关（见下）
3. 点「启动悬浮球」

#### 重新编译（不需要 Android Studio）

工具链装在 `D:\android-toolchain`（便携版 JDK 17 + Android SDK 35 + Gradle 8.9）：

```bash
./build-apk.sh           # release APK → android/app/build/outputs/apk/release/app-release.apk
./build-apk.sh debug     # debug APK
```

签名密钥在 `android/phonemic-release.keystore`，口令 `phonemic`（仅为让 APK 可安装的本地钥匙，不是安全凭证）。

### 3. 用法

| 操作 | 效果 |
|---|---|
| **长按**悬浮球（0.5 秒） | 开始录音，气泡显示"正在聆听…" |
| **松手** | 结束识别，文本发送到电脑光标处 |
| **拖动** | 移动悬浮球 |
| **双击** | 打开设置页 |
| 说"截图""打开记事本"… | 走命令层，执行动作而不是输入文字 |

---

## 三种识别方式

在 App 设置里切换：

| 方式 | 说明 | 需要联网 | 需要配置 |
|---|---|---|---|
| **系统识别**（默认） | 用 Android 自带 `SpeechRecognizer`，vivo 上通常是 Jovi/讯飞的**端侧**引擎 | 否 | 无 |
| **云端识别** | 上传 WAV 到 OpenAI 兼容的 `/audio/transcriptions`（OpenAI / Groq / 自建 Whisper 服务） | 是 | Base URL + API Key |
| **本地离线识别** | sherpa-onnx，完全离线、隐私最好 | 否 | **需手动接入 AAR + 中文模型**，见 `SherpaAsrEngine.kt` 注释 |

> 之所以把 sherpa-onnx 留成接入点：它的 Android 产物**不发 Maven Central**，只在 GitHub Releases
> 提供 AAR，必须手动放进 `app/libs/`。为了保证工程能直接编译，这里先做成明确报错的桩，
> 而不是假装可用。其余两个引擎开箱即用。

---

## PC 端注入方式

| 模式 | 机制 | 适用 |
|---|---|---|
| `clipboard`（默认） | 复制到剪贴板 + `Ctrl+V`，1.5 秒后恢复原剪贴板 | **中文首选**，所有输入框都可靠 |
| `type` | Win32 `SendInput` + `KEYEVENTF_UNICODE` 逐字输入，支持完整 UTF-16（含 emoji/生僻字） | 终端、SSH、vim、远控软件里 `Ctrl+V` 被吞的场景 |

---

## 命令 / 语音操作电脑

`%LOCALAPPDATA%\PhoneMic\commands.json` 把语音映射到动作，**最长匹配优先**：

```json
{
  "commands": [
    { "name": "截图",       "match": ["截图"],         "action": {"action": "hotkey", "keys": ["win","shift","s"]} },
    { "name": "锁屏",       "match": ["锁屏"],         "action": {"action": "shell", "cmd": "rundll32.exe user32.dll,LockWorkStation", "confirm": false} },
    { "name": "打开记事本", "match": ["打开记事本"],   "action": {"action": "launch", "target": "notepad.exe"} }
  ]
}
```

动作类型：`hotkey` / `launch` / `shell` / `text` / `clipboard`。
`shell` 默认 `confirm: true`，会在手机端先请求确认再执行。

可选 **LLM 意图解析**（`agent/llm.py`）：配置 `llm_base_url` + `llm_api_key` 后，
规则表匹配不到的话会交给 LLM 解析成同一个动作 schema。默认关闭。

---

## 安全

- 默认**只监听局域网**，不暴露公网
- 配对必须：手机扫二维码（内含 `IP:PORT` + 配对令牌）才能连上，令牌用 `hmac.compare_digest` 常量时间比较
- 已配对设备记在 `trust.json`
- `shell` 类动作默认要手机端二次确认
- 音频不落盘：识别完立即丢弃 PCM
- 端到端加密（NaCl SecretBox，密钥由配对令牌派生）已实现，**默认关闭**——M0 阶段先保证主链路可用，两端都验证过再开

---

## 验证结果（本机实测）

| 测试 | 结果 |
|---|---|
| 协议：auth / text / cmd / ping | ✅ 5 项全过 |
| 非法令牌必须被拒 | ✅ `auth_fail` |
| 加密往返 + 错误密钥必须拒绝 | ✅ |
| **真实注入**（记事本当靶子，WM_GETTEXT 读回） | ✅ **3/3 全过**，剪贴板模式与逐字模式均正确落地（含中文） |

复现：

```bash
cd pc-agent
python scripts/mock_phone.py --token <令牌> --text "你好，世界"
python scripts/test_inject_real.py        # 需在真实桌面会话运行
```

---

## 已在模拟器上验收

见 [docs/模拟器调试报告.md](docs/模拟器调试报告.md)。**长按悬浮球 → 录音 → 识别 → 送到电脑 → 落在光标处**
的完整闭环已在 Android 15 模拟器上跑通（`RESULT: ALL PASS`），并修掉 6 个 bug，其中 1 个致命：
**Android 9+ 默认禁止明文流量，导致 `ws://` 连接从来建立不起来**——这很可能就是真机上
「电脑未连接」的原因。

模拟器测不了的部分（需要你真机验证）：真实语音识别质量、vivo/OriginOS 后台白名单、
局域网直连（模拟器走 NAT）、电池优化对常驻服务的影响。

## 已知限制 / 待办

1. **sherpa-onnx 未接入**——见上文，是一个明确报错的接入点（需手动放 AAR + 中文模型）
2. **真实语音识别质量未验证**——模拟器无麦克风，识别环节用 mock 替身跑通了链路
3. **端到端加密默认关闭**——代码两端都有，验证后再开
4. **流式上屏未启用**——协议里有 `typing` 消息，但 M0 默认整句发送（逐句注入会污染撤销栈）
5. **跨网使用未做**——当前仅局域网；跨网需加中继隧道与更强鉴权（方案 V2）
6. **仅 Windows PC Agent**——注入引擎已抽象，macOS/Linux 用 enigo 重写即可（方案 V2）
