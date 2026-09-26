package com.phonemic.app.net

import android.os.Handler
import android.os.Looper
import android.util.Log
import com.phonemic.app.data.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.ArrayDeque
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Single WebSocket connection to the PC agent.
 *
 * Two things this must get right for the product to feel reliable:
 *
 *  1. **Never lose a dictation.** If the user speaks before the socket is up,
 *     the text is queued and flushed on connect instead of being dropped with
 *     a "not connected" toast.
 *  2. **Say why** it is not connected. "电脑未连接" is useless when the real
 *     cause is "the phone is on mobile data" or "the PC is on the 5 GHz SSID
 *     and this phone is on the 2.4 GHz one".
 */
class PcClient(
    private val settings: Settings,
    private val listener: Listener,
) {

    enum class State { IDLE, CONNECTING, CONNECTED, FAILED }

    interface Listener {
        fun onStateChanged(state: State, detail: String)
        fun onAck(seq: Int, ok: Boolean, mode: String, chars: Int)
        fun onCommandResult(seq: Int, ok: Boolean, detail: String, needsConfirm: Boolean)
    }

    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .connectTimeout(8, TimeUnit.SECONDS)
        .build()

    private val seq = AtomicInteger(1)
    private val handler = Handler(Looper.getMainLooper())
    private val pending = ArrayDeque<String>()

    @Volatile private var ws: WebSocket? = null
    @Volatile private var closedByUser = false
    @Volatile private var retryAttempt = 0
    @Volatile private var state: State = State.IDLE
    @Volatile private var lastError: String = ""

    val isConnected: Boolean get() = state == State.CONNECTED

    @Synchronized
    fun connect() {
        val endpoint = settings.pcEndpoint
        if (endpoint.isEmpty()) {
            transition(State.FAILED, "还没有绑定电脑，请先点「扫码绑定电脑」")
            return
        }
        if (ws != null) return
        closedByUser = false
        transition(State.CONNECTING, "正在连接 $endpoint …")

        val request = Request.Builder().url(endpoint).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                retryAttempt = 0
                webSocket.send(Protocol.auth(settings.deviceId, deviceName(), settings.token))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = Protocol.parse(text) ?: return
                when (msg.optString("t")) {
                    "auth_ok" -> {
                        transition(State.CONNECTED, msg.optString("device_name", "PC"))
                        flushPending()
                    }
                    "auth_fail" -> {
                        closedByUser = true
                        transition(State.FAILED, "配对令牌不匹配，请重新扫码绑定")
                        webSocket.close(1000, "auth failed")
                    }
                    "ack" -> listener.onAck(
                        msg.optInt("seq", -1),
                        msg.optBoolean("ok", false),
                        msg.optString("mode", ""),
                        msg.optInt("chars", 0),
                    )
                    "cmd_result" -> listener.onCommandResult(
                        msg.optInt("seq", -1),
                        msg.optBoolean("ok", false),
                        msg.optString("detail", ""),
                        msg.optBoolean("needs_confirm", false),
                    )
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                ws = null
                if (!closedByUser) {
                    transition(State.FAILED, reason.ifEmpty { "连接已关闭" })
                    scheduleReconnect()
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                ws = null
                Log.w(TAG, "websocket failure: ${t.message}")
                val why = describeFailure(t, settings.pcEndpoint)
                transition(State.FAILED, why)
                if (!closedByUser) scheduleReconnect()
            }
        })
    }

    @Synchronized
    fun disconnect() {
        closedByUser = true
        handler.removeCallbacksAndMessages(null)
        pending.clear()
        ws?.close(1000, "bye")
        ws = null
        transition(State.IDLE, "")
    }

    /** Send dictation. Queues it if the socket is still coming up. */
    fun sendText(text: String) {
        val socket = ws
        if (socket != null && state == State.CONNECTED) {
            socket.send(Protocol.text(nextSeq(), text))
            return
        }
        // Not up yet — keep it and send as soon as auth_ok arrives.
        synchronized(pending) { pending.addLast(Protocol.text(nextSeq(), text)) }
        if (state != State.CONNECTING) connect()
    }

    fun sendCommand(speech: String) {
        val socket = ws
        if (socket != null && state == State.CONNECTED) {
            socket.send(Protocol.cmd(nextSeq(), speech))
        } else {
            synchronized(pending) { pending.addLast(Protocol.cmd(nextSeq(), speech)) }
            if (state != State.CONNECTING) connect()
        }
    }

    private fun flushPending() {
        val socket = ws ?: return
        val batch = synchronized(pending) {
            val copy = pending.toList()
            pending.clear()
            copy
        }
        for (msg in batch) socket.send(msg)
        if (batch.isNotEmpty()) Log.i(TAG, "flushed ${batch.size} queued message(s)")
    }

    private fun nextSeq(): Int = seq.getAndIncrement()

    private fun transition(newState: State, detail: String) {
        state = newState
        if (newState == State.FAILED) lastError = detail
        handler.post { listener.onStateChanged(newState, detail) }
    }

    private fun scheduleReconnect() {
        if (closedByUser) return
        retryAttempt++
        val delayMs = (1_000L shl minOf(retryAttempt, 5)).coerceAtMost(30_000L)
        handler.postDelayed({
            if (!closedByUser && ws == null) connect()
        }, delayMs)
    }

    /**
     * Turn an OkHttp/IO failure into something the user can act on. The single
     * most common cause of "电脑未连接" is the phone and the PC being on
     * different networks, so say that out loud.
     */
    private fun describeFailure(t: Throwable, endpoint: String): String {
        val msg = t.message.orEmpty()
        return when {
            msg.contains("timeout", true) ->
                "连接超时（$endpoint）\n请确认手机和电脑连的是同一个 WiFi"
            msg.contains("failed to connect", true) ||
                msg.contains("connect", true) && msg.contains("refused", true) ->
                "连不上 $endpoint\n请确认电脑上的 PhoneMic 正在运行，且手机与电脑在同一 WiFi"
            msg.contains("unreachable", true) ||
                msg.contains("ENETUNREACH", true) ||
                msg.contains("EHOSTUNREACH", true) ->
                "网络不可达\n手机当前可能没连 WiFi（走的是流量），请连上和电脑同一个 WiFi"
            msg.contains("unable to resolve", true) ||
                msg.contains("UnknownHost", true) ->
                "找不到主机 $endpoint\n请检查配对信息是否正确"
            else -> "连接失败：${msg.ifEmpty { t.javaClass.simpleName }}"
        }
    }

    private fun deviceName(): String =
        "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim()

    companion object {
        private const val TAG = "PcClient"
    }
}
