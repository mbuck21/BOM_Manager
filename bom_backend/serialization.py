from __future__ import annotations

from typing import Any

from bom_backend.models import Part, Relationship, Snapshot


def part_from_record(record: dict[str, Any]) -> Part:
    return Part(
        part_number=str(record.get("part_number", "")).strip(),
        name=str(record.get("name", "")).strip(),
        last_updated=str(record.get("last_updated", "")).strip(),
        attributes=dict(record.get("attributes") or {}),
    )


def part_to_record(part: Part) -> dict[str, Any]:
    return {
        "part_number": part.part_number,
        "name": part.name,
        "last_updated": part.last_updated,
        "attributes": dict(part.attributes),
    }


def relationship_from_record(record: dict[str, Any]) -> Relationship:
    return Relationship(
        rel_id=str(record.get("rel_id", "")).strip(),
        parent_part_number=str(record.get("parent_part_number", "")).strip(),
        child_part_number=str(record.get("child_part_number", "")).strip(),
        qty=float(record.get("qty", 0) or 0),
        last_updated=str(record.get("last_updated", "")).strip(),
        attributes=dict(record.get("attributes") or {}),
    )


def relationship_to_record(relationship: Relationship) -> dict[str, Any]:
    return {
        "rel_id": relationship.rel_id,
        "parent_part_number": relationship.parent_part_number,
        "child_part_number": relationship.child_part_number,
        "qty": relationship.qty,
        "last_updated": relationship.last_updated,
        "attributes": dict(relationship.attributes),
    }


def snapshot_from_record(record: dict[str, Any]) -> Snapshot:
    part_records = record.get("parts") or []
    relationship_records = record.get("relationships") or []
    return Snapshot(
        snapshot_id=str(record.get("snapshot_id", "")).strip(),
        root_part_number=str(record.get("root_part_number", "")).strip(),
        created_at=str(record.get("created_at", "")).strip(),
        signature=str(record.get("signature", "")).strip(),
        label=record.get("label"),
        parts=[part_from_record(item) for item in part_records],
        relationships=[relationship_from_record(item) for item in relationship_records],
    )


def snapshot_to_record(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "root_part_number": snapshot.root_part_number,
        "created_at": snapshot.created_at,
        "signature": snapshot.signature,
        "label": snapshot.label,
        "parts": [part_to_record(part) for part in snapshot.parts],
        "relationships": [relationship_to_record(relationship) for relationship in snapshot.relationships],
    }
