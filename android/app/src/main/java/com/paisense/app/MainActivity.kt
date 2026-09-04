package com.paisense.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.paisense.app.ui.HomeState
import com.paisense.app.ui.HomeViewModel
import com.paisense.app.ui.IncomeScreen
import com.paisense.app.ui.CardSection
import com.paisense.app.ui.LedgerSection
import com.paisense.app.ui.OnboardingScreen
import com.paisense.app.ui.ReviewScreen
import com.paisense.app.ui.SummarySection
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

    // Onboarding is shown once, and again if the permission was later revoked
    // in Android settings — without it the app quietly stops recording and
    // would otherwise never say so.
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

private data class Tab(val label: String, val glyph: String)

// Income, expenses and card kept as separate destinations rather than one
// mixed list — the same split the earlier Kharcha ledger used, because
// "what came in", "what went out" and "what I owe" are three different
// questions and merging them answers none of them well.
private val TABS = listOf(
    Tab("Summary", "₹"),
    Tab("Expenses", "−"),
    Tab("Income", "+"),
    Tab("Card", "▭"),
    Tab("Review", "✓"),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainScaffold(viewModel: HomeViewModel = viewModel()) {
    var tab by remember { mutableIntStateOf(0) }
    val state by viewModel.state.collectAsStateWithLifecycle()

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = { TopAppBar(title = { Text(TABS[tab].label) }) },
        bottomBar = {
            NavigationBar {
                TABS.forEachIndexed { index, t ->
                    NavigationBarItem(
                        selected = tab == index,
                        onClick = { tab = index },
                        // Text glyphs rather than Material icons: five symbols
                        // don't justify another dependency.
                        icon = { Text(t.glyph) },
                        label = { Text(t.label) },
                    )
                }
            }
        },
    ) { padding ->
        val content = Modifier.padding(padding)

        if (tab == 4) {
            ReviewScreen(modifier = content)
            return@Scaffold
        }

        when (val s = state) {
            is HomeState.Loading -> Centered(content) {
                CircularProgressIndicator()
                Text(
                    "Waking the server…",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(top = 16.dp),
                )
            }

            is HomeState.Failed -> Centered(content) {
                Text("Couldn't load", style = MaterialTheme.typography.titleMedium)
                Text(
                    s.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(vertical = 12.dp),
                )
                Button(onClick = viewModel::load) { Text("Try again") }
            }

            is HomeState.Loaded -> when (tab) {
                0 -> SummarySection(s.data, content)

                1 -> LedgerSection(
                    s.data.expenses, "No spending recorded", content,
                    onEdit = { txn, name, cat -> viewModel.rename(txn.id, name, cat) },
                )

                // Income is TYPED IN, never taken from an SMS: a bank credit
                // can be a refund, a split settlement or your own money moving
                // between accounts. Those are listed separately as "received".
                2 -> IncomeScreen(
                    income = s.data.income,
                    onAdd = viewModel::addIncome,
                    modifier = content,
                )

                else -> CardSection(
                    dues = s.data.dues,
                    onSetLimit = viewModel::setCreditLimit,
                    spends = s.data.cardSpends,
                    modifier = content,
                    onEdit = { txn, name, cat -> viewModel.rename(txn.id, name, cat) },
                )
            }
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
