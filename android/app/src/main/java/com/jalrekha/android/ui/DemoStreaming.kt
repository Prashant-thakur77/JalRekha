package com.jalrekha.android.ui

import com.jalrekha.android.data.AlertSummary
import com.jalrekha.android.data.NodeAnalysisResponse
import com.jalrekha.android.data.NodeObservation
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow

enum class StreamEventKind { STEP, SUBSTEP, REASONING, RESULT, ERROR }

data class AnalysisStreamEvent(
    val id: Long,
    val text: String,
    val kind: StreamEventKind,
    val done: Boolean = false,
)

enum class DemoScenario(
    val label: String,
    val emoji: String,
    val description: String,
) {
    CALM(
        label = "Calm river",
        emoji = "🌱",
        description = "Stable baseline, no rise detected.",
    ),
    RISING(
        label = "Rising water",
        emoji = "🌧",
        description = "Sustained rise, approaching warning band.",
    ),
    CRITICAL(
        label = "Critical surge",
        emoji = "🚨",
        description = "Crossed critical mark, evacuate low zone.",
    ),
}

object DemoMocks {
    fun analysis(scenario: DemoScenario, siteId: String): NodeAnalysisResponse = when (scenario) {
        DemoScenario.CALM -> NodeAnalysisResponse(
            observation = NodeObservation(
                siteId = siteId,
                framesAnalyzed = 24,
                waterlineRatio = 0.31,
                riseVelocity = 0.4,
                confidence = 0.92,
                crossedCriticalLine = false,
                evidenceFrameUrl = null,
            ),
            alert = AlertSummary(
                id = -1,
                siteId = siteId,
                level = "green",
                score = 0.12,
                summary = "Stable river. Waterline well below reference, no rise detected over the last 24 frames.",
                createdAt = "now",
                reasoningSummary = "Waterline ratio 0.31 sits comfortably under the reference band and rise velocity is negligible.",
                reasoningChain = "[\"frames sampled at 2fps\",\"waterline stable across window\",\"no critical line crossing\",\"recommend routine watch\"]",
                reasoningModel = "gemma-demo",
            ),
        )
        DemoScenario.RISING -> NodeAnalysisResponse(
            observation = NodeObservation(
                siteId = siteId,
                framesAnalyzed = 36,
                waterlineRatio = 0.68,
                riseVelocity = 1.4,
                confidence = 0.81,
                crossedCriticalLine = false,
                evidenceFrameUrl = null,
            ),
            alert = AlertSummary(
                id = -1,
                siteId = siteId,
                level = "orange",
                score = 0.62,
                summary = "Sustained rise detected. Waterline approaching warning band, ETA to critical mark ~22 min if trend holds.",
                createdAt = "now",
                reasoningSummary = "Waterline ratio climbed from 0.42 to 0.68 in the observation window; rise velocity stable above threshold.",
                reasoningChain = "[\"baseline ratio 0.42 (10 min ago)\",\"current ratio 0.68\",\"rise velocity sustained at 1.4 cm/h\",\"projected crossing in ~22 min\",\"recommend brigade pre-stage\"]",
                reasoningModel = "gemma-demo",
            ),
        )
        DemoScenario.CRITICAL -> NodeAnalysisResponse(
            observation = NodeObservation(
                siteId = siteId,
                framesAnalyzed = 48,
                waterlineRatio = 0.94,
                riseVelocity = 3.2,
                confidence = 0.88,
                crossedCriticalLine = true,
                evidenceFrameUrl = null,
            ),
            alert = AlertSummary(
                id = -1,
                siteId = siteId,
                level = "red",
                score = 0.91,
                summary = "Critical mark crossed. Evacuate low zone, close downstream bridge access, escalate to civil protection.",
                createdAt = "now",
                reasoningSummary = "Waterline crossed the critical line 4 minutes ago and continues to rise at 3.2 cm/h with high confidence.",
                reasoningChain = "[\"critical line crossed at t-4min\",\"rise velocity 3.2 cm/h (severe)\",\"turbidity spike in last 6 frames\",\"hydromet snapshot confirms upstream surge\",\"trigger RED alert, dispatch brigade\"]",
                reasoningModel = "gemma-demo",
            ),
        )
    }
}

object AnalysisScript {
    data class Step(val text: String, val kind: StreamEventKind, val delayMs: Long)

    fun stepsFor(scenario: DemoScenario?): List<Step> {
        val base = listOf(
            Step("Connecting to camera node…", StreamEventKind.STEP, 250),
            Step("Pulling last 48 frames @ 2 fps", StreamEventKind.SUBSTEP, 350),
            Step("Detecting waterline ROI", StreamEventKind.STEP, 400),
            Step("Segmenting water vs. bank", StreamEventKind.SUBSTEP, 300),
            Step("Computing waterline ratio", StreamEventKind.STEP, 380),
            Step("Estimating rise velocity", StreamEventKind.SUBSTEP, 320),
            Step("Cross-checking hydromet snapshot", StreamEventKind.STEP, 300),
            Step("Running Gemma reasoning", StreamEventKind.STEP, 250),
        )
        val tail = when (scenario) {
            DemoScenario.CRITICAL -> listOf(
                Step("critical line crossed at t-4min", StreamEventKind.REASONING, 280),
                Step("rise velocity 3.2 cm/h — severe", StreamEventKind.REASONING, 240),
                Step("turbidity spike in last 6 frames", StreamEventKind.REASONING, 240),
                Step("trigger RED alert", StreamEventKind.REASONING, 220),
            )
            DemoScenario.RISING -> listOf(
                Step("baseline ratio 0.42 → 0.68", StreamEventKind.REASONING, 260),
                Step("rise velocity 1.4 cm/h sustained", StreamEventKind.REASONING, 240),
                Step("projected critical crossing in ~22 min", StreamEventKind.REASONING, 240),
                Step("recommend brigade pre-stage", StreamEventKind.REASONING, 220),
            )
            DemoScenario.CALM -> listOf(
                Step("waterline stable across window", StreamEventKind.REASONING, 260),
                Step("rise velocity near zero", StreamEventKind.REASONING, 220),
                Step("recommend routine watch", StreamEventKind.REASONING, 220),
            )
            null -> listOf(
                Step("waterline metrics within nominal range", StreamEventKind.REASONING, 260),
                Step("composing alert envelope", StreamEventKind.REASONING, 220),
            )
        }
        return base + tail + Step("Alert envelope ready", StreamEventKind.RESULT, 240)
    }

    fun stream(scenario: DemoScenario?): Flow<AnalysisStreamEvent> = flow {
        var id = 0L
        for (step in stepsFor(scenario)) {
            delay(step.delayMs)
            emit(AnalysisStreamEvent(id = id++, text = step.text, kind = step.kind, done = step.kind != StreamEventKind.STEP))
        }
    }
}
