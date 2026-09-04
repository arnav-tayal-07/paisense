package com.paisense.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Bucket(val count: Int = 0, val total: String = "0")

/**
 * Money grouped the way it needs to be read.
 *
 * Card spending is owed but not yet paid; account spending is already gone.
 * A card bill payment is neither — the purchases it settles were counted when
 * they happened — so it is kept apart rather than double-counted (ADR 016).
 */
@Serializable
data class Summary(
    val buckets: Buckets = Buckets(),
    @SerialName("total_spent") val totalSpent: String = "0",
    @SerialName("total_income") val totalIncome: String = "0",
    val net: String = "0",
)

@Serializable
data class Buckets(
    val income: Bucket = Bucket(),
    @SerialName("card_spend") val cardSpend: Bucket = Bucket(),
    @SerialName("account_spend") val accountSpend: Bucket = Bucket(),
    @SerialName("card_payment") val cardPayment: Bucket = Bucket(),
    val unlinked: Bucket = Bucket(),
)
