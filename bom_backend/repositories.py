from __future__ import annotations

from typing import Any

from bom_backend.models import Part, Relationship, Snapshot
from bom_backend.serialization import (
    part_from_record,
    part_to_record,
    relationship_from_record,
    relationship_to_record,
    snapshot_from_record,
    snapshot_to_record,
)
from bom_backend.store import ProjectStore
from bom_backend.utils.sorting import relationship_sort_key


class PartRepository:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def list_parts(self) -> list[Part]:
        records = self._store.read_section("parts")
        parts = [part_from_record(record) for record in records]
        parts.sort(key=lambda part: part.part_number)
        return parts

    def get(self, part_number: str) -> Part | None:
        return {p.part_number: p for p in self.list_parts()}.get(part_number)

    def exists(self, part_number: str) -> bool:
        return self.get(part_number) is not None

    def upsert(self, part: Part) -> Part:
        parts = {item.part_number: item for item in self.list_parts()}
        parts[part.part_number] = part

        ordered = [part_to_record(parts[key]) for key in sorted(parts.keys())]
        self._store.write_section("parts", ordered)
        return part

    def delete(self, part_number: str) -> bool:
        parts = self.list_parts()
        kept = [part for part in parts if part.part_number != part_number]
        deleted = len(kept) != len(parts)

        if deleted:
            ordered = [part_to_record(part) for part in kept]
            ordered.sort(key=lambda item: item["part_number"])
            self._store.write_section("parts", ordered)

        return deleted


class RelationshipRepository:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _sort_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            records,
            key=lambda item: relationship_sort_key(
                item["parent_part_number"],
                item["child_part_number"],
                item["qty"],
                item.get("rel_id", ""),
            ),
        )

    def list_relationships(self) -> list[Relationship]:
        records = self._store.read_section("relationships")
        records = self._sort_records(records)
        return [relationship_from_record(record) for record in records]

    def get(self, rel_id: str) -> Relationship | None:
        return {r.rel_id: r for r in self.list_relationships()}.get(rel_id)

    def upsert(self, relationship: Relationship) -> Relationship:
        relationships = {item.rel_id: item for item in self.list_relationships()}
        relationships[relationship.rel_id] = relationship

        records = [relationship_to_record(item) for item in relationships.values()]
        records = self._sort_records(records)
        self._store.write_section("relationships", records)
        return relationship

    def delete(self, rel_id: str) -> bool:
        relationships = self.list_relationships()
        kept = [item for item in relationships if item.rel_id != rel_id]
        deleted = len(kept) != len(relationships)

        if deleted:
            records = [relationship_to_record(item) for item in kept]
            records = self._sort_records(records)
            self._store.write_section("relationships", records)

        return deleted

    def find_children(self, parent_part_number: str) -> list[Relationship]:
        return [
            relationship
            for relationship in self.list_relationships()
            if relationship.parent_part_number == parent_part_number
        ]

    def find_parents(self, child_part_number: str) -> list[Relationship]:
        return [
            relationship
            for relationship in self.list_relationships()
            if relationship.child_part_number == child_part_number
        ]

    def count_part_references(self, part_number: str) -> int:
        count = 0
        for relationship in self.list_relationships():
            if relationship.parent_part_number == part_number or relationship.child_part_number == part_number:
                count += 1
        return count


class SnapshotRepository:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _read_snapshots(self) -> list[Snapshot]:
        return [snapshot_from_record(record) for record in self._store.read_section("snapshots")]

    def save(self, snapshot: Snapshot) -> Snapshot:
        snapshots = self._read_snapshots()
        if any(existing.snapshot_id == snapshot.snapshot_id for existing in snapshots):
            raise ValueError(f"Snapshot '{snapshot.snapshot_id}' already exists")

        snapshots.append(snapshot)
        snapshots.sort(key=lambda item: (item.created_at, item.snapshot_id))
        self._store.write_section(
            "snapshots", [snapshot_to_record(item) for item in snapshots]
        )
        return snapshot

    def get(self, snapshot_id: str) -> Snapshot | None:
        return {item.snapshot_id: item for item in self._read_snapshots()}.get(snapshot_id)

    def list_snapshots(self, root_part_number: str | None = None) -> list[Snapshot]:
        snapshots = self._read_snapshots()
        if root_part_number:
            snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.root_part_number == root_part_number
            ]
        snapshots.sort(key=lambda item: (item.created_at, item.snapshot_id))
        return snapshots
