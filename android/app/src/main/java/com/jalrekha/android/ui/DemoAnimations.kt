package com.jalrekha.android.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.coroutines.delay

@Composable
fun rememberPulse(periodMs: Int = 1400, min: Float = 0.55f, max: Float = 1f): Float {
    val transition = rememberInfiniteTransition(label = "pulse")
    val v by transition.animateFloat(
        initialValue = min,
        targetValue = max,
        animationSpec = infiniteRepeatable(
            animation = tween(periodMs, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse-v",
    )
    return v
}

@Composable
fun rememberAnimatedRatio(target: Float, durationMs: Int = 1200): State<Float> {
    return animateFloatAsState(
        targetValue = target.coerceIn(0f, 1f),
        animationSpec = tween(durationMs, easing = LinearEasing),
        label = "ratio",
    )
}

@Composable
fun rememberTyping(text: String, msPerChar: Int = 18): String {
    var visible by remember(text) { mutableIntStateOf(0) }
    LaunchedEffect(text) {
        visible = 0
        for (i in 1..text.length) {
            visible = i
            delay(msPerChar.toLong())
        }
    }
    return text.take(visible)
}

@Composable
fun rememberCounter(target: Int, durationMs: Int = 700): Int {
    var current by remember(target) { mutableIntStateOf(0) }
    LaunchedEffect(target) {
        if (target <= 0) {
            current = 0
            return@LaunchedEffect
        }
        val steps = 24
        val stepDelay = (durationMs / steps).coerceAtLeast(8)
        for (i in 1..steps) {
            current = (target.toFloat() * i / steps).toInt()
            delay(stepDelay.toLong())
        }
        current = target
    }
    return current
}
