package com.phonemic.app.net

import org.json.JSONObject

/**
 * Wire protocol mirror of pc-agent/agent/protocol.py. Keep the two in sync —
 * docs/协议.md is the single source of truth.
 */
object Protocol {

    const val VERSION = 1

    fun auth(deviceId: String, name: String, token: String): String =
        JSONObject()
            .put("t", "auth")
            .put("id", deviceId)
            .put("name", name)
            .put("token", token)
            .toString()

    fun text(seq: Int, body: String, mode: String? = null): String =
        JSONObject()
            .put("t", "text")
            .put("seq", seq)
            .put("text", body)
            .apply { if (mode != null) put("mode", mode) }
            .toString()

    fun typing(seq: Int, partial: String): String =
        JSONObject()
            .put("t", "typing")
            .put("seq", seq)
            .put("text_partial", partial)
            .toString()

    /** Send raw speech and let the PC agent decide between command and text. */
    fun cmd(seq: Int, speech: String): String =
        JSONObject()
            .put("t", "cmd")
            .put("seq", seq)
            .put("text", speech)
            .toString()

    fun ping(): String = JSONObject().put("t", "ping").toString()

    fun parse(frame: String): JSONObject? = try {
        JSONObject(frame)
    } catch (_: Exception) {
        null
    }
}
