package com.jalrekha.android.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Smoke test that exercises the in-memory pending-reports queue via the
 * Repository's `forTest` seam. We deliberately use Room.inMemoryDatabaseBuilder
 * so the test is hermetic and never touches the production DB file.
 */
@RunWith(RobolectricTestRunner::class)
class RepositoryTest {
    private lateinit var context: Context
    private lateinit var db: AppDatabase
    private lateinit var repository: JalRekhaRepository

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        repository = JalRekhaRepository.forTest(context, db)
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun `queueReport persists row visible via observePendingReports`() = runTest {
        repository.queueReport(
            siteId = "site-1",
            reporterName = "Operador Test",
            reporterRole = "brigadista",
            transcriptText = "el agua cruzo la marca critica",
        )

        val pending = repository.observePendingReports().first()
        assertEquals(1, pending.size)
        val entity = pending.first()
        assertEquals("site-1", entity.siteId)
        assertEquals("Operador Test", entity.reporterName)
        assertEquals("brigadista", entity.reporterRole)
        assertEquals("el agua cruzo la marca critica", entity.transcriptText)
    }
}
