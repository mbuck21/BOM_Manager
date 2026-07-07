# CLAUDE.md — working notes for AI agents

Mass Allocation Tracking Tool: a Streamlit app for engineers who own a program **weight
rollup**. Users edit a BOM (parts + parent→child links with qty) like a spreadsheet and
the app rolls up weight, tracks it against a budget, groups it by drawing family or any
user-defined column, and reports what changed week to week. It is a personal/side tool,
not a parts-data-management system.

**POC / owner: Matt Buckley (matthew.p.buckley@lmco.com).** This codebase was written
with the use of AI (Anthropic Claude) under his direction. Read `ARCHITECTURE.md` for the
full module map before making structural changes; `README.md` is the user-facing guide.

## Run / test / verify

```bash
pip install -r requirements.txt                       # streamlit only
streamlit run streamlit_app.py                        # opens on demo_data/
python -m unittest discover -s tests -p "test_*.py"   # full suite, <1s
```

Headless app verification uses Streamlit's AppTest (this is how past rounds were
verified — prefer it over assuming):

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("streamlit_app.py", default_timeout=120)
at.run()                     # boots on demo_data, LIVE (editable) mode
assert not at.exception
# Force a saved-version (read-only) view — all three keys are required:
from streamlit_ui.helpers import resolve_data_dir
at2 = AppTest.from_file("streamlit_app.py", default_timeout=120)
at2.session_state["active_snapshot_id"] = "<snapshot_id from demo_data/project.bom.json>"
at2.session_state["snapshot_selection_initialized"] = True
at2.session_state["snapshot_selection_data_dir"] = str(resolve_data_dir("demo_data").resolve())
at2.run()
```

Don't run two AppTest sessions in one Python process on the full demo data — it can be
OOM-killed. Use separate processes.

## Architecture in one paragraph

`bom_backend/` is a **stdlib-only** engine (never imports Streamlit): dataclass models,
services returning `{"ok", "data", "errors", "warnings"}` (via `@service_guard` in
`result.py`), and a single-file JSON store. `streamlit_ui/` renders it, and keeps its
interesting logic in **Streamlit-free modules** (`grid_edit.py`, `rollup_views.py`,
`bulk_add.py`, `restructure.py`, `report.py`) that are unit-tested directly.
`streamlit_app.py` is a thin entry point wiring 4 tabs: Edit / Weight & Rollup / History /
Data. Session-state keys live in `streamlit_ui/state.py`.

## Invariants — do not break these

1. **One file per project.** All data (parts, relationships, snapshots/versions, column
   settings) lives in `<data_dir>/project.bom.json` through `ProjectStore`
   (`bom_backend/store.py`). Writes are atomic (`.tmp` + rename). All three repositories
   share ONE store instance; `write_section` must never clobber other sections.
   Multi-step operations run inside `store.batch()` → single atomic write, discarded on
   exception.
2. **Every commit path auto-versions.** Grid Save, quick/bulk add, swap, dissolve, budget
   edit — each ends with `snapshots.create_snapshot(deduplicate_if_identical=True)`
   (empty root = whole-project). Dedup is by content signature
   (`utils/canonical.py::build_signature`), which is what keeps history from bloating.
   If you add a new write path, keep this pattern (see `_finish_commit` in
   `streamlit_ui/tabs/edit.py`).
3. **Rollup override semantics.** A part with `unit_weight` contributes
   `unit_weight × maturity_factor × path_qty` and its children are NOT traversed (an
   "allocated" weight). Implemented in `rollups.rollup_weight_with_maturity` and mirrored
   by `subtree_weight_map`; a unit test asserts they agree.
4. **Cycles are impossible** — `bom_structure.add_or_update_relationship` DFS-checks every
   upsert. Assembly swap/dissolve rely on this (they upsert links with existing rel_ids
   and abort the batch if any upsert fails).
5. **Snapshot mode is read-only.** When `ctx.snapshot_mode` is true, all editing UI must
   be hidden/disabled (writes only ever go to `ctx.live_backend`). The app always opens
   on live data (`default_to_latest=False` in `main()`).
6. **No hardcoded domain vocabulary.** Only `unit_weight`, `maturity_factor`,
   `weight_budget` are known to code (`bom_backend/constants.py`). Categories/weight
   bases/zones are user-defined columns stored in `settings["columns"]` with type
   text/number/choice; the group-by and coverage views consume them generically.
7. **Performance: never call repository lookups per BOM node.** Streamlit reruns the
   whole script on every click, and each repository read parses the project file. A
   traversal that calls `part_repo.get`/`find_children` per node once took 4+ seconds
   (418 file parses); the fix is to `list_parts()`/`list_relationships()` ONCE and index
   into dicts (see `rollup_weight_with_maturity`, `get_subgraph`, `subtree_weight_map`).
   `ProjectStore` also keeps an mtime-keyed parse cache (`_DOCUMENT_CACHE` in `store.py`)
   — cached records are shared, so never mutate records returned by a repository in
   place. `tests/test_backend.py::TestReadEfficiency` guards this.
8. **Snapshot edits are metadata-only.** `update_snapshot` may change label/created_at
   but never content or signature; `delete_snapshot` prunes history. Neither creates an
   auto-version. Per-snapshot rollups in the UI are `st.cache_data`-cached keyed by
   snapshot_id (safe: content is immutable).

## Streamlit gotchas learned the hard way

- Use `width="stretch"`, **never** `use_container_width=True` (removed after 2025-12).
- `st.data_editor` column types must match the DataFrame dtype: numeric columns are
  pinned with `pd.to_numeric(...)`, text columns with `.astype("object")`, and extra
  attribute cells are stringified in `grid_edit.build_parts_grid` (a raw bool cell +
  TextColumn crashes the editor).
- Grid row identity: parts rows carry a hidden `_row_id` (so part-number *renames* are
  detected as rename, not delete+add); BOM rows are keyed by `rel_id`. The `last_updated`
  column is display-only and excluded from reconciliation.
- Editor/session state resets by baking a version counter (`_edit_grid_v`) into widget
  keys; bump it after successful commits and `st.rerun()`.
- `main()` resets the version selection whenever the resolved data dir changes
  (`snapshot_selection_data_dir` marker) — that's why AppTest needs all three keys.

## Conventions

- Backend service methods: keyword-rich signatures, return `{ok,data,errors,warnings}`,
  decorated `@service_guard`. Don't raise across the service boundary.
- UI workflow logic goes in a Streamlit-free module with a `plan_*` (pure, returns a
  dataclass with `.errors`) + `apply_*` (executes inside `store.batch()`, returns
  `(errors, notes)`) pair — see `restructure.py`. Renderers stay thin.
- Fold service results into error/note lists with `helpers.collect_service_result`
  (usually via `functools.partial`).
- Part lookups: `helpers.part_key` / `helpers.build_part_lookup`.
- Tests are stdlib `unittest`; pure logic gets direct unit tests, app behavior gets
  AppTest spot checks. Keep the suite green — it runs in under a second.
- Part numbers are `<base>-<dash>`; `utils/parsing.py::base_number` (rsplit on the last
  dash) defines a drawing family. The demo data (`demo_data/project.bom.json`, 214 parts)
  is real-shaped; its heaviest root is `20553800-501`.

## Where to add things

| You want to… | Touch |
|---|---|
| New rollup math / analysis | `bom_backend/services/rollups.py` + a pure transform in `streamlit_ui/rollup_views.py` + a sub-tab under `tabs/weight.py` |
| New bulk/structural edit operation | plan/apply pair in `streamlit_ui/restructure.py` (or `bulk_add.py`) + an expander in `tabs/edit.py` + tests in `tests/test_workflows.py` |
| New report | pure builder in `streamlit_ui/report.py` + renderer in `tabs/reports.py`, wired in `tabs/history.py` |
| New per-part field | nothing — users define columns themselves (Edit → Manage columns); only touch code if it needs first-class math |
| Storage changes | `bom_backend/store.py` (+ `migration.py` if the file shape changes; migrations must be non-destructive) |

Open ideas parked by the owner: saveable custom breakdowns; weekly-report file export.
