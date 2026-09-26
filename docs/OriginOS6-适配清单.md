# OriginOS 6 / vivo 适配清单

悬浮球类 App 在国产 ROM 上被杀、不弹、不录音，九成问题出在下面这些**必须手动打开的开关**上。
没有公开 API，只能引导用户去点。App 里「权限与后台引导」按钮会跳到应用详情页。

> 同类问题在 MIUI / ColorOS / 鸿蒙上也存在，开关名字不同。建议做成厂商策略表，首发只做 vivo。

---

## 一、必开开关（缺一个就废）

| # | 开关 | 路径（OriginOS 6 大致位置） | 不开的后果 |
|---|---|---|---|
| 1 | **悬浮窗** | 设置 → 应用与权限 → 权限管理 → PhoneMic → 悬浮窗 | 悬浮球根本显示不出来 |
| 2 | **后台弹出界面** | 设置 → 应用与权限 → 权限管理 → PhoneMic → 后台弹出界面 | **后台无法弹出悬浮球**，锁屏/切后台后长按无效 |
| 3 | **自启动** | 设置 → 应用与权限 → 自启动 → PhoneMic | 重启或被杀后不自动拉起 |
| 4 | **关联启动** | 同上目录下 | 被其他应用拉起时受限 |
| 5 | **后台耗电不受限** | 设置 → 电池 → 后台耗电管理 → PhoneMic → 不限制 / 允许后台高耗电 | 深度休眠后 WebSocket 断连、录音被切断 |
| 6 | **最近任务加锁** | 最近任务列表 → 长按 PhoneMic 卡片 → 加锁 | 一键清理直接杀掉服务 |

## 二、权限

| 权限 | 何时要 | 说明 |
|---|---|---|
| `SYSTEM_ALERT_WINDOW` | 启动悬浮球前 | 代码里 `Settings.canDrawOverlays()` 检测，未授权跳 `ACTION_MANAGE_OVERLAY_PERMISSION` |
| `RECORD_AUDIO` | 第一次长按时 | 运行时申请 |
| `POST_NOTIFICATIONS` | Android 13+ | 常驻前台服务通知，不给则服务无法常驻 |
| `FOREGROUND_SERVICE` / `FOREGROUND_SERVICE_MICROPHONE` | Android 14+ | manifest 已声明，`foregroundServiceType="microphone"` |
| `RECEIVE_BOOT_COMPLETED` | 开机自启 | 已声明 |

## 三、锁屏 / 息屏

- 悬浮球默认**不显示在锁屏之上**（`FLAG_NOT_FOCUSABLE` 且未开 `FLAG_SHOW_WHEN_LOCKED`）
- 息屏后长按无效是预期行为；录音也不会在息屏时进行
- 若需要锁屏可用，可在 `FloatBallService` 的 `ballParams` 加 `FLAG_SHOW_WHEN_LOCKED`，但会带来误触与隐私风险，**默认不开**

## 四、可能屏蔽悬浮球的场景

| 场景 | 表现 | 兜底 |
|---|---|---|
| 游戏模式 / 电竞模式 | 悬浮球被隐藏 | 通知栏里点「停止/启动悬浮球」 |
| 小窗模式 | 悬浮球层级异常 | 同上 |
| 省电模式 | 服务被限流 | 引导关闭省电模式 |
| 隐私遮挡（输入密码时） | 系统自动隐藏所有悬浮窗 | 系统行为，无需处理 |

## 五、诊断建议

真机上按这个顺序排查：

1. `adb shell dumpsys activity services com.phonemic.app` —— 服务是否还活着
2. `adb logcat -s PcClient FloatBallService` —— WebSocket 是否在重连
3. 设置里逐项核对上面 6 个开关（ROM 升级后**可能被重置**）
4. 若只有息屏后失效 → 大概率是开关 5（后台耗电）
5. 若完全不显示 → 开关 1 / 2

## 六、代码里已做的自保措施

- 前台服务 + 常驻通知（`startForeground`）
- WebSocket 断线指数退避自动重连（1 s → 30 s 封顶）
- `onStartCommand` 返回 `START_STICKY`，被杀后系统会重建
- 通知上带「停止悬浮球」动作，避免用户只能靠强停
- `BootReceiver` 开机自启（仅在已配对 + 已有悬浮窗权限时才拉起，不弹窗）
