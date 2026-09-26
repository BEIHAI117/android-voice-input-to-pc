package com.phonemic.app

import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.doAfterTextChanged
import com.google.zxing.integration.android.IntentIntegrator
import com.phonemic.app.data.Settings
import com.phonemic.app.databinding.ActivityMainBinding
import com.phonemic.app.overlay.FloatBallService
import com.phonemic.app.pair.Pairing
import com.phonemic.app.util.Permissions

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var settings: Settings

    /**
     * Keeping the listener in a field lets refreshUi() detach it while syncing
     * widget state. Without that, setting isChecked programmatically fires the
     * listener and writes a stale/garbage engine name back into Settings — which
     * is why the engine kept reverting to "system".
     */
    private val asrCheckedListener =
        android.widget.RadioGroup.OnCheckedChangeListener { _, checkedId ->
            val value = when (checkedId) {
                R.id.rbAsrCloud -> Settings.ASR_CLOUD
                R.id.rbAsrSherpa -> Settings.ASR_SHERPA
                else -> Settings.ASR_SYSTEM
            }
            settings.asrEngine = value
            android.util.Log.i(TAG, "ASR selected -> $value (checkedId=$checkedId)")
        }

    private val overlayPermission =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
            refreshUi()
        }

    private val runtimePermission =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            refreshUi()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        settings = Settings(this)

        binding.btnPair.setOnClickListener { scanQr() }
        binding.btnManualPair.setOnClickListener { manualPair() }
        binding.btnPermission.setOnClickListener { showPermissionGuide() }
        binding.btnToggleBall.setOnClickListener { toggleBall() }
        binding.btnTest.setOnClickListener { runConnectivityTest() }

        binding.rgAsr.setOnCheckedChangeListener(asrCheckedListener)

        // Save on every change rather than on focus loss: a focus listener is
        // unreliable here (TextInputEditText inside TextInputLayout often
        // never reports the change, so the value silently never persisted).
        binding.etApiBase.doAfterTextChanged { settings.cloudBaseUrl = it?.toString().orEmpty() }
        binding.etApiModel.doAfterTextChanged {
            val value = it?.toString().orEmpty()
            settings.cloudModel = value
            // Model changed -> the endpoint's request shape may change too.
            com.phonemic.app.asr.CloudAsrEngine.resetStyleCache()
        }
        binding.etApiKey.doAfterTextChanged { settings.cloudApiKey = it?.toString().orEmpty() }
    }

    override fun onResume() {
        super.onResume()
        refreshUi()
    }

    // --------------------------------------------------------------- UI ----

    private fun refreshUi() {
        android.util.Log.i(
            TAG,
            "refreshUi: asrEngine=${settings.asrEngine} cloudBase='${settings.cloudBaseUrl}' " +
                "cloudKey=${if (settings.cloudApiKey.isEmpty()) "empty" else "set"}"
        )
        binding.tvPairState.text =
            if (settings.isPaired) getString(R.string.label_paired_pc, settings.pcName.ifEmpty { settings.pcEndpoint })
            else getString(R.string.label_not_paired)

        val running = FloatBallRunning
        binding.btnToggleBall.setText(
            if (running) R.string.btn_stop_ball else R.string.btn_start_ball,
        )

        // Detach while syncing so the assignments below cannot write back into
        // Settings through the change listener.
        binding.rgAsr.setOnCheckedChangeListener(null)
        binding.rbAsrSystem.isChecked = settings.asrEngine == Settings.ASR_SYSTEM
        binding.rbAsrCloud.isChecked = settings.asrEngine == Settings.ASR_CLOUD
        binding.rbAsrSherpa.isChecked = settings.asrEngine == Settings.ASR_SHERPA
        binding.rgAsr.setOnCheckedChangeListener(asrCheckedListener)
        if (binding.etApiBase.text.isNullOrEmpty()) binding.etApiBase.setText(settings.cloudBaseUrl)
        if (binding.etApiModel.text.isNullOrEmpty()) binding.etApiModel.setText(settings.cloudModel)
        if (binding.etApiKey.text.isNullOrEmpty()) binding.etApiKey.setText(settings.cloudApiKey)
    }

    private fun toggleBall() {
        if (FloatBallRunning) {
            FloatBallService.stop(this)
            FloatBallRunning = false
            refreshUi()
            return
        }

        if (!settings.isPaired) {
            Toast.makeText(this, R.string.hint_no_paired_pc, Toast.LENGTH_LONG).show()
            scanQr()
            return
        }
        if (!Permissions.hasOverlay(this)) {
            Toast.makeText(this, R.string.perm_overlay_title, Toast.LENGTH_LONG).show()
            overlayPermission.launch(Permissions.overlaySettingsIntent(this))
            return
        }
        if (!Permissions.hasAudio(this)) {
            runtimePermission.launch(arrayOf(android.Manifest.permission.RECORD_AUDIO))
            return
        }
        if (!Permissions.hasNotifications(this)) {
            runtimePermission.launch(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS))
            return
        }

        FloatBallService.start(this)
        FloatBallRunning = true
        refreshUi()
        Toast.makeText(this, R.string.notif_text, Toast.LENGTH_SHORT).show()
    }

    // ----------------------------------------------------------- pairing ---

    private fun scanQr() {
        IntentIntegrator(this)
            .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
            .setPrompt("扫描电脑端 PhoneMic 显示的二维码")
            .setBeepEnabled(false)
            .initiateScan()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (result != null && result.contents != null) {
            acceptPairing(result.contents)
            return
        }
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
    }

    private fun manualPair() {
        val input = android.widget.EditText(this).apply {
            hint = "192.168.1.3:8765?t=配对令牌"
            setSingleLine(true)
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.btn_manual_pair)
            .setView(input)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                acceptPairing(input.text?.toString().orEmpty())
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun acceptPairing(raw: String) {
        val payload = Pairing.parse(raw)
        if (payload == null || payload.token.isEmpty()) {
            Toast.makeText(this, "无法识别的配对信息", Toast.LENGTH_LONG).show()
            return
        }
        settings.pcEndpoint = payload.wsUrl
        settings.token = payload.token
        settings.pcName = payload.wsUrl
        Toast.makeText(this, "已绑定 ${payload.wsUrl}", Toast.LENGTH_LONG).show()
        refreshUi()
    }

    // ------------------------------------------------------- diagnostics ---

    /**
     * Answers "why can't the phone reach the PC" without guessing. Does a raw
     * TCP connect to the agent port plus an HTTP fetch of the setup page, then
     * spells out the likely cause.
     */
    private fun runConnectivityTest() {
        val endpoint = settings.pcEndpoint
        if (endpoint.isEmpty()) {
            showDiag("还没有绑定电脑。请先点「扫码绑定电脑」。")
            return
        }
        val uri = android.net.Uri.parse(endpoint)
        val host = uri.host ?: run {
            showDiag("配对地址无效：$endpoint")
            return
        }
        val port = uri.port.takeIf { it > 0 } ?: 8765

        showDiag("正在测试 $host:$port …")
        Thread {
            val sb = StringBuilder()
            sb.appendLine("目标：$host:$port")
            sb.appendLine("本机 IP：${localIpAddress()}")

            val tcp = tcpProbe(host, port)
            sb.appendLine("TCP $host:$port → ${tcp.first}${tcp.second?.let { "（$it ms）" } ?: ""}")
            sb.appendLine("网页 http://$host:${port + 1}/ → ${httpProbe(host, port + 1)}")
            sb.appendLine()
            if (tcp.first.startsWith("通")) {
                sb.appendLine("✅ 网络是通的。如果悬浮球仍提示未连接，")
                sb.appendLine("   请把 App 杀掉重开（让它重新握手）。")
            } else {
                sb.appendLine("❌ 网络不通。按可能性从高到低排查：")
                sb.appendLine("1. 手机和电脑不在同一个 WiFi")
                sb.appendLine("   （你现在可能走的是移动流量）")
                sb.appendLine("2. 两个 WiFi 不是同一频段/访客网络，路由器开了 AP 隔离")
                sb.appendLine("3. 电脑上的 PhoneMic 没在运行")
                sb.appendLine("4. Windows 防火墙拦了 python.exe 入站")
            }
            runOnUiThread { showDiag(sb.toString()) }
        }.start()
    }

    private fun tcpProbe(host: String, port: Int): Pair<String, Long?> {
        return try {
            val t0 = System.currentTimeMillis()
            java.net.Socket().use { s ->
                s.connect(java.net.InetSocketAddress(host, port), 4000)
                val dt = System.currentTimeMillis() - t0
                "通" to dt
            }
        } catch (e: Exception) {
            val reason = when (e) {
                is java.net.SocketTimeoutException -> "超时（4 秒无响应）"
                is java.net.ConnectException -> "被拒绝 / 不可达"
                is java.net.UnknownHostException -> "找不到主机（DNS 解析失败）"
                else -> e.javaClass.simpleName + ": " + (e.message ?: "")
            }
            reason to null
        }
    }

    private fun httpProbe(host: String, port: Int): String {
        return try {
            val url = java.net.URL("http://$host:$port/")
            val conn = url.openConnection().apply {
                connectTimeout = 4000
                readTimeout = 4000
            }
            conn.getInputStream().use {
                "通（${it.readBytes().size} 字节）"
            }
        } catch (e: Exception) {
            "不通（${e.javaClass.simpleName}）"
        }
    }

    private fun localIpAddress(): String = try {
        java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())
            .flatMap { it.inetAddresses.toList() }
            .firstOrNull { !it.isLoopbackAddress && it is java.net.Inet4Address }
            ?.hostAddress ?: "未知"
    } catch (_: Exception) {
        "未知"
    }

    private fun showDiag(text: String) = runOnUiThread {
        binding.tvDiag.visibility = android.view.View.VISIBLE
        binding.tvDiag.text = text
    }

    // --------------------------------------------------------- guidance ----

    private fun showPermissionGuide() {
        AlertDialog.Builder(this)
            .setTitle(R.string.vivo_bg_title)
            .setMessage(R.string.vivo_bg_body)
            .setPositiveButton("打开应用设置") { _, _ ->
                startActivity(Permissions.appDetailsIntent(this))
            }
            .setNeutralButton("悬浮窗设置") { _, _ ->
                overlayPermission.launch(Permissions.overlaySettingsIntent(this))
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    companion object {
        private const val TAG = "PhoneMic"

        /** Process-local flag; the service sets it on start/stop. */
        @Volatile
        var FloatBallRunning: Boolean = false
    }
}
