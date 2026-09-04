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
                    items(s.transactions, key = { it.id }) { TransactionRow(it) }
                }
            }
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
                    // Just the date for now. Formatting the full timestamp
                    // properly needs a timezone decision, which belongs with
                    // the rest of the display work rather than here.
                    txn.txnTime.take(10),
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
