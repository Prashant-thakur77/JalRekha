package com.jalrekha.android.data

import android.content.Context
import com.jalrekha.android.BuildConfig

class ServerConfigStore(context: Context) {
    private val prefs = context.getSharedPreferences("node_server", Context.MODE_PRIVATE)

    fun getBaseUrl(): String {
        val value = prefs.getString("api_base_url", BuildConfig.DEFAULT_API_BASE_URL) ?: BuildConfig.DEFAULT_API_BASE_URL
        return if (value.endsWith("/")) value else "$value/"
    }

    fun setBaseUrl(url: String) {
        val normalized = if (url.endsWith("/")) url else "$url/"
        prefs.edit().putString("api_base_url", normalized).apply()
    }
}
