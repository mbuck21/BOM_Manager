from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def canonical_number(value: Any) -> str:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    normalized = dec.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))

    return format(normalized, "f").rstrip("0").rstrip(".")
