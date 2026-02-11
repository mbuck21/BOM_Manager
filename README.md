# BOM Manager Backend (Python + JSON)

This project implements a backend system for multi-level BOM storage, editing, traversal, snapshots, signatures, diffing, and CSV interchange.

## Architecture

- `bom_backend/models.py`
  - Data-only models: `Part`, `Relationship`, `Snapshot`
- `bom_backend/repositories.py`
  - JSON source-of-truth repositories (`parts.json`, `relationships.json`, `snapshots/*.json`)
- `bom_backend/services/part_catalog.py`
  - Part CRUD, attribute updates, list/search
- `bom_backend/services/bom_structure.py`
  - Relationship CRUD, cycle prevention, parent/child queries, subgraph traversal
- `bom_backend/services/snapshot_diff.py`
  - Immutable snapshots, deterministic signature hashes, snapshot diffing
- `bom_backend/services/rollups.py`
  - Multi-level numeric attribute rollups (for example total `weight_kg`)
- `bom_backend/services/csv_interchange.py`
  - CSV import/export adapters (CSV is interchange only)
- `bom_backend/backend.py`
  - `BOMBackend` facade for frontend integration

## Storage Layout

Under your selected data directory (default `data/`):

- `parts.json`
- `relationships.json`
- `snapshots/<snapshot_id>.json`

## Quick Start

```python
from bom_backend import BOMBackend

backend = BOMBackend(data_dir="data")

backend.parts.add_or_update_part("A-100", "Top Assembly", {"weight_kg": 12.4})
backend.parts.add_or_update_part("B-200", "Bracket", {"weight_kg": 1.1})

backend.bom.add_or_update_relationship(
    parent_part_number="A-100",
    child_part_number="B-200",
    qty=2,
    rel_id="REL-001",
    attributes={"find_number": "10"},
)

snapshot = backend.snapshots.create_snapshot("A-100", label="baseline")
print(snapshot["ok"], snapshot["data"]["snapshot"]["signature"])

rollup = backend.rollups.rollup_numeric_attribute("A-100", "weight_kg")
print(rollup["data"]["total"], rollup["warnings"])
```

## Service Return Contract

All service methods return JSON-serializable objects:

```json
{
  "ok": true,
  "data": {},
  "errors": [],
  "warnings": []
}
```

No raw exceptions are intended to surface to frontend consumers.

## CSV Rules Implemented

- Import supports required core columns plus flexible attributes.
- `attributes_json` column can provide a JSON object.
- Any non-reserved column is treated as an attribute.
- `attr__<name>` columns map to attribute `<name>`.
- Missing timestamps are auto-stamped in services.
- Export can include an `attribute_whitelist` plus `attributes_json` fallback.

## Running Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## Streamlit Demo Frontend

Run an interactive frontend that uses the same `BOMBackend` services:

```bash
python3 -m pip install streamlit
streamlit run streamlit_app.py
```

The app defaults to `demo_data/` and supports:

- Seeding demo data
- Part and relationship CRUD operations
- Subgraph traversal and numeric rollups
- Snapshot create/list/diff
- CSV import and export
