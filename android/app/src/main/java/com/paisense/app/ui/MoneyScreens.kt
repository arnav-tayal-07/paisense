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
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Summary", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(12.dp))
                    Figure("Total income", data.summary.totalIncome, positive = true)
                    Figure("Spent from accounts", data.summary.buckets.accountSpend.total)
                    Figure("Spent on cards", data.summary.buckets.cardSpend.total)
                    if (data.summary.buckets.unlinked.count > 0) {
                        // Wallets and IPO blocks - real money, but tied to no
                        // bank account, so it belongs to neither category.
                        Figure("Wallets & other", data.summary.buckets.unlinked.total, muted = true)
                    }
                    HorizontalDivider(Modifier.padding(vertical = 12.dp))
                    Figure("Balance", data.summary.net, positive = !data.summary.net.startsWith("-"))
                }
            }
        }

        items(data.dues, key = { it.accountId }) { DueCard(it) }
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

            Text(
                "Next payment due ${due.dueDate}  ·  ${due.daysUntilDue} days",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            // What the NEXT bill will ask for - only spending since the last
            // statement, not everything ever charged.
            Figure("This cycle (since ${due.statementDate})", due.cycleSpend)

            due.availableLimit?.let { Figure("Available limit", it, muted = true) }

            if (due.outstanding != null) {
                Figure("Outstanding", due.outstanding)
            } else due.outstandingUnknownReason?.let {
                Text(
                    "Outstanding unavailable — $it",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
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
