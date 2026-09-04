package com.paisense.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One row from GET /transactions.
 *
 * Every field the backend can return as null is nullable here, mirroring the
 * schema exactly (ADR 011). If the two drift, the app crashes on a perfectly
 * valid response — a half-parsed SMS legitimately has no merchant.
 *
 * `ignoreUnknownKeys` is set on the Json instance in [Api], so the backend can
 * add columns without breaking an installed app.
 */
@Serializable
data class Transaction(
    val id: Long,
    val type: String,
    // Deliberately a String, not a Double. The backend stores numeric(12,2),
    // but JSON has no decimal type, so 120.50 arrives as 120.5 and parsing it
    // into a Double reintroduces the float problem the database avoids. Kept
    // as text for display; parse to BigDecimal if arithmetic is ever needed.
    val amount: String,
    val merchant: String? = null,
    val counterparty: String? = null,
    val category: String? = null,
    @SerialName("txn_time") val txnTime: String,
    @SerialName("account_id") val accountId: Long? = null,
    @SerialName("account_last4") val accountLast4: String? = null,
    @SerialName("upi_ref") val upiRef: String? = null,
    val source: String,
    @SerialName("review_status") val reviewStatus: String,
    @SerialName("review_reason") val reviewReason: String? = null,
) {
    /** What to show as the payee: a business name, else a UPI VPA, else nothing useful. */
    val payee: String
        get() = merchant ?: counterparty ?: "Unknown"

    val isIncome: Boolean
        get() = type == "income"

    /** Card bill payments are neither spending nor earning — see ADR 016. */
    val isCardPayment: Boolean
        get() = type == "card_payment"
}
