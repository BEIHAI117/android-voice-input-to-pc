package com.phonemic.app.pair

import android.net.Uri

/**
 * Parses the payload the PC agent puts in its QR code.
 *
 * Two shapes exist (docs/协议.md §1、§8)：
 *
 *     局域网直连  phonemic://192.168.1.3:8765?v=1&t=<token>&n=<电脑名>
 *     VPS 中转    phonemic://<中转host>:<port>?v=1&t=<token>&p=<房间ID>&n=<名>&m=relay&s=<0|1>
 *
 * A bare "host:port?t=xxx", "ws://host:port" or a full relay dial address
 * "wss://vps:8766/phone?p=<房间ID>&t=<token>" are also accepted for hand typing.
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
        /** true = 经 VPS 中转（[wsUrl] 是中转拨号地址），false = 局域网直连。 */
        val viaRelay: Boolean = false,
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

        // Manual entry forms: 192.168.1.3:8765?t=xxx  |  ws://…  |  wss://…/phone?p=…
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
        val name = query(uri, "n").orEmpty()

        // m=relay marks the QR form; a hand-typed full dial URL is recognised
        // by its /phone path. Everything else stays plain LAN direct.
        val isRelay = query(uri, "m") == "relay" ||
            (uri.encodedPath ?: "").contains("/phone")
        if (isRelay) {
            val room = query(uri, "p").orEmpty()
            if (room.isEmpty()) return null
            // QR comes in as ws://… so the s flag decides; a hand-typed wss:// URL
            // carries its own scheme. wss wins when both are present.
            val scheme = if (uri.scheme == "wss" || query(uri, "s") == "1") "wss" else "ws"
            return Payload("$scheme://$host:$port/phone?p=$room", token, version, name, viaRelay = true)
        }

        return Payload("ws://$host:$port", token, version, name, viaRelay = false)
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
