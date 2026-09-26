package com.phonemic.app.overlay

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.TextView
import androidx.core.app.NotificationCompat
import com.phonemic.app.App
import com.phonemic.app.MainActivity
import com.phonemic.app.R
import com.phonemic.app.asr.AsrEngine
import com.phonemic.app.asr.AsrFactory
import com.phonemic.app.data.Settings
import com.phonemic.app.net.PcClient
import com.phonemic.app.util.Permissions
import kotlin.math.abs

/**
 * The floating ball itself.
 *
 * Gestures:
 *   long press (500 ms)  -> start dictation
 *   release              -> stop dictation, send the recognised text to the PC
 *   single tap           -> switch to the next bound computer (name shown below)
 *   double tap           -> open settings
 *   drag                 -> move the ball (cancelled if it becomes a long press)
 *
 * The service is a foreground service with the `microphone` type so it can keep
 * recording while backgrounded — which is the whole point of the product.
 */
class FloatBallService : Service(), PcClient.Listener {

    private lateinit var windowManager: WindowManager
    private lateinit var settings: Settings
    private lateinit var client: PcClient

    /**
     * Recreated for every utterance so that switching the engine in Settings
     * takes effect immediately — binding it in onCreate() would silently keep
     * using whatever was selected when the ball was started.
     */
    private var asr: AsrEngine? = null

    private var ballView: View? = null
    private var panelView: TextView? = null
    private var ballParams: WindowManager.LayoutParams? = null
    /** Shows which computer the next dictation goes to. */
    private var pcLabel: TextView? = null

    private val main = Handler(Looper.getMainLooper())
    private var listening = false
    private var dragStartX = 0
    private var dragStartY = 0
    private var paramStartX = 0
    private var paramStartY = 0
    private var dragging = false
    private var lastTapAt = 0L

    private val longPressRunnable = Runnable { startDictation() }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        windowManager = getSystemService(WindowManager::class.java)
        settings = Settings(this)
        client = PcClient(settings, this)
        if (!promoteToForeground()) {
            // startForeground() must succeed within ~5s of startForegroundService;
            // giving up cleanly is better than taking the whole app down.
            stopSelf()
            return
        }
        addBall()
        client.connect()
    }

    /**
     * Promote to a foreground service using a type we are actually allowed to
     * use right now.
     *
     * A `microphone` foreground service is rejected outright (and crashes the
     * app) whenever RECORD_AUDIO is missing — including after the user revokes
     * it later and the system restarts this service. In that case the ball
     * still has value (connection status, sending queued text), so fall back to
     * the `specialUse` type instead of dying.
     */
    private fun promoteToForeground(): Boolean {
        val notification = buildNotification()
        return try {
            if (Permissions.hasAudio(this)) {
                startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            } else {
                Log.w(TAG, "RECORD_AUDIO not granted — running without microphone FGS type")
                startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            }
            true
        } catch (e: SecurityException) {
            Log.e(TAG, "startForeground rejected: ${e.message}")
            try {
                startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
                true
            } catch (e2: Exception) {
                Log.e(TAG, "fallback startForeground failed: ${e2.message}")
                false
            }
        } catch (e: Exception) {
            Log.e(TAG, "startForeground failed: ${e.message}")
            false
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
            // Settings changed the active computer (or re-scanned one) while
            // the ball was up — rebuild the connection against it.
            ACTION_RECONNECT -> {
                client.switchTarget()
                refreshBallLabel()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        asr?.let { runCatching { it.cancel(); it.close() } }
        asr = null
        client.disconnect()
        removeBall()
        super.onDestroy()
    }

    // ------------------------------------------------------------ overlay ---

    private fun addBall() {
        // Fixed 56dp window: the computer name lives inside the circle, so the
        // ball never occupies more of the screen than the bare icon did.
        val size = dp(56)
        val params = WindowManager.LayoutParams(
            size,
            size,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else
                @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 24
            y = dp(220)
        }

        val ball = LayoutInflater.from(this).inflate(R.layout.view_ball, null)
        ball.setOnTouchListener(BallTouchHandler())
        windowManager.addView(ball, params)
        ballView = ball
        ballParams = params
        pcLabel = ball.findViewById(R.id.tvPcLabel)
        refreshBallLabel()

        val panel = TextView(this).apply {
            setBackgroundResource(R.drawable.bg_panel)
            setTextColor(0xFFFFFFFF.toInt())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            visibility = View.GONE
        }
        val panelParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            params.type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = params.x + dp(56) + dp(12)
            y = params.y
        }
        windowManager.addView(panel, panelParams)
        panelView = panel
    }

    private fun removeBall() {
        ballView?.let { runCatching { windowManager.removeView(it) } }
        panelView?.let { runCatching { windowManager.removeView(it) } }
        ballView = null
        panelView = null
        pcLabel = null
    }

    /**
     * Keeps the message panel beside the ball no matter how wide the name
     * label gets, and flips it to the left side near the screen edge instead
     * of letting it run off-screen.
     */
    private fun updatePanelPosition() {
        val p = ballParams ?: return
        val panel = panelView ?: return
        val lp = panel.layoutParams as WindowManager.LayoutParams
        val ballWidth = ballView?.width?.takeIf { it > 0 } ?: dp(56)

        panel.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val panelWidth = panel.measuredWidth
        val screenW = resources.displayMetrics.widthPixels
        val rightX = p.x + ballWidth + dp(12)
        lp.x = if (rightX + panelWidth <= screenW - dp(8)) {
            rightX
        } else {
            (p.x - panelWidth - dp(12)).coerceAtLeast(dp(8))
        }
        lp.y = p.y
        runCatching { windowManager.updateViewLayout(panel, lp) }
    }

    /**
     * Redraw the computer name inside the ball. The filled/hollow dot doubles
     * as the connection state, and the same string becomes the accessibility
     * description so screen readers hear which PC is targeted.
     */
    private fun refreshBallLabel() {
        val label = pcLabel ?: return
        val pc = settings.activePc
        val connected = client.isConnected
        if (pc == null) {
            label.text = getString(R.string.label_no_pc)
            label.alpha = 0.6f
            ballView?.contentDescription = getString(R.string.ball_desc)
            return
        }
        label.text = if (connected) "● ${pc.name}" else "○ ${pc.name}"
        label.alpha = if (connected) 1f else 0.7f
        ballView?.contentDescription =
            getString(R.string.ball_desc_with_pc, pc.name, if (connected) "已连接" else "未连接")
    }

    // ----------------------------------------------------------- gestures ---

    private inner class BallTouchHandler : View.OnTouchListener {
        override fun onTouch(v: View, event: MotionEvent): Boolean {
            val params = ballParams ?: return false
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    dragStartX = event.rawX.toInt()
                    dragStartY = event.rawY.toInt()
                    paramStartX = params.x
                    paramStartY = params.y
                    dragging = false
                    if (!listening) main.postDelayed(longPressRunnable, LONG_PRESS_MS)
                    return true
                }

                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX.toInt() - dragStartX
                    val dy = event.rawY.toInt() - dragStartY
                    if (!dragging && (abs(dx) > touchSlop || abs(dy) > touchSlop)) {
                        dragging = true
                        if (!listening) main.removeCallbacks(longPressRunnable)
                    }
                    if (dragging && !listening) {
                        params.x = paramStartX + dx
                        params.y = paramStartY + dy
                        runCatching { windowManager.updateViewLayout(v, params) }
                        updatePanelPosition()
                    }
                    return true
                }

                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    main.removeCallbacks(longPressRunnable)
                    if (listening) {
                        stopDictation()
                    } else if (!dragging) {
                        onTap()
                    }
                    dragging = false
                    return true
                }
            }
            return false
        }
    }

    /**
     * Single tap = switch to the next computer; double tap = open Settings.
     *
     * The switch is deferred by the double-tap window so one tap can still be
     * read as the first half of a double tap. Nothing else changes: a tap that
     * turns into a drag or a long press never reaches here.
     */
    private fun onTap() {
        val now = System.currentTimeMillis()
        if (now - lastTapAt < 350) {
            lastTapAt = 0
            main.removeCallbacks(switchRunnable)
            startActivity(
                Intent(this, MainActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                },
            )
        } else {
            lastTapAt = now
            main.removeCallbacks(switchRunnable)
            main.postDelayed(switchRunnable, DOUBLE_TAP_MS)
        }
    }

    private val switchRunnable = Runnable { switchPc() }

    private fun switchPc() {
        if (listening) return
        val next = settings.cyclePc()
        if (next == null) {
            flash(getString(R.string.hint_only_one_pc))
            return
        }
        vibrate(20)
        client.switchTarget()
        refreshBallLabel()
        flash(getString(R.string.hint_switched, next.name))
    }

    // ---------------------------------------------------------- dictation ---

    private fun startDictation() {
        if (listening) return
        if (!settings.isPaired) {
            flash(getString(R.string.hint_no_paired_pc))
            return
        }
        // Fresh engine per utterance: picks up Settings changes without a
        // service restart, and gives every attempt a clean internal state.
        val engine = AsrFactory.create(settings)
        asr = engine

        listening = true
        vibrate(20)
        flash(getString(R.string.hint_listening))
        engine.start(this, object : AsrEngine.Callback {
            override fun onPartial(text: String) = flash(text)
            override fun onResult(text: String) = handleResult(text)
            override fun onError(message: String) = flash(getString(R.string.hint_error, message))
        })
    }

    private fun stopDictation() {
        if (!listening) return
        listening = false
        flash(getString(R.string.hint_thinking))
        asr?.stop()
        vibrate(12)
    }

    private fun handleResult(text: String) {
        main.post {
            // sendText() queues the dictation if the socket is still coming up,
            // so the words the user just said are never dropped — they go out
            // the moment auth_ok arrives.
            client.sendText(text)
            flash(
                if (client.isConnected) getString(R.string.hint_sent)
                else "已排队，连接建立后自动发送…"
            )
        }
    }

    // -------------------------------------------------------------- misc ---

    private fun flash(message: String) {
        main.post {
            val panel = panelView ?: return@post
            panel.text = message
            if (panel.visibility != View.VISIBLE) {
                panel.visibility = View.VISIBLE
                panel.alpha = 0f
                panel.animate().alpha(1f).setDuration(160).start()
            }
            updatePanelPosition()
            main.removeCallbacks(hidePanelRunnable)
            if (!listening) main.postDelayed(hidePanelRunnable, PANEL_HIDE_MS)
        }
    }

    private val hidePanelRunnable = Runnable {
        panelView?.animate()?.alpha(0f)?.setDuration(220)?.withEndAction {
            panelView?.visibility = View.GONE
        }?.start()
    }

    private fun vibrate(ms: Long) {
        val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (getSystemService(VibratorManager::class.java)?.defaultVibrator)
        } else {
            @Suppress("DEPRECATION") getSystemService(Vibrator::class.java)
        } ?: return
        runCatching {
            vibrator.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    private fun buildNotification(): Notification {
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, FloatBallService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, App.CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_ball)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text))
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .addAction(0, getString(R.string.btn_stop_ball), stopIntent)
            .build()
    }

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            value.toFloat(),
            resources.displayMetrics,
        ).toInt()

    private val touchSlop: Int by lazy { ViewConfiguration.get(this).scaledTouchSlop }

    // -------------------------------------------------- PcClient.Listener ---

    override fun onStateChanged(state: PcClient.State, detail: String) {
        main.post {
            refreshBallLabel()
            when (state) {
                PcClient.State.CONNECTED -> flash("已连接 $detail")
                PcClient.State.CONNECTING -> flash("正在连接电脑…")
                PcClient.State.FAILED -> flash(detail)
                PcClient.State.IDLE -> Unit
            }
        }
    }

    override fun onAck(seq: Int, ok: Boolean, mode: String, chars: Int) {
        main.post { flash(if (ok) getString(R.string.hint_sent) else "发送失败") }
    }

    override fun onCommandResult(seq: Int, ok: Boolean, detail: String, needsConfirm: Boolean) {
        main.post { flash(if (ok) "已执行：$detail" else "命令未执行：$detail") }
    }

    companion object {
        const val ACTION_STOP = "com.phonemic.app.STOP"
        const val ACTION_RECONNECT = "com.phonemic.app.RECONNECT"
        private const val TAG = "FloatBall"
        private const val NOTIF_ID = 42
        private const val LONG_PRESS_MS = 500L
        private const val DOUBLE_TAP_MS = 350L
        private const val PANEL_HIDE_MS = 2500L

        fun start(context: android.content.Context) {
            val intent = Intent(context, FloatBallService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: android.content.Context) {
            context.startService(
                Intent(context, FloatBallService::class.java).setAction(ACTION_STOP),
            )
        }

        /**
         * Re-point a running ball at whatever computer is active now. No-op
         * when the service is not up, so callers never have to check.
         */
        fun reconnect(context: android.content.Context) {
            runCatching {
                context.startService(
                    Intent(context, FloatBallService::class.java).setAction(ACTION_RECONNECT),
                )
            }
        }
    }
}
