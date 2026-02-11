from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

_INT_PATTERN = re.compile(r"^[+-]?\d+$")
_FLOAT_PATTERN = re.compile(r"^[+-]?(\d+\.\d+|\d+\.|\.\d+)$")


def parse_csv_value(raw: Any) -> Any:
    if raw is None:
        return None

    if isinstance(raw, (bool, int, float, dict, list)):
        return raw

    text = str(raw).strip()
    if text == "":
        return None

    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    if _INT_PATTERN.match(text):
        try:
            return int(text)
        except ValueError:
            pass

    if _FLOAT_PATTERN.match(text):
        try:
            return float(text)
        except ValueError:
            pass

    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    return text


def parse_qty(raw: Any) -> float | None:
    value = parse_csv_value(raw)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def canonical_number(value: Any) -> str:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    normalized = dec.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))

    return format(normalized, "f").rstrip("0").rstrip(".")
