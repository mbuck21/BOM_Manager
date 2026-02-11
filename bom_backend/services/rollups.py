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

    @service_guard
    def rollup_weight_with_maturity(
        self,
        root_part_number: str,
        unit_weight_key: str = "unit_weight",
        maturity_factor_key: str = "maturity_factor",
        default_maturity_factor: float = 1.0,
        include_root: bool = True,
        top_n: int = 10,
    ) -> ServiceResult:
        root_part_number = (root_part_number or "").strip()
        unit_weight_key = (unit_weight_key or "").strip()
        maturity_factor_key = (maturity_factor_key or "").strip()

        if not root_part_number:
            return err_result("root_part_number is required")
        if not unit_weight_key:
            return err_result("unit_weight_key is required")
        if not maturity_factor_key:
            return err_result("maturity_factor_key is required")
        if top_n <= 0:
            return err_result("top_n must be > 0")

        try:
            normalized_default_maturity = float(default_maturity_factor)
        except (TypeError, ValueError):
            return err_result("default_maturity_factor must be numeric")
        if normalized_default_maturity <= 0:
            return err_result("default_maturity_factor must be > 0")

        queue: deque[tuple[str, float, list[str]]] = deque()
        queue.append((root_part_number, 1.0, [root_part_number]))

        total = 0.0
        breakdown: list[dict[str, Any]] = []
        warnings: list[str] = []
        warning_set: set[str] = set()
        unresolved_nodes: list[dict[str, Any]] = []
        unresolved_set: set[tuple[str, str]] = set()

        part_totals: dict[str, dict[str, Any]] = {}

        def add_warning(message: str) -> None:
            if message not in warning_set:
                warning_set.add(message)
                warnings.append(message)

        def add_unresolved(part_number: str, path: list[str], reason: str) -> None:
            key = (part_number, reason)
            if key in unresolved_set:
                return
            unresolved_set.add(key)
            unresolved_nodes.append(
                {
                    "part_number": part_number,
                    "path": list(path),
                    "reason": reason,
                }
            )

        while queue:
            part_number, quantity_multiplier, path = queue.popleft()
            is_root = len(path) == 1

            part = self.part_repo.get(part_number)
            children = self.relationship_repo.find_children(part_number)

            if part is None:
                add_warning(f"Part '{part_number}' is missing from catalog")
                if not children:
                    add_unresolved(part_number, path, "missing part and no children to continue rollup")
                for relationship in children:
                    queue.append(
                        (
                            relationship.child_part_number,
                            quantity_multiplier * relationship.qty,
                            path + [relationship.child_part_number],
                        )
                    )
                continue

            evaluate_here = include_root or not is_root
            raw_unit_weight = part.attributes.get(unit_weight_key)

            if raw_unit_weight is not None and evaluate_here:
                try:
                    unit_weight = float(raw_unit_weight)
                except (TypeError, ValueError):
                    add_warning(
                        f"Part '{part_number}' has non-numeric '{unit_weight_key}': {raw_unit_weight}"
                    )
                else:
                    raw_maturity = part.attributes.get(maturity_factor_key, normalized_default_maturity)
                    if raw_maturity is None:
                        raw_maturity = normalized_default_maturity

                    try:
                        maturity_factor = float(raw_maturity)
                    except (TypeError, ValueError):
                        maturity_factor = normalized_default_maturity
                        add_warning(
                            f"Part '{part_number}' has non-numeric '{maturity_factor_key}': {raw_maturity}; "
                            f"using default {normalized_default_maturity}"
                        )

                    if maturity_factor <= 0:
                        maturity_factor = normalized_default_maturity
                        add_warning(
                            f"Part '{part_number}' has non-positive '{maturity_factor_key}': {raw_maturity}; "
                            f"using default {normalized_default_maturity}"
                        )

                    effective_unit_weight = unit_weight * maturity_factor
                    contribution = effective_unit_weight * quantity_multiplier
                    total += contribution

                    breakdown.append(
                        {
                            "part_number": part_number,
                            "path": list(path),
                            "multiplier": quantity_multiplier,
                            "unit_weight": unit_weight,
                            "maturity_factor": maturity_factor,
                            "effective_unit_weight": effective_unit_weight,
                            "contribution": contribution,
                            "override_applied": True,
                        }
                    )

                    aggregate = part_totals.setdefault(
                        part_number,
                        {
                            "part_number": part_number,
                            "total_contribution": 0.0,
                            "occurrences": 0,
                        },
                    )
                    aggregate["total_contribution"] += contribution
                    aggregate["occurrences"] += 1

                    # Unit weight is an override; do not continue to children.
                    continue

            if evaluate_here and raw_unit_weight is None and not children:
                add_warning(
                    f"Part '{part_number}' has no '{unit_weight_key}' and no children to derive weight"
                )
                add_unresolved(part_number, path, "no unit weight and no children")

            for relationship in children:
                queue.append(
                    (
                        relationship.child_part_number,
                        quantity_multiplier * relationship.qty,
                        path + [relationship.child_part_number],
                    )
                )

        breakdown.sort(key=lambda item: (item["path"], item["part_number"]))
        part_total_rows = sorted(
            part_totals.values(),
            key=lambda item: (-item["total_contribution"], item["part_number"]),
        )
        top_contributors = part_total_rows[:top_n]

        return ok_result(
            {
                "root_part_number": root_part_number,
                "unit_weight_key": unit_weight_key,
                "maturity_factor_key": maturity_factor_key,
                "default_maturity_factor": normalized_default_maturity,
                "include_root": include_root,
                "total": total,
                "breakdown": breakdown,
                "part_totals": part_total_rows,
                "top_contributors": top_contributors,
                "unresolved_nodes": unresolved_nodes,
            },
            warnings=warnings,
        )
