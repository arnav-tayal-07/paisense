package com.paisense.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import com.paisense.app.ui.OnboardingScreen
import com.paisense.app.ui.ReviewScreen
import com.paisense.app.ui.TransactionsScreen
import com.paisense.app.ui.hasSmsPermission
import com.paisense.app.ui.theme.PaiSenseTheme

private const val PREFS = "paisense"
private const val KEY_ONBOARDED = "onboarded"

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { PaiSenseTheme { App() } }
    }
}

@Composable
private fun App() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences(PREFS, Context.MODE_PRIVATE) }

    // Onboarding is shown once. Also re-shown if the permission was granted
    // and later revoked in Android settings, since without it the app quietly
    // stops recording anything and would otherwise never say so.
    var onboarded by remember {
        mutableStateOf(prefs.getBoolean(KEY_ONBOARDED, false) && hasSmsPermission(context))
    }

    if (!onboarded) {
        OnboardingScreen(onDone = {
            prefs.edit().putBoolean(KEY_ONBOARDED, true).apply()
            onboarded = true
        })
    } else {
        MainScaffold()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainScaffold() {
    var tab by remember { mutableIntStateOf(0) }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = { TopAppBar(title = { Text(if (tab == 0) "PaiSense" else "Review") }) },
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = tab == 0,
                    onClick = { tab = 0 },
                    // Text rather than a Material icon: the icons artifact is a
                    // separate dependency, and two glyphs do not justify it.
                    icon = { Text("₹") },
                    label = { Text("Spending") },
                )
                NavigationBarItem(
                    selected = tab == 1,
                    onClick = { tab = 1 },
                    icon = { Text("✓") },
                    label = { Text("Review") },
                )
            }
        },
    ) { innerPadding ->
        when (tab) {
            0 -> TransactionsScreen(modifier = Modifier.padding(innerPadding))
            else -> ReviewScreen(modifier = Modifier.padding(innerPadding))
        }
    }
}
