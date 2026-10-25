package com.jalrekha.android.ui

import androidx.arch.core.executor.testing.InstantTaskExecutorRule
import com.jalrekha.android.data.JalRekhaRepository
import com.jalrekha.android.data.GemmaOnDevice
import com.jalrekha.android.data.PendingReportEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.never
import org.mockito.kotlin.verifyBlocking
import org.mockito.kotlin.whenever

@OptIn(ExperimentalCoroutinesApi::class)
class MainViewModelTest {

    @get:Rule
    val instantTaskExecutorRule = InstantTaskExecutorRule()

    private val testDispatcher = StandardTestDispatcher()

    private lateinit var repository: JalRekhaRepository
    private lateinit var gemma: GemmaOnDevice

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        repository = mock {
            on { currentBaseUrl() } doReturn "http://localhost/api/"
            on { observePendingReports() } doReturn flowOf(emptyList<PendingReportEntity>())
        }
        gemma = mock()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `submitReport with available gemma sets parserSource gemma-android and skips backend`() = runTest(testDispatcher) {
        whenever(gemma.isAvailable()).thenReturn(true)
        whenever(gemma.structureReport(any())).thenReturn(
            "{\"water_level_category\":\"critical\"," +
                "\"trend\":\"rising\"," +
                "\"road_status\":\"blocked\"," +
                "\"bridge_status\":\"unknown\"," +
                "\"urgency\":\"critical\"," +
                "\"summary\":\"cruzo la marca\"," +
                "\"confidence\":0.9}"
        )

        val viewModel = MainViewModel(repository, gemma)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = false,
        )
        advanceUntilIdle()

        val result = viewModel.siteState.value.reportResult
        assertNotNull("expected report envelope to be populated", result)
        assertEquals("gemma-android", result!!.parsed.parserSource)
        assertEquals("Reporte estructurado localmente con Gemma.", viewModel.siteState.value.message)
        verifyBlocking(repository, never()) {
            submitOrQueueReport(any(), any(), any(), any(), any())
        }
    }

    @Test
    fun `submitReport with available gemma but null structuring sets error and skips backend`() = runTest(testDispatcher) {
        whenever(gemma.isAvailable()).thenReturn(true)
        whenever(gemma.structureReport(any())).thenReturn(null)

        val viewModel = MainViewModel(repository, gemma)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = false,
        )
        advanceUntilIdle()

        assertNull(viewModel.siteState.value.reportResult)
        assertEquals(
            "Gemma local no disponible — usá conexión a servidor.",
            viewModel.siteState.value.error,
        )
        assertFalse(viewModel.siteState.value.isSubmitting)
        verifyBlocking(repository, never()) {
            submitOrQueueReport(any(), any(), any(), any(), any())
        }
    }

    @Test
    fun `submitReport falls through to repository when gemma is null`() = runTest(testDispatcher) {
        val viewModel = MainViewModel(repository, gemma = null)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = true,
        )
        advanceUntilIdle()

        verifyBlocking(repository) {
            submitOrQueueReport("site-1", "Op", "brigadista", "el agua subio", true)
        }
    }

    @Test
    fun `submitReport falls through to repository when gemma is not available`() = runTest(testDispatcher) {
        whenever(gemma.isAvailable()).thenReturn(false)

        val viewModel = MainViewModel(repository, gemma)
        viewModel.submitReport(
            siteId = "site-1",
            reporterName = "Op",
            reporterRole = "brigadista",
            transcriptText = "el agua subio",
            forceOffline = false,
        )
        advanceUntilIdle()

        verifyBlocking(repository) {
            submitOrQueueReport("site-1", "Op", "brigadista", "el agua subio", false)
        }
    }
}
