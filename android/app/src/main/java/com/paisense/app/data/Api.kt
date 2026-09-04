package com.paisense.app.data

import com.paisense.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
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

    private suspend fun post(path: String, body: String? = null): String =
        withContext(Dispatchers.IO) {
            if (BuildConfig.API_KEY.isBlank()) {
                throw ApiException("No API key. Add PAISENSE_API_KEY to local.properties.")
            }

            val request = Request.Builder()
                .url(BuildConfig.API_BASE + path)
                .header("X-API-Key", BuildConfig.API_KEY)
                .post((body ?: "").toRequestBody("application/json".toMediaType()))
                .build()

            client.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw ApiException("HTTP ${response.code}: ${text.take(200)}")
                }
                text
            }
        }

    /** Recent transactions, newest first. Excludes anything awaiting review. */
    suspend fun transactions(limit: Int = 100): List<Transaction> =
        json.decodeFromString(get("/transactions?limit=$limit"))

    /** Money split into income, card spending and account spending. */
    suspend fun summary(): Summary = json.decodeFromString(get("/summary"))

    /** Transactions flagged for a human tick, with the SMS each came from. */
    suspend fun reviewQueue(): List<ReviewItem> =
        json.decodeFromString(get("/transactions/review"))

    suspend fun confirm(id: Long) { post("/transactions/$id/confirm") }

    suspend fun reject(id: Long) { post("/transactions/$id/reject") }

    /**
     * Upload messages without extracting them. Sent in chunks so one enormous
     * request can't time out and lose the lot — a partial import is fine,
     * because whatever arrives is stored and the rest is retried.
     */
    suspend fun uploadSms(messages: List<OutgoingSms>, chunk: Int = 100): Int {
        var stored = 0
        messages.chunked(chunk).forEach { batch ->
            val body = json.encodeToString(batch)
            val result: BatchResult = json.decodeFromString(post("/sms/batch", body))
            stored += result.stored
        }
        return stored
    }

    /** Extract pending messages, spending at most [budget] model calls. */
    suspend fun runImport(budget: Int = 30): ImportRun =
        json.decodeFromString(post("/sms/import/run?budget=$budget"))

    suspend fun importStatus(): ImportStatus =
        json.decodeFromString(get("/sms/import/status"))

    /** Cheap round trip that also proves the database is reachable. */
    suspend fun health(): String = get("/health")
}
