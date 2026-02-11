from __future__ import annotations

import hashlib
import json
from typing import Any

from bom_backend.models import Part, Relationship
from bom_backend.serialization import part_to_record, relationship_to_record
from bom_backend.utils.parsing import canonical_number


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize_value(value[key]) for key in sorted(value.keys())}

    if isinstance(value, list):
        return [_canonicalize_value(item) for item in value]

    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return canonical_number(value)

    return value


def canonicalize_part(part: Part) -> dict[str, Any]:
    record = part_to_record(part)
    record["attributes"] = _canonicalize_value(record.get("attributes") or {})
    return record


def canonicalize_relationship(relationship: Relationship) -> dict[str, Any]:
    record = relationship_to_record(relationship)
    record["qty"] = canonical_number(record.get("qty"))
    record["attributes"] = _canonicalize_value(record.get("attributes") or {})
    return record


def canonical_snapshot_payload(
    root_part_number: str,
    parts: list[Part],
    relationships: list[Relationship],
) -> dict[str, Any]:
    canonical_parts = [canonicalize_part(part) for part in parts]
    canonical_relationships = [canonicalize_relationship(rel) for rel in relationships]

    canonical_parts.sort(key=lambda item: item["part_number"])
    canonical_relationships.sort(
        key=lambda item: (
            item["parent_part_number"],
            item["child_part_number"],
            item["qty"],
            item.get("rel_id", ""),
        )
    )

    return {
        "root_part_number": root_part_number,
        "parts": canonical_parts,
        "relationships": canonical_relationships,
    }


def build_signature(root_part_number: str, parts: list[Part], relationships: list[Relationship]) -> str:
    payload = canonical_snapshot_payload(root_part_number, parts, relationships)
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
