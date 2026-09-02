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
        "avl_limit": Decimal("135651.12"),
        "card_last4": "1234",
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
        "avl_limit": None,
        "card_last4": "56789",
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

CASES = [AXIS_SPEND, AMEX_PAYMENT, OTP, PROMO]


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
        if field == "card_last4":
            have = result.card_last4
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
