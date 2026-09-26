package com.phonemic.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.phonemic.app.data.Settings
import com.phonemic.app.overlay.FloatBallService
import com.phonemic.app.util.Permissions

/**
 * Restarts the ball after a reboot. Only acts if the user had it running and
 * has already granted the overlay permission — never prompts from a receiver.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val settings = Settings(context)
        if (!settings.isPaired) return
        if (!Permissions.hasOverlay(context)) return
        runCatching { FloatBallService.start(context) }
    }
}
