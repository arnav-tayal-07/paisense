package com.paisense.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * A credit card's next payment.
 *
 * `cycleSpend` and `outstanding` are different numbers on purpose.
 * `cycleSpend` is what has landed since the last statement — what the NEXT
 * bill will ask for. `outstanding` is everything ever purchased minus
 * everything ever paid. Confusing them is how people underpay.
 *
 * `outstanding` is null when bill payments exceed the purchases on record,
 * which happens whenever history starts mid-cycle. Showing the negative
 * number would be a confident lie.
 */
@Serializable
data class Due(
    @SerialName("account_id") val accountId: Long,
    val name: String,
    /** The bill you owe NEXT, and the statement it covers. */
    @SerialName("due_date") val dueDate: String,
    @SerialName("days_until_due") val daysUntilDue: Int,
    @SerialName("billed_statement_date") val billedStatementDate: String = "",
    /** The cycle still accumulating — this spending lands on a LATER bill. */
    @SerialName("statement_date") val statementDate: String,
    @SerialName("cycle_due_date") val cycleDueDate: String = "",
    @SerialName("credit_limit") val creditLimit: String? = null,
    @SerialName("cycle_spend") val cycleSpend: String = "0",
    @SerialName("cycle_count") val cycleCount: Int = 0,
    val outstanding: String? = null,
    @SerialName("outstanding_unknown_reason") val outstandingUnknownReason: String? = null,
    @SerialName("available_limit") val availableLimit: String? = null,
) {
    /** Human label for the cycle that is still accumulating. */
    fun cycleStartLabel(): String = statementDate
}
