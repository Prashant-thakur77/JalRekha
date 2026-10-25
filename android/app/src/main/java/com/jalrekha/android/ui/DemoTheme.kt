package com.jalrekha.android.ui

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

object DemoPalette {
    val Emerald = Color(0xFF0D3B2A)
    val EmeraldDeep = Color(0xFF06241A)
    val EmeraldSoft = Color(0xFF1F6A4C)
    val River = Color(0xFF1476B8)
    val RiverLight = Color(0xFF4FB3E8)
    val RiverDeep = Color(0xFF0C4C7A)
    val Clay = Color(0xFFB45F22)
    val Sand = Color(0xFFF3E9D2)
    val SandLight = Color(0xFFFBF6E8)
    val SurfaceDark = Color(0xFF0A1A22)
    val SurfaceCard = Color(0xFFFFFFFF)
    val Ink = Color(0xFF14232C)
    val InkSoft = Color(0xFF4B5C66)

    val AlertRed = Color(0xFFC23320)
    val AlertRedDeep = Color(0xFF7B1B0F)
    val AlertOrange = Color(0xFFE07B2C)
    val AlertYellow = Color(0xFFCE9A05)
    val AlertGreen = Color(0xFF2E7D5B)
    val AlertGrey = Color(0xFF6E7B82)
}

data class SeverityTokens(
    val label: String,
    val solid: Color,
    val soft: Color,
    val onSolid: Color,
    val gradient: Brush,
)

fun severityTokensFor(level: String?): SeverityTokens = when (level?.lowercase()) {
    "red", "critical" -> SeverityTokens(
        label = "CRITICAL",
        solid = DemoPalette.AlertRed,
        soft = Color(0xFFFCE5E1),
        onSolid = Color.White,
        gradient = Brush.linearGradient(
            colors = listOf(DemoPalette.AlertRed, DemoPalette.AlertRedDeep),
        ),
    )
    "orange", "high" -> SeverityTokens(
        label = "HIGH",
        solid = DemoPalette.AlertOrange,
        soft = Color(0xFFFDEAD8),
        onSolid = Color.White,
        gradient = Brush.linearGradient(
            colors = listOf(DemoPalette.AlertOrange, DemoPalette.Clay),
        ),
    )
    "yellow", "watch", "medium" -> SeverityTokens(
        label = "WATCH",
        solid = DemoPalette.AlertYellow,
        soft = Color(0xFFFAF1CF),
        onSolid = Color.White,
        gradient = Brush.linearGradient(
            colors = listOf(DemoPalette.AlertYellow, Color(0xFF8A6B05)),
        ),
    )
    "green", "low", "calm" -> SeverityTokens(
        label = "STABLE",
        solid = DemoPalette.AlertGreen,
        soft = Color(0xFFD9EFE4),
        onSolid = Color.White,
        gradient = Brush.linearGradient(
            colors = listOf(DemoPalette.AlertGreen, DemoPalette.EmeraldSoft),
        ),
    )
    else -> SeverityTokens(
        label = level?.uppercase() ?: "—",
        solid = DemoPalette.AlertGrey,
        soft = Color(0xFFE7ECEF),
        onSolid = Color.White,
        gradient = Brush.linearGradient(
            colors = listOf(DemoPalette.AlertGrey, DemoPalette.InkSoft),
        ),
    )
}

val HeroGradient: Brush = Brush.linearGradient(
    colors = listOf(DemoPalette.EmeraldDeep, DemoPalette.RiverDeep),
)

val WaterGradient: Brush = Brush.verticalGradient(
    colors = listOf(DemoPalette.RiverLight, DemoPalette.RiverDeep),
)
