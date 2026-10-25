package com.jalrekha.android

import android.app.Application
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.jalrekha.android.data.GemmaOnDevice
import com.jalrekha.android.data.SyncQueuedReportsWorker

class JalRekhaApplication : Application() {
    val gemma: GemmaOnDevice by lazy { GemmaOnDevice(this) }

    override fun onCreate() {
        super.onCreate()
        val request = OneTimeWorkRequestBuilder<SyncQueuedReportsWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .build()
        WorkManager.getInstance(this).enqueueUniqueWork(
            "sync-pending-reports",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }
}
