package com.paisense.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.paisense.app.data.Transaction

/**
 * Naming a transaction the bank wouldn't name.
 *
 * 107 of Arnav's transactions arrived with only a masked account number,
 * because RBL's UPI format says "credited to a/c XX0233" and stops. No prompt
 * can extract a name that isn't in the message, so the name has to come from
 * the person who knows it.
 *
 * The original text is shown alongside, unchanged — it's the only context for
 * working out who XX0233 actually was.
 */
@Composable
fun EditTransactionDialog(
    txn: Transaction,
    onDismiss: () -> Unit,
    onSave: (merchant: String, category: String) -> Unit,
) {
    var name by remember { mutableStateOf(txn.merchant ?: txn.counterparty ?: "") }
    var category by remember { mutableStateOf(txn.category ?: "") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("₹${txn.amount}  ·  ${txn.localDate}") },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name") },
                    singleLine = true,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = category,
                    onValueChange = { category = it },
                    label = { Text("Category (optional)") },
                    singleLine = true,
                )

                txn.counterparty?.let {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "Bank said: $it",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(name.trim(), category.trim()) }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
