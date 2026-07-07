# Architecture

How the Mass Allocation Tracking Tool is put together. For usage, see `README.md`.
For AI-agent-oriented working notes, see `CLAUDE.md`.

> This codebase was written with the use of AI (Anthropic Claude), guided and reviewed by
> the maintainer. **POC for bugs, features, or setup help: Matt Buckley
> (matthew.p.buckley@lmco.com).**

## The two layers

```
streamlit_app.py            thin entry point: page config, session state, 4 tabs
        │
streamlit_ui/               GUI layer (Streamlit) + pure view/workflow logic
        │  calls services on
bom_backend/                stdlib-only engine: models, services, storage
        │  reads/writes
<data folder>/project.bom.json    ONE file: parts + BOM links + versions + settings
```

`bom_backend` has **zero third-party dependencies** and never imports Streamlit — it can
be used as a plain Python library. `streamlit_ui` splits into *renderers* (import
Streamlit) and *pure logic modules* (no Streamlit import) so the interesting behavior is
unit-testable without a browser or app session.

## Module map

### `bom_backend/` — the engine

| File | Purpose |
|---|---|
| `backend.py` | `BOMBackend(data_dir)` composition root: runs migration, opens the `ProjectStore`, wires repositories + services |
| `models.py` | Dataclasses: `Part`, `Relationship` (parent→child edge carrying qty), `Snapshot` (frozen version) |
| `store.py` | `ProjectStore` — the single-file JSON store. Atomic writes (`.tmp` + rename); `read_section`/`write_section` for parts/relationships/snapshots; `read_settings`/`write_settings` for the settings dict; `batch()` groups many writes into one atomic file write |
| `repositories.py` | `PartRepository`, `RelationshipRepository`, `SnapshotRepository` — typed CRUD over the store's sections |
| `serialization.py` | Record ↔ dataclass converters (the on-disk shapes) |
| `migration.py` | Folds the legacy multi-file layout (`parts.json` + `relationships.json` + `snapshots/`) into `project.bom.json`, non-destructively, on first open |
| `constants.py` | The only attribute names the code knows: `unit_weight`, `maturity_factor`, `weight_budget`, plus `QTY_MAX` |
| `result.py` | The service contract: every service method returns `{"ok", "data", "errors", "warnings"}`; `@service_guard` turns exceptions into error results |
| `services/part_catalog.py` | Part CRUD; `delete_part(cascade=True)` removes the part's BOM links with it |
| `services/bom_structure.py` | Relationship CRUD with qty validation and DFS **cycle prevention**; `get_children`/`get_parents`/`get_subgraph` |
| `services/rollups.py` | The weight engine: `rollup_weight_with_maturity` (BFS; per-path `breakdown`, per-part `part_totals`, `unresolved_nodes`) and `subtree_weight_map` (one-pass weight of every part) |
| `services/snapshot_diff.py` | `SnapshotService` (create/list versions; whole-project when root is empty; **dedup by content signature**) and `SnapshotDiffService` (`compare_snapshots` / `compare_snapshot_objects`) |
| `utils/` | `canonical.py` (deterministic snapshot signature), `parsing.py` (`base_number` — drawing family of a part number), `clock.py`, `sorting.py` |

### `streamlit_ui/` — the GUI layer

Pure logic (no Streamlit import — unit-tested directly):

| File | Purpose |
|---|---|
| `grid_edit.py` | Spreadsheet reconciliation: builds grid rows from records and diffs the edited grid back into create/update/rename/delete plans (row identity = hidden `_row_id` / `rel_id`, so renames work) |
| `rollup_views.py` | Transforms rollup output: per-direct-child totals, group-by (family or any attribute), attribute coverage, allocation-override list, budget reader |
| `bulk_add.py` | Excel-paste parsing (tab/comma, header skip, per-row validation) + atomic apply |
| `restructure.py` | Assembly **swap** (replace old with new, carry chosen children) and **dissolve** (remove a grouping level, quantities multiplied through) — plan/apply pairs |
| `report.py` | Weekly report builder + copy-ready text, per-part history across versions, staleness |

Renderers (import Streamlit):

| File | Purpose |
|---|---|
| `sidebar.py` | Root-part directory tree, part search, About box |
| `context.py` | `AppContext`: loads live data or materializes a saved version into a read-only temp backend |
| `state.py` | Shared session-state keys + POC constants |
| `helpers.py` | `format_timestamp`, `resolve_data_dir`, `part_key`/`build_part_lookup`, `collect_service_result`, `show_service_result` |
| `tabs/edit.py` | Edit tab: two `st.data_editor` grids + Save, Manage columns, quick add, bulk add, replace assembly, dissolve assembly |
| `tabs/weight.py` | Weight & Rollup orchestrator: ONE rollup shared by the sub-tabs, budget row |
| `tabs/dashboard.py` | Overview sub-tab (per-child chart/table) |
| `tabs/weight_analysis.py` | Reduction opportunities sub-tab |
| `tabs/families.py` | Group-by sub-tab (family / any user column) |
| `tabs/history.py` | History tab: save baseline, version selector, weight-over-time chart, sub-tabs |
| `tabs/reports.py` | Weekly report, part history, weight-over-time renderers |
| `tabs/analysis.py` | Compare-versions diff view |
| `tabs/data.py` | Data-folder picker |

### `tests/`

`test_backend.py` (engine), `test_ui_logic.py` (helpers, context, grid reconciliation),
`test_workflows.py` (bulk add, grouping, swap/dissolve, reports). All pure Python — run in
well under a second with `python -m unittest discover -s tests -p "test_*.py"`.

## The data file

Everything lives in `<data folder>/project.bom.json`:

```json
{
  "version": 2,
  "parts":         [ {"part_number", "name", "last_updated", "attributes": {...}} ],
  "relationships": [ {"rel_id", "parent_part_number", "child_part_number", "qty", ...} ],
  "snapshots":     [ {"snapshot_id", "root_part_number", "created_at", "signature",
                      "label", "parts": [...], "relationships": [...]} ],
  "settings":      { "columns": {"<name>": {"type": "text|number|choice", "choices": [...]}} }
}
```

- Weight fields (`unit_weight`, `maturity_factor`, `weight_budget`) live in each part's
  free-form `attributes` dict; user-defined columns are just more attributes, with their
  type/choices declared in `settings.columns`.
- Every write rewrites the file atomically; `ProjectStore.batch()` collapses a multi-step
  operation (a grid Save, a swap) into one write, all-or-nothing.

## Key behaviors and invariants

1. **Rollup semantics** — a part *with* `unit_weight` contributes
   `unit_weight × maturity_factor × path-qty` and its subtree is **not** traversed (the
   unit weight is an allocation/override). A part *without* one sums its children.
   Cycles contribute 0 (and can't be created — the BOM service refuses them).
2. **Versioning** — every commit path (grid Save, quick/bulk add, swap, dissolve, budget
   change) ends by appending a **whole-project snapshot**, deduplicated by a content
   signature so no-op saves add nothing. Named baselines are the same mechanism with a
   label. The weekly report, part history, and weight-over-time chart all ride on this.
3. **Live vs saved versions** — selecting a saved version materializes it into a
   temp-dir backend (`context.py`); the whole app renders that point in time and all
   editing UI is disabled. Live data is the only thing ever written.
4. **Grid editing** — the baseline grid carries a hidden stable row id; on Save the edited
   grid is diffed against the baseline (`grid_edit.py`), producing an explicit plan that
   is applied through the normal services inside one `batch()`.
5. **No hardcoded vocabulary** — categories, weight bases, zones, etc. are user-defined
   columns; the group-by and coverage views work generically off whatever exists.

## Open ideas

- Saveable custom breakdowns (user-defined saved views with hand-picked parts).
- Weekly report export to a file in addition to the copy block.
