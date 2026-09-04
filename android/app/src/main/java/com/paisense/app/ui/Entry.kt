package com.paisense.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.paisense.app.data.Account
import java.time.LocalDate

/**
 * Swipe a row left to delete it, with a confirmation.
 *
 * The confirmation is not ceremony. There is no undo, the gesture is easy to
 * make by accident while scrolling, and a deleted row takes its amount out of
 * every total — a silent one would leave you wondering why a figure moved.
 *
 * The swipe deliberately springs back instead of dismissing: the row must not
 * disappear before the server has agreed, or a failed delete leaves the screen
 * disagreeing with the database until the next refresh.
 */
@Composable
fun SwipeToDelete(
    label: String,
    onDelete: () -> Unit,
    content: @Composable () -> Unit,
) {
    var confirming by remember { mutableStateOf(false) }

    val state = rememberSwipeToDismissBoxState(
        confirmValueChange = { value ->
            if (value == SwipeToDismissBoxValue.EndToStart) confirming = true
            // Never let the box settle in a dismissed state — see above.
            false
        }
    )

    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text("Delete this entry?") },
            text = {
                Column {
                    Text(label)
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "This can't be undone. If it came from an SMS the " +
                            "message is kept, so a future import could bring it back.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { confirming = false; onDelete() }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { confirming = false }) { Text("Cancel") }
            },
        )
    }

    SwipeToDismissBox(
        state = state,
        enableDismissFromStartToEnd = false,
        backgroundContent = {
            // Painted only while a swipe is under way. This box sits directly
            // beneath the card, and the card has rounded corners — so a
            // background drawn at rest shows through all four of them as red
            // specks on every row.
            //
            // Clipped to the same shape as well, so the red that IS visible
            // during a swipe follows the card's outline instead of squaring
            // off behind it.
            if (state.dismissDirection == SwipeToDismissBoxValue.EndToStart) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .clip(MaterialTheme.shapes.medium)
                        .background(MaterialTheme.colorScheme.errorContainer)
                        .padding(horizontal = 24.dp),
                    contentAlignment = Alignment.CenterEnd,
                ) {
                    Text(
                        "Delete",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                }
            }
        },
        content = { content() },
    )
}

/**
 * Add a spend by hand: cash, or anything the bank never texted about.
 *
 * Picking an account is required rather than optional. The lists are filtered
 * by account kind, so an entry filed nowhere would save successfully and then
 * appear on no screen — the worst possible outcome, because it looks like the
 * app lost it.
 */
@Composable
fun AddExpenseDialog(
    accounts: List<Account>,
    title: String,
    onDismiss: () -> Unit,
    onSave: (amount: String, payee: String, date: String, accountId: Long) -> Unit,
) {
    var amount by remember { mutableStateOf("") }
    var payee by remember { mutableStateOf("") }
    var date by remember { mutableStateOf(LocalDate.now().toString()) }
    var accountId by remember { mutableStateOf(accounts.firstOrNull()?.id) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                OutlinedTextField(
                    value = amount,
                    onValueChange = { amount = it; error = null },
                    label = { Text("Amount (₹)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    isError = error != null,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = payee,
                    onValueChange = { payee = it; error = null },
                    label = { Text("Paid to") },
                    singleLine = true,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = date,
                    onValueChange = { date = it },
                    label = { Text("Date (YYYY-MM-DD)") },
                    singleLine = true,
                )

                if (accounts.size > 1) {
                    Spacer(Modifier.height(12.dp))
                    Text("From", style = MaterialTheme.typography.labelMedium)
                    Spacer(Modifier.height(4.dp))
                    accounts.forEach { account ->
                        FilterChip(
                            selected = accountId == account.id,
                            onClick = { accountId = account.id },
                            label = { Text(account.name) },
                            modifier = Modifier.padding(end = 8.dp),
                        )
                    }
                }

                error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                // Checked here so a bad entry never costs a round trip to a
                // server that may be asleep.
                val value = amount.trim().toBigDecimalOrNull()
                val account = accountId
                when {
                    value == null || value <= java.math.BigDecimal.ZERO ->
                        error = "Enter an amount greater than zero"
                    payee.isBlank() -> error = "Enter who it was paid to"
                    account == null -> error = "No account to file this under"
                    else -> onSave(amount.trim(), payee.trim(), date.trim(), account)
                }
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
