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
 * Everything the money tabs need.
 *
 * Each field is fetched independently and allowed to FAIL independently. One
 * endpoint returning something unexpected used to blank the entire app — a
 * single malformed number in the summary meant no expenses either, which is a
 * terrible trade. Now a broken part is empty and the rest still shows.
 */
data class HomeData(
    /** Null when the summary call failed. The lists remain usable. */
    val summary: Summary? = null,
    val expenses: List<Transaction> = emptyList(),
    /** Only what the user typed. Bank credits live in [received]. */
    val income: List<Transaction> = emptyList(),
    val received: List<Transaction> = emptyList(),
    /** Purchases made ON a credit card. */
    val cardSpends: List<Transaction> = emptyList(),
    val dues: List<Due> = emptyList(),
    /** What went wrong, if anything, so a partial load can say so quietly. */
    val problems: List<String> = emptyList(),
)

sealed interface HomeState {
    data object Loading : HomeState
    data class Loaded(val data: HomeData) : HomeState
    /** Only when EVERYTHING failed — usually the server being unreachable. */
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
            val data = fetch()
            // A full-screen error only when nothing at all came back. Anything
            // less is a partial load, and four working tabs beat none.
            _state.value = if (data.problems.size >= 7) {
                HomeState.Failed(data.problems.first())
            } else {
                HomeState.Loaded(data)
            }
        }
    }

    /** Rename a transaction, then reload so every tab reflects it. */
    fun rename(id: Long, name: String, category: String) {
        viewModelScope.launch {
            // Reloading below shows the unchanged value, so a failed save
            // reads as "the name didn't stick" rather than a false success.
            runCatching {
                Api.updateTransaction(
                    id = id,
                    merchant = name.ifBlank { null },
                    category = category.ifBlank { null },
                )
            }
            load()
        }
    }

    /** Set a card's credit limit, then reload so "available" recomputes. */
    fun setCreditLimit(accountId: Long, limit: String) {
        viewModelScope.launch {
            runCatching { Api.setCreditLimit(accountId, limit) }
            load()
        }
    }

    /** Add income by hand, then reload. */
    fun addIncome(amount: String, source: String, date: String) {
        viewModelScope.launch {
            runCatching { Api.addIncome(amount, source, date) }
            load()
        }
    }

    /**
     * Six calls in parallel, each surviving the others' failures.
     *
     * Parallel because a sleeping free-tier server should wake once, not six
     * times. Independently caught because a fault in one endpoint must not
     * take the other five down with it.
     */
    private suspend fun fetch(): HomeData = coroutineScope {
        val summaryJob = async { runCatching { Api.summary() } }
        val expensesJob = async { runCatching { Api.bankExpenses() } }
        val incomeJob = async { runCatching { Api.transactionsOfType("income", source = "manual") } }
        val receivedJob = async { runCatching { Api.transactionsOfType("income", source = "sms") } }
        val cardSpendJob = async { runCatching { Api.cardSpends() } }
        val duesJob = async { runCatching { Api.dues() } }

        val s = summaryJob.await()
        val e = expensesJob.await()
        val i = incomeJob.await()
        val r = receivedJob.await()
                val d = duesJob.await()
        val cs = cardSpendJob.await()

        HomeData(
            summary = s.getOrNull(),
            expenses = e.getOrDefault(emptyList()),
            income = i.getOrDefault(emptyList()),
            received = r.getOrDefault(emptyList()),
            cardSpends = cs.getOrDefault(emptyList()),
            dues = d.getOrDefault(emptyList()),
            problems = listOf(s, e, i, r, d, cs).mapNotNull { it.exceptionOrNull()?.message },
        )
    }
}
