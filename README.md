# BOM Manager Backend

This project provides a file-backed BOM backend with services for:
- part catalog CRUD
- BOM relationship management with cycle prevention
- subgraph traversal
- numeric rollups
- snapshots and snapshot diffs
- CSV import/export

## Install and Initialize

```python
from bom_backend import BOMBackend

backend = BOMBackend(data_dir="data")  # default is "data"
```

Data is stored in:
- `data/parts.json`
- `data/relationships.json`
- `data/snapshots/<snapshot_id>.json`

## Response Format (All Backend Functions)

Every service method returns:

```python
{
    "ok": bool,
    "data": dict,
    "errors": list[str],
    "warnings": list[str],
}
```

- Check `result["ok"]` first.
- Read payload from `result["data"]` on success.
- Read `result["errors"]` on failure.
- Use `result["warnings"]` for non-fatal issues.

## Quick Usage Example

```python
from bom_backend import BOMBackend

backend = BOMBackend(data_dir="data")

backend.parts.add_or_update_part("A", "Assembly A", {"weight_kg": 10})
backend.parts.add_or_update_part("B", "Part B", {"weight_kg": 2})
backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1")

rollup = backend.rollups.rollup_numeric_attribute("A", "weight_kg")
print(rollup["data"]["total"])  # 14.0
```

## Backend Function Reference

### `backend.parts` (Part Catalog)

1. `add_or_update_part(part_number, name, attributes=None, last_updated=None, merge_attributes=True)`
- Creates or updates a part.
- Returns `data.part` and `data.created` (`True` if new).

2. `get_part(part_number)`
- Fetches one part by part number.
- Returns `data.part`.

3. `list_parts(query=None)`
- Lists all parts, optional case-insensitive search by part number or name.
- Returns `data.parts`.

4. `delete_part(part_number, allow_if_referenced=False)`
- Deletes a part.
- By default, fails if referenced by relationships.
- Returns `data.deleted` and `data.part_number`.

5. `update_attributes(part_number, attributes, merge_attributes=True)`
- Updates only the `attributes` object on an existing part.
- Returns updated `data.part`.

### `backend.bom` (Relationships and Structure)

1. `add_or_update_relationship(parent_part_number, child_part_number, qty, rel_id=None, attributes=None, last_updated=None, allow_dangling=False, merge_attributes=True)`
- Creates or updates a relationship.
- Validates required fields, `qty > 0`, and blocks graph cycles.
- If parts are missing:
  - fails by default
  - succeeds with warnings when `allow_dangling=True`
- Returns `data.relationship` and `data.created`.

2. `delete_relationship(rel_id)`
- Deletes a relationship by id.
- Returns `data.deleted` and `data.rel_id`.

3. `get_children(parent_part_number)`
- Returns direct children of a parent part.
- Returns `data.children` with both relationship and child part data.

4. `get_parents(child_part_number)`
- Returns direct parents of a child part.
- Returns `data.parents` with both relationship and parent part data.

5. `get_subgraph(root_part_number)`
- Traverses BOM downward from root and returns reachable nodes/edges.
- Returns `data.parts` and `data.relationships`.

### `backend.rollups`

1. `rollup_numeric_attribute(root_part_number, attribute_key, include_root=True)`
- Traverses from root and sums a numeric attribute through quantity multipliers.
- Adds warnings for missing/non-numeric attributes.
- Returns:
  - `data.total`
  - `data.breakdown` (per-path contribution details)

2. `rollup_weight_with_maturity(root_part_number, unit_weight_key="unit_weight", maturity_factor_key="maturity_factor", default_maturity_factor=1.0, include_root=True, top_n=10)`
- Weight-specific rollup with override behavior for assembly weights.
- If a part has `unit_weight`, that part contributes:
  - `unit_weight * maturity_factor * path_quantity_multiplier`
- When `unit_weight` is present, child rollup is stopped for that path (override).
- If `maturity_factor` is missing, default is `1.0` (or `default_maturity_factor`).
- Returns:
  - `data.total`
  - `data.breakdown` (path-level contributions)
  - `data.part_totals` (aggregated contributions by part)
  - `data.top_contributors` (largest contributors, limited by `top_n`)
  - `data.unresolved_nodes` (no `unit_weight` and no children to derive from)

### `backend.snapshots`

1. `create_snapshot(root_part_number, label=None, deduplicate_if_identical=True)`
- Captures immutable snapshot of the root subgraph.
- Computes deterministic signature.
- If identical snapshot already exists and deduplication is enabled, returns existing snapshot with `data.deduplicated=True`.
- Returns `data.snapshot`.

2. `get_snapshot(snapshot_id)`
- Loads one snapshot.
- Returns `data.snapshot`.

3. `list_snapshots(root_part_number=None)`
- Lists snapshots, optionally filtered by root.
- Returns `data.snapshots`.

### `backend.diff`

1. `compare_snapshots(snapshot_id_a, snapshot_id_b)`
- Compares two snapshots and reports:
  - part adds/removes/modifications
  - relationship adds/removes/modifications
  - signature equality and overall equality flags
- Returns diff details under `data`.

### `backend.csv` (CSV Import/Export)

1. `import_parts_csv(csv_path, merge_attributes=True)`
- Required columns: `part_number`, `name`
- Imports rows as parts.
- Returns created/updated/failed counts and `row_errors`.

2. `import_relationships_csv(csv_path, allow_dangling=False, merge_attributes=True)`
- Required columns: `parent_part_number`, `child_part_number`, `qty`
- Imports rows as relationships.
- Returns created/updated/failed counts and `row_errors`.

3. `export_parts_csv(csv_path, attribute_whitelist=None, include_attributes_json=True)`
- Exports parts to CSV.
- `attribute_whitelist` emits explicit attribute columns.
- Returns output file path, row count, and column list.

4. `export_relationships_csv(csv_path, attribute_whitelist=None, include_attributes_json=True)`
- Exports relationships to CSV.
- Same whitelist behavior as parts export.

## CSV Attribute Mapping Rules

- `attributes_json` can provide a JSON object of attributes.
- Any non-reserved column is treated as an attribute.
- Columns prefixed with `attr__` are mapped to the attribute name without the prefix.
- CSV values are parsed into typed values when possible (for example numbers/bools).

## Run Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## Run Streamlit Demo

```bash
python3 -m pip install streamlit
streamlit run streamlit_app.py
```
