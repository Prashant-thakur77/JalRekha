package com.jalrekha.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey
import com.google.gson.annotations.SerializedName

data class RuntimeStatus(
    @SerializedName("is_online") val isOnline: Boolean,
    val llm: RuntimeHealth,
    val hydromet: RuntimeDependency,
)

data class RuntimeHealth(
    val enabled: Boolean,
    val reachable: Boolean,
    @SerializedName("base_url") val baseUrl: String,
    val model: String,
    val detail: String,
)

data class RuntimeDependency(
    val enabled: Boolean,
    val reachable: Boolean,
    val detail: String,
)

data class SiteSummary(
    val id: String,
    val name: String,
    val region: String,
    val lat: Double,
    val lng: Double,
    val description: String?,
    @SerializedName("is_active") val isActive: Boolean,
)

data class SiteDetail(
    val id: String,
    val name: String,
    val region: String,
    val lat: Double,
    val lng: Double,
    val description: String?,
    @SerializedName("is_active") val isActive: Boolean,
    @SerializedName("sample_video_url") val sampleVideoUrl: String?,
    @SerializedName("sample_video_source_url") val sampleVideoSourceUrl: String?,
    @SerializedName("sample_frame_url") val sampleFrameUrl: String?,
)

data class AlertSummary(
    val id: Long,
    @SerializedName("site_id") val siteId: String,
    val level: String,
    val score: Double,
    val summary: String,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("reasoning_summary") val reasoningSummary: String? = null,
    @SerializedName("reasoning_chain") val reasoningChain: String? = null,
    @SerializedName("reasoning_model") val reasoningModel: String? = null,
)

data class CalibrationResponse(
    @SerializedName("roi_polygon") val roiPolygon: String?,
    @SerializedName("critical_line") val criticalLine: String?,
    @SerializedName("reference_line") val referenceLine: String?,
    val notes: String?,
)

data class CalibrationPayload(
    @SerializedName("roi_polygon") val roiPolygon: List<List<Int>>,
    @SerializedName("critical_line") val criticalLine: List<List<Int>>,
    @SerializedName("reference_line") val referenceLine: List<List<Int>>,
    val notes: String,
)

data class ExternalSnapshot(
    @SerializedName("site_id") val siteId: String,
    @SerializedName("signal_score") val signalScore: Double,
    val summary: String,
    @SerializedName("precipitation_mm") val precipitationMm: Double,
    @SerializedName("precipitation_probability") val precipitationProbability: Double,
    @SerializedName("river_discharge") val riverDischarge: Double?,
    @SerializedName("river_discharge_max") val riverDischargeMax: Double?,
    @SerializedName("river_discharge_trend") val riverDischargeTrend: Double?,
)

data class NodeAnalysisResponse(
    val observation: NodeObservation,
    val alert: AlertSummary,
)

data class NodeObservation(
    @SerializedName("site_id") val siteId: String,
    @SerializedName("frames_analyzed") val framesAnalyzed: Int,
    @SerializedName("waterline_ratio") val waterlineRatio: Double,
    @SerializedName("rise_velocity") val riseVelocity: Double,
    val confidence: Double,
    @SerializedName("crossed_critical_line") val crossedCriticalLine: Boolean,
    @SerializedName("evidence_frame_url") val evidenceFrameUrl: String?,
)

data class ReportEnvelope(
    val report: VolunteerReport,
    val parsed: ParsedObservation,
    val alert: AlertSummary,
)

data class VolunteerReport(
    val id: Long,
    @SerializedName("site_id") val siteId: String,
    @SerializedName("reporter_name") val reporterName: String,
    @SerializedName("reporter_role") val reporterRole: String,
    @SerializedName("transcript_text") val transcriptText: String,
    @SerializedName("offline_created") val offlineCreated: Boolean,
    @SerializedName("created_at") val createdAt: String,
)

data class ParsedObservation(
    @SerializedName("water_level_category") val waterLevelCategory: String,
    val trend: String,
    @SerializedName("road_status") val roadStatus: String,
    @SerializedName("bridge_status") val bridgeStatus: String,
    val urgency: String,
    val confidence: Double,
    val summary: String,
    @SerializedName("parser_source") val parserSource: String,
)

data class ConnectivityStatus(
    @SerializedName("is_online") val isOnline: Boolean,
)

data class SyncFlushResponse(
    val queued: Int,
    val flushed: Int,
    val failed: Int,
)

@Entity(tableName = "pending_reports")
data class PendingReportEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val siteId: String,
    val reporterName: String,
    val reporterRole: String,
    val transcriptText: String,
    val createdAt: Long,
)
