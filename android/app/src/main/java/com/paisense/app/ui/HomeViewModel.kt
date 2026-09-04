package com.paisense.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.paisense.app.data.Account
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
    /** Where a manually added transaction can be filed. */
    val accounts: List<Account> = emptyList(),
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

    /** True while a pull-to-refresh is in flight, so the spinner can show. */
    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    init {
        load()
    }

    fun load() {
        // Only blank the screen when there is nothing worth keeping. Showing
        // a full-screen spinner over data we already have made every resume
        // and every pull-to-refresh flash empty for no reason — the numbers
        // were about to be replaced by nearly identical ones.
        if (_state.value !is HomeState.Loaded) {
            _state.value = HomeState.Loading
        }
        viewModelScope.launch {
            val data = fetch()
            // A full-screen error only when nothing at all came back. Anything
            // less is a partial load, and four working tabs beat none.
            _state.value = if (data.problems.size >= 7) {
                HomeState.Failed(data.problems.first())
            } else {
                HomeState.Loaded(data)
            }
            _refreshing.value = false
        }
    }

    /**
     * Pull-to-refresh.
     *
     * Separate from [load] only so the indicator knows to spin. The app
     * refetches on its own when it returns to the foreground, but that can't
     * help while you are already looking at the screen — an import finishing
     * in the background, or a message arriving, has no way to announce
     * itself. This is the manual answer to "is this number current?".
     */
    fun refresh() {
        _refreshing.value = true
        load()
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

    /**
     * Set a card's credit limit, then reload so "available" recomputes.
     *
     * Reports a failed save instead of swallowing it. Discarding the error
     * and reloading anyway shows the OLD limit, which looks exactly like a
     * save that worked on a value that happened to match — the user is left
     * pressing Save repeatedly with no idea anything is wrong.
     */
    fun setCreditLimit(accountId: Long, limit: String) {
        viewModelScope.launch {
            val failure = runCatching { Api.setCreditLimit(accountId, limit) }.exceptionOrNull()
            val data = fetch()
            _state.value = HomeState.Loaded(
                if (failure == null) data
                else data.copy(
                    problems = data.problems +
                        "Couldn't save the credit limit: ${failure.message}"
                )
            )
            _refreshing.value = false
        }
    }

    /** Add income by hand, then reload. */
    fun addIncome(amount: String, source: String, date: String) {
        mutate("Couldn't save the income") { Api.addIncome(amount, source, date) }
    }

    /**
     * Record a spend by hand — cash, or anything the bank never texted about.
     *
     * `accountId` is required by the caller rather than optional: the lists
     * are filtered by account kind, so an entry filed nowhere would be saved
     * and then invisible.
     */
    fun addExpense(amount: String, payee: String, date: String, accountId: Long) {
        mutate("Couldn't save the expense") {
            Api.addTransaction("expense", amount, payee, date, accountId)
        }
    }

    /**
     * Delete a transaction.
     *
     * No undo, so the UI asks first. Deleting a row that came from an SMS
     * removes the transaction but keeps the message, which means a later
     * re-import can bring it back — worth knowing, and better than losing the
     * message too.
     */
    fun delete(id: Long) {
        mutate("Couldn't delete") { Api.deleteTransaction(id) }
    }

    /**
     * Run a change, then refetch, reporting failure instead of hiding it.
     *
     * Every one of these used to be `runCatching { ... }; load()`, which
     * discards the error and reloads — so a failed save looks exactly like a
     * successful one that changed nothing, and you press the button again
     * wondering why nothing happens. That is what made the credit limit
     * appear broken.
     */
    private fun mutate(failureMessage: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            val failure = runCatching { block() }.exceptionOrNull()
            // Fetching inline rather than calling load(): load() writes state
            // from its own coroutine, so a message appended after it would be
            // overwritten by the very refresh that caused it.
            val data = fetch()
            _state.value = HomeState.Loaded(
                if (failure == null) data
                else data.copy(problems = data.problems + "$failureMessage: ${failure.message}")
            )
            _refreshing.value = false
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
        val accountsJob = async { runCatching { Api.accounts() } }

        val s = summaryJob.await()
        val e = expensesJob.await()
        val i = incomeJob.await()
        val r = receivedJob.await()
                val d = duesJob.await()
        val cs = cardSpendJob.await()
        val ac = accountsJob.await()

        HomeData(
            summary = s.getOrNull(),
            expenses = e.getOrDefault(emptyList()),
            income = i.getOrDefault(emptyList()),
            received = r.getOrDefault(emptyList()),
            cardSpends = cs.getOrDefault(emptyList()),
            accounts = ac.getOrDefault(emptyList()),
            dues = d.getOrDefault(emptyList()),
            problems = listOf(s, e, i, r, d, cs, ac).mapNotNull { it.exceptionOrNull()?.message },
        )
    }
}
