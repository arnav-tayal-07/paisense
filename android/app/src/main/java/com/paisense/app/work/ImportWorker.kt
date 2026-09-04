package com.paisense.app.work

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.ExistingWorkPolicy
import androidx.work.WorkManager
import androidx.work.workDataOf
import androidx.work.Data
import com.paisense.app.R
import com.paisense.app.data.Api
import com.paisense.app.data.SmsReader

/**
 * Importing SMS history, properly in the background.
 *
 * The first version ran this loop in a ViewModel, and the "continue in
 * background" button was a lie: `viewModelScope` is cancelled the moment the
 * screen goes away, so leaving the screen silently killed the import. That is
 * exactly what WorkManager exists for — it survives navigation, backgrounding,
 * and being swept out of recents, and it reports progress through a
 * notification the user can actually see.
 */
class ImportWorker(context: Context, params: androidx.work.WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val months = inputData.getInt(KEY_MONTHS, 1)

        return try {
            setProgressAndNotify("Reading your inbox…", 0, 0)
            val messages = SmsReader.read(applicationContext, months)

            setProgressAndNotify("Uploading ${messages.size} messages…", 0, messages.size)
            Api.uploadSms(messages)

            // Each pass through the queue teaches patterns that make the next
            // pass cheaper, so this loop gets faster as it goes. It stops when
            // the queue empties, when nothing moved (budget spent), or after a
            // bounded number of rounds so a pathological case can't spin.
            var rounds = 0
            while (rounds++ < 40) {
                val status = Api.importStatus()
                setProgressAndNotify(
                    "Reading messages…", status.processed, status.total
                )
                if (status.pending == 0) break

                val run = Api.runImport(budget = 25)
                if (run.remaining == 0) break

                // Nothing was extracted and nothing matched a pattern: quota is
                // spent for now. Everything still pending is stored and will be
                // picked up next time — stopping beats burning the battery.
                if (run.byModel == 0 && run.byPattern == 0) break
            }

            val end = Api.importStatus()
            notify(
                if (end.pending == 0) "Import complete"
                else "Import paused — ${end.pending} left for later",
                end.processed,
                end.total,
                ongoing = false,
            )
            Result.success(workDataOf(KEY_PROCESSED to end.processed, KEY_TOTAL to end.total))
        } catch (e: Exception) {
            notify("Import failed: ${e.message}", 0, 0, ongoing = false)
            // Retry rather than fail: the usual cause is a sleeping server or a
            // dropped connection, and everything uploaded so far is safe.
            Result.retry()
        }
    }

    private suspend fun setProgressAndNotify(step: String, done: Int, total: Int) {
        setProgress(workDataOf(KEY_STEP to step, KEY_PROCESSED to done, KEY_TOTAL to total))
        setForeground(foregroundInfo(step, done, total))
    }

    private fun foregroundInfo(step: String, done: Int, total: Int): ForegroundInfo {
        val notification = buildNotification(step, done, total, ongoing = true)
        return if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
            ForegroundInfo(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    private fun notify(step: String, done: Int, total: Int, ongoing: Boolean) {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(step, done, total, ongoing))
    }

    private fun buildNotification(step: String, done: Int, total: Int, ongoing: Boolean) =
        NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle("PaiSense")
            .setContentText(if (total > 0) "$step  ($done of $total)" else step)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setOngoing(ongoing)
            .setOnlyAlertOnce(true)
            .apply { if (total > 0 && ongoing) setProgress(total, done, false) }
            .build()

    companion object {
        const val WORK_NAME = "paisense-import"
        const val KEY_MONTHS = "months"
        const val KEY_STEP = "step"
        const val KEY_PROCESSED = "processed"
        const val KEY_TOTAL = "total"

        private const val CHANNEL_ID = "import"
        private const val NOTIFICATION_ID = 1

        fun ensureChannel(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Importing messages",
                    // LOW: progress is worth showing but not worth a sound at
                    // every step of a several-minute job.
                    NotificationManager.IMPORTANCE_LOW,
                )
            )
        }

        /**
         * KEEP, not REPLACE: pressing the button twice should not restart a
         * running import and re-upload everything.
         */
        fun start(context: Context, months: Int) {
            ensureChannel(context)
            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_NAME,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<ImportWorker>()
                    .setInputData(Data.Builder().putInt(KEY_MONTHS, months).build())
                    .build(),
            )
        }
    }
}
