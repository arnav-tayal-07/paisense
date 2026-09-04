package com.paisense.app.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.paisense.app.data.SmsReader
import com.paisense.app.work.ImportWorker
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
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

    private var lastMonths = 1

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

    /**
     * Hand the work to WorkManager and then only *watch* it.
     *
     * The import itself no longer lives in this ViewModel: it used to, and
     * leaving the screen cancelled `viewModelScope` and silently killed the
     * import while the button claimed it was continuing in the background.
     * Now the worker owns the job and this just mirrors its progress, so
     * closing the app is genuinely safe.
     */
    fun import(context: Context, months: Int) {
        lastMonths = months
        _state.value = OnboardingState.Importing("Starting…")
        ImportWorker.start(context, months)
        observe(context)
    }

    fun observe(context: Context) {
        viewModelScope.launch {
            WorkManager.getInstance(context)
                .getWorkInfosForUniqueWorkFlow(ImportWorker.WORK_NAME)
                .collectLatest { infos ->
                    val info = infos.lastOrNull() ?: return@collectLatest
                    _state.value = when (info.state) {
                        WorkInfo.State.RUNNING, WorkInfo.State.ENQUEUED -> OnboardingState.Importing(
                            step = info.progress.getString(ImportWorker.KEY_STEP) ?: "Working…",
                            done = info.progress.getInt(ImportWorker.KEY_PROCESSED, 0),
                            total = info.progress.getInt(ImportWorker.KEY_TOTAL, 0),
                        )

                        WorkInfo.State.SUCCEEDED -> {
                            val done = info.outputData.getInt(ImportWorker.KEY_PROCESSED, 0)
                            val total = info.outputData.getInt(ImportWorker.KEY_TOTAL, 0)
                            OnboardingState.Finished(
                                if (total > 0 && done < total) {
                                    "$done of $total messages read. The rest will finish over " +
                                        "the next day or two."
                                } else {
                                    "$done messages read."
                                }
                            )
                        }

                        WorkInfo.State.FAILED -> OnboardingState.Failed("Import failed.")
                        WorkInfo.State.CANCELLED -> OnboardingState.Failed("Import cancelled.")
                        WorkInfo.State.BLOCKED -> OnboardingState.Importing("Waiting…")
                    }
                }
        }
    }
}
