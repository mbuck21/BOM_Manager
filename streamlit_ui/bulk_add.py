"""Pure parsing + apply logic for quick-add and bulk-add (paste from Excel).

Line grammar (one part per line, all under one chosen parent):

    part_number [SEP name [SEP qty [SEP unit_weight]]]

SEP is a tab when the line contains one (Excel paste), otherwise a comma. Quick add
uses the same machinery with a single row, so there is only one code path to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bom_backend.constants import QTY_MAX, UNIT_WEIGHT_KEY


@dataclass
class BulkRow:
    line_no: int
    part_number: str
    name: str
    qty: float = 1.0
    unit_weight: float | None = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class BulkParseResult:
    rows: list[BulkRow] = field(default_factory=list)
    header_skipped: bool = False

    @property
    def ok_rows(self) -> list[BulkRow]:
        return [row for row in self.rows if not row.error]

    @property
    def error_rows(self) -> list[BulkRow]:
        return [row for row in self.rows if row.error]


def _split_line(line: str) -> list[str]:
    sep = "\t" if "\t" in line else ","
    return [cell.strip() for cell in line.split(sep)]


def _looks_like_header(cells: list[str]) -> bool:
    if not cells or "part" not in cells[0].lower():
        return False
    for cell in cells[2:4]:  # qty / unit_weight positions
        if cell:
            try:
                float(cell)
                return False  # numeric data → not a header
            except ValueError:
                pass
    return True


def parse_bulk_lines(
    text: str,
    existing_part_numbers: set[str],
    existing_links: set[tuple[str, str]],
    parent_part_number: str,
) -> BulkParseResult:
    result = BulkParseResult()
    seen_in_paste: dict[str, int] = {}
    first_content_line = True

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or not line.replace(",", "").replace("\t", "").strip():
            continue

        cells = _split_line(line)
        if first_content_line and _looks_like_header(cells):
            result.header_skipped = True
            first_content_line = False
            continue
        first_content_line = False

        part_number = cells[0] if cells else ""
        name = cells[1] if len(cells) > 1 else ""
        qty_text = cells[2] if len(cells) > 2 else ""
        weight_text = cells[3] if len(cells) > 3 else ""

        row = BulkRow(line_no=line_no, part_number=part_number, name=name)

        if not part_number:
            row.error = "missing part number"
            result.rows.append(row)
            continue

        if part_number in seen_in_paste:
            row.error = f"duplicate of line {seen_in_paste[part_number]}"
            result.rows.append(row)
            continue
        seen_in_paste[part_number] = line_no

        if not name:
            row.name = part_number
            row.warnings.append("no name given — using the part number")

        if qty_text:
            try:
                qty = float(qty_text)
            except ValueError:
                row.error = f"qty '{qty_text}' is not a number"
                result.rows.append(row)
                continue
            if not (0 < qty <= QTY_MAX):
                row.error = f"qty must be between 0 and {QTY_MAX:,.0f}"
                result.rows.append(row)
                continue
            row.qty = qty

        if weight_text:
            try:
                weight = float(weight_text)
            except ValueError:
                row.error = f"unit weight '{weight_text}' is not a number"
                result.rows.append(row)
                continue
            if weight < 0:
                row.error = "unit weight cannot be negative"
                result.rows.append(row)
                continue
            row.unit_weight = weight

        if part_number == parent_part_number:
            row.error = "a part cannot be added under itself"
            result.rows.append(row)
            continue

        if part_number in existing_part_numbers:
            row.warnings.append("existing part — its name/weight will be updated, link added")
        if (parent_part_number, part_number) in existing_links:
            row.warnings.append("link to this parent exists — its qty will be updated")

        result.rows.append(row)

    return result


def apply_bulk_add(
    backend: Any,
    parent_part_number: str,
    rows: list[BulkRow],
    existing_rel_lookup: dict[tuple[str, str], str] | None = None,
) -> tuple[list[str], list[str]]:
    """Create/update each row's part and link it under the parent, atomically.

    existing_rel_lookup maps (parent, child) -> rel_id so an existing link's qty is
    updated instead of minting a duplicate edge. Returns (errors, notes).
    """
    existing_rel_lookup = existing_rel_lookup or {}
    errors: list[str] = []
    notes: list[str] = []

    with backend.store.batch():
        for row in rows:
            if row.error:
                errors.append(f"line {row.line_no}: {row.error}")
                continue

            attributes = {UNIT_WEIGHT_KEY: row.unit_weight} if row.unit_weight is not None else {}
            part_result = backend.parts.add_or_update_part(
                part_number=row.part_number,
                name=row.name,
                attributes=attributes,
                merge_attributes=True,
            )
            if not part_result.get("ok"):
                for err in part_result.get("errors", []):
                    errors.append(f"{row.part_number}: {err}")
                continue

            rel_id = existing_rel_lookup.get((parent_part_number, row.part_number))
            rel_result = backend.bom.add_or_update_relationship(
                parent_part_number=parent_part_number,
                child_part_number=row.part_number,
                qty=row.qty,
                rel_id=rel_id,
                attributes={},
                merge_attributes=True,
            )
            if not rel_result.get("ok"):
                for err in rel_result.get("errors", []):
                    errors.append(f"{parent_part_number}→{row.part_number}: {err}")
            for warning in row.warnings:
                notes.append(f"{row.part_number}: {warning}")

    return errors, notes
