# Mass Allocation Tracking Tool (BOM Manager)

A side tool for engineers who own a **weight rollup**: keep a bill of materials with unit
weights, edit it like a spreadsheet, and instantly see assembly weights, budget margin,
reduction opportunities, and what changed since last week. Every save is versioned, so
history and weekly reporting come for free.

It is **not** a parts-data-management system — it's the fast, local scratchpad for
understanding and reporting weight.

> **Point of contact:** Matt Buckley — <matthew.p.buckley@lmco.com> — for bugs, feature
> ideas, or help getting the tool running.
>
> This tool was built with AI assistance (Anthropic Claude), guided and reviewed by the
> maintainer. Developers: see [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the code is
> organized.

## Get up and running

1. **Install Python 3.11 or newer** — from [python.org/downloads](https://www.python.org/downloads/)
   (on Windows, tick *"Add Python to PATH"* during install).
2. Open a terminal in this folder and install the one dependency:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   streamlit run streamlit_app.py
   ```

   Your browser opens at `http://localhost:8501` with example data loaded.

> **If something goes wrong:** if `python` isn't found, try `python3` (and `python3 -m pip`).
> If the browser doesn't open, browse to `http://localhost:8501` yourself.

## A five-minute tour

**Sidebar — pick your root.** The tree on the left is your BOM, heaviest branches first.
Click **Use as root** on any assembly to make it the focus of the Weight tab. Use the
*Find part* box to jump to a part by number or name.

**Edit tab — your spreadsheet.** Two tables:
- **Parts** — one row per part: part number, name, **Unit Weight**, **Maturity Factor**,
  plus any columns you define. Click a cell and type; paste whole columns from Excel; add
  rows at the bottom; tick rows to delete them (their BOM links are removed too).
- **BOM structure** — one row per parent→child link with its **Qty**.

Nothing is written until you press **💾 Save changes** (an `● Unsaved changes` badge shows
when you have pending edits). Each save also records a version in History automatically.

Also on the Edit tab:
- **Manage columns** — add your own columns, with your own vocabulary: e.g. a
  `weight_basis` dropdown (measured / Creo estimate / vendor quote), a structural vs
  non-structural `category`, `zone`, `supplier`… Dropdown columns keep entries consistent.
- **Quick add a part** — one part + its parent link + qty + weight in one step.
- **Bulk add parts** — paste many rows from Excel (see recipe below).
- **Replace an assembly** — swap an old subassembly for a new one, keeping the subparts
  you choose.

**Weight & Rollup tab — the answers.** A budget bar on top (Budget / Actual / Margin),
then four views of one rollup:
- **Overview** — total weight, maturity growth, and the per-child breakdown chart/table.
- **Reduction opportunities** — parts ranked by how much assembly weight a redesign could
  save ("If unit weight −5/10/20%").
- **Group by** — weight by **drawing family** (base part number) or by **any column you
  added** (category, weight basis, zone…), with drill-down into each group.
- **Data health** — most out-of-date weights, parts that can't roll up, column coverage,
  and allocated weights that override their children.

**History tab — versions and reporting.**
- **Save version now** records a named baseline (e.g. "PDR baseline"). Auto-saves happen on
  every Save too.
- **Weekly report** — pick a baseline (defaults to ~a week ago) and get total delta, top
  movers, added/removed parts, and a **copy-ready text block** for your weekly email.
- **Compare versions** — full diff between any two versions, with weight impact.
- **Part history** — every recorded change to one part, across all versions.

**Data tab** — points the app at a data folder and shows the one file everything lives in.

## Common tasks

**Update a weight (e.g. new Creo number).** Edit tab → click the part's *Unit Weight*
cell → type the number → **Save changes**. The rollup, budget margin, and every parent
assembly update immediately.

**Record where a weight came from.** Manage columns → add a dropdown column like
`weight_basis` with choices such as *measured, Creo estimate, vendor quote* → set it per
part in the grid. *Group by* and *Data health* will then show weight by basis and how much
of the rollup has a basis recorded.

**Add one part.** Edit tab → *Quick add a part* → pick the parent, type number/name/qty/
weight → **Add part**.

**Paste many parts from Excel.** Put columns in this order in Excel: **part number, name,
qty, unit weight** (qty/weight optional). Copy the block, Edit tab → *Bulk add parts* →
pick the parent → paste → **Preview** (problem rows are flagged) → **Add N parts**.
Comma-separated lines typed by hand work too.

**Delete a part.** Tick its row in the Parts grid, delete it, **Save changes**. Its BOM
links are removed with it (the save note tells you how many).

**Replace a subassembly with a new design.** Edit tab → *Replace an assembly* → pick the
old one, give the new part number/name, untick any subparts that don't carry over →
**Replace assembly**. The new assembly takes the old one's place everywhere it was used.

**Set a weight budget.** Weight & Rollup tab → *Set / change budget* → enter the target.
Budget / Actual / Margin then shows on top, red when over.

**Run the weekly report.** History tab → *Weekly report* → check the baseline (defaults
to the newest version at least a week old) → copy the text block at the bottom into your
update.

**See weight by drawing family, or structural vs non-structural.** Weight & Rollup →
*Group by*. "Part family" groups `-1/-2/-501` variants of the same base drawing together;
or group by any column you've added (e.g. `category`).

**See when a part last changed, and what changed.** The read-only *Last Updated* column in
the Parts grid, and History → *Part history* for the full change list.

## How the rollup works (FAQ)

- **Leave Unit Weight blank on an assembly** → its weight rolls up from its children
  (qty × child weight, all the way down).
- **Set Unit Weight on an assembly** → that number **overrides** the children (an
  *allocated* weight). The children are ignored until you clear it. *Data health* lists
  every allocation that is currently hiding children.
- **Maturity Factor** is a growth margin multiplier: weight counts as
  `unit weight × maturity factor` (1.0 = mature/as-designed, 1.15 = +15% growth allowance).
- **Does a change trickle down?** Changes flow **up** automatically — the rollup is
  recomputed live, so editing one part instantly updates every assembly above it.
  Timestamps are per-part: touching a parent doesn't mark its children as updated.
- A part with **no unit weight and no children** contributes 0 and is flagged in
  *Data health*.

## Where your data lives

Everything — current parts, BOM links, your column definitions, and the full version
history — is one file:

```
<data folder>/project.bom.json
```

Back it up by copying that file. The app ships pointing at `demo_data/`; use the Data tab
to point it at your own folder (a fresh empty project is created automatically). Older
multi-file layouts (`parts.json` + `relationships.json` + `snapshots/`) are migrated into
the single file automatically and non-destructively on first open.

## Getting help

- **Hover any ⓘ icon in the app** — every major control has a one-line explanation.
- The sidebar's **About / getting help** box has the quick workflow reminder.
- Stuck, found a bug, or want a feature? **Contact Matt Buckley —
  <matthew.p.buckley@lmco.com>.**

## Running tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## Appendix: Python API reference (for developers)

The UI sits on a stdlib-only backend you can use directly:

```python
from bom_backend import BOMBackend

backend = BOMBackend(data_dir="data")   # opens/creates data/project.bom.json
```

Every service method returns `{"ok": bool, "data": dict, "errors": [...], "warnings": [...]}`.
Check `ok` first; read the payload from `data`.

### `backend.parts` (part catalog)

1. `add_or_update_part(part_number, name, attributes=None, last_updated=None, merge_attributes=True)`
   — create or update; returns `data.part`, `data.created`.
2. `get_part(part_number)` — returns `data.part`.
3. `list_parts(query=None)` — optional case-insensitive search; returns `data.parts`.
4. `delete_part(part_number, allow_if_referenced=False, cascade=False)` — with
   `cascade=True`, deletes every relationship touching the part first and returns their
   ids in `data.removed_relationships`; with `cascade=False` (default) it refuses while
   references exist unless `allow_if_referenced=True`.
5. `update_attributes(part_number, attributes, merge_attributes=True)`.

### `backend.bom` (relationships and structure)

1. `add_or_update_relationship(parent_part_number, child_part_number, qty, rel_id=None,
   attributes=None, last_updated=None, allow_dangling=False, merge_attributes=True)` —
   validates `qty > 0`, blocks cycles; returns `data.relationship`, `data.created`.
2. `delete_relationship(rel_id)`.
3. `get_children(parent_part_number)` / `get_parents(child_part_number)`.
4. `get_subgraph(root_part_number)` — reachable parts + relationships from a root.

### `backend.rollups`

1. `rollup_weight_with_maturity(root_part_number, unit_weight_key="unit_weight",
   maturity_factor_key="maturity_factor", default_maturity_factor=1.0, include_root=True,
   top_n=10)` — the weight engine: a part with `unit_weight` contributes
   `unit_weight × maturity_factor × path qty` and its subtree is not traversed (allocation
   override). Returns `data.total`, `data.breakdown` (per path), `data.part_totals`
   (per part), `data.top_contributors`, `data.unresolved_nodes`.
2. `subtree_weight_map(default_maturity_factor=1.0)` — effective subtree weight for every
   part in one pass; returns `data.weights` (`{part_number: weight}`).

### `backend.snapshots` (version history)

1. `create_snapshot(root_part_number="", label=None, deduplicate_if_identical=True)` —
   empty root freezes the **whole project** (this is how save-history works); a specific
   root freezes just that subgraph. Identical content is deduplicated by signature.
2. `get_snapshot(snapshot_id)` / `list_snapshots(root_part_number=None)`.

### `backend.diff`

1. `compare_snapshots(snapshot_id_a, snapshot_id_b)` — part/relationship adds, removes,
   and modifications plus signature equality.
2. `compare_snapshot_objects(snapshot_a, snapshot_b)` — same diff for in-memory
   `Snapshot` objects (used to compare a baseline against unsaved live data).

### `backend.store` (project file)

`read_section(name)` / `write_section(name, records)` for `parts` / `relationships` /
`snapshots`; `read_settings()` / `write_settings(dict)` for project settings (e.g.
user-defined column types/choices under `settings["columns"]`); `batch()` context manager
groups many writes into one atomic file write.
