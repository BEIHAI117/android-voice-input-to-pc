package com.phonemic.app.asr

import android.content.Context
import android.util.Base64
import android.util.Log
import com.phonemic.app.audio.AudioRecorder
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Speech-to-text through an HTTP API.
 *
 * "OpenAI-compatible" providers split into two different request shapes and
 * the model name alone does not tell you which one. Both are implemented here:
 *
 *  1. `STYLE_TRANSCRIPTIONS` — OpenAI's `POST {base}/audio/transcriptions`
 *     (multipart `file`). OpenAI / Groq / self-hosted whisper-asr-webservice.
 *
 *  2. `STYLE_CHAT_AUDIO` — `POST {base}/chat/completions` with a user message
 *     carrying exactly one `input_audio` part. This is what Xiaomi's mimo
 *     gateway uses; it rejects any text part and any other route.
 *
 * `STYLE_AUTO` tries the OpenAI route first and permanently remembers the
 * answer, so the first request pays for the probe and every later one goes
 * straight to the right shape.
 */
class CloudAsrEngine(
    private val baseUrl: String,
    private val apiKey: String,
    private val model: String = DEFAULT_MODEL,
    private val language: String = "zh",
    private val style: String = STYLE_AUTO,
) : AsrEngine {

    override val name: String = "cloud"

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    private val recorder = AudioRecorder()

    @Volatile private var callback: AsrEngine.Callback? = null
    @Volatile private var worker: Thread? = null

    override fun start(context: Context, callback: AsrEngine.Callback) {
        if (baseUrl.isBlank()) {
            callback.onError("未配置云端识别 Base URL")
            return
        }
        if (model.isBlank()) {
            callback.onError("未配置云端识别模型名")
            return
        }
        this.callback = callback
        try {
            recorder.start()
        } catch (e: Exception) {
            this.callback = null
            callback.onError("无法开始录音：${e.message}")
        }
    }

    override fun stop() {
        val cb = callback ?: run {
            recorder.stop()
            return
        }
        callback = null

        val samples = recorder.stop()
        if (samples.isEmpty()) {
            cb.onError("没有录到声音")
            return
        }

        worker = thread(name = "phonemic-cloud-asr") {
            try {
                val wav = AudioRecorder.toWav(samples, SAMPLE_RATE)
                Log.i(TAG, "utterance: ${samples.size} samples, ${wav.size} bytes wav, model=$model")
                val text = transcribe(wav)
                Log.i(TAG, "recognised -> ${text.take(80)}")
                if (text.isBlank()) cb.onError("没有识别到内容") else cb.onResult(text)
            } catch (e: IOException) {
                Log.w(TAG, "transcribe IO failure: ${e.message}")
                cb.onError("网络错误：${e.message}")
            } catch (e: Exception) {
                Log.w(TAG, "transcribe failure: ${e.message}")
                cb.onError("识别失败：${e.message}")
            }
        }
    }

    override fun cancel() {
        callback = null
        runCatching { recorder.stop() }
    }

    override fun close() = cancel()

    // ------------------------------------------------------------ request ---

    private fun transcribe(wav: ByteArray): String {
        return when (resolvedStyle()) {
            STYLE_CHAT_AUDIO -> transcribeViaChat(wav)
            else -> transcribeViaTranscriptions(wav)
        }
    }

    /** OpenAI `POST /audio/transcriptions`, multipart form. */
    private fun transcribeViaTranscriptions(wav: ByteArray): String {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", "audio.wav", wav.toRequestBody("audio/wav".toMediaType()))
            .addFormDataPart("model", model)
            .addFormDataPart("language", language)
            .addFormDataPart("response_format", "json")
            .build()

        val request = Request.Builder()
            .url(join(base = baseUrl, path = "/audio/transcriptions"))
            .post(body)
            .apply { if (apiKey.isNotBlank()) header("Authorization", "Bearer $apiKey") }
            .build()

        client.newCall(request).execute().use { resp ->
            val payload = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw IOException("HTTP ${resp.code}: ${payload.take(200)}")
            return JSONObject(payload).optString("text", "").trim()
        }
    }

    /**
     * Chat-completions with a single `input_audio` part.
     *
     * Strict on purpose: gateways implementing this shape reject any text part
     * ("text prompt is injected by the gateway") and require exactly one audio
     * part, so the message body must contain audio and nothing else.
     */
    private fun transcribeViaChat(wav: ByteArray): String {
        val audioPart = JSONObject()
            .put("type", "input_audio")
            .put(
                "input_audio",
                JSONObject()
                    .put("data", Base64.encodeToString(wav, Base64.NO_WRAP))
                    .put("format", "wav"),
            )
        val message = JSONObject()
            .put("role", "user")
            .put("content", JSONArray().put(audioPart))
        val body = JSONObject()
            .put("model", model)
            .put("messages", JSONArray().put(message))

        val request = Request.Builder()
            .url(join(base = baseUrl, path = "/chat/completions"))
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .apply { if (apiKey.isNotBlank()) header("Authorization", "Bearer $apiKey") }
            .build()

        client.newCall(request).execute().use { resp ->
            val payload = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw IOException("HTTP ${resp.code}: ${payload.take(300)}")
            val json = JSONObject(payload)
            return json
                .optJSONArray("choices")
                ?.optJSONObject(0)
                ?.optJSONObject("message")
                ?.optString("content", "")
                .orEmpty()
                .trim()
        }
    }

    // ------------------------------------------------------- style detect ---

    private fun resolvedStyle(): String {
        if (style != STYLE_AUTO) return style
        // `.also` returns its receiver, so the probe result must be the thing
        // being chained — otherwise the cache is written but the wrong shape is
        // returned for the first request.
        return discoveredStyle ?: probeStyle().also { discoveredStyle = it }
    }

    private fun probeStyle(): String {
        // Cheapest possible probe: hit the OpenAI route with an empty body and
        // read only the status code. 404/405 => wrong route, try chat-audio.
        return try {
            val body = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("model", model)
                .addFormDataPart("file", "audio.wav", ByteArray(44).toRequestBody("audio/wav".toMediaType()))
                .build()
            val request = Request.Builder()
                .url(join(base = baseUrl, path = "/audio/transcriptions"))
                .post(body)
                .apply { if (apiKey.isNotBlank()) header("Authorization", "Bearer $apiKey") }
                .build()
            client.newCall(request).execute().use { resp ->
                val chosen = if (resp.code == 404 || resp.code == 405) STYLE_CHAT_AUDIO else STYLE_TRANSCRIPTIONS
                Log.i(TAG, "probe: /audio/transcriptions -> ${resp.code}, using $chosen")
                chosen
            }
        } catch (e: Exception) {
            Log.i(TAG, "probe failed (${e.message}), assuming chat-audio")
            STYLE_CHAT_AUDIO
        }
    }

    /** `{base}` may or may not already end with /v1 — join without doubling. */
    private fun join(base: String, path: String): String {
        val root = base.trimEnd('/')
        return if (root.endsWith("/v1") || root.endsWith("/anthropic")) root + path
        else root + "/v1" + path
    }

    companion object {
        private const val TAG = "CloudAsr"
        const val SAMPLE_RATE = 16_000

        const val STYLE_AUTO = "auto"
        const val STYLE_TRANSCRIPTIONS = "transcriptions"
        const val STYLE_CHAT_AUDIO = "chat-audio"

        /** Xiaomi mimo gateway; works with chat-audio. */
        const val DEFAULT_MODEL = "mimo-v2.5-asr"

        @Volatile private var discoveredStyle: String? = null

        /** Test hook: forget which shape the endpoint speaks. */
        fun resetStyleCache() {
            discoveredStyle = null
        }
    }
}
