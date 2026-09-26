package com.phonemic.app.asr

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/**
 * Wraps the platform speech recogniser.
 *
 * This is the default because it is free, needs no key, and on modern devices
 * (including vivo / OriginOS) is often running on-device — so it works with no
 * network. Quality and language coverage depend on the ROM's own engine.
 *
 * [SpeechRecognizer] is main-thread only and has a hard ~1 minute listening
 * ceiling, which is well beyond a press-and-hold dictation.
 */
class SystemAsrEngine : AsrEngine {

    override val name: String = "system"

    private val mainHandler = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    private var callback: AsrEngine.Callback? = null
    private var delivered = false

    override fun start(context: Context, callback: AsrEngine.Callback) {
        mainHandler.post {
            if (!SpeechRecognizer.isRecognitionAvailable(context)) {
                callback.onError("系统语音识别不可用，请改用云端识别")
                return@post
            }
            this.callback = callback
            this.delivered = false

            val rec = SpeechRecognizer.createSpeechRecognizer(context)
            recognizer = rec
            rec.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onError(error: Int) {
                    if (delivered) return
                    delivered = true
                    callback.onError(errorLabel(error))
                    release()
                }

                override fun onResults(results: Bundle?) {
                    if (delivered) return
                    val texts = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val best = texts?.firstOrNull().orEmpty()
                    delivered = true
                    if (best.isBlank()) callback.onError("没有识别到内容") else callback.onResult(best)
                    release()
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val texts = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    texts?.firstOrNull()?.takeIf { it.isNotBlank() }?.let { callback.onPartial(it) }
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            })

            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(
                    RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
                )
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                // Never silently switch to the keyboard if the engine bails out.
                putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
            }
            try {
                rec.startListening(intent)
            } catch (e: Exception) {
                callback.onError("无法开始识别：${e.message}")
                release()
            }
        }
    }

    override fun stop() {
        mainHandler.post {
            try {
                recognizer?.stopListening()
            } catch (_: Exception) {
            }
            // Some engines never call onResults after stopListening; make sure
            // the gesture still terminates.
            mainHandler.postDelayed({
                if (!delivered) {
                    delivered = true
                    callback?.onError("识别超时")
                    release()
                }
            }, 4_000)
        }
    }

    override fun cancel() {
        mainHandler.post {
            delivered = true
            try {
                recognizer?.cancel()
            } catch (_: Exception) {
            }
            release()
        }
    }

    override fun close() = cancel()

    private fun release() {
        try {
            recognizer?.destroy()
        } catch (_: Exception) {
        }
        recognizer = null
        callback = null
    }

    private fun errorLabel(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_AUDIO -> "录音出错"
        SpeechRecognizer.ERROR_CLIENT -> "识别服务出错"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "缺少麦克风权限"
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "网络错误"
        SpeechRecognizer.ERROR_NO_MATCH -> "没有识别到内容"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别服务忙，请稍后再试"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没有听到声音"
        else -> "识别失败（$code）"
    }
}
