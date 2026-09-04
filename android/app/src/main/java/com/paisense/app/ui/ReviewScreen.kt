package com.paisense.app.ui

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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.paisense.app.data.ReviewItem

@Composable
fun ReviewScreen(
    modifier: Modifier = Modifier,
    viewModel: ReviewViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    when (val s = state) {
        is ReviewState.Loading -> Box(modifier) { CircularProgressIndicator() }

        is ReviewState.Failed -> Box(modifier) {
            Text("Couldn't load", style = MaterialTheme.typography.titleMedium)
            Text(
                s.message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(vertical = 12.dp),
            )
            Button(onClick = viewModel::load) { Text("Try again") }
        }

        is ReviewState.Loaded ->
            if (s.items.isEmpty()) {
                // The empty state is the NORMAL state. A queue with something
                // in it every day would get tapped through without reading,
                // which is worse than no queue at all.
                Box(modifier) {
                    Text("Nothing to review", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Transactions only appear here when something looked wrong.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
            } else {
                LazyColumn(
                    modifier = modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(s.items, key = { it.id }) { item ->
                        ReviewCard(
                            item = item,
                            onConfirm = { viewModel.confirm(item.id) },
                            onReject = { viewModel.reject(item.id) },
                        )
                    }
                }
            }
    }
}

@Composable
private fun ReviewCard(item: ReviewItem, onConfirm: () -> Unit, onReject: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    item.payee,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    "₹" + item.amount,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium,
                )
            }

            // Why it was flagged. Without this the user is being asked to
            // check something without being told what to check.
            item.reviewReason?.let {
                Spacer(Modifier.height(8.dp))
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            // The original message, so the extracted values can be compared
            // against what the bank actually said. That comparison IS the
            // review; without the source it's just a guess.
            item.sourceMessage?.let {
                Spacer(Modifier.height(12.dp))
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Spacer(Modifier.height(16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onConfirm, modifier = Modifier.weight(1f)) { Text("Correct") }
                OutlinedButton(onClick = onReject, modifier = Modifier.weight(1f)) {
                    Text("Wrong")
                }
            }
        }
    }
}

@Composable
private fun Box(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(
        modifier = modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) { content() }
}
