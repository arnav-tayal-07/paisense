package com.paisense.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.paisense.app.data.Summary
import com.paisense.app.data.Transaction

@Composable
fun TransactionsScreen(
    modifier: Modifier = Modifier,
    viewModel: TransactionsViewModel = viewModel(),
) {
    // collectAsStateWithLifecycle, not collectAsState: it stops collecting
    // when the app is backgrounded instead of holding the subscription open.
    val state by viewModel.state.collectAsStateWithLifecycle()

    when (val s = state) {
        is TransactionsState.Loading -> Centered(modifier) {
            CircularProgressIndicator()
            Spacer(Modifier.width(0.dp))
            Text(
                "Waking the server…",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 16.dp),
            )
        }

        is TransactionsState.Failed -> Centered(modifier) {
            Text("Couldn't load", style = MaterialTheme.typography.titleMedium)
            Text(
                s.message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(vertical = 12.dp),
            )
            Button(onClick = viewModel::load) { Text("Try again") }
        }

        is TransactionsState.Loaded ->
            if (s.transactions.isEmpty()) {
                Centered(modifier) { Text("No transactions yet") }
            } else {
                LazyColumn(
                    modifier = modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item { SummaryPanel(s.summary) }
                    items(s.transactions, key = { it.id }) { TransactionRow(it) }
                }
            }
    }
}

/**
 * The three totals kept apart on purpose.
 *
 * Card spending is money owed but not yet paid; account spending is money
 * already gone. A card bill payment is neither — the purchases it settles
 * were counted when they happened — so it never joins the spending total
 * (ADR 016). Unlinked is shown rather than hidden: leaving it out would make
 * the totals quietly wrong.
 */
@Composable
private fun SummaryPanel(summary: Summary) {
    Card(modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
        Column(Modifier.padding(16.dp)) {
            Line("Income", summary.buckets.income, MaterialTheme.colorScheme.primary)
            Line("Account spending (UPI)", summary.buckets.accountSpend, null)
            Line("Credit card spending", summary.buckets.cardSpend, null)
            if (summary.buckets.cardPayment.count > 0) {
                Line("Card bills paid", summary.buckets.cardPayment, null, muted = true)
            }
            if (summary.buckets.unlinked.count > 0) {
                Line("Unlinked", summary.buckets.unlinked, null, muted = true)
            }
        }
    }
}

@Composable
private fun Line(
    label: String,
    bucket: com.paisense.app.data.Bucket,
    accent: androidx.compose.ui.graphics.Color?,
    muted: Boolean = false,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                label,
                style = MaterialTheme.typography.bodyMedium,
                color = if (muted) MaterialTheme.colorScheme.onSurfaceVariant
                        else MaterialTheme.colorScheme.onSurface,
            )
            Text(
                "${bucket.count} transactions",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            "₹" + bucket.total,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Medium,
            color = accent ?: if (muted) MaterialTheme.colorScheme.onSurfaceVariant
                              else MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun TransactionRow(txn: Transaction) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(txn.payee, style = MaterialTheme.typography.bodyLarge)
                Text(
                    // localDate, not txnTime: the backend sends an instant in
                    // UTC, so slicing the string shows the wrong day for
                    // anything after 17:30 IST.
                    txn.localDate,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                // Sign is derived from `type`, never stored: amounts are always
                // positive in the database (ADR 011).
                text = (if (txn.isIncome) "+" else "−") + "₹" + txn.amount,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
                color = if (txn.isIncome) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
            )
        }
    }
}

@Composable
private fun Centered(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(
        modifier = modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) { content() }
}
