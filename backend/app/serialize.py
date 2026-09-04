"""Money leaves this API as a string, never as a JSON number.

Postgres stores `numeric(12,2)` and psycopg hands back a `Decimal`, both exact.
JSON has no decimal type, so FastAPI's default encoder turns that Decimal into
a float — and `120.50` becomes `120.5`, `0.1 + 0.2` stops being `0.3`, and the
client re-inherits precisely the problem ADR 011 chose `numeric` to avoid.

Sending money as a string keeps it exact all the way to the phone, which can
parse it into its own decimal type if it needs arithmetic.

Internal code still works in Decimal — reconciliation subtracts balances, and
that must not happen on strings. The conversion belongs at the boundary and
nowhere else.
"""

from decimal import Decimal

from fastapi.encoders import jsonable_encoder


def out(content):
    """Prepare a value for the wire. Decimals become strings; everything else
    is encoded as usual (datetimes to ISO 8601, and so on)."""
    return jsonable_encoder(content, custom_encoder={Decimal: str})
