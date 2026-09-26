package com.phonemic.app.data

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/**
 * One bound computer. [id] is derived from the pairing token, so it survives
 * the PC getting a new DHCP address — re-pairing after an IP change updates the
 * entry instead of creating a second one.
 */
data class PcTarget(
    val id: String,
    val name: String,
    val endpoint: String,
    val token: String,
)

/**
 * Tiny wrapper over SharedPreferences. Kept in one place so the service, the
 * activity and the ASR factory all read the same values.
 *
 * Holds a *list* of bound computers: one phone, several desktops on the same
 * LAN, and the floating ball cycles through them with a single tap.
 */
class Settings(context: Context) {

    private val sp: SharedPreferences =
        context.applicationContext.getSharedPreferences("phonemic", Context.MODE_PRIVATE)

    // ------------------------------------------------------- computers ---

    /** Bound computers, in the order the ball cycles through them. */
    val pcs: List<PcTarget>
        get() = readPcs()

    var activePcId: String
        get() = sp.getString(KEY_ACTIVE_PC, "") ?: ""
        set(v) = sp.edit().putString(KEY_ACTIVE_PC, v).apply()

    /** The computer text is currently sent to, or null when nothing is bound. */
    val activePc: PcTarget?
        get() {
            val list = readPcs()
            if (list.isEmpty()) return null
            return list.firstOrNull { it.id == activePcId } ?: list[0].also { activePcId = it.id }
        }

    /**
     * Add or refresh a computer and make it the active one.
     *
     * Matched by endpoint first (same host:port = same machine) then by id
     * (same token = same machine whose IP just changed), so re-scanning the
     * second desktop never duplicates it.
     */
    fun upsertPc(name: String, endpoint: String, token: String): PcTarget? {
        if (endpoint.isEmpty()) return null
        val list = readPcs().toMutableList()
        val byEndpoint = list.indexOfFirst { it.endpoint == endpoint }
        val id = idFor(token, endpoint)
        val byId = if (byEndpoint >= 0) -1 else list.indexOfFirst { it.id == id }
        val idx = if (byEndpoint >= 0) byEndpoint else byId
        val existing = list.getOrNull(idx)

        val merged = PcTarget(
            id = existing?.id ?: id,
            name = name.ifEmpty { existing?.name ?: hostOf(endpoint) },
            endpoint = endpoint,
            token = token.ifEmpty { existing?.token ?: "" },
        )
        if (idx >= 0) list[idx] = merged else list.add(merged)
        writePcs(list)
        activePcId = merged.id
        return merged
    }

    /** Make [id] the target of every future dictation. */
    fun setActive(id: String) {
        if (readPcs().any { it.id == id }) activePcId = id
    }

    /**
     * Move to the next bound computer. Returns the newly active one, or null
     * when there is nothing to switch to (fewer than two bound).
     */
    fun cyclePc(): PcTarget? {
        val list = readPcs()
        if (list.size < 2) return null
        val current = list.indexOfFirst { it.id == activePcId }
        val next = list[(current + 1) % list.size]
        activePcId = next.id
        return next
    }

    fun removePc(id: String) {
        val list = readPcs().filterNot { it.id == id }
        writePcs(list)
        if (activePcId == id) activePcId = list.firstOrNull()?.id ?: ""
    }

    /** Adopt the name the PC reports in auth_ok (it is the configured one). */
    fun updatePcName(id: String, name: String) {
        if (name.isEmpty()) return
        val list = readPcs().toMutableList()
        val idx = list.indexOfFirst { it.id == id }
        if (idx < 0 || list[idx].name == name) return
        list[idx] = list[idx].copy(name = name)
        writePcs(list)
    }

    private fun readPcs(): List<PcTarget> {
        // null = never written, i.e. this install predates the list. An empty
        // list must NOT re-run the migration, or deleting the last computer
        // would resurrect the legacy single-PC entry on the next read.
        val raw = sp.getString(KEY_PCS, null) ?: return migrateLegacy()
        return try {
            val arr = JSONArray(raw)
            val out = ArrayList<PcTarget>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.getJSONObject(i)
                val endpoint = o.optString("endpoint")
                if (endpoint.isEmpty()) continue
                out.add(
                    PcTarget(
                        id = o.optString("id").ifEmpty { idFor(o.optString("token"), endpoint) },
                        name = o.optString("name").ifEmpty { endpoint },
                        endpoint = endpoint,
                        token = o.optString("token"),
                    ),
                )
            }
            out
        } catch (_: Exception) {
            // Corrupt value: fall back to the legacy single-PC keys once.
            migrateLegacy()
        }
    }

    /** First run after the single-PC version: adopt pc_endpoint/token as-is. */
    private fun migrateLegacy(): List<PcTarget> {
        val endpoint = sp.getString(KEY_PC_ENDPOINT, "") ?: ""
        if (endpoint.isEmpty()) return emptyList()
        val token = sp.getString(KEY_TOKEN, "") ?: ""
        val migrated = listOf(
            PcTarget(
                id = idFor(token, endpoint),
                name = sp.getString(KEY_PC_NAME, "")?.ifEmpty { endpoint } ?: endpoint,
                endpoint = endpoint,
                token = token,
            ),
        )
        writePcs(migrated)
        if (activePcId.isEmpty()) activePcId = migrated[0].id
        return migrated
    }

    private fun writePcs(list: List<PcTarget>) {
        val arr = JSONArray()
        for (t in list) {
            arr.put(
                JSONObject()
                    .put("id", t.id)
                    .put("name", t.name)
                    .put("endpoint", t.endpoint)
                    .put("token", t.token),
            )
        }
        sp.edit().putString(KEY_PCS, arr.toString()).apply()
    }

    private fun idFor(token: String, endpoint: String): String =
        if (token.isEmpty()) endpoint else "pc-" + sha1(token).take(16)

    private fun sha1(value: String): String = try {
        MessageDigest.getInstance("SHA-1")
            .digest(value.toByteArray())
            .joinToString("") { "%02x".format(it) }
    } catch (_: Exception) {
        value
    }

    private fun hostOf(endpoint: String): String = try {
        android.net.Uri.parse(endpoint).host ?: endpoint
    } catch (_: Exception) {
        endpoint
    }

    // ---------------------------------------------------------- device ---

    val deviceId: String
        get() {
            val existing = sp.getString(KEY_DEVICE_ID, "") ?: ""
            if (existing.isNotEmpty()) return existing
            val fresh = java.util.UUID.randomUUID().toString()
            sp.edit().putString(KEY_DEVICE_ID, fresh).apply()
            return fresh
        }

    /**
     * Defaults to the system recognizer: it needs no key and no network, so a
     * fresh install dictates on the first try. Cloud is opt-in (bring a key).
     */
    var asrEngine: String
        get() = sp.getString(KEY_ASR, ASR_SYSTEM) ?: ASR_SYSTEM
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
        get() = activePc != null

    fun clearPairing() {
        sp.edit()
            .remove(KEY_PCS)
            .remove(KEY_ACTIVE_PC)
            .remove(KEY_PC_ENDPOINT)
            .remove(KEY_PC_NAME)
            .remove(KEY_TOKEN)
            .apply()
    }

    companion object {
        const val ASR_SYSTEM = "system"
        const val ASR_CLOUD = "cloud"
        const val ASR_SHERPA = "sherpa"

        private const val KEY_PCS = "pcs"
        private const val KEY_ACTIVE_PC = "active_pc"
        private const val KEY_PC_ENDPOINT = "pc_endpoint"
        private const val KEY_PC_NAME = "pc_name"
        private const val KEY_TOKEN = "token"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_ASR = "asr"
        private const val KEY_CLOUD_BASE = "cloud_base"
        private const val KEY_CLOUD_KEY = "cloud_key"
        private const val KEY_CLOUD_MODEL = "cloud_model"
        private const val KEY_CLOUD_STYLE = "cloud_style"

        // Endpoint shape is pre-filled so the cloud engine only needs a key.
        // No API key ships with the app — a key baked into a binary is a leaked
        // key the moment that binary is shared, so users bring their own.
        const val DEFAULT_CLOUD_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
        const val DEFAULT_CLOUD_KEY = ""
        const val DEFAULT_CLOUD_MODEL = "mimo-v2.5-asr"
    }
}
