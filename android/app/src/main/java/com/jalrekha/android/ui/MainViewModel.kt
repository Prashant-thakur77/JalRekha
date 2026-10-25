package com.jalrekha.android.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.jalrekha.android.JalRekhaApplication
import com.jalrekha.android.data.JalRekhaRepository
import com.jalrekha.android.data.AlertSummary
import com.jalrekha.android.data.CalibrationPayload
import com.jalrekha.android.data.CalibrationResponse
import com.jalrekha.android.data.ExternalSnapshot
import com.jalrekha.android.data.GemmaOnDevice
import com.jalrekha.android.data.LocalParsedObservation
import com.jalrekha.android.data.NodeAnalysisResponse
import com.jalrekha.android.data.PendingReportEntity
import com.jalrekha.android.data.ReportEnvelope
import com.jalrekha.android.data.RuntimeStatus
import com.jalrekha.android.data.SiteDetail
import com.jalrekha.android.data.SiteSummary
import com.jalrekha.android.data.VolunteerReport
import com.google.gson.Gson
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class DashboardState(
    val runtime: RuntimeStatus? = null,
    val sites: List<SiteSummary> = emptyList(),
    val alerts: List<AlertSummary> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

data class SiteScreenState(
    val site: SiteDetail? = null,
    val calibration: CalibrationResponse? = null,
    val snapshot: ExternalSnapshot? = null,
    val analysis: NodeAnalysisResponse? = null,
    val reportResult: ReportEnvelope? = null,
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val isStreaming: Boolean = false,
    val activeScenario: DemoScenario? = null,
    val analysisStream: List<AnalysisStreamEvent> = emptyList(),
    val message: String? = null,
    val error: String? = null,
)

class MainViewModel(
    private val repository: JalRekhaRepository,
    private val gemma: GemmaOnDevice? = null,
) : ViewModel() {
    private val _dashboard = MutableStateFlow(DashboardState(isLoading = true))
    val dashboard: StateFlow<DashboardState> = _dashboard.asStateFlow()

    private val _siteState = MutableStateFlow(SiteScreenState())
    val siteState: StateFlow<SiteScreenState> = _siteState.asStateFlow()

    private val _serverUrl = MutableStateFlow(repository.currentBaseUrl())
    val serverUrl: StateFlow<String> = _serverUrl.asStateFlow()

    val pendingReports = repository.observePendingReports()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    init {
        refreshDashboard()
    }

    fun refreshDashboard() {
        viewModelScope.launch {
            _dashboard.value = _dashboard.value.copy(isLoading = true, error = null)
            runCatching { repository.fetchDashboard() }
                .onSuccess { (runtime, sites, alerts) ->
                    _dashboard.value = DashboardState(
                        runtime = runtime,
                        sites = sites,
                        alerts = alerts,
                        isLoading = false,
                    )
                }
                .onFailure { error ->
                    _dashboard.value = _dashboard.value.copy(isLoading = false, error = error.message)
                }
        }
    }

    fun loadSite(siteId: String) {
        viewModelScope.launch {
            _siteState.value = SiteScreenState(isLoading = true)
            runCatching {
                Triple(
                    repository.fetchSite(siteId),
                    repository.fetchCalibration(siteId),
                    repository.fetchSnapshot(siteId),
                )
            }.onSuccess { (site, calibration, snapshot) ->
                _siteState.value = SiteScreenState(
                    site = site,
                    calibration = calibration,
                    snapshot = snapshot,
                    isLoading = false,
                )
            }.onFailure { error ->
                _siteState.value = SiteScreenState(isLoading = false, error = error.message)
            }
        }
    }

    fun refreshSnapshot(siteId: String) {
        viewModelScope.launch {
            _siteState.value = _siteState.value.copy(isLoading = true, error = null)
            runCatching { repository.refreshSnapshot(siteId) }
                .onSuccess { snapshot -> _siteState.value = _siteState.value.copy(snapshot = snapshot, isLoading = false) }
                .onFailure { error -> _siteState.value = _siteState.value.copy(isLoading = false, error = error.message) }
        }
    }

    /**
     * Run the real backend analysis while overlaying a scripted streaming log
     * so the demo feels alive. The two run in parallel; the result lands once
     * both the API call and the scripted stream complete.
     */
    fun analyzeSample(siteId: String) {
        viewModelScope.launch {
            val scenario = _siteState.value.activeScenario
            _siteState.value = _siteState.value.copy(
                isStreaming = true,
                error = null,
                analysisStream = emptyList(),
            )
            val deferredAnalysis = async {
                runCatching { repository.analyzeSample(siteId) }
            }
            AnalysisScript.stream(scenario).collect { event ->
                val current = _siteState.value
                _siteState.value = current.copy(analysisStream = current.analysisStream + event)
            }
            deferredAnalysis.await()
                .onSuccess { result ->
                    _siteState.value = _siteState.value.copy(
                        analysis = result,
                        isStreaming = false,
                    )
                }
                .onFailure { error ->
                    _siteState.value = _siteState.value.copy(
                        isStreaming = false,
                        error = error.message,
                    )
                }
        }
    }

    /**
     * Demo helper: pick a canned scenario and run the streaming animation
     * over a mock analysis response. Useful when presenting without a live
     * water-level signal to drive the real backend.
     */
    fun runDemoScenario(siteId: String, scenario: DemoScenario) {
        viewModelScope.launch {
            _siteState.value = _siteState.value.copy(
                activeScenario = scenario,
                isStreaming = true,
                analysisStream = emptyList(),
                analysis = null,
                error = null,
            )
            AnalysisScript.stream(scenario).collect { event ->
                val current = _siteState.value
                _siteState.value = current.copy(analysisStream = current.analysisStream + event)
            }
            _siteState.value = _siteState.value.copy(
                analysis = DemoMocks.analysis(scenario, siteId),
                isStreaming = false,
                message = "Demo scenario: ${scenario.label}.",
            )
        }
    }

    fun clearActiveScenario() {
        _siteState.value = _siteState.value.copy(
            activeScenario = null,
            analysisStream = emptyList(),
            analysis = null,
        )
    }

    fun submitReport(siteId: String, reporterName: String, reporterRole: String, transcriptText: String, forceOffline: Boolean, audioWav: ByteArray? = null) {
        viewModelScope.launch {
            _siteState.value = _siteState.value.copy(isSubmitting = true, message = null, error = null)
            // On-device Gemma fast path: when a model file is present we structure
            // the transcript locally and surface the result without hitting the
            // backend. Queue flushing remains a separate user action.
            val gemmaInstance = gemma
            if (gemmaInstance != null && gemmaInstance.isAvailable()) {
                runCatching {
                    val rawJson = gemmaInstance.structureReport(transcriptText, audioWav)
                    if (rawJson.isNullOrBlank()) {
                        null
                    } else {
                        Gson().fromJson(rawJson, LocalParsedObservation::class.java)
                            ?.toParsedObservation()
                    }
                }.onSuccess { parsed ->
                    if (parsed == null) {
                        _siteState.value = _siteState.value.copy(
                            isSubmitting = false,
                            error = "Local Gemma unavailable — use server connection.",
                        )
                    } else {
                        val envelope = ReportEnvelope(
                            report = VolunteerReport(
                                id = 0L,
                                siteId = siteId,
                                reporterName = reporterName,
                                reporterRole = reporterRole,
                                transcriptText = transcriptText,
                                offlineCreated = true,
                                createdAt = "",
                            ),
                            parsed = parsed.copy(parserSource = "gemma-android"),
                            alert = AlertSummary(
                                id = 0L,
                                siteId = siteId,
                                level = parsed.urgency,
                                score = parsed.confidence,
                                summary = parsed.summary,
                                createdAt = "",
                            ),
                        )
                        _siteState.value = _siteState.value.copy(
                            isSubmitting = false,
                            reportResult = envelope,
                            message = "Report structured locally with Gemma.",
                        )
                    }
                }.onFailure { error ->
                    _siteState.value = _siteState.value.copy(
                        isSubmitting = false,
                        error = "Local Gemma unavailable — use server connection.",
                    )
                }
                return@launch
            }
            runCatching {
                repository.submitOrQueueReport(siteId, reporterName, reporterRole, transcriptText, forceOffline)
            }.onSuccess { envelope ->
                _siteState.value = _siteState.value.copy(
                    isSubmitting = false,
                    reportResult = envelope,
                    message = if (envelope == null) "Report saved offline." else "Report sent to backend.",
                )
                refreshDashboard()
            }.onFailure { error ->
                _siteState.value = _siteState.value.copy(isSubmitting = false, error = error.message)
            }
        }
    }

    fun saveCalibration(siteId: String, payload: CalibrationPayload, onDone: () -> Unit) {
        viewModelScope.launch {
            _siteState.value = _siteState.value.copy(isSubmitting = true, message = null, error = null)
            runCatching { repository.saveCalibration(siteId, payload) }
                .onSuccess { calibration ->
                    _siteState.value = _siteState.value.copy(
                        calibration = calibration,
                        isSubmitting = false,
                        message = "Calibration saved.",
                    )
                    onDone()
                }
                .onFailure { error -> _siteState.value = _siteState.value.copy(isSubmitting = false, error = error.message) }
        }
    }

    fun flushPendingReports() {
        viewModelScope.launch {
            _dashboard.value = _dashboard.value.copy(isLoading = true, error = null)
            runCatching { repository.flushPendingReports() }
                .onSuccess {
                    _siteState.value = _siteState.value.copy(message = "Queue synced.")
                    refreshDashboard()
                }
                .onFailure { error ->
                    _dashboard.value = _dashboard.value.copy(isLoading = false, error = error.message)
                }
        }
    }

    fun updateServerUrl(url: String) {
        repository.updateBaseUrl(url)
        _serverUrl.value = repository.currentBaseUrl()
        refreshDashboard()
    }

    fun setBackendConnectivity(isOnline: Boolean) {
        viewModelScope.launch {
            runCatching { repository.setConnectivity(isOnline) }
                .onSuccess { refreshDashboard() }
                .onFailure { _dashboard.value = _dashboard.value.copy(error = it.message) }
        }
    }
}

class MainViewModelFactory(context: Context) : ViewModelProvider.Factory {
    private val repository = JalRekhaRepository.get(context)
    private val gemma: GemmaOnDevice? = (context.applicationContext as? JalRekhaApplication)?.gemma

    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return MainViewModel(repository, gemma) as T
    }
}
