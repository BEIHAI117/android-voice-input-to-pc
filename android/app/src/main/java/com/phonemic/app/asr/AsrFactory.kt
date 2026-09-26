package com.phonemic.app.asr

import com.phonemic.app.data.Settings

object AsrFactory {

    fun create(settings: Settings): AsrEngine {
        val engine = when (settings.asrEngine) {
            Settings.ASR_CLOUD -> CloudAsrEngine(
                baseUrl = settings.cloudBaseUrl,
                apiKey = settings.cloudApiKey,
                model = settings.cloudModel,
                style = settings.cloudStyle,
            )
            Settings.ASR_SHERPA -> SherpaAsrEngine()
            else -> SystemAsrEngine()
        }
        android.util.Log.i(
            "PhoneMic",
            "AsrFactory.create -> ${engine.name} (setting=${settings.asrEngine}, " +
                "base='${settings.cloudBaseUrl}', model='${settings.cloudModel}', style=${settings.cloudStyle})"
        )
        return engine
    }
}
