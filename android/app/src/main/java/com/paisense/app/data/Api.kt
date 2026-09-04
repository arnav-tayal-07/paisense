package com.paisense.app.data

import com.paisense.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
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

    private suspend fun patch(path: String, body: String): String =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url(BuildConfig.API_BASE + path)
                .header("X-API-Key", BuildConfig.API_KEY)
                .patch(body.toRequestBody("application/json".toMediaType()))
                .build()
            client.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw ApiException("HTTP ${response.code}: ${text.take(200)}")
                }
                text
            }
        }

    private suspend fun delete(path: String) =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url(BuildConfig.API_BASE + path)
                .header("X-API-Key", BuildConfig.API_KEY)
                .delete()
                .build()
            client.newCall(request).execute().use { response ->
                // 404 is treated as success: the row is gone, which is what
                // the caller wanted. Failing here would strand a deleted item
                // on screen with an error under it.
                if (!response.isSuccessful && response.code != 404) {
                    throw ApiException(
                        "HTTP ${response.code}: ${response.body?.string().orEmpty().take(200)}"
                    )
                }
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

    /**
     * Record income by hand.
     *
     * Income is never taken from an SMS. A bank credit might be a refund, a
     * friend settling a split, a cheque, or money moved between your own
     * accounts — counting those as earnings makes the figure meaningless.
     * Only what you type counts.
     */
    suspend fun addIncome(amount: String, source: String, date: String) =
        addTransaction("income", amount, source, date)

    /**
     * Record a transaction by hand.
     *
     * `accountId` matters more than it looks: the lists are filtered by
     * account kind, so an entry with no account is accepted by the server and
     * then appears on no screen at all. The caller always supplies one.
     *
     * Amount travels as a string. Money never becomes a float on the way
     * (ADR 032) — a JSON number would round it in transit.
     */
    suspend fun addTransaction(
        type: String,
        amount: String,
        payee: String,
        date: String,
        accountId: Long? = null,
    ) {
        val body = buildJsonObject {
            put("type", JsonPrimitive(type))
            put("amount", JsonPrimitive(amount))
            put("merchant", JsonPrimitive(payee))
            put("txn_time", JsonPrimitive(date))
            put("source", JsonPrimitive("manual"))
            accountId?.let { put("account_id", JsonPrimitive(it)) }
        }
        post("/transactions", json.encodeToString(JsonObject.serializer(), body))
    }

    /** Every account, so a manual entry can name where the money went. */
    suspend fun accounts(): List<Account> = json.decodeFromString(get("/accounts"))

    /** Remove a transaction. Used by swipe-to-delete. */
    suspend fun deleteTransaction(id: Long) = delete("/transactions/$id")

    /**
     * Rename or recategorise a transaction.
     *
     * Most UPI messages name no payee at all - RBL says "credited to a/c
     * XX0233" and stops - so the only way those rows ever get a readable
     * name is the user typing one. PATCH sends only what changed, so setting
     * a name can't blank the amount.
     */
    suspend fun updateTransaction(
        id: Long,
        merchant: String? = null,
        category: String? = null,
        note: String? = null,
    ) {
        val body = buildJsonObject {
            merchant?.let { put("merchant", JsonPrimitive(it)) }
            category?.let { put("category", JsonPrimitive(it)) }
            note?.let { put("note", JsonPrimitive(it)) }
        }
        patch("/transactions/$id", json.encodeToString(JsonObject.serializer(), body))
    }

    /**
     * Money that actually left a bank account.
     *
     * Not card purchases — those are on the Card tab, and showing them here
     * too listed the same spend in two places. Not wallet spends either:
     * paying with Amazon Pay balance or Swiggy Money moves nothing out of an
     * account, because the rupees left when the wallet was topped up and that
     * debit is already in this list.
     */
    suspend fun bankExpenses(limit: Int = 200): List<Transaction> =
        json.decodeFromString(
            get("/transactions?type=expense&account_kind=bank_account&limit=$limit")
        )

    /**
     * Purchases made ON a credit card — not bill payments.
     *
     * The Card tab was showing bill payments, which is what you PAID rather
     * than what you SPENT. Those are opposite directions.
     */
    suspend fun cardSpends(limit: Int = 200): List<Transaction> =
        json.decodeFromString(
            get("/transactions?type=expense&account_kind=credit_card&limit=$limit")
        )

    /**
     * Set a card's credit limit.
     *
     * The one figure nothing else can supply: it is not in any transaction,
     * and reading it from limit-change messages proved unreliable — a stale
     * limit silently produces a wrong "available".
     */
    suspend fun setCreditLimit(accountId: Long, limit: String) {
        val body = buildJsonObject { put("credit_limit", JsonPrimitive(limit)) }
        patch("/accounts/$accountId", json.encodeToString(JsonObject.serializer(), body))
    }

    /** Next payment date and amount for every credit card. */
    suspend fun dues(): List<Due> = json.decodeFromString(get("/dues"))

    /** Transactions of one type only - income, expense or card_payment. */
    suspend fun transactionsOfType(
        type: String,
        source: String? = null,
        limit: Int = 200,
    ): List<Transaction> {
        val src = if (source != null) "&source=$source" else ""
        return json.decodeFromString(get("/transactions?type=$type$src&limit=$limit"))
    }

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
