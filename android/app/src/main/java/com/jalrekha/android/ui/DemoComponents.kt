package com.jalrekha.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@Composable
fun LivePulseDot(color: Color = DemoPalette.AlertGreen, size: Int = 10) {
    val alpha = rememberPulse(periodMs = 1200, min = 0.35f, max = 1f)
    Box(
        modifier = Modifier
            .size(size.dp)
            .alpha(alpha)
            .clip(RoundedCornerShape(50))
            .background(color),
    )
}

@Composable
fun SeverityBadge(
    severity: SeverityTokens,
    pulsing: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val alpha = if (pulsing) rememberPulse(periodMs = 1000, min = 0.65f, max = 1f) else 1f
    Box(
        modifier = modifier
            .alpha(alpha)
            .clip(RoundedCornerShape(50))
            .background(severity.gradient)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Text(
            severity.label,
            color = severity.onSolid,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
fun MetricCard(
    label: String,
    value: Int,
    accent: Color,
    modifier: Modifier = Modifier,
) {
    val animated = rememberCounter(value)
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .clip(RoundedCornerShape(50))
                        .background(accent),
                )
                Spacer(Modifier.width(6.dp))
                Text(label, style = MaterialTheme.typography.labelMedium, color = DemoPalette.InkSoft)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                animated.toString(),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = DemoPalette.Ink,
            )
        }
    }
}

@Composable
fun StreamingLog(
    events: List<AnalysisStreamEvent>,
    isStreaming: Boolean,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceDark),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LivePulseDot(
                    color = if (isStreaming) DemoPalette.RiverLight else DemoPalette.AlertGreen,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (isStreaming) "Streaming analysis…" else "Analysis complete",
                    color = Color.White,
                    fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            Spacer(Modifier.height(10.dp))
            if (events.isEmpty()) {
                Text(
                    "Tap Analyze sample or pick a demo scenario to start.",
                    color = Color(0xFF9AB1BC),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            events.forEach { event ->
                StreamLine(event)
            }
        }
    }
}

@Composable
private fun StreamLine(event: AnalysisStreamEvent) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
        verticalAlignment = Alignment.Top,
    ) {
        val (prefix, color) = when (event.kind) {
            StreamEventKind.STEP -> "▸" to DemoPalette.RiverLight
            StreamEventKind.SUBSTEP -> "  ·" to Color(0xFF7FA9BD)
            StreamEventKind.REASONING -> "  »" to Color(0xFFFFC663)
            StreamEventKind.RESULT -> "✓" to DemoPalette.AlertGreen
            StreamEventKind.ERROR -> "✕" to DemoPalette.AlertRed
        }
        Text(
            prefix,
            color = color,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.width(20.dp),
        )
        Spacer(Modifier.width(4.dp))
        val typed = rememberTyping(event.text, msPerChar = 14)
        Text(
            typed,
            color = if (event.kind == StreamEventKind.REASONING) Color(0xFFFFE2A8) else Color(0xFFD8E5EC),
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
fun ScenarioChip(
    scenario: DemoScenario,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val severity = when (scenario) {
        DemoScenario.CALM -> severityTokensFor("green")
        DemoScenario.RISING -> severityTokensFor("orange")
        DemoScenario.CRITICAL -> severityTokensFor("red")
    }
    val bg = if (selected) severity.solid else severity.soft
    val fg = if (selected) severity.onSolid else DemoPalette.Ink
    val alpha = if (selected && scenario == DemoScenario.CRITICAL) {
        rememberPulse(periodMs = 1100, min = 0.7f, max = 1f)
    } else 1f
    Box(
        modifier = modifier
            .alpha(alpha)
            .clip(RoundedCornerShape(14.dp))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(scenario.emoji, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.width(6.dp))
                Text(
                    scenario.label,
                    color = fg,
                    fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            Spacer(Modifier.height(2.dp))
            Text(
                scenario.description,
                color = if (selected) fg.copy(alpha = 0.85f) else DemoPalette.InkSoft,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
