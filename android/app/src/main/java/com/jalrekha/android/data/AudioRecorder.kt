package com.jalrekha.android.data

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class AudioRecorder {
    @Volatile private var recording = false
    @Volatile private var record: AudioRecord? = null
    private val pcm = ByteArrayOutputStream()

    @SuppressLint("MissingPermission")
    fun start() {
        if (recording) return
        pcm.reset()
        val bufSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING).coerceAtLeast(4096)
        val r = AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE, CHANNEL, ENCODING, bufSize)
        record = r
        r.startRecording()
        recording = true
        Thread({
            val buf = ByteArray(bufSize)
            while (recording) {
                val n = r.read(buf, 0, buf.size)
                if (n > 0) synchronized(pcm) { pcm.write(buf, 0, n) }
            }
        }, "AudioRecorder").start()
    }

    suspend fun stopAndBuildWav(): ByteArray? = withContext(Dispatchers.IO) {
        if (!recording) return@withContext null
        recording = false
        Thread.sleep(120)
        record?.let {
            runCatching { it.stop() }
            runCatching { it.release() }
        }
        record = null
        val pcmBytes = synchronized(pcm) { pcm.toByteArray() }
        if (pcmBytes.isEmpty()) null else wrapWav(pcmBytes)
    }

    fun isRecording(): Boolean = recording

    private fun wrapWav(pcm: ByteArray): ByteArray {
        val totalDataLen = pcm.size + 36
        val byteRate = SAMPLE_RATE * CHANNELS * BITS_PER_SAMPLE / 8
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray())
        header.putInt(totalDataLen)
        header.put("WAVE".toByteArray())
        header.put("fmt ".toByteArray())
        header.putInt(16)
        header.putShort(1)
        header.putShort(CHANNELS.toShort())
        header.putInt(SAMPLE_RATE)
        header.putInt(byteRate)
        header.putShort((CHANNELS * BITS_PER_SAMPLE / 8).toShort())
        header.putShort(BITS_PER_SAMPLE.toShort())
        header.put("data".toByteArray())
        header.putInt(pcm.size)
        return header.array() + pcm
    }

    companion object {
        const val SAMPLE_RATE = 16000
        private const val CHANNELS = 1
        private const val BITS_PER_SAMPLE = 16
        private const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        private const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
    }
}
