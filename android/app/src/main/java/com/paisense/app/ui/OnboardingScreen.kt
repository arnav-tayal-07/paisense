package com.paisense.app.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

fun hasSmsPermission(context: Context): Boolean =
    ContextCompat.checkSelfPermission(context, Manifest.permission.READ_SMS) ==
        PackageManager.PERMISSION_GRANTED

@Composable
fun OnboardingScreen(
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: OnboardingViewModel = viewModel(),
) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { granted ->
        if (granted[Manifest.permission.READ_SMS] == true) {
            viewModel.onPermissionGranted(context)
        } else {
            viewModel.onPermissionDenied()
        }
    }

    LaunchedEffect(Unit) {
        if (hasSmsPermission(context)) viewModel.onPermissionGranted(context)
    }

    Column(
        modifier = modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        when (val s = state) {
            is OnboardingState.NeedsPermission -> {
                Title("Read your bank SMS")
                Body(
                    "PaiSense records your spending by reading bank messages on this " +
                        "phone. Only messages from banks are used — never conversations."
                )
                Spacer(Modifier.height(24.dp))
                Button(onClick = {
                    permissionLauncher.launch(
                        arrayOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS)
                    )
                }) { Text("Allow") }
                Spacer(Modifier.height(8.dp))
                TextButton(onClick = onDone) { Text("Not now") }
            }

            is OnboardingState.Denied -> {
                Title("Permission denied")
                Body(
                    "Without SMS access PaiSense can't record spending automatically. " +
                        "You can still add transactions by hand, or grant it later in " +
                        "Android Settings → Apps → PaiSense → Permissions."
                )
                Spacer(Modifier.height(24.dp))
                Button(onClick = onDone) { Text("Continue anyway") }
            }

            is OnboardingState.Counting -> {
                CircularProgressIndicator()
                Spacer(Modifier.height(16.dp))
                Body("Looking through your messages…")
            }

            is OnboardingState.ChooseRange -> {
                Title("Import your history")
                // Counted on-device before anything is uploaded, so the number
                // is real rather than an estimate the user has to trust.
                Body("Found ${s.counts[3] ?: 0} bank messages on this phone.")
                Spacer(Modifier.height(24.dp))
                listOf(1, 2, 3).forEach { months ->
                    OutlinedButton(
                        onClick = { viewModel.import(context, months) },
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    ) {
                        Text(
                            "Last ${if (months == 1) "month" else "$months months"}" +
                                "  ·  ${s.counts[months] ?: 0} messages"
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                TextButton(onClick = onDone) { Text("Skip for now") }
            }

            is OnboardingState.Importing -> {
                Title("Importing")
                Body(s.step)
                Spacer(Modifier.height(24.dp))
                if (s.total > 0) {
                    LinearProgressIndicator(
                        progress = { s.done.toFloat() / s.total },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    Body("${s.done} of ${s.total} processed")
                } else {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                Spacer(Modifier.height(16.dp))
                // Extraction continues server-side whether or not this screen
                // is open, so there is no reason to hold the user here.
                TextButton(onClick = onDone) { Text("Continue in background") }
            }

            is OnboardingState.Finished -> {
                Title("Done")
                Body(s.summary)
                Spacer(Modifier.height(24.dp))
                Button(onClick = onDone) { Text("Start using PaiSense") }
            }

            is OnboardingState.Failed -> {
                Title("Import problem")
                Body(s.message)
                Spacer(Modifier.height(24.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedButton(onClick = { viewModel.retry(context) }) { Text("Try again") }
                    Button(onClick = onDone) { Text("Continue") }
                }
            }
        }
    }
}

@Composable
private fun Title(text: String) {
    Text(text, style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
    Spacer(Modifier.height(12.dp))
}

@Composable
private fun Body(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
    )
}
