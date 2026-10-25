package com.jalrekha.android.data

import com.google.gson.annotations.SerializedName

/**
 * On-device counterpart of [ParsedObservation]. Mirrors the same JSON shape
 * produced by the backend few-shot prompt so Gson can decode either source
 * into a common model. When decoded from a Gemma-on-device payload, the
 * [parserSource] field defaults to "gemma-android" (the server never sends
 * that value).
 */
data class LocalParsedObservation(
    @SerializedName("water_level_category") val waterLevelCategory: String = "unknown",
    val trend: String = "unknown",
    @SerializedName("road_status") val roadStatus: String = "unknown",
    @SerializedName("bridge_status") val bridgeStatus: String = "unknown",
    val urgency: String = "low",
    val confidence: Double = 0.0,
    val summary: String = "",
    @SerializedName("parser_source") val parserSource: String = "gemma-android",
) {
    fun toParsedObservation(): ParsedObservation = ParsedObservation(
        waterLevelCategory = waterLevelCategory,
        trend = trend,
        roadStatus = roadStatus,
        bridgeStatus = bridgeStatus,
        urgency = urgency,
        confidence = confidence,
        summary = summary,
        parserSource = parserSource.ifBlank { "gemma-android" },
    )
}
