package com.paisense.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.paisense.app.data.Transaction
import java.time.LocalDate

/**
 * Income you typed, and — separately — money the bank says arrived.
 *
 * They are not the same thing and merging them was making the total useless.
 * A bank credit can be a refund, a friend settling a split, a cheque, or you
 * moving your own money between accounts. Only the entries below the first
 * heading count as earnings.
 */
@Composable
fun IncomeScreen(
    income: List<Transaction>,
    received: List<Transaction>,
    onAdd: (amount: String, source: String, date: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var showDialog by remember { mutableStateOf(false) }

    Box(modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp, 16.dp, 16.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item { SectionHeading("Income you've entered") }

            if (income.isEmpty()) {
                item {
                    Text(
                        "Nothing yet. Add your salary or any other earnings with the button below.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 8.dp),
                    )
                }
            } else {
                items(income, key = { it.id }) { IncomeRow(it, earned = true) }
            }

            if (received.isNotEmpty()) {
                item {
                    Spacer(Modifier.height(16.dp))
                    SectionHeading("Money received (${received.size})")
                    Text(
                        "Bank credits — refunds, transfers and split settlements. " +
                            "Not counted as income.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 8.dp),
                    )
                }
                items(received, key = { it.id }) { IncomeRow(it, earned = false) }
            }
        }

        ExtendedFloatingActionButton(
            onClick = { showDialog = true },
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
        ) { Text("+  Add income") }
    }

    if (showDialog) {
        AddIncomeDialog(
            onDismiss = { showDialog = false },
            onSave = { amount, source, date ->
                onAdd(amount, source, date)
                showDialog = false
            },
        )
    }
}

@Composable
private fun SectionHeading(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium)
}

@Composable
private fun IncomeRow(txn: Transaction, earned: Boolean) {
    Card(
        Modifier.fillMaxWidth(),
        colors = if (earned) CardDefaults.cardColors()
                 else CardDefaults.cardColors(
                     containerColor = MaterialTheme.colorScheme.surfaceVariant
                 ),
    ) {
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
                "+₹" + txn.amount,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
                color = if (earned) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AddIncomeDialog(
    onDismiss: () -> Unit,
    onSave: (amount: String, source: String, date: String) -> Unit,
) {
    var amount by remember { mutableStateOf("") }
    var source by remember { mutableStateOf("") }
    var date by remember { mutableStateOf(LocalDate.now().toString()) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add income") },
        text = {
            Column {
                OutlinedTextField(
                    value = amount,
                    onValueChange = { amount = it; error = null },
                    label = { Text("Amount (₹)") },
                    // Decimal keyboard, and the value travels to the server as
                    // a string — money never becomes a float on the way (ADR 032).
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    isError = error != null,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = source,
                    onValueChange = { source = it; error = null },
                    label = { Text("Source (e.g. Salary)") },
                    singleLine = true,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = date,
                    onValueChange = { date = it },
                    label = { Text("Date (YYYY-MM-DD)") },
                    singleLine = true,
                )
                error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, style = MaterialTheme.typography.bodySmall,
                         color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                // Validated here so a bad entry is caught before a round trip
                // to a server that may be asleep.
                val value = amount.trim().toBigDecimalOrNull()
                when {
                    value == null || value <= java.math.BigDecimal.ZERO ->
                        error = "Enter an amount greater than zero"
                    source.isBlank() -> error = "Enter where it came from"
                    else -> onSave(amount.trim(), source.trim(), date.trim())
                }
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
