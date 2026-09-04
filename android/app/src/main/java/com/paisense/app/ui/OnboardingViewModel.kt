package com.paisense.app.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.paisense.app.data.Api
import com.paisense.app.data.SmsReader
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface OnboardingState {
    data object NeedsPermission : OnboardingState
    data object Denied : OnboardingState
    data object Counting : OnboardingState
    /** Message counts keyed by months, so each option shows a real number. */
    data class ChooseRange(val counts: Map<Int, Int>) : OnboardingState
    data class Importing(val step: String, val done: Int = 0, val total: Int = 0) : OnboardingState
    data class Finished(val summary: String) : OnboardingState
    data class Failed(val message: String) : OnboardingState
}

class OnboardingViewModel : ViewModel() {

    private val _state = MutableStateFlow<OnboardingState>(OnboardingState.NeedsPermission)
    val state: StateFlow<OnboardingState> = _state.asStateFlow()

    private var lastMonths = 3

    fun onPermissionDenied() {
        _state.value = OnboardingState.Denied
    }

    fun onPermissionGranted(context: Context) {
        _state.value = OnboardingState.Counting
        viewModelScope.launch {
            _state.value = try {
                // Counted before uploading anything, so the choice is informed
                // and nothing leaves the phone until the user picks a range.
                OnboardingState.ChooseRange(
                    mapOf(
                        1 to SmsReader.count(context, 1),
                        2 to SmsReader.count(context, 2),
                        3 to SmsReader.count(context, 3),
                    )
                )
            } catch (e: Exception) {
                OnboardingState.Failed(e.message ?: "Couldn't read messages")
            }
        }
    }

    fun retry(context: Context) = import(context, lastMonths)

    fun import(context: Context, months: Int) {
        lastMonths = months
        viewModelScope.launch {
            try {
                _state.value = OnboardingState.Importing("Reading your inbox…")
                val messages = SmsReader.read(context, months)

                _state.value = OnboardingState.Importing("Uploading ${messages.size} messages…")
                Api.uploadSms(messages)

                // Extraction runs in rounds with a call budget, so the loop
                // below is progress reporting, not the work itself. Each pass
                // teaches patterns that make the next pass cheaper.
                var guard = 0
                while (guard++ < 12) {
                    val status = Api.importStatus()
                    if (status.pending == 0) break

                    _state.value = OnboardingState.Importing(
                        step = "Reading messages…",
                        done = status.processed,
                        total = status.total,
                    )

                    val run = Api.runImport(budget = 25)
                    if (run.remaining == 0) break

                    // Nothing moved: the budget is spent or the queue can't be
                    // progressed right now. Stopping beats spinning — the rest
                    // is still stored and gets picked up next time.
                    if (run.byModel == 0 && run.byPattern == 0) break
                }

                val end = Api.importStatus()
                _state.value = OnboardingState.Finished(
                    if (end.pending == 0) {
                        "${end.processed} messages imported."
                    } else {
                        "${end.processed} of ${end.total} imported. " +
                            "The rest will finish over the next day or two."
                    }
                )
            } catch (e: Exception) {
                _state.value = OnboardingState.Failed(e.message ?: e.toString())
            }
        }
    }
}
