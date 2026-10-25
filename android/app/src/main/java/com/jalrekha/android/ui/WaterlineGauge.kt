package com.jalrekha.android.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@Composable
fun WaterlineGauge(
    ratio: Float,
    criticalRatio: Float = 0.85f,
    referenceRatio: Float = 0.6f,
    severity: SeverityTokens,
    modifier: Modifier = Modifier,
) {
    val animated by rememberAnimatedRatio(ratio)
    Column(modifier = modifier) {
        Text("Waterline", style = MaterialTheme.typography.labelMedium, color = DemoPalette.InkSoft)
        Spacer(Modifier.height(6.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(150.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(Color(0xFFE7EEF2)),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .fillMaxSize(),
            ) {
                Canvas(modifier = Modifier.fillMaxSize()) {
                    val height = size.height
                    val width = size.width
                    val waterTop = height * (1f - animated)
                    drawRect(
                        brush = WaterGradient,
                        topLeft = Offset(0f, waterTop),
                        size = Size(width, height - waterTop),
                    )
                    val critY = height * (1f - criticalRatio)
                    drawLine(
                        color = DemoPalette.AlertRed,
                        start = Offset(0f, critY),
                        end = Offset(width, critY),
                        strokeWidth = 4f,
                    )
                    val refY = height * (1f - referenceRatio)
                    drawLine(
                        color = DemoPalette.AlertYellow,
                        start = Offset(0f, refY),
                        end = Offset(width, refY),
                        strokeWidth = 3f,
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 8f)),
                    )
                }
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.Top,
                ) {
                    Text(
                        text = "%.0f%%".format(animated * 100),
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.headlineSmall,
                    )
                    Column(horizontalAlignment = Alignment.End) {
                        Text(
                            "CRIT %.0f%%".format(criticalRatio * 100),
                            color = DemoPalette.AlertRed,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            "REF %.0f%%".format(referenceRatio * 100),
                            color = DemoPalette.AlertYellow,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .width(10.dp)
                    .height(10.dp)
                    .clip(RoundedCornerShape(50))
                    .background(severity.solid),
            )
            Spacer(Modifier.width(6.dp))
            Text(severity.label, style = MaterialTheme.typography.labelMedium, color = DemoPalette.Ink, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
fun RiseVelocityMeter(
    cmPerHour: Float,
    modifier: Modifier = Modifier,
) {
    val normalized = (cmPerHour / 5f).coerceIn(0f, 1f)
    val animated by rememberAnimatedRatio(normalized)
    val color = when {
        cmPerHour >= 2.5f -> DemoPalette.AlertRed
        cmPerHour >= 1f -> DemoPalette.AlertOrange
        cmPerHour >= 0.3f -> DemoPalette.AlertYellow
        else -> DemoPalette.AlertGreen
    }
    Column(modifier = modifier) {
        Text("Rise velocity", style = MaterialTheme.typography.labelMedium, color = DemoPalette.InkSoft)
        Spacer(Modifier.height(6.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Color(0xFFEEF3F6)),
        ) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val barHeight = size.height * 0.5f
                val y = (size.height - barHeight) / 2f
                drawRect(
                    color = color,
                    topLeft = Offset(0f, y),
                    size = Size(size.width * animated, barHeight),
                )
            }
            Row(
                modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "%.1f cm/h".format(cmPerHour),
                    fontWeight = FontWeight.Bold,
                    color = DemoPalette.Ink,
                )
                Text("max 5", style = MaterialTheme.typography.labelSmall, color = DemoPalette.InkSoft)
            }
        }
    }
}
