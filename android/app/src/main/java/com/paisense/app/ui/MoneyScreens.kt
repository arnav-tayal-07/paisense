package com.paisense.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.paisense.app.data.Due
import com.paisense.app.data.Transaction

// ---------------------------------------------------------------- Summary

/**
 * The figures your old ledger showed, in the same shape:
 * total income, money actually spent, and what the card owes.
 */
@Composable
fun SummarySection(data: HomeData, modifier: Modifier = Modifier) {
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // The summary is optional. If that one call failed, the card is
        // simply absent and the due cards below still render — a broken part
        // should cost you that part, not the screen.
        data.summary?.let { summary ->
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("Summary", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(12.dp))
                        Figure("Income entered", summary.totalIncome, positive = true)
                        HorizontalDivider(Modifier.padding(vertical = 12.dp))
                        Figure("Spent from accounts", summary.buckets.accountSpend.total)
                        Figure("Spent on cards", summary.buckets.cardSpend.total)
                        Figure("Card bills paid", summary.buckets.cardPayment.total, muted = true)
                        if (summary.buckets.unlinked.count > 0) {
                            // Wallets and IPO blocks - real money, but tied to
                            // no bank account, so neither category fits.
                            Figure("Wallets & other", summary.buckets.unlinked.total, muted = true)
                        }
                        // No "Balance" line for now: income is manual and
                        // mostly unfilled, so a balance would just be a large
                        // negative number that means nothing yet.
                    }
                }
            }
        }

        if (data.problems.isNotEmpty()) {
            item {
                Text(
                    "Some parts didn't load: ${data.problems.first()}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            }
        }

        items(data.dues, key = { it.accountId }) { DueCard(it) }
    }
}

/**
 * The Card tab: what you owe, when, and what you've charged.
 *
 * Previously this listed BILL PAYMENTS, which is what you paid rather than
 * what you spent — opposite directions, and the reason the tab read as
 * nonsense.
 */
@Composable
fun CardSection(
    dues: List<Due>,
    spends: List<Transaction>,
    payments: List<Transaction>,
    modifier: Modifier = Modifier,
    onEdit: ((Transaction, String, String) -> Unit)? = null,
) {
    var editing by remember { mutableStateOf<Transaction?>(null) }

    editing?.let { txn ->
        EditTransactionDialog(txn, onDismiss = { editing = null }) { name, cat ->
            onEdit?.invoke(txn, name, cat); editing = null
        }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(dues, key = { it.accountId }) { DueCard(it) }

        if (spends.isNotEmpty()) {
            item { Text("Charged to cards", style = MaterialTheme.typography.titleMedium) }
            items(spends, key = { "s" + it.id }) { txn ->
                Card(Modifier.fillMaxWidth().clickable(enabled = onEdit != null) { editing = txn }) {
                    TxnRow(txn)
                }
            }
        }

        if (payments.isNotEmpty()) {
            item {
                Spacer(Modifier.height(8.dp))
                Text("Bill payments", style = MaterialTheme.typography.titleMedium)
                Text(
                    "Money paid TO the card. Not spending — it settles charges already counted.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            items(payments, key = { "p" + it.id }) { txn ->
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                ) { TxnRow(txn) }
            }
        }
    }
}

@Composable
private fun TxnRow(txn: Transaction) {
    Row(
        Modifier.fillMaxWidth().padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(txn.payee, style = MaterialTheme.typography.bodyLarge)
            Text(
                txn.localDate + (txn.accountLast4?.let { "  ·  $it" } ?: ""),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            "₹" + txn.amount,
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun DueCard(due: Due) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(due.name, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))

            // The bill actually owed next - from the statement that has ALREADY
            // generated, not the cycle still running. Showing the open cycle's
            // date would have said "34 days" while a bill was due in 4.
            Text(
                "Next payment due ${due.dueDate}  ·  ${due.daysUntilDue} days",
                style = MaterialTheme.typography.bodyMedium,
                color = if (due.daysUntilDue <= 7) MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "for the statement of ${due.billedStatementDate}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            if (due.outstanding != null) {
                Figure("Outstanding now", due.outstanding)
            } else due.outstandingUnknownReason?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 8.dp),
                )
            }

            due.creditLimit?.let { Figure("Credit limit", it, muted = true) }
            // Dated on purpose. This is the last figure the BANK sent, which
            // may be days old — labelling it "now" made a 27 August balance
            // look like today's.
            due.availableLimit?.let {
                Figure(
                    "Available (as of ${due.availableLimitAt?.take(10) ?: "unknown"})",
                    it,
                    muted = true,
                )
            }

            // Charges since the last statement — these land on the bill due
            // ${due.cycleDueDate}, not the one above.
            Figure(
                "Since ${due.statementDate.let { due.cycleStartLabel() }} (next bill)",
                due.cycleSpend,
                muted = true,
            )
        }
    }
}

@Composable
private fun Figure(
    label: String,
    amount: String,
    positive: Boolean = false,
    muted: Boolean = false,
) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = if (muted) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
        Text(
            "₹$amount",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Medium,
            color = when {
                positive -> MaterialTheme.colorScheme.primary
                muted -> MaterialTheme.colorScheme.onSurfaceVariant
                else -> MaterialTheme.colorScheme.onSurface
            },
        )
    }
}

// ------------------------------------------------------------ Ledger list

/** One tab's worth of transactions — income, expenses or card payments. */
@Composable
fun LedgerSection(
    transactions: List<Transaction>,
    emptyMessage: String,
    modifier: Modifier = Modifier,
    onEdit: ((Transaction, String, String) -> Unit)? = null,
) {
    // Tapping a row opens the rename dialog. Most UPI rows arrive with only a
    // masked account number, so naming them by hand is the only way they ever
    // become readable.
    var editing by remember { mutableStateOf<Transaction?>(null) }

    editing?.let { txn ->
        EditTransactionDialog(
            txn = txn,
            onDismiss = { editing = null },
            onSave = { name, category ->
                onEdit?.invoke(txn, name, category)
                editing = null
            },
        )
    }

    if (transactions.isEmpty()) {
        Column(
            modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) { Text(emptyMessage, style = MaterialTheme.typography.bodyLarge) }
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(transactions, key = { it.id }) { txn ->
            Card(Modifier.fillMaxWidth().clickable(enabled = onEdit != null) { editing = txn }) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(txn.payee, style = MaterialTheme.typography.bodyLarge)
                        Text(
                            txn.localDate,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(
                        (if (txn.isIncome) "+" else "−") + "₹" + txn.amount,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                        color = if (txn.isIncome) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}
