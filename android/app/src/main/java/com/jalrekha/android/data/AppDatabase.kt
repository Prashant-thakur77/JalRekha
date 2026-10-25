package com.jalrekha.android.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Dao
interface PendingReportDao {
    @Query("SELECT * FROM pending_reports ORDER BY createdAt ASC")
    fun observeAll(): Flow<List<PendingReportEntity>>

    @Query("SELECT * FROM pending_reports ORDER BY createdAt ASC")
    suspend fun getAll(): List<PendingReportEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(report: PendingReportEntity)

    @Query("DELETE FROM pending_reports WHERE id = :id")
    suspend fun deleteById(id: Long)
}

@Database(entities = [PendingReportEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun pendingReportDao(): PendingReportDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                AppDatabase::class.java,
                "jalrekha-android.db",
            ).build().also { instance = it }
        }
    }
}
