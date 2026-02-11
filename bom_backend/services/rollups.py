from __future__ import annotations

from collections import deque
from typing import Any

from bom_backend.repositories import PartRepository, RelationshipRepository
from bom_backend.result import ServiceResult, err_result, ok_result, service_guard


class RollupService:
    def __init__(self, part_repo: PartRepository, relationship_repo: RelationshipRepository) -> None:
        self.part_repo = part_repo
        self.relationship_repo = relationship_repo

    @service_guard
    def rollup_numeric_attribute(
        self,
        root_part_number: str,
        attribute_key: str,
        include_root: bool = True,
    ) -> ServiceResult:
        root_part_number = (root_part_number or "").strip()
        attribute_key = (attribute_key or "").strip()

        if not root_part_number:
            return err_result("root_part_number is required")
        if not attribute_key:
            return err_result("attribute_key is required")

        queue: deque[tuple[str, float, list[str]]] = deque()
        queue.append((root_part_number, 1.0, [root_part_number]))

        total = 0.0
        breakdown: list[dict[str, Any]] = []
        warnings: list[str] = []
        warning_set: set[str] = set()

        while queue:
            part_number, quantity_multiplier, path = queue.popleft()
            is_root = len(path) == 1

            if include_root or not is_root:
                part = self.part_repo.get(part_number)
                if part is None:
                    warning = f"Part '{part_number}' is missing from catalog"
                    if warning not in warning_set:
                        warnings.append(warning)
                        warning_set.add(warning)
                else:
                    raw_value = part.attributes.get(attribute_key)
                    if raw_value is None:
                        warning = (
                            f"Part '{part_number}' is missing attribute '{attribute_key}'"
                        )
                        if warning not in warning_set:
                            warnings.append(warning)
                            warning_set.add(warning)
                    else:
                        try:
                            numeric_value = float(raw_value)
                        except (TypeError, ValueError):
                            warning = (
                                f"Part '{part_number}' has non-numeric '{attribute_key}': {raw_value}"
                            )
                            if warning not in warning_set:
                                warnings.append(warning)
                                warning_set.add(warning)
                        else:
                            contribution = numeric_value * quantity_multiplier
                            total += contribution
                            breakdown.append(
                                {
                                    "part_number": part_number,
                                    "path": list(path),
                                    "multiplier": quantity_multiplier,
                                    "attribute_value": numeric_value,
                                    "contribution": contribution,
                                }
                            )

            for relationship in self.relationship_repo.find_children(part_number):
                queue.append(
                    (
                        relationship.child_part_number,
                        quantity_multiplier * relationship.qty,
                        path + [relationship.child_part_number],
                    )
                )

        breakdown.sort(key=lambda item: (item["path"], item["part_number"]))
        return ok_result(
            {
                "root_part_number": root_part_number,
                "attribute_key": attribute_key,
                "include_root": include_root,
                "total": total,
                "breakdown": breakdown,
            },
            warnings=warnings,
        )
