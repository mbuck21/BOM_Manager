from __future__ import annotations

from typing import Any

from bom_backend.models import Part
from bom_backend.repositories import PartRepository, RelationshipRepository
from bom_backend.result import ServiceResult, err_result, ok_result, service_guard
from bom_backend.serialization import part_to_record
from bom_backend.utils.clock import now_iso_utc


class PartCatalogService:
    def __init__(self, part_repo: PartRepository, relationship_repo: RelationshipRepository) -> None:
        self.part_repo = part_repo
        self.relationship_repo = relationship_repo

    @service_guard
    def add_or_update_part(
        self,
        part_number: str,
        name: str,
        attributes: dict[str, Any] | None = None,
        last_updated: str | None = None,
        merge_attributes: bool = True,
    ) -> ServiceResult:
        part_number = (part_number or "").strip()
        name = (name or "").strip()

        if not part_number:
            return err_result("part_number is required")
        if not name:
            return err_result("name is required")

        existing = self.part_repo.get(part_number)
        incoming_attributes = dict(attributes or {})

        if existing and merge_attributes:
            merged_attributes = dict(existing.attributes)
            merged_attributes.update(incoming_attributes)
            final_attributes = merged_attributes
        else:
            final_attributes = incoming_attributes

        part = Part(
            part_number=part_number,
            name=name,
            last_updated=last_updated or now_iso_utc(),
            attributes=final_attributes,
        )
        self.part_repo.upsert(part)

        return ok_result(
            {
                "part": part_to_record(part),
                "created": existing is None,
            }
        )

    @service_guard
    def get_part(self, part_number: str) -> ServiceResult:
        part = self.part_repo.get((part_number or "").strip())
        if part is None:
            return err_result(f"Part '{part_number}' not found")
        return ok_result({"part": part_to_record(part)})

    @service_guard
    def list_parts(self, query: str | None = None) -> ServiceResult:
        parts = self.part_repo.list_parts()
        if query:
            needle = query.lower().strip()
            parts = [
                part
                for part in parts
                if needle in part.part_number.lower() or needle in part.name.lower()
            ]

        return ok_result({"parts": [part_to_record(part) for part in parts]})

    @service_guard
    def delete_part(self, part_number: str, allow_if_referenced: bool = False) -> ServiceResult:
        part_number = (part_number or "").strip()
        if not part_number:
            return err_result("part_number is required")

        if not allow_if_referenced:
            reference_count = self.relationship_repo.count_part_references(part_number)
            if reference_count > 0:
                return err_result(
                    f"Part '{part_number}' has {reference_count} relationship references and cannot be deleted"
                )

        deleted = self.part_repo.delete(part_number)
        if not deleted:
            return err_result(f"Part '{part_number}' not found")

        return ok_result({"deleted": True, "part_number": part_number})

    @service_guard
    def update_attributes(
        self,
        part_number: str,
        attributes: dict[str, Any],
        merge_attributes: bool = True,
    ) -> ServiceResult:
        existing = self.part_repo.get((part_number or "").strip())
        if existing is None:
            return err_result(f"Part '{part_number}' not found")

        incoming_attributes = dict(attributes or {})
        if merge_attributes:
            updated_attributes = dict(existing.attributes)
            updated_attributes.update(incoming_attributes)
        else:
            updated_attributes = incoming_attributes

        updated_part = Part(
            part_number=existing.part_number,
            name=existing.name,
            last_updated=now_iso_utc(),
            attributes=updated_attributes,
        )
        self.part_repo.upsert(updated_part)

        return ok_result({"part": part_to_record(updated_part)})
