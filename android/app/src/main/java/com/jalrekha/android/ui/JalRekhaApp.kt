package com.jalrekha.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.MicOff
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import kotlinx.coroutines.launch
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import coil.compose.AsyncImage
import com.jalrekha.android.data.AlertSummary
import com.jalrekha.android.data.CalibrationPayload
import com.jalrekha.android.data.PendingReportEntity
import com.jalrekha.android.data.SiteSummary
import com.google.gson.Gson

private val Emerald = DemoPalette.Emerald
private val River = DemoPalette.River
private val Clay = DemoPalette.Clay
private val Sand = DemoPalette.SandLight

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JalRekhaApp(viewModel: MainViewModel) {
    val navController = rememberNavController()
    val dashboard by viewModel.dashboard.collectAsState()
    val siteState by viewModel.siteState.collectAsState()
    val pendingReports by viewModel.pendingReports.collectAsState()
    val serverUrl by viewModel.serverUrl.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    LaunchedEffect(dashboard.error, siteState.message, siteState.error) {
        listOfNotNull(dashboard.error, siteState.message, siteState.error).firstOrNull()?.let {
            snackbarHostState.showSnackbar(it)
        }
    }

    MaterialTheme {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(
                        selected = currentRoute == "dashboard",
                        onClick = { navController.navigate("dashboard") },
                        label = { Text("Dashboard") },
                        icon = { Icon(Icons.Rounded.Refresh, null) },
                    )
                    NavigationBarItem(
                        selected = currentRoute == "queue",
                        onClick = { navController.navigate("queue") },
                        label = { Text("Queue") },
                        icon = { Icon(Icons.Rounded.CloudUpload, null) },
                    )
                    NavigationBarItem(
                        selected = currentRoute == "settings",
                        onClick = { navController.navigate("settings") },
                        label = { Text("Settings") },
                        icon = { Icon(Icons.Rounded.Save, null) },
                    )
                }
            },
        ) { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = "dashboard",
                modifier = Modifier.padding(innerPadding),
            ) {
                composable("dashboard") {
                    DashboardScreen(
                        state = dashboard,
                        queueCount = pendingReports.size,
                        onRefresh = viewModel::refreshDashboard,
                        onOpenSite = { navController.navigate("site/$it") },
                    )
                }
                composable("queue") {
                    QueueScreen(
                        reports = pendingReports,
                        onFlush = viewModel::flushPendingReports,
                    )
                }
                composable("settings") {
                    SettingsScreen(
                        serverUrl = serverUrl,
                        onSaveServerUrl = viewModel::updateServerUrl,
                        onSetBackendConnectivity = viewModel::setBackendConnectivity,
                    )
                }
                composable(
                    route = "site/{siteId}",
                    arguments = listOf(navArgument("siteId") { type = NavType.StringType }),
                ) { backStack ->
                    val siteId = backStack.arguments?.getString("siteId").orEmpty()
                    LaunchedEffect(siteId) { viewModel.loadSite(siteId) }
                    SiteDetailScreen(
                        state = siteState,
                        onAnalyzeSample = { viewModel.analyzeSample(siteId) },
                        onRefreshHydromet = { viewModel.refreshSnapshot(siteId) },
                        onPickScenario = { scenario -> viewModel.runDemoScenario(siteId, scenario) },
                        onClearScenario = viewModel::clearActiveScenario,
                        onSubmitReport = { name, role, transcript, offline, audio ->
                            viewModel.submitReport(siteId, name, role, transcript, offline, audio)
                        },
                        onCalibrate = { navController.navigate("site/$siteId/calibration") },
                    )
                }
                composable(
                    route = "site/{siteId}/calibration",
                    arguments = listOf(navArgument("siteId") { type = NavType.StringType }),
                ) { backStack ->
                    val siteId = backStack.arguments?.getString("siteId").orEmpty()
                    CalibrationScreen(
                        state = siteState,
                        onSave = { payload -> viewModel.saveCalibration(siteId, payload) { navController.popBackStack() } },
                    )
                }
            }
        }
    }
}

@Composable
private fun DashboardScreen(
    state: DashboardState,
    queueCount: Int,
    onRefresh: () -> Unit,
    onOpenSite: (String) -> Unit,
) {
    val counts = remember(state.alerts) {
        val byLevel = state.alerts.groupBy { it.level.lowercase() }
        intArrayOf(
            (byLevel["red"]?.size ?: 0) + (byLevel["critical"]?.size ?: 0),
            (byLevel["orange"]?.size ?: 0) + (byLevel["high"]?.size ?: 0),
            (byLevel["yellow"]?.size ?: 0) + (byLevel["watch"]?.size ?: 0),
            (byLevel["green"]?.size ?: 0) + (byLevel["low"]?.size ?: 0),
        )
    }
    val topAlert = state.alerts.firstOrNull { it.level.lowercase() in setOf("red", "critical") }
        ?: state.alerts.firstOrNull { it.level.lowercase() in setOf("orange", "high") }
        ?: state.alerts.firstOrNull()
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { DashboardHero(state, queueCount, onRefresh) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                MetricCard("Critical", counts[0], DemoPalette.AlertRed, Modifier.weight(1f))
                MetricCard("High", counts[1], DemoPalette.AlertOrange, Modifier.weight(1f))
                MetricCard("Watch", counts[2], DemoPalette.AlertYellow, Modifier.weight(1f))
                MetricCard("Stable", counts[3], DemoPalette.AlertGreen, Modifier.weight(1f))
            }
        }
        if (topAlert != null) {
            item { TopAlertCard(topAlert, onOpenSite) }
        }
        item {
            Text("All alerts", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, color = DemoPalette.Ink)
        }
        items(state.alerts) { alert -> AlertCard(alert) }
        item {
            Text("Sites", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, color = DemoPalette.Ink)
        }
        items(state.sites) { site -> SiteRow(site, state.alerts, onOpenSite) }
    }
}

@Composable
private fun DashboardHero(state: DashboardState, queueCount: Int, onRefresh: () -> Unit) {
    val llmReachable = state.runtime?.llm?.reachable == true
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(HeroGradient)
            .padding(20.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LivePulseDot(
                    color = if (llmReachable) DemoPalette.AlertGreen else DemoPalette.AlertRed,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (llmReachable) "LIVE" else "OFFLINE",
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelMedium,
                )
                Spacer(Modifier.width(12.dp))
                Text(
                    state.runtime?.llm?.model ?: "—",
                    color = Color(0xFFB8D3DD),
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Text(
                "JalRekha",
                color = Color.White,
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "On-edge water-level monitoring with Gemma reasoning over the camera-node clips.",
                color = Color(0xFFD2E0E6),
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = onRefresh,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color.White,
                        contentColor = DemoPalette.EmeraldDeep,
                    ),
                ) {
                    Icon(Icons.Rounded.Refresh, null)
                    Spacer(Modifier.width(6.dp))
                    Text(if (state.isLoading) "Refreshing…" else "Refresh")
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(50))
                        .background(Color(0x33FFFFFF))
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    Text(
                        "Queue · $queueCount",
                        color = Color.White,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
        }
    }
}

@Composable
private fun TopAlertCard(alert: AlertSummary, onOpenSite: (String) -> Unit) {
    val severity = severityTokensFor(alert.level)
    val pulsing = alert.level.lowercase() in setOf("red", "critical")
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(severity.gradient)
            .clickable { onOpenSite(alert.siteId) }
            .padding(18.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SeverityBadge(severity = severity, pulsing = pulsing)
                Text(
                    "Top alert · ${alert.siteId}",
                    color = Color.White.copy(alpha = 0.9f),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text(
                alert.summary,
                color = Color.White,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                "score ${String.format("%.2f", alert.score)} · tap to inspect",
                color = Color.White.copy(alpha = 0.85f),
                style = MaterialTheme.typography.labelMedium,
            )
        }
    }
}

@Composable
private fun AlertCard(alert: AlertSummary) {
    val severity = severityTokensFor(alert.level)
    Card(colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard)) {
        Row(modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
            Box(
                modifier = Modifier
                    .width(6.dp)
                    .fillMaxHeight()
                    .background(severity.solid),
            )
            Column(Modifier.padding(14.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SeverityBadge(severity = severity)
                    Text(alert.siteId, color = DemoPalette.InkSoft, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                }
                Text(alert.summary, fontWeight = FontWeight.Medium, color = DemoPalette.Ink)
                Text(
                    "score ${String.format("%.2f", alert.score)} · ${alert.createdAt}",
                    style = MaterialTheme.typography.bodySmall,
                    color = DemoPalette.InkSoft,
                )
                ReasoningPanel(alert)
            }
        }
    }
}

@Composable
private fun SiteRow(site: SiteSummary, alerts: List<AlertSummary>, onOpenSite: (String) -> Unit) {
    val worst = alerts.filter { it.siteId == site.id }
        .maxByOrNull {
            when (it.level.lowercase()) {
                "red", "critical" -> 4
                "orange", "high" -> 3
                "yellow", "watch" -> 2
                "green", "low" -> 1
                else -> 0
            }
        }
    val severity = severityTokensFor(worst?.level)
    Card(
        modifier = Modifier.fillMaxWidth().clickable { onOpenSite(site.id) },
        colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard),
    ) {
        Row(modifier = Modifier.height(IntrinsicSize.Min)) {
            Box(modifier = Modifier.width(6.dp).fillMaxHeight().background(severity.solid))
            Column(Modifier.padding(14.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(site.name, fontWeight = FontWeight.Bold, color = DemoPalette.Ink)
                    if (worst != null) SeverityBadge(severity = severity)
                }
                Text(site.region, color = DemoPalette.InkSoft, style = MaterialTheme.typography.bodySmall)
                site.description?.let {
                    Text(it, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = DemoPalette.Ink)
                }
            }
        }
    }
}

@Composable
private fun ReasoningPanel(alert: AlertSummary) {
    val summary = alert.reasoningSummary ?: return
    var expanded by remember { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = !expanded }, contentPadding = PaddingValues(0.dp)) {
            Text(
                if (expanded) "Hide Gemma reasoning" else "Gemma reasoning (${alert.reasoningModel ?: "local"})",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        if (expanded) {
            Text(summary, style = MaterialTheme.typography.bodySmall)
            val chain = alert.reasoningChain
            if (!chain.isNullOrBlank()) {
                val parsedChain: String = try {
                    val items = Gson().fromJson(chain, Array<String>::class.java) ?: emptyArray()
                    items.joinToString(" → ")
                } catch (_: Exception) {
                    chain.trim('[', ']').replace("\"", "")
                }
                Text(parsedChain, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun SiteDetailScreen(
    state: SiteScreenState,
    onAnalyzeSample: () -> Unit,
    onRefreshHydromet: () -> Unit,
    onPickScenario: (DemoScenario) -> Unit,
    onClearScenario: () -> Unit,
    onSubmitReport: (String, String, String, Boolean, ByteArray?) -> Unit,
    onCalibrate: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        SiteHeader(state)
        ScenarioPickerRow(state.activeScenario, onPickScenario, onClearScenario)
        SiteActionRow(state.isStreaming, onRefreshHydromet, onAnalyzeSample, onCalibrate)
        AnalysisVisualization(state)
        StreamingLog(events = state.analysisStream, isStreaming = state.isStreaming, modifier = Modifier.fillMaxWidth())
        state.analysis?.alert?.let { AnalysisAlertCard(it) }
        state.snapshot?.let { HydrometCard(it) }
        VolunteerReportCard(state, onSubmitReport)
    }
}

@Composable
private fun SiteHeader(state: SiteScreenState) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(HeroGradient)
            .padding(16.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LivePulseDot(color = DemoPalette.RiverLight)
                Spacer(Modifier.width(8.dp))
                Text(
                    state.site?.id ?: "—",
                    color = Color(0xFFB8D3DD),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text(
                state.site?.name ?: "Site",
                color = Color.White,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            state.site?.region?.let {
                Text(it, color = Color(0xFFD2E0E6), style = MaterialTheme.typography.bodyMedium)
            }
            state.site?.sampleFrameUrl?.let { frame ->
                Spacer(Modifier.height(6.dp))
                AsyncImage(
                    model = frame,
                    contentDescription = "Calibration frame",
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)),
                )
            }
        }
    }
}

@Composable
private fun ScenarioPickerRow(
    active: DemoScenario?,
    onPick: (DemoScenario) -> Unit,
    onClear: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Demo scenario",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold,
                color = DemoPalette.Ink,
            )
            if (active != null) {
                TextButton(onClick = onClear, contentPadding = PaddingValues(horizontal = 6.dp)) {
                    Text("Clear", style = MaterialTheme.typography.labelMedium, color = DemoPalette.River)
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            DemoScenario.entries.forEach { scenario ->
                ScenarioChip(
                    scenario = scenario,
                    selected = active == scenario,
                    onClick = { onPick(scenario) },
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun SiteActionRow(
    streaming: Boolean,
    onRefreshHydromet: () -> Unit,
    onAnalyzeSample: () -> Unit,
    onCalibrate: () -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        Button(
            onClick = onRefreshHydromet,
            modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(containerColor = DemoPalette.River),
        ) {
            Icon(Icons.Rounded.Refresh, null)
            Spacer(Modifier.width(4.dp))
            Text("Hydromet", style = MaterialTheme.typography.labelMedium)
        }
        Button(
            onClick = onAnalyzeSample,
            enabled = !streaming,
            modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(containerColor = DemoPalette.EmeraldSoft),
        ) {
            Icon(Icons.Rounded.PlayArrow, null)
            Spacer(Modifier.width(4.dp))
            Text(if (streaming) "Streaming…" else "Analyze", style = MaterialTheme.typography.labelMedium)
        }
        Button(
            onClick = onCalibrate,
            modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(containerColor = DemoPalette.Clay),
        ) {
            Text("Calibrate", style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
private fun AnalysisVisualization(state: SiteScreenState) {
    val observation = state.analysis?.observation
    val ratio = observation?.waterlineRatio?.toFloat() ?: 0f
    val velocity = observation?.riseVelocity?.toFloat() ?: 0f
    val severity = severityTokensFor(state.analysis?.alert?.level)
    Card(colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Waterline analysis",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = DemoPalette.Ink,
                )
                Spacer(Modifier.width(8.dp))
                if (state.isStreaming) {
                    LivePulseDot(color = DemoPalette.RiverLight, size = 8)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                WaterlineGauge(
                    ratio = ratio,
                    severity = severity,
                    modifier = Modifier.weight(1.2f),
                )
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    RiseVelocityMeter(cmPerHour = velocity)
                    Column {
                        Text("Frames analyzed", style = MaterialTheme.typography.labelMedium, color = DemoPalette.InkSoft)
                        Text(
                            (observation?.framesAnalyzed ?: 0).toString(),
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.titleLarge,
                            color = DemoPalette.Ink,
                        )
                    }
                    Column {
                        Text("Confidence", style = MaterialTheme.typography.labelMedium, color = DemoPalette.InkSoft)
                        Text(
                            "%.0f%%".format((observation?.confidence ?: 0.0) * 100),
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.titleLarge,
                            color = DemoPalette.Ink,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun AnalysisAlertCard(alert: AlertSummary) {
    val severity = severityTokensFor(alert.level)
    val pulsing = alert.level.lowercase() in setOf("red", "critical")
    val typedSummary = rememberTyping(alert.summary)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(severity.gradient)
            .padding(16.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SeverityBadge(severity = severity, pulsing = pulsing)
                Text(
                    "score ${String.format("%.2f", alert.score)}",
                    color = Color.White.copy(alpha = 0.9f),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text(
                typedSummary,
                color = Color.White,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            alert.reasoningChain?.let { chain ->
                val parsed = try {
                    Gson().fromJson(chain, Array<String>::class.java)?.toList() ?: emptyList()
                } catch (_: Exception) {
                    listOf(chain.trim('[', ']').replace("\"", ""))
                }
                parsed.forEach { step ->
                    Text(
                        "» $step",
                        color = Color.White.copy(alpha = 0.92f),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
}

@Composable
private fun HydrometCard(snapshot: com.jalrekha.android.data.ExternalSnapshot) {
    Card(colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Hydromet", fontWeight = FontWeight.SemiBold, color = DemoPalette.Ink, style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.width(8.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(50))
                        .background(DemoPalette.River.copy(alpha = 0.12f))
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                ) {
                    Text(
                        "signal ${String.format("%.0f%%", snapshot.signalScore * 100)}",
                        color = DemoPalette.River,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            Text(snapshot.summary, color = DemoPalette.Ink, style = MaterialTheme.typography.bodyMedium)
            Text(
                "rain ${snapshot.precipitationMm} mm · p(rain) ${String.format("%.0f%%", snapshot.precipitationProbability * 100)}",
                style = MaterialTheme.typography.bodySmall,
                color = DemoPalette.InkSoft,
            )
        }
    }
}

@Composable
private fun VolunteerReportCard(
    state: SiteScreenState,
    onSubmitReport: (String, String, String, Boolean, ByteArray?) -> Unit,
) {
    var reporterName by rememberSaveable { mutableStateOf("Android Operator") }
    var reporterRole by rememberSaveable { mutableStateOf("brigade member") }
    var transcriptText by rememberSaveable { mutableStateOf("Water has already crossed the critical mark and brings mud, evacuate low zone.") }
    var saveOffline by rememberSaveable { mutableStateOf(false) }
    val ctx = LocalContext.current
    val recorder = remember { com.jalrekha.android.data.AudioRecorder() }
    var isRecording by remember { mutableStateOf(false) }
    var pendingAudio by remember { mutableStateOf<ByteArray?>(null) }
    val coroutineScope = androidx.compose.runtime.rememberCoroutineScope()
    Card(colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Volunteer report", fontWeight = FontWeight.SemiBold, color = DemoPalette.Ink, style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(value = reporterName, onValueChange = { reporterName = it }, label = { Text("Reporter") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = reporterRole, onValueChange = { reporterRole = it }, label = { Text("Role") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = transcriptText, onValueChange = { transcriptText = it }, label = { Text("Transcript") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    onClick = {
                        if (!isRecording) {
                            recorder.start()
                            isRecording = true
                            pendingAudio = null
                        } else {
                            isRecording = false
                            coroutineScope.launch {
                                val wav = recorder.stopAndBuildWav()
                                pendingAudio = wav
                                if (wav != null) {
                                    runCatching {
                                        java.io.File(ctx.cacheDir, "last_recording.wav").writeBytes(wav)
                                    }
                                }
                            }
                        }
                    },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (isRecording) Color(0xFFB91C1C) else DemoPalette.River,
                    ),
                ) {
                    Icon(if (isRecording) Icons.Rounded.MicOff else Icons.Rounded.Mic, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(if (isRecording) "Stop" else "Record audio")
                }
                pendingAudio?.let { Text("audio ${it.size / 1024} KB", style = MaterialTheme.typography.bodySmall, color = DemoPalette.InkSoft) }
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Switch(checked = saveOffline, onCheckedChange = { saveOffline = it })
                Text("Force offline queue", color = DemoPalette.Ink, style = MaterialTheme.typography.bodyMedium)
            }
            Button(
                onClick = {
                    onSubmitReport(reporterName, reporterRole, transcriptText, saveOffline, pendingAudio)
                    pendingAudio = null
                },
                enabled = !state.isSubmitting && !isRecording,
                colors = ButtonDefaults.buttonColors(containerColor = DemoPalette.Emerald),
            ) {
                Text(if (state.isSubmitting) "Submitting…" else "Send report")
            }
            state.reportResult?.let { result ->
                val parserLabel = when (result.parsed.parserSource) {
                    "gemma-android" -> "Analyzed with Gemma on this device"
                    "llm" -> "Analyzed by Gemma on the server"
                    "rules" -> "Structured by local rules"
                    else -> "Source: ${result.parsed.parserSource}"
                }
                AssistChip(onClick = {}, label = { Text(parserLabel) })
                val typedSummary = rememberTyping(result.alert.summary)
                Text(
                    "urgency ${result.parsed.urgency} · water ${result.parsed.waterLevelCategory}",
                    style = MaterialTheme.typography.bodySmall,
                    color = DemoPalette.InkSoft,
                )
                Text(typedSummary, color = DemoPalette.Ink, fontWeight = FontWeight.Medium)
            }
        }
    }
}

@Composable
private fun CalibrationScreen(
    state: SiteScreenState,
    onSave: (CalibrationPayload) -> Unit,
) {
    var width by rememberSaveable { mutableStateOf("980") }
    var roiTop by rememberSaveable { mutableStateOf("70") }
    var roiBottom by rememberSaveable { mutableStateOf("265") }
    var criticalY by rememberSaveable { mutableStateOf("118") }
    var referenceY by rememberSaveable { mutableStateOf("190") }
    var notes by rememberSaveable { mutableStateOf(state.calibration?.notes ?: "Android calibration update") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Calibration", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        state.site?.sampleFrameUrl?.let { AsyncImage(model = it, contentDescription = null, modifier = Modifier.fillMaxWidth()) }
        NumericField("Frame width", width) { width = it }
        NumericField("ROI top", roiTop) { roiTop = it }
        NumericField("ROI bottom", roiBottom) { roiBottom = it }
        NumericField("Critical Y", criticalY) { criticalY = it }
        NumericField("Reference Y", referenceY) { referenceY = it }
        OutlinedTextField(value = notes, onValueChange = { notes = it }, label = { Text("Notes") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
        Button(onClick = {
            val frameWidth = width.toIntOrNull() ?: 980
            val payload = CalibrationPayload(
                roiPolygon = listOf(listOf(0, roiTop.toIntOrNull() ?: 70), listOf(frameWidth, roiTop.toIntOrNull() ?: 70), listOf(frameWidth, roiBottom.toIntOrNull() ?: 265), listOf(0, roiBottom.toIntOrNull() ?: 265)),
                criticalLine = listOf(listOf(0, criticalY.toIntOrNull() ?: 118), listOf(frameWidth, criticalY.toIntOrNull() ?: 118)),
                referenceLine = listOf(listOf(0, referenceY.toIntOrNull() ?: 190), listOf(frameWidth, referenceY.toIntOrNull() ?: 190)),
                notes = notes,
            )
            onSave(payload)
        }) { Text("Save calibration") }
    }
}

@Composable
private fun NumericField(label: String, value: String, onValueChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun QueueScreen(reports: List<PendingReportEntity>, onFlush: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Offline queue", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = DemoPalette.Ink)
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(DemoPalette.Clay.copy(alpha = 0.15f))
                    .padding(horizontal = 10.dp, vertical = 4.dp),
            ) {
                Text(
                    "${reports.size} pending",
                    color = DemoPalette.Clay,
                    fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
        }
        Button(
            onClick = onFlush,
            enabled = reports.isNotEmpty(),
            colors = ButtonDefaults.buttonColors(containerColor = DemoPalette.River),
        ) {
            Icon(Icons.Rounded.CloudUpload, null)
            Spacer(Modifier.width(6.dp))
            Text("Flush queue")
        }
        LazyColumn(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(reports) { report ->
                Card(colors = CardDefaults.cardColors(containerColor = DemoPalette.SurfaceCard)) {
                    Row(modifier = Modifier.height(IntrinsicSize.Min)) {
                        Box(modifier = Modifier.width(4.dp).fillMaxHeight().background(DemoPalette.Clay))
                        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(report.siteId, fontWeight = FontWeight.Bold, color = DemoPalette.Ink)
                            Text(
                                "${report.reporterName} · ${report.reporterRole}",
                                style = MaterialTheme.typography.bodySmall,
                                color = DemoPalette.InkSoft,
                            )
                            Text(report.transcriptText, color = DemoPalette.Ink, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    serverUrl: String,
    onSaveServerUrl: (String) -> Unit,
    onSetBackendConnectivity: (Boolean) -> Unit,
) {
    var editableUrl by rememberSaveable(serverUrl) { mutableStateOf(serverUrl) }
    var backendOnline by rememberSaveable { mutableStateOf(true) }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Sand)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("By default the emulator uses 10.0.2.2 to reach the local FastAPI backend.")
        OutlinedTextField(value = editableUrl, onValueChange = { editableUrl = it }, label = { Text("API base URL") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { onSaveServerUrl(editableUrl) }) { Text("Save URL") }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Switch(checked = backendOnline, onCheckedChange = {
                backendOnline = it
                onSetBackendConnectivity(it)
            })
            Text("Backend connectivity toggle")
        }
    }
}
