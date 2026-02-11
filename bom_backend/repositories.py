from __future__ import annotations

import json
from pathlib import Path
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
from bom_backend.utils.parsing import canonical_number


class JSONFileCollection:
    def __init__(self, path: Path, root_key: str) -> None:
        self.path = path
        self.root_key = root_key
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_records([])

    def _read_records(self) -> list[dict[str, Any]]:
        self._ensure_file()
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if isinstance(payload, dict):
            items = payload.get(self.root_key, [])
            if isinstance(items, list):
                return [dict(item) for item in items]
            return []

        if isinstance(payload, list):
            return [dict(item) for item in payload]

        return []

    def _write_records(self, records: list[dict[str, Any]]) -> None:
        payload = {self.root_key: records}
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")


class PartRepository:
    def __init__(self, data_dir: str | Path) -> None:
        base = Path(data_dir)
        self._store = JSONFileCollection(base / "parts.json", "parts")

    def list_parts(self) -> list[Part]:
        records = self._store._read_records()
        parts = [part_from_record(record) for record in records]
        parts.sort(key=lambda part: part.part_number)
        return parts

    def get(self, part_number: str) -> Part | None:
        for part in self.list_parts():
            if part.part_number == part_number:
                return part
        return None

    def exists(self, part_number: str) -> bool:
        return self.get(part_number) is not None

    def upsert(self, part: Part) -> Part:
        parts = {item.part_number: item for item in self.list_parts()}
        parts[part.part_number] = part

        ordered = [part_to_record(parts[key]) for key in sorted(parts.keys())]
        self._store._write_records(ordered)
        return part

    def delete(self, part_number: str) -> bool:
        parts = self.list_parts()
        kept = [part for part in parts if part.part_number != part_number]
        deleted = len(kept) != len(parts)

        if deleted:
            ordered = [part_to_record(part) for part in kept]
            ordered.sort(key=lambda item: item["part_number"])
            self._store._write_records(ordered)

        return deleted


class RelationshipRepository:
    def __init__(self, data_dir: str | Path) -> None:
        base = Path(data_dir)
        self._store = JSONFileCollection(base / "relationships.json", "relationships")

    def _sort_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            records,
            key=lambda item: (
                item["parent_part_number"],
                item["child_part_number"],
                canonical_number(item["qty"]),
                item.get("rel_id", ""),
            ),
        )

    def list_relationships(self) -> list[Relationship]:
        records = self._store._read_records()
        records = self._sort_records(records)
        return [relationship_from_record(record) for record in records]

    def get(self, rel_id: str) -> Relationship | None:
        for relationship in self.list_relationships():
            if relationship.rel_id == rel_id:
                return relationship
        return None

    def upsert(self, relationship: Relationship) -> Relationship:
        relationships = {item.rel_id: item for item in self.list_relationships()}
        relationships[relationship.rel_id] = relationship

        records = [relationship_to_record(item) for item in relationships.values()]
        records = self._sort_records(records)
        self._store._write_records(records)
        return relationship

    def delete(self, rel_id: str) -> bool:
        relationships = self.list_relationships()
        kept = [item for item in relationships if item.rel_id != rel_id]
        deleted = len(kept) != len(relationships)

        if deleted:
            records = [relationship_to_record(item) for item in kept]
            records = self._sort_records(records)
            self._store._write_records(records)

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
    def __init__(self, data_dir: str | Path) -> None:
        base = Path(data_dir)
        self.snapshot_dir = base / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, snapshot_id: str) -> Path:
        return self.snapshot_dir / f"{snapshot_id}.json"

    def save(self, snapshot: Snapshot) -> Snapshot:
        path = self._path_for(snapshot.snapshot_id)
        if path.exists():
            raise ValueError(f"Snapshot '{snapshot.snapshot_id}' already exists")

        payload = snapshot_to_record(snapshot)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")

        return snapshot

    def get(self, snapshot_id: str) -> Snapshot | None:
        path = self._path_for(snapshot_id)
        if not path.exists():
            return None

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return snapshot_from_record(payload)

    def list_snapshots(self, root_part_number: str | None = None) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for file_path in sorted(self.snapshot_dir.glob("*.json")):
            with file_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            snapshot = snapshot_from_record(payload)
            if root_part_number and snapshot.root_part_number != root_part_number:
                continue
            snapshots.append(snapshot)

        snapshots.sort(key=lambda item: (item.created_at, item.snapshot_id))
        return snapshots
