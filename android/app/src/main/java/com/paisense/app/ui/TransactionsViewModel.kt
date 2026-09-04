package com.paisense.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.paisense.app.data.Api
import com.paisense.app.data.Summary
import com.paisense.app.data.Transaction
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Three states, not two.
 *
 * "Loading or loaded" would leave nowhere for a failure to go, and this app
 * talks to a free-tier server that sleeps — a slow or failed first call is the
 * normal case, not an exception. Failure has to be something the screen can
 * render and the user can retry, not a crash or a blank list.
 */
sealed interface TransactionsState {
    data object Loading : TransactionsState
    data class Loaded(
        val transactions: List<Transaction>,
        val summary: Summary,
    ) : TransactionsState
    data class Failed(val message: String) : TransactionsState
}

class TransactionsViewModel : ViewModel() {

    private val _state = MutableStateFlow<TransactionsState>(TransactionsState.Loading)
    val state: StateFlow<TransactionsState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.value = TransactionsState.Loading
        // viewModelScope cancels itself when the screen goes away, so rotating
        // the phone mid-request doesn't leak the call or crash on return.
        viewModelScope.launch {
            _state.value = try {
                TransactionsState.Loaded(Api.transactions(), Api.summary())
            } catch (e: Exception) {
                // Surfaced verbatim: on a first run the useful failures are
                // "no API key" and "server asleep", and a generic
                // "Something went wrong" would hide both.
                TransactionsState.Failed(e.message ?: e.toString())
            }
        }
    }
}
