"""Pure planning + apply logic for replacing one assembly with another.

Scenario: a subassembly is scrapped and replaced by a new design that reuses some (but
not all) of the old one's subparts. The swap:

  1. creates the new assembly part (unless it already exists),
  2. re-points the old assembly's parent links to the new one (same rel_id, qty,
     attributes — the new assembly takes the old one's place in every BOM position),
  3. re-parents the carried-over children under the new assembly (same rel_id/qty),
  4. deletes the old assembly; its remaining (un-carried) child links go with it.

Everything applies inside one store.batch() so it lands as a single atomic save.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SwapPlan:
    old_part_number: str
    new_part_number: str
    new_name: str
    create_new: bool
    parent_links: list[dict[str, Any]] = field(default_factory=list)   # links re-pointed to new
    carried_links: list[dict[str, Any]] = field(default_factory=list)  # children moved under new
    dropped_children: list[str] = field(default_factory=list)
    delete_old: bool = True
    errors: list[str] = field(default_factory=list)


def plan_assembly_swap(
    old_part_number: str,
    new_part_number: str,
    new_name: str,
    carry_children: list[str],
    parts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    delete_old: bool = True,
) -> SwapPlan:
    old_pn = (old_part_number or "").strip()
    new_pn = (new_part_number or "").strip()
    new_name = (new_name or "").strip()

    part_numbers = {
        str(p.get("part_number", "")).strip()
        for p in parts
        if str(p.get("part_number", "")).strip()
    }
    create_new = new_pn not in part_numbers

    plan = SwapPlan(
        old_part_number=old_pn,
        new_part_number=new_pn,
        new_name=new_name,
        create_new=create_new,
        delete_old=delete_old,
    )

    if not old_pn:
        plan.errors.append("Pick the assembly being replaced.")
    elif old_pn not in part_numbers:
        plan.errors.append(f"'{old_pn}' is not in the project.")
    if not new_pn:
        plan.errors.append("Give the replacement assembly a part number.")
    if old_pn and new_pn and old_pn == new_pn:
        plan.errors.append("The replacement must have a different part number.")
    if create_new and not new_name:
        plan.errors.append("Give the new assembly a name.")
    if plan.errors:
        return plan

    child_links: dict[str, list[dict[str, Any]]] = {}
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child = str(rel.get("child_part_number", "")).strip()
        if parent == old_pn:
            child_links.setdefault(child, []).append(rel)
        elif child == old_pn:
            plan.parent_links.append(
                {
                    "rel_id": str(rel.get("rel_id", "")).strip(),
                    "parent_part_number": parent,
                    "qty": float(rel.get("qty", 1) or 1),
                }
            )

    carry_set = {c.strip() for c in carry_children if c and c.strip()}
    unknown = sorted(carry_set - set(child_links.keys()))
    if unknown:
        plan.errors.append(
            f"Not children of '{old_pn}': " + ", ".join(unknown)
        )
        return plan

    for child, rels in sorted(child_links.items()):
        if child in carry_set:
            if child == new_pn:
                plan.errors.append(
                    f"'{new_pn}' cannot be carried under itself — uncheck it or pick another part number."
                )
                return plan
            for rel in rels:
                plan.carried_links.append(
                    {
                        "rel_id": str(rel.get("rel_id", "")).strip(),
                        "child_part_number": child,
                        "qty": float(rel.get("qty", 1) or 1),
                    }
                )
        else:
            plan.dropped_children.append(child)

    return plan


def apply_assembly_swap(backend: Any, plan: SwapPlan) -> tuple[list[str], list[str]]:
    """Execute a validated SwapPlan atomically. Returns (errors, notes)."""
    if plan.errors:
        return list(plan.errors), []

    errors: list[str] = []
    notes: list[str] = []

    def _collect(label: str, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            for err in result.get("errors", []):
                errors.append(f"{label}: {err}")
        for warning in result.get("warnings", []):
            notes.append(f"{label}: {warning}")

    try:
        with backend.store.batch():
            if plan.create_new:
                _collect(
                    f"Create {plan.new_part_number}",
                    backend.parts.add_or_update_part(
                        part_number=plan.new_part_number,
                        name=plan.new_name,
                        attributes={},
                        merge_attributes=True,
                    ),
                )

            # New assembly takes the old one's place under each of its parents.
            for link in plan.parent_links:
                _collect(
                    f"{link['parent_part_number']}→{plan.new_part_number}",
                    backend.bom.add_or_update_relationship(
                        parent_part_number=link["parent_part_number"],
                        child_part_number=plan.new_part_number,
                        qty=link["qty"],
                        rel_id=link["rel_id"],
                        attributes={},
                        merge_attributes=True,
                    ),
                )

            # Carried children move under the new assembly.
            for link in plan.carried_links:
                _collect(
                    f"{plan.new_part_number}→{link['child_part_number']}",
                    backend.bom.add_or_update_relationship(
                        parent_part_number=plan.new_part_number,
                        child_part_number=link["child_part_number"],
                        qty=link["qty"],
                        rel_id=link["rel_id"],
                        attributes={},
                        merge_attributes=True,
                    ),
                )

            if errors:
                # Abort (batch discards everything) if any re-pointing failed, e.g. a cycle.
                raise _SwapAborted()

            if plan.delete_old:
                _collect(
                    f"Delete {plan.old_part_number}",
                    backend.parts.delete_part(plan.old_part_number, cascade=True),
                )
    except _SwapAborted:
        errors.append("Nothing was changed — fix the issue above and try again.")
        return errors, notes

    if plan.dropped_children:
        notes.append(
            "Not carried over (their links to the old assembly were removed): "
            + ", ".join(plan.dropped_children)
        )
    return errors, notes


class _SwapAborted(Exception):
    pass


# ── dissolving a grouping level ───────────────────────────────────────────────
@dataclass
class DissolvePlan:
    part_number: str
    new_links: list[dict[str, Any]] = field(default_factory=list)  # parent, child, qty, rel_id|None
    errors: list[str] = field(default_factory=list)


def plan_assembly_dissolve(
    part_number: str,
    parts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> DissolvePlan:
    """Plan removing one grouping level: the assembly's children are re-linked
    directly under each of its parents (quantities multiplied through), then the
    assembly itself is deleted. The rollup total is unchanged.
    """
    pn = (part_number or "").strip()
    plan = DissolvePlan(part_number=pn)

    part_numbers = {
        str(p.get("part_number", "")).strip()
        for p in parts
        if str(p.get("part_number", "")).strip()
    }
    if not pn:
        plan.errors.append("Pick the assembly to dissolve.")
        return plan
    if pn not in part_numbers:
        plan.errors.append(f"'{pn}' is not in the project.")
        return plan

    parent_links: list[tuple[str, float]] = []
    child_links: list[tuple[str, float]] = []
    existing_qty: dict[tuple[str, str], tuple[str, float]] = {}
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child = str(rel.get("child_part_number", "")).strip()
        qty = float(rel.get("qty", 1) or 1)
        if child == pn:
            parent_links.append((parent, qty))
        elif parent == pn:
            child_links.append((child, qty))
        else:
            existing_qty[(parent, child)] = (str(rel.get("rel_id", "")).strip(), qty)

    if not child_links:
        plan.errors.append(f"'{pn}' has no children — just delete its row in the Parts grid instead.")
        return plan
    if not parent_links:
        plan.errors.append(
            f"'{pn}' is a top-level assembly; dissolving it would leave its children floating. "
            "Pick a new home for them first (BOM grid) or use Replace an assembly."
        )
        return plan

    merged: dict[tuple[str, str], float] = {}
    for parent, parent_qty in parent_links:
        for child, child_qty in child_links:
            merged[(parent, child)] = merged.get((parent, child), 0.0) + parent_qty * child_qty

    for (parent, child), qty in sorted(merged.items()):
        rel_id = None
        if (parent, child) in existing_qty:
            # The parent already links this child directly — fold the quantities together.
            rel_id, direct_qty = existing_qty[(parent, child)]
            qty += direct_qty
        plan.new_links.append(
            {"parent_part_number": parent, "child_part_number": child, "qty": qty, "rel_id": rel_id}
        )

    return plan


def apply_assembly_dissolve(backend: Any, plan: DissolvePlan) -> tuple[list[str], list[str]]:
    """Execute a validated DissolvePlan atomically. Returns (errors, notes)."""
    if plan.errors:
        return list(plan.errors), []

    errors: list[str] = []
    notes: list[str] = []

    def _collect(label: str, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            for err in result.get("errors", []):
                errors.append(f"{label}: {err}")
        for warning in result.get("warnings", []):
            notes.append(f"{label}: {warning}")

    try:
        with backend.store.batch():
            for link in plan.new_links:
                _collect(
                    f"{link['parent_part_number']}→{link['child_part_number']}",
                    backend.bom.add_or_update_relationship(
                        parent_part_number=link["parent_part_number"],
                        child_part_number=link["child_part_number"],
                        qty=link["qty"],
                        rel_id=link["rel_id"],
                        attributes={},
                        merge_attributes=True,
                    ),
                )
            if errors:
                raise _SwapAborted()
            _collect(
                f"Delete {plan.part_number}",
                backend.parts.delete_part(plan.part_number, cascade=True),
            )
    except _SwapAborted:
        errors.append("Nothing was changed — fix the issue above and try again.")
        return errors, notes

    notes.append(
        f"Moved {len(plan.new_links)} link(s) up a level and removed {plan.part_number}."
    )
    return errors, notes
