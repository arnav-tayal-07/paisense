package com.paisense.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.paisense.app.data.Api
import com.paisense.app.data.ReviewItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface ReviewState {
    data object Loading : ReviewState
    data class Loaded(val items: List<ReviewItem>) : ReviewState
    data class Failed(val message: String) : ReviewState
}

class ReviewViewModel : ViewModel() {

    private val _state = MutableStateFlow<ReviewState>(ReviewState.Loading)
    val state: StateFlow<ReviewState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = try {
                ReviewState.Loaded(Api.reviewQueue())
            } catch (e: Exception) {
                ReviewState.Failed(e.message ?: e.toString())
            }
        }
    }

    fun confirm(id: Long) = decide(id) { Api.confirm(it) }

    fun reject(id: Long) = decide(id) { Api.reject(it) }

    /**
     * Remove the card immediately, then tell the server.
     *
     * Optimistic on purpose: waiting on a sleeping free-tier server before the
     * card disappears would make every tap feel broken. If the call fails the
     * list is reloaded, so the card comes back rather than silently vanishing
     * while the server still thinks it needs review.
     */
    private fun decide(id: Long, action: suspend (Long) -> Unit) {
        val current = _state.value
        if (current is ReviewState.Loaded) {
            _state.value = ReviewState.Loaded(current.items.filterNot { it.id == id })
        }
        viewModelScope.launch {
            try {
                action(id)
            } catch (_: Exception) {
                load()
            }
        }
    }
}
