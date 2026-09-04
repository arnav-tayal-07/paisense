package com.paisense.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One credit card's current billing cycle.
 *
 * Counted from the cycle start only — everything before it is assumed settled.
 * No carried balance, no interest. That is a deliberate simplification: those
 * figures can't be derived from imported SMS, and a guess would be worse than
 * their absence.
 *
 * `paid` is money paid TO the card during this cycle, which cleared the
 * previous bill. It is shown but never added back to `available`, because the
 * bill it settled is already assumed paid — counting it twice would inflate
 * the headroom.
 */
@Serializable
data class Due(
    @SerialName("account_id") val accountId: Long,
    val name: String,
    @SerialName("credit_limit") val creditLimit: String? = null,

    @SerialName("cycle_start") val cycleStart: String,
    @SerialName("statement_date") val statementDate: String,
    @SerialName("due_date") val dueDate: String,
    @SerialName("days_until_due") val daysUntilDue: Int = 0,
    @SerialName("days_until_statement") val daysUntilStatement: Int = 0,

    @SerialName("cycle_spend") val cycleSpend: String = "0",
    @SerialName("cycle_count") val cycleCount: Int = 0,
    val paid: String = "0",
    val available: String? = null,

    /** True until the user tells us the limit — nothing else can supply it. */
    @SerialName("needs_limit") val needsLimit: Boolean = false,
)
