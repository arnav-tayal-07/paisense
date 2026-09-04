package com.paisense.app.data

import com.paisense.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Talking to the PaiSense backend.
 *
 * Plain OkHttp rather than Retrofit: there are a handful of endpoints, and an
 * annotation-driven layer would add a dependency and a level of indirection to
 * hide about ten lines of code.
 */
object Api {

    private val json = Json {
        // The backend will grow columns. Without this, adding one to the API
        // crashes every app already installed on a phone.
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    private val client = OkHttpClient.Builder()
        // Render's free tier sleeps after 15 minutes and takes up to a minute
        // to wake, so the first call of the day is genuinely slow. A default
        // 10s timeout would report that as a failure.
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .build()

    class ApiException(message: String) : Exception(message)

    private suspend fun get(path: String): String = withContext(Dispatchers.IO) {
        if (BuildConfig.API_KEY.isBlank()) {
            throw ApiException("No API key. Add PAISENSE_API_KEY to local.properties and re-sync.")
        }

        val request = Request.Builder()
            .url(BuildConfig.API_BASE + path)
            .header("X-API-Key", BuildConfig.API_KEY)
            .build()

        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw ApiException(
                    when (response.code) {
                        401 -> "Rejected by the server: the API key doesn't match."
                        503 -> "Server has no API key configured."
                        else -> "HTTP ${response.code}: ${body.take(200)}"
                    }
                )
            }
            body
        }
    }

    /** Recent transactions, newest first. Excludes anything awaiting review. */
    suspend fun transactions(limit: Int = 50): List<Transaction> =
        json.decodeFromString(get("/transactions?limit=$limit"))

    /** Cheap round trip that also proves the database is reachable. */
    suspend fun health(): String = get("/health")
}
