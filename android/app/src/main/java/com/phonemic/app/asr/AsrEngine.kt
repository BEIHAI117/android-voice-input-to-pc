package com.phonemic.app.asr

import android.content.Context

/**
 * Pluggable speech recognition back-end.
 *
 * The contract is "start / stop / get one utterance" rather than "recognise
 * this PCM buffer", because the cheapest engine (Android's own
 * [android.speech.SpeechRecognizer]) only works off the live microphone and
 * cannot consume a pre-recorded buffer. Engines that do want PCM
 * ([CloudAsrEngine], [SherpaAsrEngine]) own their own recorder internally.
 */
interface AsrEngine {

    /** Human-readable name used in logs and error messages. */
    val name: String

    /** True if the engine can emit incremental results while the user talks. */
    val supportsPartials: Boolean get() = false

    /**
     * Begin capturing. Call on the main thread.
     * [callback] may be invoked on any thread.
     */
    fun start(context: Context, callback: Callback)

    /**
     * Stop capturing and deliver the final result through the callback given to
     * [start]. Safe to call when already stopped.
     */
    fun stop()

    /** Abandon the current utterance; no callback will be invoked. */
    fun cancel()

    /** Release native resources. */
    fun close() {}

    interface Callback {
        fun onPartial(text: String) {}
        fun onResult(text: String)
        fun onError(message: String)
    }
}
