from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def base_number(part_number: str) -> str:
    """Drawing-family base of a part number: '20547015-101' -> '20547015'.

    The dash suffix identifies a variant of the same base drawing; parts without a
    dash are their own base. Only the last dash is treated as the suffix separator.
    """
    pn = (part_number or "").strip()
    return pn.rsplit("-", 1)[0] if "-" in pn else pn


def canonical_number(value: Any) -> str:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    normalized = dec.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))

    return format(normalized, "f").rstrip("0").rstrip(".")
