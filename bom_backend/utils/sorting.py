from __future__ import annotations

from typing import Any

from bom_backend.utils.parsing import canonical_number


def relationship_sort_key(parent: str, child: str, qty: Any, rel_id: str) -> tuple[str, str, str, str]:
    return (parent, child, canonical_number(qty), rel_id)
