package com.phonemic.app.pair

import android.net.Uri

/**
 * Parses the payload the PC agent puts in its QR code:
 *
 *     phonemic://192.168.1.3:8765?v=1&t=<token>
 *
 * A bare "host:port" or "ws://host:port" is also accepted so the user can type
 * it in by hand when scanning is inconvenient.
 */
object Pairing {

    data class Payload(val wsUrl: String, val token: String, val version: Int)

    private const val SCHEME = "phonemic"

    fun parse(raw: String): Payload? {
        val text = raw.trim()
        if (text.isEmpty()) return null

        // QR payload form
        if (text.startsWith("$SCHEME://")) {
            val uri = Uri.parse(text.replaceFirst("$SCHEME", "ws"))
            val host = uri.host ?: return null
            val port = uri.port.takeIf { it > 0 } ?: 8765
            val token = uri.getQueryParameter("t") ?: return null
            val version = uri.getQueryParameter("v")?.toIntOrNull() ?: 1
            return Payload("ws://$host:$port", token, version)
        }

        // Manual entry forms: 192.168.1.3:8765?t=xxx  |  ws://192.168.1.3:8765
        val normalised = if (text.startsWith("ws://") || text.startsWith("wss://")) text else "ws://$text"
        return try {
            val uri = Uri.parse(normalised)
            val host = uri.host ?: return null
            val port = uri.port.takeIf { it > 0 } ?: 8765
            val token = uri.getQueryParameter("t")
            if (token.isNullOrEmpty()) {
                // allow "host:port" + separately-stored token
                Payload("ws://$host:$port", "", 1)
            } else {
                Payload("ws://$host:$port", token, uri.getQueryParameter("v")?.toIntOrNull() ?: 1)
            }
        } catch (_: Exception) {
            null
        }
    }
}
