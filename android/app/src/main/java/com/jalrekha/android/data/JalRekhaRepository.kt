package com.jalrekha.android.data

import android.content.Context
import java.net.URI
import kotlinx.coroutines.flow.Flow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

class JalRekhaRepository private constructor(
    context: Context,
    db: AppDatabase = AppDatabase.get(context),
) {
    private val dao = db.pendingReportDao()
    private val configStore = ServerConfigStore(context)

    fun observePendingReports(): Flow<List<PendingReportEntity>> = dao.observeAll()
    fun currentBaseUrl(): String = configStore.getBaseUrl()
    fun updateBaseUrl(url: String) = configStore.setBaseUrl(url)

    private fun api(): JalRekhaApi = ApiFactory.create(configStore.getBaseUrl())

    suspend fun fetchDashboard(): Triple<RuntimeStatus, List<SiteSummary>, List<AlertSummary>> {
        val runtime = api().getRuntimeStatus()
        val sites = api().getSites()
        val alerts = api().getAlerts()
        return Triple(runtime, sites, alerts)
    }

    suspend fun fetchSite(siteId: String): SiteDetail {
        val site = api().getSite(siteId)
        return site.copy(
            sampleVideoUrl = absolutizeAsset(site.sampleVideoUrl),
            sampleFrameUrl = absolutizeAsset(site.sampleFrameUrl),
        )
    }

    suspend fun fetchCalibration(siteId: String): CalibrationResponse? = try {
        api().getCalibration(siteId)
    } catch (_: HttpException) {
        null
    }

    suspend fun fetchSnapshot(siteId: String): ExternalSnapshot? = try {
        api().getExternalSnapshot(siteId)
    } catch (_: HttpException) {
        null
    }

    suspend fun refreshSnapshot(siteId: String): ExternalSnapshot = api().refreshExternalSnapshot(siteId)

    suspend fun analyzeSample(siteId: String): NodeAnalysisResponse {
        val result = api().analyzeSample(siteId)
        return result.copy(
            observation = result.observation.copy(
                evidenceFrameUrl = absolutizeAsset(result.observation.evidenceFrameUrl),
            ),
        )
    }
    suspend fun setConnectivity(isOnline: Boolean): ConnectivityStatus = api().setConnectivity(ConnectivityStatus(isOnline))
    suspend fun getConnectivity(): ConnectivityStatus = api().getConnectivity()

    suspend fun saveCalibration(siteId: String, payload: CalibrationPayload) = api().saveCalibration(siteId, payload)

    suspend fun queueReport(siteId: String, reporterName: String, reporterRole: String, transcriptText: String) {
        dao.insert(
            PendingReportEntity(
                siteId = siteId,
                reporterName = reporterName,
                reporterRole = reporterRole,
                transcriptText = transcriptText,
                createdAt = System.currentTimeMillis(),
            )
        )
    }

    suspend fun submitOrQueueReport(
        siteId: String,
        reporterName: String,
        reporterRole: String,
        transcriptText: String,
        forceOffline: Boolean,
    ): ReportEnvelope? {
        if (forceOffline) {
            queueReport(siteId, reporterName, reporterRole, transcriptText)
            return null
        }
        return try {
            val result = submitReportInternal(siteId, reporterName, reporterRole, transcriptText, offlineCreated = false)
            api().flushSync()
            result
        } catch (_: Exception) {
            queueReport(siteId, reporterName, reporterRole, transcriptText)
            null
        }
    }

    suspend fun flushPendingReports(): SyncFlushResponse {
        var delivered = 0
        dao.getAll().forEach { pending ->
            submitReportInternal(
                siteId = pending.siteId,
                reporterName = pending.reporterName,
                reporterRole = pending.reporterRole,
                transcriptText = pending.transcriptText,
                offlineCreated = true,
            )
            dao.deleteById(pending.id)
            delivered += 1
        }
        val sync = api().flushSync()
        return sync.copy(flushed = sync.flushed.coerceAtLeast(delivered))
    }

    private suspend fun submitReportInternal(
        siteId: String,
        reporterName: String,
        reporterRole: String,
        transcriptText: String,
        offlineCreated: Boolean,
    ): ReportEnvelope {
        val text = "text/plain".toMediaType()
        return api().submitReport(
            siteId = siteId.toRequestBody(text),
            reporterName = reporterName.toRequestBody(text),
            reporterRole = reporterRole.toRequestBody(text),
            transcriptText = transcriptText.toRequestBody(text),
            offlineCreated = offlineCreated.toString().toRequestBody(text),
        )
    }

    private fun absolutizeAsset(path: String?): String? {
        if (path.isNullOrBlank()) {
            return null
        }
        if (path.startsWith("http://") || path.startsWith("https://")) {
            return path
        }
        val base = URI(configStore.getBaseUrl())
        return "${base.scheme}://${base.host}${if (base.port != -1) ":${base.port}" else ""}$path"
    }

    companion object {
        @Volatile private var instance: JalRekhaRepository? = null

        fun get(context: Context): JalRekhaRepository = instance ?: synchronized(this) {
            instance ?: JalRekhaRepository(context.applicationContext).also { instance = it }
        }

        /** Test seam — never wire this in production code. */
        internal fun forTest(context: Context, db: AppDatabase): JalRekhaRepository =
            JalRekhaRepository(context.applicationContext, db)
    }
}
