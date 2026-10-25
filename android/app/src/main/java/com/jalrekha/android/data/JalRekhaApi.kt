package com.jalrekha.android.data

import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path

interface JalRekhaApi {
    @GET("settings/runtime")
    suspend fun getRuntimeStatus(): RuntimeStatus

    @GET("alerts")
    suspend fun getAlerts(): List<AlertSummary>

    @GET("sites")
    suspend fun getSites(): List<SiteSummary>

    @GET("sites/{siteId}")
    suspend fun getSite(@Path("siteId") siteId: String): SiteDetail

    @GET("sites/{siteId}/calibration")
    suspend fun getCalibration(@Path("siteId") siteId: String): CalibrationResponse?

    @POST("sites/{siteId}/calibration")
    suspend fun saveCalibration(@Path("siteId") siteId: String, @Body payload: CalibrationPayload): CalibrationResponse

    @GET("sites/{siteId}/external-snapshot")
    suspend fun getExternalSnapshot(@Path("siteId") siteId: String): ExternalSnapshot

    @POST("sites/{siteId}/external-snapshot/refresh")
    suspend fun refreshExternalSnapshot(@Path("siteId") siteId: String): ExternalSnapshot

    @POST("sites/{siteId}/sample-node-analysis")
    suspend fun analyzeSample(@Path("siteId") siteId: String): NodeAnalysisResponse

    @Multipart
    @POST("reports")
    suspend fun submitReport(
        @Part("site_id") siteId: RequestBody,
        @Part("reporter_name") reporterName: RequestBody,
        @Part("reporter_role") reporterRole: RequestBody,
        @Part("transcript_text") transcriptText: RequestBody,
        @Part("offline_created") offlineCreated: RequestBody,
        @Part photo: MultipartBody.Part? = null,
        @Part audio: MultipartBody.Part? = null,
    ): ReportEnvelope

    @POST("sync/flush")
    suspend fun flushSync(): SyncFlushResponse

    @GET("settings/connectivity")
    suspend fun getConnectivity(): ConnectivityStatus

    @POST("settings/connectivity")
    suspend fun setConnectivity(@Body payload: ConnectivityStatus): ConnectivityStatus
}

object ApiFactory {
    fun create(baseUrl: String): JalRekhaApi {
        val logging = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC }
        val client = OkHttpClient.Builder().addInterceptor(logging).build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(JalRekhaApi::class.java)
    }
}
