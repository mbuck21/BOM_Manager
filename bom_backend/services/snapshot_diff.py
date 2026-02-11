from __future__ import annotations

from uuid import uuid4

from bom_backend.models import Part, Relationship, Snapshot
from bom_backend.repositories import PartRepository, RelationshipRepository, SnapshotRepository
from bom_backend.result import ServiceResult, err_result, ok_result, service_guard
from bom_backend.serialization import (
    part_to_record,
    relationship_to_record,
    snapshot_to_record,
)
from bom_backend.services.bom_structure import BOMStructureService
from bom_backend.utils.canonical import build_signature
from bom_backend.utils.clock import now_iso_utc


class SnapshotService:
    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        part_repo: PartRepository,
        relationship_repo: RelationshipRepository,
        bom_service: BOMStructureService,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.part_repo = part_repo
        self.relationship_repo = relationship_repo
        self.bom_service = bom_service

    def _ordered_parts(self, parts: list[Part]) -> list[Part]:
        return sorted(parts, key=lambda item: item.part_number)

    def _ordered_relationships(self, relationships: list[Relationship]) -> list[Relationship]:
        return sorted(
            relationships,
            key=lambda item: (
                item.parent_part_number,
                item.child_part_number,
                item.qty,
                item.rel_id,
            ),
        )

    @service_guard
    def create_snapshot(
        self,
        root_part_number: str,
        label: str | None = None,
        deduplicate_if_identical: bool = True,
    ) -> ServiceResult:
        root_part_number = (root_part_number or "").strip()
        if not root_part_number:
            return err_result("root_part_number is required")

        subgraph_result = self.bom_service.get_subgraph(root_part_number)
        if not subgraph_result["ok"]:
            return subgraph_result

        relationship_records = subgraph_result["data"]["relationships"]
        relationships = [Relationship(**record) for record in relationship_records]
        relationship_lookup_ids = {item.rel_id for item in relationships}

        # Pull from repository to freeze the exact relationship records at snapshot time.
        frozen_relationships = [
            relationship
            for relationship in self.relationship_repo.list_relationships()
            if relationship.rel_id in relationship_lookup_ids
        ]
        frozen_relationships = self._ordered_relationships(frozen_relationships)

        reachable_parts = {root_part_number}
        for relationship in frozen_relationships:
            reachable_parts.add(relationship.parent_part_number)
            reachable_parts.add(relationship.child_part_number)

        warnings: list[str] = list(subgraph_result.get("warnings") or [])
        frozen_parts: list[Part] = []

        for part_number in sorted(reachable_parts):
            part = self.part_repo.get(part_number)
            if part is None:
                warnings.append(
                    f"Part '{part_number}' is referenced in BOM but missing from catalog"
                )
                continue
            frozen_parts.append(part)

        frozen_parts = self._ordered_parts(frozen_parts)
        signature = build_signature(root_part_number, frozen_parts, frozen_relationships)

        if deduplicate_if_identical:
            for existing in self.snapshot_repo.list_snapshots(root_part_number=root_part_number):
                if existing.signature == signature:
                    return ok_result(
                        {
                            "snapshot": snapshot_to_record(existing),
                            "deduplicated": True,
                        },
                        warnings=warnings,
                    )

        created_at = now_iso_utc()
        snapshot_id = f"snap_{created_at.replace(':', '').replace('-', '').replace('Z', '').replace('T', '_')}_{uuid4().hex[:8]}"
        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            root_part_number=root_part_number,
            created_at=created_at,
            signature=signature,
            parts=frozen_parts,
            relationships=frozen_relationships,
            label=(label or None),
        )
        self.snapshot_repo.save(snapshot)

        return ok_result(
            {
                "snapshot": snapshot_to_record(snapshot),
                "deduplicated": False,
            },
            warnings=warnings,
        )

    @service_guard
    def get_snapshot(self, snapshot_id: str) -> ServiceResult:
        snapshot_id = (snapshot_id or "").strip()
        if not snapshot_id:
            return err_result("snapshot_id is required")

        snapshot = self.snapshot_repo.get(snapshot_id)
        if snapshot is None:
            return err_result(f"Snapshot '{snapshot_id}' not found")

        return ok_result({"snapshot": snapshot_to_record(snapshot)})

    @service_guard
    def list_snapshots(self, root_part_number: str | None = None) -> ServiceResult:
        snapshots = self.snapshot_repo.list_snapshots(root_part_number=root_part_number)
        return ok_result({"snapshots": [snapshot_to_record(item) for item in snapshots]})


class SnapshotDiffService:
    def __init__(self, snapshot_repo: SnapshotRepository) -> None:
        self.snapshot_repo = snapshot_repo

    def _attributes_diff(self, old: dict, new: dict) -> dict:
        old_keys = set(old.keys())
        new_keys = set(new.keys())

        added = {key: new[key] for key in sorted(new_keys - old_keys)}
        removed = {key: old[key] for key in sorted(old_keys - new_keys)}
        modified = {}
        for key in sorted(old_keys & new_keys):
            if old[key] != new[key]:
                modified[key] = {"before": old[key], "after": new[key]}

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
        }

    @service_guard
    def compare_snapshots(self, snapshot_id_a: str, snapshot_id_b: str) -> ServiceResult:
        snapshot_id_a = (snapshot_id_a or "").strip()
        snapshot_id_b = (snapshot_id_b or "").strip()

        if not snapshot_id_a or not snapshot_id_b:
            return err_result("snapshot_id_a and snapshot_id_b are required")

        snapshot_a = self.snapshot_repo.get(snapshot_id_a)
        snapshot_b = self.snapshot_repo.get(snapshot_id_b)

        errors: list[str] = []
        if snapshot_a is None:
            errors.append(f"Snapshot '{snapshot_id_a}' not found")
        if snapshot_b is None:
            errors.append(f"Snapshot '{snapshot_id_b}' not found")
        if errors:
            return err_result(errors)

        signature_equal = snapshot_a.signature == snapshot_b.signature

        parts_a = {part.part_number: part for part in snapshot_a.parts}
        parts_b = {part.part_number: part for part in snapshot_b.parts}

        added_part_numbers = sorted(set(parts_b.keys()) - set(parts_a.keys()))
        removed_part_numbers = sorted(set(parts_a.keys()) - set(parts_b.keys()))
        common_part_numbers = sorted(set(parts_a.keys()) & set(parts_b.keys()))

        added_parts = [part_to_record(parts_b[key]) for key in added_part_numbers]
        removed_parts = [part_to_record(parts_a[key]) for key in removed_part_numbers]

        modified_parts = []
        for part_number in common_part_numbers:
            before = parts_a[part_number]
            after = parts_b[part_number]
            if before.name == after.name and before.last_updated == after.last_updated and before.attributes == after.attributes:
                continue

            modified_parts.append(
                {
                    "part_number": part_number,
                    "changes": {
                        "name": (
                            None
                            if before.name == after.name
                            else {"before": before.name, "after": after.name}
                        ),
                        "last_updated": (
                            None
                            if before.last_updated == after.last_updated
                            else {"before": before.last_updated, "after": after.last_updated}
                        ),
                        "attributes": self._attributes_diff(before.attributes, after.attributes),
                    },
                }
            )

        rels_a = {rel.rel_id: rel for rel in snapshot_a.relationships}
        rels_b = {rel.rel_id: rel for rel in snapshot_b.relationships}

        added_rel_ids = sorted(set(rels_b.keys()) - set(rels_a.keys()))
        removed_rel_ids = sorted(set(rels_a.keys()) - set(rels_b.keys()))
        common_rel_ids = sorted(set(rels_a.keys()) & set(rels_b.keys()))

        added_relationships = [relationship_to_record(rels_b[key]) for key in added_rel_ids]
        removed_relationships = [relationship_to_record(rels_a[key]) for key in removed_rel_ids]

        modified_relationships = []
        for rel_id in common_rel_ids:
            before = rels_a[rel_id]
            after = rels_b[rel_id]
            if (
                before.parent_part_number == after.parent_part_number
                and before.child_part_number == after.child_part_number
                and before.qty == after.qty
                and before.last_updated == after.last_updated
                and before.attributes == after.attributes
            ):
                continue

            modified_relationships.append(
                {
                    "rel_id": rel_id,
                    "changes": {
                        "parent_part_number": (
                            None
                            if before.parent_part_number == after.parent_part_number
                            else {
                                "before": before.parent_part_number,
                                "after": after.parent_part_number,
                            }
                        ),
                        "child_part_number": (
                            None
                            if before.child_part_number == after.child_part_number
                            else {
                                "before": before.child_part_number,
                                "after": after.child_part_number,
                            }
                        ),
                        "qty": (
                            None
                            if before.qty == after.qty
                            else {"before": before.qty, "after": after.qty}
                        ),
                        "last_updated": (
                            None
                            if before.last_updated == after.last_updated
                            else {"before": before.last_updated, "after": after.last_updated}
                        ),
                        "attributes": self._attributes_diff(before.attributes, after.attributes),
                    },
                }
            )

        data = {
            "snapshot_a": {
                "snapshot_id": snapshot_a.snapshot_id,
                "signature": snapshot_a.signature,
                "created_at": snapshot_a.created_at,
            },
            "snapshot_b": {
                "snapshot_id": snapshot_b.snapshot_id,
                "signature": snapshot_b.signature,
                "created_at": snapshot_b.created_at,
            },
            "signature_equal": signature_equal,
            "equal": signature_equal,
            "part_changes": {
                "added": added_parts,
                "removed": removed_parts,
                "modified": modified_parts,
            },
            "relationship_changes": {
                "added": added_relationships,
                "removed": removed_relationships,
                "modified": modified_relationships,
            },
        }
        if not signature_equal:
            data["equal"] = (
                len(added_parts) == 0
                and len(removed_parts) == 0
                and len(modified_parts) == 0
                and len(added_relationships) == 0
                and len(removed_relationships) == 0
                and len(modified_relationships) == 0
            )

        return ok_result(data)
