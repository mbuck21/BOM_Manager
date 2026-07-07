"""Pure (Streamlit-free) helpers for the spreadsheet Edit tab.

This module turns backend records into flat grid rows and, on Save, diffs the edited
grid back into a plan of create/update/rename/delete operations. Keeping it free of
Streamlit makes the reconciliation logic unit-testable.

Identity model:
- Parts grid rows carry a hidden ``_row_id`` (stable within a render). ``st.data_editor``
  keeps it on retained rows, leaves it blank on newly added rows, and drops it on deleted
  rows. So the row id — not the editable ``part_number`` — is the identity key, which lets
  us detect a renamed part cleanly.
- BOM grid rows are keyed by ``rel_id`` (the backend mints it); blank means a new row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bom_backend.constants import MATURITY_FACTOR_KEY, UNIT_WEIGHT_KEY

ROW_ID = "_row_id"
RESERVED_PART_COLUMNS = ("part_number", "name", UNIT_WEIGHT_KEY, MATURITY_FACTOR_KEY)
NUMERIC_PART_COLUMNS = (UNIT_WEIGHT_KEY, MATURITY_FACTOR_KEY)


# ── value coercion ────────────────────────────────────────────────────────────
def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        # NaN (from an empty spreadsheet cell) counts as blank.
        return value != value
    if isinstance(value, str):
        return value.strip() == ""
    return False


def coerce_number(value: Any) -> float | None:
    if is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_text_scalar(value: Any) -> Any:
    """Best-effort typing for free-form attribute cells: number/bool where clear, else text."""
    if is_blank(value):
        return None
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if text.lstrip("+-").isdigit():
            return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


# ── parts grid ────────────────────────────────────────────────────────────────
@dataclass
class PartsGrid:
    rows: list[dict[str, Any]]
    attribute_columns: list[str]
    preserved: dict[str, dict[str, Any]] = field(default_factory=dict)


def collect_attribute_columns(parts: list[dict[str, Any]]) -> list[str]:
    """Extra scalar attribute keys (beyond the reserved weight columns) to show as columns."""
    keys: set[str] = set()
    for part in parts:
        for key, value in (part.get("attributes") or {}).items():
            if key in NUMERIC_PART_COLUMNS:
                continue
            if _is_scalar(value):
                keys.add(key)
    return sorted(keys)


def build_parts_grid(parts: list[dict[str, Any]]) -> PartsGrid:
    attribute_columns = collect_attribute_columns(parts)
    rows: list[dict[str, Any]] = []
    preserved: dict[str, dict[str, Any]] = {}

    for index, part in enumerate(parts):
        row_id = f"p{index}"
        attributes = dict(part.get("attributes") or {})
        row: dict[str, Any] = {
            ROW_ID: row_id,
            "part_number": part.get("part_number", ""),
            "name": part.get("name", ""),
            UNIT_WEIGHT_KEY: coerce_number(attributes.get(UNIT_WEIGHT_KEY)),
            MATURITY_FACTOR_KEY: coerce_number(attributes.get(MATURITY_FACTOR_KEY)),
        }

        leftover: dict[str, Any] = {}
        for key, value in attributes.items():
            if key in NUMERIC_PART_COLUMNS:
                continue
            if key in attribute_columns and _is_scalar(value):
                # Render extra attribute columns as text so a single grid column can hold
                # mixed types (a bool/int/float stays editable); coerce_text_scalar restores type.
                row[key] = None if is_blank(value) else str(value)
            else:
                # Non-scalar values (nested dicts/lists) ride along untouched so Save never drops them.
                leftover[key] = value

        for column in attribute_columns:
            row.setdefault(column, None)

        if leftover:
            preserved[row_id] = leftover
        rows.append(row)

    return PartsGrid(rows=rows, attribute_columns=attribute_columns, preserved=preserved)


def _row_attributes(
    row: dict[str, Any],
    attribute_columns: list[str],
    preserved_for_row: dict[str, Any],
) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for column in NUMERIC_PART_COLUMNS:
        number = coerce_number(row.get(column))
        if number is not None:
            attributes[column] = number
    for column in attribute_columns:
        value = coerce_text_scalar(row.get(column))
        if not is_blank(value):
            attributes[column] = value
    attributes.update(preserved_for_row)
    return attributes


@dataclass
class PartOp:
    part_number: str
    name: str
    attributes: dict[str, Any]
    old_part_number: str = ""


@dataclass
class PartsPlan:
    creates: list[PartOp] = field(default_factory=list)
    updates: list[PartOp] = field(default_factory=list)
    renames: list[PartOp] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.creates or self.updates or self.renames or self.deletes)


def reconcile_parts(
    baseline: PartsGrid,
    edited_rows: list[dict[str, Any]],
) -> PartsPlan:
    plan = PartsPlan()
    baseline_by_id = {row[ROW_ID]: row for row in baseline.rows}
    seen_ids: set[str] = set()

    for row in edited_rows:
        row_id = row.get(ROW_ID)
        part_number = str(row.get("part_number") or "").strip()
        name = str(row.get("name") or "").strip()

        if is_blank(row_id) or row_id not in baseline_by_id:
            # Newly added row. Skip entirely blank rows the user left untouched.
            if not part_number and not name:
                continue
            preserved_for_row = {}
            attributes = _row_attributes(row, baseline.attribute_columns, preserved_for_row)
            plan.creates.append(PartOp(part_number=part_number, name=name, attributes=attributes))
            continue

        seen_ids.add(row_id)
        base_row = baseline_by_id[row_id]
        old_part_number = str(base_row.get("part_number") or "").strip()
        preserved_for_row = baseline.preserved.get(row_id, {})
        attributes = _row_attributes(row, baseline.attribute_columns, preserved_for_row)
        base_attributes = _row_attributes(base_row, baseline.attribute_columns, preserved_for_row)

        renamed = bool(part_number) and part_number != old_part_number
        changed = (
            name != str(base_row.get("name") or "").strip()
            or attributes != base_attributes
        )

        if renamed:
            plan.renames.append(
                PartOp(
                    part_number=part_number,
                    name=name,
                    attributes=attributes,
                    old_part_number=old_part_number,
                )
            )
        elif changed:
            plan.updates.append(PartOp(part_number=part_number, name=name, attributes=attributes))

    for row_id, base_row in baseline_by_id.items():
        if row_id not in seen_ids:
            deleted_pn = str(base_row.get("part_number") or "").strip()
            if deleted_pn:
                plan.deletes.append(deleted_pn)

    return plan


# ── BOM grid ──────────────────────────────────────────────────────────────────
@dataclass
class BomGrid:
    rows: list[dict[str, Any]]
    preserved: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_bom_grid(relationships: list[dict[str, Any]]) -> BomGrid:
    rows: list[dict[str, Any]] = []
    preserved: dict[str, dict[str, Any]] = {}
    for rel in relationships:
        rel_id = str(rel.get("rel_id", "")).strip()
        rows.append(
            {
                "rel_id": rel_id,
                "parent_part_number": rel.get("parent_part_number", ""),
                "child_part_number": rel.get("child_part_number", ""),
                "qty": coerce_number(rel.get("qty")) or 0.0,
            }
        )
        attributes = dict(rel.get("attributes") or {})
        if attributes and rel_id:
            preserved[rel_id] = attributes
    return BomGrid(rows=rows, preserved=preserved)


@dataclass
class BomOp:
    parent_part_number: str
    child_part_number: str
    qty: float
    rel_id: str | None
    attributes: dict[str, Any]


@dataclass
class BomPlan:
    upserts: list[BomOp] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.upserts or self.deletes)


def reconcile_bom(baseline: BomGrid, edited_rows: list[dict[str, Any]]) -> BomPlan:
    plan = BomPlan()
    baseline_by_id = {row["rel_id"]: row for row in baseline.rows if row["rel_id"]}
    seen_ids: set[str] = set()

    for row in edited_rows:
        rel_id = str(row.get("rel_id") or "").strip()
        parent = str(row.get("parent_part_number") or "").strip()
        child = str(row.get("child_part_number") or "").strip()
        qty = coerce_number(row.get("qty"))
        qty = 1.0 if (qty is None or qty <= 0) else qty

        if not rel_id or rel_id not in baseline_by_id:
            if not parent and not child:
                continue  # untouched blank row
            plan.upserts.append(
                BomOp(
                    parent_part_number=parent,
                    child_part_number=child,
                    qty=qty,
                    rel_id=None,
                    attributes={},
                )
            )
            continue

        seen_ids.add(rel_id)
        base_row = baseline_by_id[rel_id]
        changed = (
            parent != str(base_row.get("parent_part_number") or "").strip()
            or child != str(base_row.get("child_part_number") or "").strip()
            or qty != (coerce_number(base_row.get("qty")) or 0.0)
        )
        if changed:
            plan.upserts.append(
                BomOp(
                    parent_part_number=parent,
                    child_part_number=child,
                    qty=qty,
                    rel_id=rel_id,
                    attributes=baseline.preserved.get(rel_id, {}),
                )
            )

    for rel_id in baseline_by_id:
        if rel_id not in seen_ids:
            plan.deletes.append(rel_id)

    return plan
