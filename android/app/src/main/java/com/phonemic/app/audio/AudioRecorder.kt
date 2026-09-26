package com.phonemic.app.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlin.concurrent.thread

/**
 * Minimal PCM recorder: 16 kHz / 16-bit / mono, the format every offline ASR
 * model expects. Buffers into memory — utterances are a few seconds, so no
 * disk I/O and nothing to clean up.
 */
class AudioRecorder(private val sampleRate: Int = 16_000) {

    private var record: AudioRecord? = null
    private var worker: Thread? = null
    @Volatile private var running = false

    private val buffer = ArrayList<ShortArray>()
    private val lock = Object()

    /** Peak absolute sample seen since [start]; useful for a level meter. */
    @Volatile private var peak: Int = 0
    val amplitude: Int get() = peak

    @SuppressLint("MissingPermission")
    fun start() {
        if (running) return
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, sampleRate), // ~1s of headroom
        )
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            throw IllegalStateException("AudioRecord init failed (mic in use or permission missing)")
        }
        record = rec
        synchronized(lock) { buffer.clear() }
        peak = 0
        running = true
        rec.startRecording()

        worker = thread(name = "phonemic-recorder") {
            val chunk = ShortArray(2048)
            while (running) {
                val read = rec.read(chunk, 0, chunk.size)
                if (read > 0) {
                    var localPeak = 0
                    for (i in 0 until read) {
                        val v = kotlin.math.abs(chunk[i].toInt())
                        if (v > localPeak) localPeak = v
                    }
                    if (localPeak > peak) peak = localPeak
                    synchronized(lock) { buffer.add(chunk.copyOf(read)) }
                }
            }
        }
    }

    /** Stops recording and returns everything captured so far. */
    fun stop(): ShortArray {
        running = false
        try {
            record?.stop()
        } catch (_: Exception) {
        }
        record?.release()
        record = null
        try {
            worker?.join(500)
        } catch (_: InterruptedException) {
        }
        worker = null

        synchronized(lock) {
            val total = buffer.sumOf { it.size }
            val out = ShortArray(total)
            var off = 0
            for (part in buffer) {
                System.arraycopy(part, 0, out, off, part.size)
                off += part.size
            }
            buffer.clear()
            return out
        }
    }

    companion object {
        /** 16-bit PCM little-endian, ready for an HTTP upload. */
        fun toPcm16(samples: ShortArray): ByteArray {
            val out = ByteArray(samples.size * 2)
            for (i in samples.indices) {
                out[i * 2] = (samples[i].toInt() and 0xFF).toByte()
                out[i * 2 + 1] = ((samples[i].toInt() shr 8) and 0xFF).toByte()
            }
            return out
        }

        /** Minimal WAV container around PCM16, accepted by Whisper-compatible APIs. */
        fun toWav(samples: ShortArray, sampleRate: Int): ByteArray {
            val pcm = toPcm16(samples)
            val header = ByteArray(44)
            val total = 36 + pcm.size
            fun put(offset: Int, v: Int) {
                header[offset] = (v and 0xFF).toByte()
                header[offset + 1] = ((v shr 8) and 0xFF).toByte()
                header[offset + 2] = ((v shr 16) and 0xFF).toByte()
                header[offset + 3] = ((v shr 24) and 0xFF).toByte()
            }
            fun putShort(offset: Int, v: Int) {
                header[offset] = (v and 0xFF).toByte()
                header[offset + 1] = ((v shr 8) and 0xFF).toByte()
            }
            // RIFF header
            header[0] = 'R'.code.toByte(); header[1] = 'I'.code.toByte()
            header[2] = 'F'.code.toByte(); header[3] = 'F'.code.toByte()
            put(4, total)
            header[8] = 'W'.code.toByte(); header[9] = 'A'.code.toByte()
            header[10] = 'V'.code.toByte(); header[11] = 'E'.code.toByte()
            // fmt chunk
            header[12] = 'f'.code.toByte(); header[13] = 'm'.code.toByte()
            header[14] = 't'.code.toByte(); header[15] = ' '.code.toByte()
            put(16, 16); putShort(20, 1)   // PCM
            putShort(22, 1)                 // mono
            put(24, sampleRate)
            put(28, sampleRate * 2)         // byte rate
            putShort(32, 2)                 // block align
            putShort(34, 16)                // bits per sample
            // data chunk
            header[36] = 'd'.code.toByte(); header[37] = 'a'.code.toByte()
            header[38] = 't'.code.toByte(); header[39] = 'a'.code.toByte()
            put(40, pcm.size)
            return header + pcm
        }
    }
}
