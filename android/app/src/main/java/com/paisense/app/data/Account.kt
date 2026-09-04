package com.paisense.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * An account money belongs to: a bank account, a credit card, or a wallet.
 *
 * Needed on the client so a manually added expense can say WHERE the money
 * went. Without an account the row is unattributed, and the lists are filtered
 * by account kind — so a manual expense with no account would be accepted by
 * the server, then never appear anywhere. Silently swallowed entries are worse
 * than a rejected one.
 */
@Serializable
data class Account(
    val id: Long,
    val name: String,
    /** credit_card | bank_account | wallet */
    val kind: String,
    @SerialName("issuer_code") val issuerCode: String? = null,
    @SerialName("credit_limit") val creditLimit: String? = null,
) {
    val isCard: Boolean get() = kind == "credit_card"
    val isBank: Boolean get() = kind == "bank_account"
}
