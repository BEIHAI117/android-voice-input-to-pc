package com.phonemic.app.pair

import android.net.Uri

/**
 * Parses the payload the PC agent puts in its QR code:
 *
 *     phonemic://192.168.1.3:8765?v=1&t=<token>&n=<电脑名>
 *
 * A bare "host:port" or "ws://host:port" is also accepted so the user can type
 * it in by hand when scanning is inconvenient.
 *
 * Query values are read from the *encoded* query and decoded exactly once
 * here: `Uri.getQueryParameter()` leaves `%XX` alone on some Android builds,
 * which put the percent-encoded computer name straight onto the ball.
 */
object Pairing {

    data class Payload(
        val wsUrl: String,
        val token: String,
        val version: Int,
        /** Computer name from the PC agent; empty when it did not send one. */
        val name: String = "",
    )

    private const val SCHEME = "phonemic"
    private const val DEFAULT_PORT = 8765

    fun parse(raw: String): Payload? {
        val text = raw.trim()
        if (text.isEmpty()) return null

        // QR payload form
        if (text.startsWith("$SCHEME://")) {
            val uri = Uri.parse(text.replaceFirst("$SCHEME", "ws"))
            return fromUri(uri, requireToken = true)
        }

        // Manual entry forms: 192.168.1.3:8765?t=xxx  |  ws://192.168.1.3:8765
        val normalised = if (text.startsWith("ws://") || text.startsWith("wss://")) text else "ws://$text"
        return try {
            fromUri(Uri.parse(normalised), requireToken = false)
        } catch (_: Exception) {
            null
        }
    }

    private fun fromUri(uri: Uri, requireToken: Boolean): Payload? {
        val host = uri.host ?: return null
        val port = uri.port.takeIf { it > 0 } ?: DEFAULT_PORT
        val token = query(uri, "t").orEmpty()
        if (requireToken && token.isEmpty()) return null
        val version = query(uri, "v")?.toIntOrNull() ?: 1
        return Payload("ws://$host:$port", token, version, name = query(uri, "n").orEmpty())
    }

    /** Read one query value from the raw query and percent-decode it once. */
    private fun query(uri: Uri, key: String): String? {
        val raw = uri.encodedQuery ?: return null
        for (pair in raw.split('&')) {
            val eq = pair.indexOf('=')
            val name = if (eq >= 0) pair.substring(0, eq) else pair
            if (name != key) continue
            val value = if (eq >= 0) pair.substring(eq + 1) else ""
            return Uri.decode(value)
        }
        return null
    }
}
