from __future__ import annotations

from collections import defaultdict, deque
from typing import Any
from uuid import uuid4

from bom_backend.models import Relationship
from bom_backend.repositories import PartRepository, RelationshipRepository
from bom_backend.result import ServiceResult, err_result, ok_result, service_guard
from bom_backend.serialization import part_to_record, relationship_to_record
from bom_backend.utils.clock import now_iso_utc
from bom_backend.utils.parsing import canonical_number


class BOMStructureService:
    def __init__(self, relationship_repo: RelationshipRepository, part_repo: PartRepository) -> None:
        self.relationship_repo = relationship_repo
        self.part_repo = part_repo

    def _sort_relationships(self, relationships: list[Relationship]) -> list[Relationship]:
        return sorted(
            relationships,
            key=lambda rel: (
                rel.parent_part_number,
                rel.child_part_number,
                canonical_number(rel.qty),
                rel.rel_id,
            ),
        )

    def _detect_cycle(self, relationships: list[Relationship]) -> list[str] | None:
        adjacency: dict[str, list[str]] = defaultdict(list)
        nodes: set[str] = set()

        for rel in relationships:
            adjacency[rel.parent_part_number].append(rel.child_part_number)
            nodes.add(rel.parent_part_number)
            nodes.add(rel.child_part_number)

        state: dict[str, int] = {node: 0 for node in nodes}
        stack: list[str] = []
        stack_pos: dict[str, int] = {}

        def dfs(node: str) -> list[str] | None:
            state[node] = 1
            stack_pos[node] = len(stack)
            stack.append(node)

            for child in adjacency.get(node, []):
                if state.get(child, 0) == 0:
                    cycle = dfs(child)
                    if cycle:
                        return cycle
                elif state[child] == 1:
                    start = stack_pos[child]
                    return stack[start:] + [child]

            state[node] = 2
            stack.pop()
            stack_pos.pop(node, None)
            return None

        for node in sorted(nodes):
            if state[node] == 0:
                cycle = dfs(node)
                if cycle:
                    return cycle

        return None

    def _candidate_relationships(self, candidate: Relationship) -> list[Relationship]:
        relationships = [
            rel for rel in self.relationship_repo.list_relationships() if rel.rel_id != candidate.rel_id
        ]
        relationships.append(candidate)
        return relationships

    @service_guard
    def add_or_update_relationship(
        self,
        parent_part_number: str,
        child_part_number: str,
        qty: float,
        rel_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        last_updated: str | None = None,
        allow_dangling: bool = False,
        merge_attributes: bool = True,
    ) -> ServiceResult:
        parent_part_number = (parent_part_number or "").strip()
        child_part_number = (child_part_number or "").strip()

        if not parent_part_number:
            return err_result("parent_part_number is required")
        if not child_part_number:
            return err_result("child_part_number is required")
        if parent_part_number == child_part_number:
            return err_result("parent_part_number and child_part_number cannot be equal")

        try:
            qty_value = float(qty)
        except (TypeError, ValueError):
            return err_result("qty must be numeric")

        if qty_value <= 0:
            return err_result("qty must be > 0")

        normalized_rel_id = (rel_id or "").strip() or f"rel_{uuid4().hex[:12]}"
        existing = self.relationship_repo.get(normalized_rel_id)

        incoming_attributes = dict(attributes or {})
        if existing and merge_attributes:
            final_attributes = dict(existing.attributes)
            final_attributes.update(incoming_attributes)
        else:
            final_attributes = incoming_attributes

        candidate = Relationship(
            rel_id=normalized_rel_id,
            parent_part_number=parent_part_number,
            child_part_number=child_part_number,
            qty=qty_value,
            last_updated=last_updated or now_iso_utc(),
            attributes=final_attributes,
        )

        warnings: list[str] = []
        missing_parts: list[str] = []
        if not self.part_repo.exists(parent_part_number):
            missing_parts.append(parent_part_number)
        if not self.part_repo.exists(child_part_number):
            missing_parts.append(child_part_number)

        if missing_parts and not allow_dangling:
            return err_result(
                [
                    "Missing part(s): " + ", ".join(sorted(set(missing_parts))),
                    "Set allow_dangling=True to allow storing this relationship",
                ]
            )

        if missing_parts:
            warnings.append("Missing part(s): " + ", ".join(sorted(set(missing_parts))))

        cycle = self._detect_cycle(self._candidate_relationships(candidate))
        if cycle:
            cycle_repr = " -> ".join(cycle)
            return err_result(f"Cycle detected: {cycle_repr}")

        self.relationship_repo.upsert(candidate)
        return ok_result(
            {
                "relationship": relationship_to_record(candidate),
                "created": existing is None,
            },
            warnings=warnings,
        )

    @service_guard
    def delete_relationship(self, rel_id: str) -> ServiceResult:
        rel_id = (rel_id or "").strip()
        if not rel_id:
            return err_result("rel_id is required")

        deleted = self.relationship_repo.delete(rel_id)
        if not deleted:
            return err_result(f"Relationship '{rel_id}' not found")

        return ok_result({"deleted": True, "rel_id": rel_id})

    @service_guard
    def get_children(self, parent_part_number: str) -> ServiceResult:
        parent_part_number = (parent_part_number or "").strip()
        if not parent_part_number:
            return err_result("parent_part_number is required")

        relationships = self._sort_relationships(self.relationship_repo.find_children(parent_part_number))
        children: list[dict[str, Any]] = []
        warnings: list[str] = []

        for relationship in relationships:
            child_part = self.part_repo.get(relationship.child_part_number)
            if child_part is None:
                warnings.append(
                    f"Child part '{relationship.child_part_number}' does not exist in part catalog"
                )

            children.append(
                {
                    "relationship": relationship_to_record(relationship),
                    "child_part": part_to_record(child_part) if child_part else None,
                }
            )

        return ok_result(
            {
                "parent_part_number": parent_part_number,
                "children": children,
            },
            warnings=warnings,
        )

    @service_guard
    def get_parents(self, child_part_number: str) -> ServiceResult:
        child_part_number = (child_part_number or "").strip()
        if not child_part_number:
            return err_result("child_part_number is required")

        relationships = self._sort_relationships(self.relationship_repo.find_parents(child_part_number))
        parents: list[dict[str, Any]] = []
        warnings: list[str] = []

        for relationship in relationships:
            parent_part = self.part_repo.get(relationship.parent_part_number)
            if parent_part is None:
                warnings.append(
                    f"Parent part '{relationship.parent_part_number}' does not exist in part catalog"
                )

            parents.append(
                {
                    "relationship": relationship_to_record(relationship),
                    "parent_part": part_to_record(parent_part) if parent_part else None,
                }
            )

        return ok_result(
            {
                "child_part_number": child_part_number,
                "parents": parents,
            },
            warnings=warnings,
        )

    @service_guard
    def get_subgraph(self, root_part_number: str) -> ServiceResult:
        root_part_number = (root_part_number or "").strip()
        if not root_part_number:
            return err_result("root_part_number is required")

        warnings: list[str] = []
        visited_nodes: set[str] = set()
        visited_relationship_ids: set[str] = set()
        queue: deque[str] = deque([root_part_number])

        subgraph_relationships: list[Relationship] = []

        while queue:
            current = queue.popleft()
            if current in visited_nodes:
                continue

            visited_nodes.add(current)
            for relationship in self.relationship_repo.find_children(current):
                if relationship.rel_id in visited_relationship_ids:
                    continue

                visited_relationship_ids.add(relationship.rel_id)
                subgraph_relationships.append(relationship)
                queue.append(relationship.child_part_number)

        parts: list[dict[str, Any]] = []
        missing_parts: list[str] = []
        for part_number in sorted(visited_nodes):
            part = self.part_repo.get(part_number)
            if part is None:
                missing_parts.append(part_number)
                continue
            parts.append(part_to_record(part))

        if missing_parts:
            warnings.append("Missing parts in catalog: " + ", ".join(missing_parts))

        ordered_relationships = self._sort_relationships(subgraph_relationships)
        return ok_result(
            {
                "root_part_number": root_part_number,
                "parts": parts,
                "relationships": [relationship_to_record(item) for item in ordered_relationships],
            },
            warnings=warnings,
        )
