package com.paisense.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.paisense.app.data.Api
import com.paisense.app.data.Due
import com.paisense.app.data.Summary
import com.paisense.app.data.Transaction
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Everything the three money tabs need, loaded once.
 *
 * Income, expenses and card sections all read from the same fetch rather than
 * each firing its own — on a free-tier server that sleeps, three separate cold
 * starts would mean three separate minute-long waits.
 */
data class HomeData(
    val summary: Summary,
    val expenses: List<Transaction>,
    /** Only what the user typed. Bank credits live in [received]. */
    val income: List<Transaction>,
    val received: List<Transaction>,
    val cardPayments: List<Transaction>,
    val dues: List<Due>,
)

sealed interface HomeState {
    data object Loading : HomeState
    data class Loaded(val data: HomeData) : HomeState
    data class Failed(val message: String) : HomeState
}

class HomeViewModel : ViewModel() {

    private val _state = MutableStateFlow<HomeState>(HomeState.Loading)
    val state: StateFlow<HomeState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.value = HomeState.Loading
        viewModelScope.launch {
            _state.value = try {
                HomeState.Loaded(fetch())
            } catch (e: Exception) {
                HomeState.Failed(e.message ?: e.toString())
            }
        }
    }

    /** Rename a transaction, then reload so every tab reflects it. */
    fun rename(id: Long, name: String, category: String) {
        viewModelScope.launch {
            try {
                Api.updateTransaction(
                    id = id,
                    merchant = name.ifBlank { null },
                    category = category.ifBlank { null },
                )
            } catch (_: Exception) {
                // Reloading below surfaces the unchanged value, so a failed
                // save shows as "the name didn't stick" rather than a lie.
            }
            load()
        }
    }

    /** Add income by hand, then reload. */
    fun addIncome(amount: String, source: String, date: String) {
        viewModelScope.launch {
            try {
                Api.addIncome(amount, source, date)
            } catch (_: Exception) {
            }
            load()
        }
    }

    /** Five calls in parallel — the server wakes once, not five times. */
    private suspend fun fetch(): HomeData = coroutineScope {
        val summary = async { Api.summary() }
        val expenses = async { Api.transactionsOfType("expense") }
        val income = async { Api.transactionsOfType("income", source = "manual") }
        val received = async { Api.transactionsOfType("income", source = "sms") }
        val payments = async { Api.transactionsOfType("card_payment") }
        val dues = async { Api.dues() }
        HomeData(
            summary = summary.await(),
            expenses = expenses.await(),
            income = income.await(),
            received = received.await(),
            cardPayments = payments.await(),
            dues = dues.await(),
        )
    }
}
