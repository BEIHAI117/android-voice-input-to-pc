package com.phonemic.app.asr

import android.content.Context

/**
 * Fully offline recognition via [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx).
 *
 * ## Status: integration point, not wired
 *
 * The sherpa-onnx Android artefacts are **not published to Maven Central**;
 * they ship as AARs attached to GitHub releases and have to be dropped into
 * `app/libs/` by hand. Because of that this class is a deliberate stub — it
 * reports clearly rather than pretending to work, and the app builds without
 * the native dependency.
 *
 * ## How to enable it
 *
 * 1. Download the Android AAR from
 *    <https://github.com/k2-fsa/sherpa-onnx/releases> (look for
 *    `sherpa-onnx-v*-android-aar.tar.gz`) and extract it into `app/libs/`.
 * 2. In `app/build.gradle.kts`, uncomment:
 *
 *        implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar"))))
 *
 * 3. Download a Chinese model (e.g. `sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20`
 *    or the newer SenseVoice model) into `app/src/main/assets/`.
 * 4. Replace [recognise] below with the Kotlin API from
 *    <https://k2-fsa.github.io/sherpa/onnx/kotlin-api/index.html>, which is
 *    generated from `kotlin-api/` in that repo. The shape is roughly:
 *
 *        val config = OnlineRecognizerConfig(...)
 *        val recognizer = OnlineRecognizer(config)
 *        recognizer.acceptWaveform(sampleRate, samples)   // feed PCM16
 *        recognizer.isReady / decode() / getResult().text // read text
 *
 * 5. Switch `Settings.asrEngine` to `Settings.ASR_SHERPA`.
 *
 * The recording side is already handled: [com.phonemic.app.audio.AudioRecorder]
 * produces exactly the 16 kHz mono PCM16 these models expect.
 */
class SherpaAsrEngine : AsrEngine {

    override val name: String = "sherpa-onnx"

    override fun start(context: Context, callback: AsrEngine.Callback) {
        callback.onError(
            "本地离线识别尚未接入：需要把 sherpa-onnx 的 AAR 与中文模型放进工程，" +
                "步骤见 SherpaAsrEngine.kt 的注释。当前请用「系统识别」或「云端识别」。"
        )
    }

    override fun stop() {}
    override fun cancel() {}
}
