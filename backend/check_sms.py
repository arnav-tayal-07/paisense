"""Run the SMS extractor against sample messages and report field by field.

    cd C:\\projects\\paisense\\backend
    .\\.venv\\Scripts\\python.exe check_sms.py

Hits the real Gemini API, so it needs GEMINI_API_KEY in .env and an internet
connection. No database involved.

NOTE ON THE SAMPLES: card digits, available limits and phone numbers below
are ALTERED. The message *format* is identical to the real ones, which is all
that matters here — but this repo is public on GitHub, and real card digits
and balances have no business in it.
"""

from decimal import Decimal

from app.sms import extract

AXIS_SPEND = (
    "Axis card spend",
    "AX-AXISBK-S",
    "Spent INR 845\n"
    "Axis Bank Card no. XX1234\n"
    "27-08-26 17:31:03 IST\n"
    "PVR LIMITED\n"
    "Avl Limit: INR 135651.12\n"
    "Not you? SMS BLOCK 1234 to 919999999999",
    {
        "status": "parsed",
        "type": "expense",
        "amount": Decimal("845"),
        "merchant": "PVR LIMITED",
        "txn_time": "2026-08-27T17:31:03+05:30",
        "reported_balance": Decimal("135651.12"),
        "account_last4": "1234",
    },
)

AMEX_PAYMENT = (
    "Amex bill payment",
    "TX-AMEXIN-S",
    "Dear Customer, a payment of INR 3,230.00 was received on your Amex Card "
    "***56789 29/08/2026. It may take 24-48 hours for your payment to be "
    "credited. Thank you.",
    {
        "status": "parsed",
        "type": "card_payment",
        "amount": Decimal("3230.00"),
        "merchant": None,
        "txn_time": "2026-08-29T00:00:00+05:30",
        "reported_balance": None,
        "account_last4": "56789",
    },
)

OTP = (
    "Axis OTP (must be ignored)",
    "AX-AXISBK-S",
    "OTP for your Axis Bank transaction is 482913. Valid for 10 minutes. "
    "Do not share it with anyone.",
    {"status": "ignored"},
)

PROMO = (
    "Marketing (must be ignored)",
    "AX-AXISBK-S",
    "Get 10% cashback up to INR 500 on your Axis Bank Credit Card this "
    "weekend! T&C apply. Click ccm.axis.bank.in/OFFER to know more.",
    {"status": "ignored"},
)

IDFC_PURCHASE = (
    "IDFC purchase",
    "JD-IDFCFB-S",
    "Delicious Purchase! INR 84.00 spent on your IDFC FIRST Bank Credit Card "
    "ending XX4321 at KARIMS MUGHLAI RESTA on 07 AUG 2026 at 08:38 PM "
    "Avbl Limit: INR 15000.00 If not done by you, call 1800100000 for "
    "dispute or to block your card SMS CCBLOCK 4321 to 5670000",
    {
        "status": "parsed",
        "type": "expense",
        "amount": Decimal("84.00"),
        "merchant": "KARIMS MUGHLAI RESTA",
        # 08:38 PM -> 20:38. 12-hour time appears in no other bank's format.
        "txn_time": "2026-08-07T20:38:00+05:30",
        "reported_balance": Decimal("15000.00"),
        "account_last4": "4321",
    },
)

# Recurring subscription charge. No merchant keyword like "at" or "to" —
# the payee is named mid-sentence, and the message is mostly noise: a URL,
# a reference ID, and instructions for managing the standing instruction.
IDFC_STANDING_INSTRUCTION = (
    "IDFC standing instruction",
    "JD-IDFCFB-S",
    "INR 2399.00 for Anthropic paid from your IDFC FIRST Bank Credit Card "
    "XX9876 on 01/09/2026 basis standing instruction (SI). "
    "Manage SI on your card: https://example.invalid/x "
    "using the SiHub ID: ABCDEF",
    {
        "status": "parsed",
        "type": "expense",
        "amount": Decimal("2399.00"),
        "merchant": "Anthropic",
        "txn_time": "2026-09-01T00:00:00+05:30",
        "reported_balance": None,
        "account_last4": "9876",
    },
)

RBL_UPI_DEBIT = (
    "RBL UPI debit (no time, no merchant)",
    "VA-RBLBNK-S",
    "Your a/c XX1111 is debited for Rs.658.36 on 02-09-26 and credited to "
    "a/c XX2222 (UPI Ref 661188335104). Not you? pls forward this SMS to "
    "8500000000 -RBL Bank",
    {
        "status": "parsed",
        "type": "expense",
        "amount": Decimal("658.36"),
        # No business is named - only a destination account. merchant must
        # stay null rather than being filled with an account number.
        "merchant": None,
        "counterparty": "XX2222",
        "account_last4": "1111",
        "reported_balance": None,
        # THE CASE THAT MATTERS: this format has a date and no time, so
        # txn_time falls back to midnight. Two same-amount payments on one day
        # would collide on a derived key - the reference is what prevents it.
        "upi_ref": "661188335104",
    },
)

RBL_UPI_CREDIT = (
    "RBL UPI credit (money in)",
    "VA-RBLBNK-S",
    "Your a/c no. XX1111 is credited for Rs.160.00 on 2026-09-02 10:51:35 "
    "and debited from a/c no. XX3333 (UPI Ref no 105143193111)- RBL Bank",
    {
        "status": "parsed",
        # Credited, so income - not an expense.
        "type": "income",
        "amount": Decimal("160.00"),
        "merchant": None,
        "account_last4": "1111",
        "upi_ref": "105143193111",
        # Different label ("UPI Ref no") and a different date format
        # (YYYY-MM-DD with time) from the debit message on the SAME sender.
        "txn_time": "2026-09-02T10:51:35+05:30",
    },
)

BOB_UPI_DEBIT = (
    "BOB UPI debit (VPA payee, AvlBal, colon dates)",
    "VM-BOBSMS-S",
    "Rs.340.00 Dr. from A/C XXXXXX4444 and Cr. to paytmqr6s4v8c@ptys. "
    "Ref:623928991037. AvlBal:Rs7180.70(2026:08:27 08:01:42). "
    "Not you? Call 18005700/5000-BOB",
    {
        "status": "parsed",
        "type": "expense",
        "amount": Decimal("340.00"),
        "counterparty": "paytmqr6s4v8c@ptys",
        "account_last4": "4444",
        # AvlBal on a bank account, not Avl Limit on a card. Same column.
        "reported_balance": Decimal("7180.70"),
        "upi_ref": "623928991037",
        # (2026:08:27 08:01:42) - colon-separated date, seen nowhere else.
        "txn_time": "2026-08-27T08:01:42+05:30",
    },
)

BOB_LINKING = (
    "BOB account-linking notice (must be ignored)",
    "VM-BOBSMS-S",
    "We got a request for linking your account for UPI 4444. If its not you "
    "kindly contact your bank on helpline no. 1800-5700 immediately -BOB",
    {"status": "ignored"},
)

CASES = [
    AXIS_SPEND,
    AMEX_PAYMENT,
    IDFC_PURCHASE,
    IDFC_STANDING_INSTRUCTION,
    RBL_UPI_DEBIT,
    RBL_UPI_CREDIT,
    BOB_UPI_DEBIT,
    OTP,
    PROMO,
    BOB_LINKING,
]


def check(label, sender, body, expected):
    print(f"\n=== {label} ===")
    result = extract(sender, body)

    if result.status != expected["status"]:
        print(f"  FAIL status    want={expected['status']!r} got={result.status!r}")
        if result.error:
            print(f"       error: {result.error}")
        return
    print(f"  ok   status    {result.status}")

    if result.status != "parsed":
        if result.error:
            print(f"       reason: {result.error}")
        return

    for field, want in expected.items():
        if field == "status":
            continue
        if field == "account_last4":
            have = result.account_last4
        else:
            have = getattr(result.txn, field, None)
            if field == "txn_time":
                have = have.isoformat() if have else None
        mark = "ok  " if have == want else "FAIL"
        print(f"  {mark} {field:<10} want={want!r:<32} got={have!r}")

    print(f"       dedupe_key: {result.txn.dedupe_key}")


if __name__ == "__main__":
    for label, sender, body, expected in CASES:
        check(label, sender, body, expected)
    print()
