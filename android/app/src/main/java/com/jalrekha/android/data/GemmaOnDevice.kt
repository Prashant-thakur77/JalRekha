package com.jalrekha.android.data

import android.content.Context
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Content
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.Message
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.system.measureTimeMillis

/**
 * On-device Gemma wrapper backed by LiteRT-LM (`gemma-4-E2B-it.litertlm`).
 *
 * Format choice: Google publishes Gemma 4 only as `.litertlm` (LiteRT-LM
 * runtime). MediaPipe `.task` files do not exist for Gemma 4, so the previous
 * `tasks-genai` path was unusable. LiteRT-LM is the native runtime for the
 * same artifact the backend loads (`backend/data/models/gemma-4-E2B-it.litertlm`).
 *
 * Contract:
 * - Model file lives at `context.filesDir/gemma-4-E2B-it.litertlm`.
 * - [isAvailable] true iff file exists; no silent backend fallback.
 * - [ensureLoaded] is idempotent and logs cold-start time on first call.
 * - [structureReport] is suspending; callers must invoke from a coroutine.
 */
class GemmaOnDevice(private val context: Context) {
    @Volatile private var engine: Engine? = null
    private var lastColdStartMs: Long = -1

    val modelFile: File get() = File(context.filesDir, MODEL_FILE_NAME)

    fun isAvailable(): Boolean = modelFile.exists()

    suspend fun ensureLoaded(): Boolean = withContext(Dispatchers.IO) {
        engine?.let { return@withContext true }
        if (!modelFile.exists()) {
            Log.w(TAG, "LiteRT-LM model missing at ${modelFile.absolutePath}")
            return@withContext false
        }
        runCatching {
            lastColdStartMs = measureTimeMillis {
                val config = EngineConfig(
                    modelPath = modelFile.absolutePath,
                    backend = Backend.CPU(),
                    visionBackend = Backend.CPU(),
                    audioBackend = Backend.CPU(),
                    maxNumTokens = 2048,
                    maxNumImages = null,
                    cacheDir = context.cacheDir.absolutePath,
                )
                val built = Engine(config)
                built.initialize()
                engine = built
            }
            Log.i(TAG, "LiteRT-LM engine ready in ${lastColdStartMs}ms (${modelFile.name})")
            true
        }.getOrElse { t ->
            Log.e(TAG, "LiteRT-LM engine init failed", t)
            engine = null
            false
        }
    }

    suspend fun generate(prompt: String, audioWav: ByteArray? = null): String? = withContext(Dispatchers.IO) {
        if (!ensureLoaded()) return@withContext null
        val current = engine ?: return@withContext null
        runCatching {
            current.createConversation().use { conversation ->
                val reply: Message = if (audioWav != null) {
                    val parts: List<Content> = listOf(Content.Text(prompt), Content.AudioBytes(audioWav))
                    conversation.sendMessage(Contents.of(parts), emptyMap())
                } else {
                    conversation.sendMessage(prompt, emptyMap())
                }
                reply.contents.contents
                    .filterIsInstance<Content.Text>()
                    .joinToString(separator = "") { it.text }
            }
        }.getOrElse { t ->
            Log.e(TAG, "LiteRT-LM generate failed", t)
            null
        }
    }

    suspend fun structureReport(transcript: String, audioWav: ByteArray? = null): String? {
        if (transcript.isBlank() && audioWav == null) return null
        val prompt = if (audioWav != null) buildAudioPrompt() else buildFewShotPrompt(transcript)
        val raw = generate(prompt, audioWav) ?: return null
        Log.i(TAG, "raw response (audio=${audioWav != null}, ${raw.length} chars): ${raw.take(400)}")
        val start = raw.indexOf('{')
        val end = raw.lastIndexOf('}')
        if (start == -1 || end == -1 || end < start) return null
        return raw.substring(start, end + 1)
    }

    fun lastColdStartMs(): Long = lastColdStartMs

    companion object {
        private const val TAG = "GemmaOnDevice"
        const val MODEL_FILE_NAME = "gemma-4-E2B-it.litertlm"

        private fun buildFewShotPrompt(transcript: String): String = """
            Sos un parser de reportes de voluntarios en espanol rioplatense.
            Devolve SOLO un JSON con claves: water_level_category, trend,
            road_status, bridge_status, homes_affected, urgency, summary, confidence.

            Ejemplo: {"water_level_category":"critical","trend":"rising","road_status":"blocked","bridge_status":"unknown","homes_affected":false,"urgency":"critical","summary":"paso la marca","confidence":0.9}
            Ejemplo: {"water_level_category":"low","trend":"stable","road_status":"open","bridge_status":"open","homes_affected":false,"urgency":"low","summary":"tranquilo","confidence":0.9}

            Transcript: $transcript
            JSON:
        """.trimIndent()

        private fun buildAudioPrompt(): String = """
            Sos un parser de reportes de voluntarios en espanol rioplatense.
            Escucha el audio adjunto, transcribi mentalmente y devolve SOLO un JSON con claves:
            water_level_category, trend, road_status, bridge_status, homes_affected, urgency, summary, confidence.

            Ejemplo: {"water_level_category":"critical","trend":"rising","road_status":"blocked","bridge_status":"unknown","homes_affected":false,"urgency":"critical","summary":"paso la marca","confidence":0.9}

            JSON:
        """.trimIndent()
    }
}
