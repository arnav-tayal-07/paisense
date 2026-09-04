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
    val income: List<Transaction>,
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

    /** Five calls in parallel — the server wakes once, not five times. */
    private suspend fun fetch(): HomeData = coroutineScope {
        val summary = async { Api.summary() }
        val expenses = async { Api.transactionsOfType("expense") }
        val income = async { Api.transactionsOfType("income") }
        val payments = async { Api.transactionsOfType("card_payment") }
        val dues = async { Api.dues() }
        HomeData(
            summary = summary.await(),
            expenses = expenses.await(),
            income = income.await(),
            cardPayments = payments.await(),
            dues = dues.await(),
        )
    }
}
