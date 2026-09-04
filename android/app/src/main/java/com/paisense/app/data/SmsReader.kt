package com.paisense.app.data

import android.content.Context
import android.provider.Telephony
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** One message on its way to the backend. Matches `SmsIn` on the server. */
@Serializable
data class OutgoingSms(
    val sender: String,
    val message: String,
    @SerialName("sms_sent_at") val smsSentAt: String,
)

/**
 * Reading the phone's SMS inbox.
 *
 * Two filters are applied here rather than on the server, and both matter:
 *
 * 1. **Only DLT-style senders.** Bank messages arrive from headers like
 *    `VA-RBLBNK-S` — letters and dashes. Messages from people come from phone
 *    numbers. Skipping numeric senders removes the overwhelming majority of an
 *    inbox before anything leaves the device, which is both a privacy property
 *    and the reason importing three months is affordable.
 *
 * 2. **A date floor.** The user chooses how far back to import.
 *
 * Nothing else is filtered. Deciding whether a bank message is a transaction is
 * the server's job — a phone-side guess would silently drop spending.
 */
object SmsReader {

    private val ISO = DateTimeFormatter.ISO_INSTANT

    /**
     * Bank and service senders are alphabetic; people are numeric.
     *
     * Deliberately loose: it only has to exclude conversations with humans, and
     * a false positive costs one wasted message rather than a missed one.
     */
    private fun isServiceSender(address: String?): Boolean {
        if (address.isNullOrBlank()) return false
        return address.any { it.isLetter() }
    }

    /**
     * Does the message mention an amount of money?
     *
     * Every Indian bank writes amounts as INR or Rs followed by digits, so a
     * message without one cannot be a transaction. On a real inbox this cut
     * 293 messages to 184 and — the part that matters — 95 distinct senders
     * to 33, because OTPs, delivery updates and IPO notices all vanish.
     *
     * Deliberately NOT stricter than this. Requiring a verb like "debited"
     * was tried and dropped real transactions: "Rs.1500.00 Dr. from A/C...",
     * "Thank you for payment of INR 1,500.00 towards your Credit Card", and
     * "Payment of Rs 149.00 using Apay balance is successful" are all genuine
     * and all phrased differently. Deciding what counts as a transaction is
     * the model's job; the phone's job is only to skip what obviously isn't.
     */
    private val MONEY = Regex("""(?:INR|RS\.?)\s*[\d,]+(?:\.\d{1,2})?""", RegexOption.IGNORE_CASE)

    private fun mentionsMoney(body: String): Boolean = MONEY.containsMatchIn(body)

    /** How many bank messages exist in the last [months] months. Cheap; no upload. */
    fun count(context: Context, months: Int): Int = read(context, months).size

    /**
     * Bank messages from the last [months] months, newest first.
     *
     * @throws SecurityException if READ_SMS hasn't been granted — the caller
     *   should check first rather than treat this as an expected outcome.
     */
    fun read(context: Context, months: Int): List<OutgoingSms> {
        val since = Instant.now()
            .atZone(ZoneOffset.UTC)
            .minusMonths(months.toLong())
            .toInstant()
            .toEpochMilli()

        val out = mutableListOf<OutgoingSms>()

        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE),
            "${Telephony.Sms.DATE} >= ?",
            arrayOf(since.toString()),
            "${Telephony.Sms.DATE} DESC",
        )?.use { cursor ->
            val addressCol = cursor.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
            val bodyCol = cursor.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val dateCol = cursor.getColumnIndexOrThrow(Telephony.Sms.DATE)

            while (cursor.moveToNext()) {
                val address = cursor.getString(addressCol)
                if (!isServiceSender(address)) continue

                val body = cursor.getString(bodyCol) ?: continue
                if (body.isBlank()) continue
                if (!mentionsMoney(body)) continue

                out += OutgoingSms(
                    sender = address,
                    // Sent verbatim. The server stores this as evidence, and a
                    // well-meant trim here would be invisible there when a
                    // parse goes wrong.
                    message = body,
                    smsSentAt = ISO.format(Instant.ofEpochMilli(cursor.getLong(dateCol))),
                )
            }
        }

        return out
    }
}
