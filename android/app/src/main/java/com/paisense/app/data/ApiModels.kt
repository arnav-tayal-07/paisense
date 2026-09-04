package com.paisense.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Result of POST /sms/batch — how many messages were new. */
@Serializable
data class BatchResult(
    val received: Int,
    val stored: Int,
    @SerialName("already_had") val alreadyHad: Int,
)

/**
 * Result of POST /sms/import/run.
 *
 * `remaining` is the one that matters to the UI: anything left is picked up on
 * the next call, so a run that stops early is a pause rather than a failure.
 */
@Serializable
data class ImportRun(
    @SerialName("by_pattern") val byPattern: Int = 0,
    @SerialName("by_model") val byModel: Int = 0,
    @SerialName("model_calls") val modelCalls: Int = 0,
    @SerialName("patterns_generated") val patternsGenerated: Int = 0,
    val remaining: Int = 0,
)

@Serializable
data class ImportStatus(
    val pending: Int = 0,
    val processed: Int = 0,
    val total: Int = 0,
)

/**
 * A transaction awaiting review, with the message it came from.
 *
 * The original SMS travels with it deliberately — the whole point of a review
 * card is comparing what was extracted against what the bank actually said.
 */
@Serializable
data class ReviewItem(
    val id: Long,
    val type: String,
    val amount: String,
    val merchant: String? = null,
    val counterparty: String? = null,
    @SerialName("txn_time") val txnTime: String,
    @SerialName("account_last4") val accountLast4: String? = null,
    @SerialName("review_reason") val reviewReason: String? = null,
    @SerialName("source_message") val sourceMessage: String? = null,
    @SerialName("source_sender") val sourceSender: String? = null,
) {
    val payee: String get() = merchant ?: counterparty ?: "Unknown"
}
