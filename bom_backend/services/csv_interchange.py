from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from bom_backend.repositories import PartRepository, RelationshipRepository
from bom_backend.result import ServiceResult, err_result, ok_result, service_guard
from bom_backend.services.bom_structure import BOMStructureService
from bom_backend.services.part_catalog import PartCatalogService
from bom_backend.utils.parsing import parse_csv_value, parse_qty

_PART_RESERVED = {"part_number", "name", "last_updated", "attributes_json"}
_REL_RESERVED = {
    "rel_id",
    "parent_part_number",
    "child_part_number",
    "qty",
    "last_updated",
    "attributes_json",
}


class CSVInterchangeService:
    def __init__(
        self,
        part_service: PartCatalogService,
        bom_service: BOMStructureService,
        part_repo: PartRepository,
        relationship_repo: RelationshipRepository,
    ) -> None:
        self.part_service = part_service
        self.bom_service = bom_service
        self.part_repo = part_repo
        self.relationship_repo = relationship_repo

    def _extract_attributes(
        self,
        row: dict[str, Any],
        reserved_columns: set[str],
    ) -> tuple[dict[str, Any], list[str]]:
        attributes: dict[str, Any] = {}
        warnings: list[str] = []

        attributes_json = (row.get("attributes_json") or "").strip()
        if attributes_json:
            try:
                parsed = json.loads(attributes_json)
                if isinstance(parsed, dict):
                    attributes.update(parsed)
                else:
                    warnings.append("attributes_json was not a JSON object and was ignored")
            except json.JSONDecodeError:
                warnings.append("attributes_json was invalid JSON and was ignored")

        for key, raw_value in row.items():
            if key in reserved_columns:
                continue
            if raw_value is None or str(raw_value).strip() == "":
                continue

            attr_key = key[6:] if key.startswith("attr__") else key
            parsed_value = parse_csv_value(raw_value)
            attributes[attr_key] = parsed_value

        return attributes, warnings

    @service_guard
    def import_parts_csv(
        self,
        csv_path: str | Path,
        merge_attributes: bool = True,
    ) -> ServiceResult:
        path = Path(csv_path)
        if not path.exists():
            return err_result(f"CSV file not found: {path}")

        created_count = 0
        updated_count = 0
        row_errors: list[str] = []
        warnings: list[str] = []

        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"part_number", "name"}
            header = set(reader.fieldnames or [])
            missing = required - header
            if missing:
                return err_result(
                    f"Missing required columns for parts import: {', '.join(sorted(missing))}"
                )

            for idx, row in enumerate(reader, start=2):
                part_number = str(row.get("part_number", "")).strip()
                name = str(row.get("name", "")).strip()
                last_updated = str(row.get("last_updated", "")).strip() or None

                if not part_number:
                    row_errors.append(f"Row {idx}: part_number is required")
                    continue
                if not name:
                    row_errors.append(f"Row {idx}: name is required")
                    continue

                attributes, row_warnings = self._extract_attributes(row, _PART_RESERVED)
                for warning in row_warnings:
                    warnings.append(f"Row {idx}: {warning}")

                result = self.part_service.add_or_update_part(
                    part_number=part_number,
                    name=name,
                    attributes=attributes,
                    last_updated=last_updated,
                    merge_attributes=merge_attributes,
                )
                if not result["ok"]:
                    row_errors.append(
                        f"Row {idx}: " + "; ".join(result["errors"])
                    )
                    continue

                if result["data"]["created"]:
                    created_count += 1
                else:
                    updated_count += 1

        return ok_result(
            {
                "file": str(path),
                "created": created_count,
                "updated": updated_count,
                "failed_rows": len(row_errors),
                "row_errors": row_errors,
            },
            warnings=warnings,
        )

    @service_guard
    def import_relationships_csv(
        self,
        csv_path: str | Path,
        allow_dangling: bool = False,
        merge_attributes: bool = True,
    ) -> ServiceResult:
        path = Path(csv_path)
        if not path.exists():
            return err_result(f"CSV file not found: {path}")

        created_count = 0
        updated_count = 0
        row_errors: list[str] = []
        warnings: list[str] = []

        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"parent_part_number", "child_part_number", "qty"}
            header = set(reader.fieldnames or [])
            missing = required - header
            if missing:
                return err_result(
                    "Missing required columns for relationships import: "
                    + ", ".join(sorted(missing))
                )

            for idx, row in enumerate(reader, start=2):
                parent = str(row.get("parent_part_number", "")).strip()
                child = str(row.get("child_part_number", "")).strip()
                rel_id = str(row.get("rel_id", "")).strip() or None
                qty = parse_qty(row.get("qty"))
                last_updated = str(row.get("last_updated", "")).strip() or None

                if not parent:
                    row_errors.append(f"Row {idx}: parent_part_number is required")
                    continue
                if not child:
                    row_errors.append(f"Row {idx}: child_part_number is required")
                    continue
                if qty is None:
                    row_errors.append(f"Row {idx}: qty must be numeric")
                    continue

                attributes, row_warnings = self._extract_attributes(row, _REL_RESERVED)
                for warning in row_warnings:
                    warnings.append(f"Row {idx}: {warning}")

                result = self.bom_service.add_or_update_relationship(
                    parent_part_number=parent,
                    child_part_number=child,
                    qty=qty,
                    rel_id=rel_id,
                    attributes=attributes,
                    last_updated=last_updated,
                    allow_dangling=allow_dangling,
                    merge_attributes=merge_attributes,
                )
                if not result["ok"]:
                    row_errors.append(
                        f"Row {idx}: " + "; ".join(result["errors"])
                    )
                    continue

                if result["data"]["created"]:
                    created_count += 1
                else:
                    updated_count += 1

                for warning in result.get("warnings") or []:
                    warnings.append(f"Row {idx}: {warning}")

        return ok_result(
            {
                "file": str(path),
                "created": created_count,
                "updated": updated_count,
                "failed_rows": len(row_errors),
                "row_errors": row_errors,
            },
            warnings=warnings,
        )

    @service_guard
    def export_parts_csv(
        self,
        csv_path: str | Path,
        attribute_whitelist: list[str] | None = None,
        include_attributes_json: bool = True,
    ) -> ServiceResult:
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        whitelist = list(attribute_whitelist or [])
        fieldnames = ["part_number", "name", "last_updated"] + whitelist
        if include_attributes_json:
            fieldnames.append("attributes_json")

        parts = self.part_repo.list_parts()
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()

            for part in parts:
                row: dict[str, Any] = {
                    "part_number": part.part_number,
                    "name": part.name,
                    "last_updated": part.last_updated,
                }
                for attr_key in whitelist:
                    row[attr_key] = part.attributes.get(attr_key, "")
                if include_attributes_json:
                    row["attributes_json"] = json.dumps(
                        part.attributes,
                        sort_keys=True,
                        ensure_ascii=True,
                    )
                writer.writerow(row)

        return ok_result(
            {
                "file": str(path),
                "rows": len(parts),
                "columns": fieldnames,
            }
        )

    @service_guard
    def export_relationships_csv(
        self,
        csv_path: str | Path,
        attribute_whitelist: list[str] | None = None,
        include_attributes_json: bool = True,
    ) -> ServiceResult:
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        whitelist = list(attribute_whitelist or [])
        fieldnames = [
            "rel_id",
            "parent_part_number",
            "child_part_number",
            "qty",
            "last_updated",
        ] + whitelist
        if include_attributes_json:
            fieldnames.append("attributes_json")

        relationships = self.relationship_repo.list_relationships()
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()

            for relationship in relationships:
                row: dict[str, Any] = {
                    "rel_id": relationship.rel_id,
                    "parent_part_number": relationship.parent_part_number,
                    "child_part_number": relationship.child_part_number,
                    "qty": relationship.qty,
                    "last_updated": relationship.last_updated,
                }
                for attr_key in whitelist:
                    row[attr_key] = relationship.attributes.get(attr_key, "")
                if include_attributes_json:
                    row["attributes_json"] = json.dumps(
                        relationship.attributes,
                        sort_keys=True,
                        ensure_ascii=True,
                    )
                writer.writerow(row)

        return ok_result(
            {
                "file": str(path),
                "rows": len(relationships),
                "columns": fieldnames,
            }
        )
