package com.phonemic.app.data

import android.content.Context
import android.content.SharedPreferences

/**
 * Tiny wrapper over SharedPreferences. Kept in one place so the service, the
 * activity and the ASR factory all read the same values.
 */
class Settings(context: Context) {

    private val sp: SharedPreferences =
        context.applicationContext.getSharedPreferences("phonemic", Context.MODE_PRIVATE)

    var pcEndpoint: String
        get() = sp.getString(KEY_PC_ENDPOINT, "") ?: ""
        set(v) = sp.edit().putString(KEY_PC_ENDPOINT, v).apply()

    var pcName: String
        get() = sp.getString(KEY_PC_NAME, "") ?: ""
        set(v) = sp.edit().putString(KEY_PC_NAME, v).apply()

    var token: String
        get() = sp.getString(KEY_TOKEN, "") ?: ""
        set(v) = sp.edit().putString(KEY_TOKEN, v).apply()

    val deviceId: String
        get() {
            val existing = sp.getString(KEY_DEVICE_ID, "") ?: ""
            if (existing.isNotEmpty()) return existing
            val fresh = java.util.UUID.randomUUID().toString()
            sp.edit().putString(KEY_DEVICE_ID, fresh).apply()
            return fresh
        }

    var asrEngine: String
        get() = sp.getString(KEY_ASR, ASR_CLOUD) ?: ASR_CLOUD
        set(v) = sp.edit().putString(KEY_ASR, v).apply()

    var cloudBaseUrl: String
        get() = sp.getString(KEY_CLOUD_BASE, DEFAULT_CLOUD_BASE) ?: DEFAULT_CLOUD_BASE
        set(v) = sp.edit().putString(KEY_CLOUD_BASE, v).apply()

    var cloudApiKey: String
        get() = sp.getString(KEY_CLOUD_KEY, DEFAULT_CLOUD_KEY) ?: DEFAULT_CLOUD_KEY
        set(v) = sp.edit().putString(KEY_CLOUD_KEY, v).apply()

    var cloudModel: String
        get() = sp.getString(KEY_CLOUD_MODEL, DEFAULT_CLOUD_MODEL) ?: DEFAULT_CLOUD_MODEL
        set(v) = sp.edit().putString(KEY_CLOUD_MODEL, v).apply()

    /**
     * Which request shape the endpoint speaks. "auto" probes once and remembers;
     * the explicit values skip the probe entirely.
     */
    var cloudStyle: String
        get() = sp.getString(KEY_CLOUD_STYLE, "auto") ?: "auto"
        set(v) = sp.edit().putString(KEY_CLOUD_STYLE, v).apply()

    val isPaired: Boolean
        get() = pcEndpoint.isNotEmpty() && token.isNotEmpty()

    fun clearPairing() {
        sp.edit().remove(KEY_PC_ENDPOINT).remove(KEY_PC_NAME).remove(KEY_TOKEN).apply()
    }

    companion object {
        const val ASR_SYSTEM = "system"
        const val ASR_CLOUD = "cloud"
        const val ASR_SHERPA = "sherpa"

        private const val KEY_PC_ENDPOINT = "pc_endpoint"
        private const val KEY_PC_NAME = "pc_name"
        private const val KEY_TOKEN = "token"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_ASR = "asr"
        private const val KEY_CLOUD_BASE = "cloud_base"
        private const val KEY_CLOUD_KEY = "cloud_key"
        private const val KEY_CLOUD_MODEL = "cloud_model"
        private const val KEY_CLOUD_STYLE = "cloud_style"

        // Pre-configured so a fresh install can dictate without any typing.
        // NOTE: the API key travels inside the APK — swap it in Settings before
        // sharing the binary with anyone.
        const val DEFAULT_CLOUD_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
        const val DEFAULT_CLOUD_KEY = "REDACTED"
        const val DEFAULT_CLOUD_MODEL = "mimo-v2.5-asr"
    }
}
