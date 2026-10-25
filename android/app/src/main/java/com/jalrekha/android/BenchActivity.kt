package com.jalrekha.android

import android.app.Activity
import android.app.ActivityManager
import android.content.Context
import android.os.Bundle
import android.os.Debug
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File
import kotlin.system.measureTimeMillis

/**
 * Debug-only benchmark activity. Loads `gemma-4-E2B-it.litertlm` from
 * externalFilesDir, runs N representative Rioplatense flood-report transcripts
 * through the structuring prompt, and logs cold-start + per-prompt latency +
 * RSS via logcat tag `VolunteerBench`.
 *
 * Trigger:
 *   adb shell am start -n com.jalrekha.android/.BenchActivity
 *   adb logcat -s VolunteerBench:I
 */
class BenchActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "bench start pid=${android.os.Process.myPid()}")
        CoroutineScope(Dispatchers.IO).launch { runBench(applicationContext) }
    }

    private suspend fun runBench(ctx: Context) {
        val extDir = ctx.getExternalFilesDir(null) ?: run {
            Log.e(TAG, "no externalFilesDir"); finish(); return
        }
        val modelFile = File(extDir, "gemma-4-E2B-it.litertlm")
        if (!modelFile.exists()) {
            Log.e(TAG, "model missing at ${modelFile.absolutePath}"); finish(); return
        }
        Log.i(TAG, "model_size_bytes=${modelFile.length()}")

        val rssBefore = readRssKb()
        Log.i(TAG, "rss_before_load_kb=$rssBefore")

        val engine: Engine
        val coldMs = measureTimeMillis {
            val config = EngineConfig(
                modelPath = modelFile.absolutePath,
                backend = Backend.CPU(),
                visionBackend = Backend.CPU(),
                audioBackend = Backend.CPU(),
                maxNumTokens = 2048,
                maxNumImages = null,
                cacheDir = ctx.cacheDir.absolutePath,
            )
            engine = Engine(config)
            engine.initialize()
        }
        Log.i(TAG, "cold_start_ms=$coldMs")
        val rssAfter = readRssKb()
        Log.i(TAG, "rss_after_load_kb=$rssAfter")

        for ((i, transcript) in TRANSCRIPTS.withIndex()) {
            val prompt = buildPrompt(transcript)
            val rssPre = readRssKb()
            var output = ""
            val ms = measureTimeMillis {
                engine.createConversation().use { conv ->
                    val reply = conv.sendMessage(prompt, emptyMap())
                    output = reply.contents.contents
                        .filterIsInstance<com.google.ai.edge.litertlm.Content.Text>()
                        .joinToString("") { it.text }
                }
            }
            val rssPeak = readRssKb()
            val jsonStart = output.indexOf('{')
            val jsonEnd = output.lastIndexOf('}')
            val jsonOk = jsonStart >= 0 && jsonEnd > jsonStart
            val outChars = output.length
            Log.i(
                TAG,
                "prompt_idx=$i latency_ms=$ms rss_pre_kb=$rssPre rss_peak_kb=$rssPeak json_ok=$jsonOk out_chars=$outChars"
            )
            Log.i(TAG, "prompt_idx=$i raw=${output.take(300).replace("\n", " | ")}")
        }
        Log.i(TAG, "bench done")
        finish()
    }

    private fun readRssKb(): Long {
        val mi = Debug.MemoryInfo()
        Debug.getMemoryInfo(mi)
        // totalPss is a closer proxy to "what this process actually costs" than RSS.
        return mi.totalPss.toLong()
    }

    companion object {
        private const val TAG = "VolunteerBench"

        private val TRANSCRIPTS = listOf(
            "El agua ya paso la marca roja del puente, esta subiendo rapido y se cortaron dos calles cerca de la plaza.",
            "Vine al arroyo, esta tranquilo, el agua bajo un poco desde anoche, la calle de adelante esta libre.",
            "Mira, esto no me gusta nada, hay como 30 centimetros en la calle principal y no para de llover.",
            "Salio el sol, el rio esta normal, los vecinos ya volvieron a sus casas, el puente esta despejado.",
            "Recien pasamos por la ruta 8 y el agua tapa medio auto, hay gente que no puede salir de las casas.",
            "Esto ya esta complicado, el agua entra a los garajes, dos familias estan en el techo esperando.",
            "Tranquilo todo, paso una llovizna nomas, ningun arroyo desbordo, ni la cuneta se llenan.",
            "Hace media hora subio un monton, ahora esta bajando, pero la calle del fondo sigue intransitable.",
            "El bombero me dice que cortaron el puente nuevo porque el agua roza los pilares, mejor no pasen.",
            "No hay problema aca, todo seco, el medidor sigue en cero, la gente sigue con su vida normal."
        )

        private fun buildPrompt(transcript: String): String = """
            Sos un parser de reportes de voluntarios en espanol rioplatense.
            Devolve SOLO un JSON con claves: water_level_category, trend,
            road_status, bridge_status, homes_affected, urgency, summary, confidence.

            Ejemplo: {"water_level_category":"critical","trend":"rising","road_status":"blocked","bridge_status":"unknown","homes_affected":false,"urgency":"critical","summary":"paso la marca","confidence":0.9}
            Ejemplo: {"water_level_category":"low","trend":"stable","road_status":"open","bridge_status":"open","homes_affected":false,"urgency":"low","summary":"tranquilo","confidence":0.9}

            Transcript: $transcript
            JSON:
        """.trimIndent()
    }
}
