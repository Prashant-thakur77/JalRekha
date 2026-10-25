package com.jalrekha.android.data

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class SyncQueuedReportsWorker(
    appContext: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(appContext, workerParams) {
    override suspend fun doWork(): Result {
        val repository = JalRekhaRepository.get(applicationContext)
        return try {
            repository.flushPendingReports()
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}
