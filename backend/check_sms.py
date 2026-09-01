"""Run the SMS parsers against sample messages and report field by field.

    cd C:\\projects\\paisense\\backend
    .\\.venv\\Scripts\\python.exe check_sms.py

No database, no server — pure parsing, so the loop is fast. Edit app/sms.py,
re-run, see what changed.

NOTE ON THE SAMPLES: card numbers, available limits and phone numbers below
are ALTERED. The message *format* is byte-identical to the real ones — which
is all the regexes care about — but this repo is public on GitHub, and real
card digits and balances have no business being in it.
"""

from decimal import Decimal

from app.sms import parse_sms

AXIS_SPEND_SMS = (
    "AX-AXISBK-S",
    "Spent INR 845\n"
    "Axis Bank Card no. XX1234\n"
    "27-08-26 17:31:03 IST\n"
    "PVR LIMITED\n"
    "Avl Limit: INR 135651.12\n"
    "Not you? SMS BLOCK 1234 to 919999999999",
    {
        "type": "expense",
        "amount": Decimal("845"),
        "merchant": "PVR LIMITED",
        "txn_time": "2026-08-27T17:31:03+05:30",
        "avl_limit": Decimal("135651.12"),
        "source": "sms",
    },
)

AMEX_PAYMENT_SMS = (
    "TX-AMEXIN-S",
    "Dear Customer, a payment of INR 3,230.00 was received on your Amex Card "
    "***56789 29/08/2026. It may take 24-48 hours for your payment to be "
    "credited. Thank you.",
    {
        "type": "card_payment",
        "amount": Decimal("3230.00"),
        "merchant": None,
        "txn_time": "2026-08-29T00:00:00+05:30",
        "avl_limit": None,
        "source": "sms",
    },
)

# Must return None. Banks send OTPs and marketing from the same sender, and
# a parser that guesses at those will write garbage into your table.
NOT_A_TRANSACTION = (
    "AX-AXISBK-S",
    "OTP for your Axis Bank transaction is 482913. Valid for 10 minutes. "
    "Do not share it with anyone.",
    None,
)

CASES = [
    ("Axis spend", AXIS_SPEND_SMS),
    ("Amex payment", AMEX_PAYMENT_SMS),
    ("Axis OTP (should be ignored)", NOT_A_TRANSACTION),
]


def check(label, case):
    sender, message, expected = case
    print(f"\n=== {label} ===")

    try:
        got = parse_sms(sender, message)
    except NotImplementedError:
        print("  not written yet")
        return
    except Exception as e:
        print(f"  CRASHED: {type(e).__name__}: {e}")
        return

    if expected is None:
        print("  PASS  returned None" if got is None else f"  FAIL  expected None, got {got}")
        return

    if got is None:
        print("  FAIL  returned None, expected a transaction")
        return

    for field, want in expected.items():
        have = getattr(got, field, None)
        if field == "txn_time":
            have = have.isoformat() if have else None
        mark = "ok  " if have == want else "FAIL"
        print(f"  {mark} {field:<10} want={want!r:<32} got={have!r}")


if __name__ == "__main__":
    for label, case in CASES:
        check(label, case)
    print()
