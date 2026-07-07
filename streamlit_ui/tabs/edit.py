from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from bom_backend.constants import MATURITY_FACTOR_KEY, QTY_MAX, UNIT_WEIGHT_KEY
from streamlit_ui.bulk_add import apply_bulk_add, parse_bulk_lines
from streamlit_ui.context import AppContext
from streamlit_ui.grid_edit import (
    LAST_UPDATED_COLUMN,
    ROW_ID,
    BomGrid,
    PartsGrid,
    build_bom_grid,
    build_parts_grid,
    reconcile_bom,
    reconcile_parts,
)
from streamlit_ui.helpers import format_timestamp
from streamlit_ui.restructure import apply_assembly_swap, plan_assembly_swap

GRID_VERSION_KEY = "_edit_grid_v"
BULK_PREVIEW_KEY = "_bulk_preview"
SHOW_EVERYTHING = "(show everything)"


# ── project column settings (user-defined part columns) ──────────────────────
def _column_settings(ctx: AppContext) -> dict[str, dict[str, Any]]:
    settings = ctx.live_backend.store.read_settings()
    columns = settings.get("columns")
    return dict(columns) if isinstance(columns, dict) else {}


def _save_column_settings(ctx: AppContext, columns: dict[str, dict[str, Any]]) -> None:
    settings = ctx.live_backend.store.read_settings()
    settings["columns"] = columns
    ctx.live_backend.store.write_settings(settings)


def _part_number_set(parts: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {str(p.get("part_number", "")).strip() for p in parts if str(p.get("part_number", "")).strip()}
    )


def _filter_to_subgraph(
    ctx: AppContext, focus: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result = ctx.live_backend.bom.get_subgraph(focus)
    if not result.get("ok"):
        st.warning(f"Could not focus on {focus}; showing everything.")
        return ctx.parts, ctx.relationships
    keep = {str(p.get("part_number", "")).strip() for p in result["data"]["parts"]}
    keep.add(focus)
    parts = [p for p in ctx.parts if str(p.get("part_number", "")).strip() in keep]
    rels = [
        r
        for r in ctx.relationships
        if str(r.get("parent_part_number", "")).strip() in keep
        and str(r.get("child_part_number", "")).strip() in keep
    ]
    return parts, rels


def _existing_column_values(parts: list[dict[str, Any]], column: str) -> set[str]:
    values: set[str] = set()
    for part in parts:
        value = (part.get("attributes") or {}).get(column)
        if value is not None and str(value).strip():
            values.add(str(value).strip())
    return values


def _parts_column_config(
    attribute_columns: list[str],
    column_settings: dict[str, dict[str, Any]],
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "part_number": st.column_config.TextColumn("Part Number", required=True, width="medium"),
        "name": st.column_config.TextColumn("Name", required=True, width="large"),
        UNIT_WEIGHT_KEY: st.column_config.NumberColumn(
            "Unit Weight",
            help="Weight of one unit of this part. Leave blank for assemblies that roll up from children.",
            min_value=0.0,
            format="%.4f",
        ),
        MATURITY_FACTOR_KEY: st.column_config.NumberColumn(
            "Maturity Factor",
            help="Growth/margin multiplier on weight (1.0 = mature/as-designed).",
            min_value=0.0,
            format="%.3f",
        ),
        LAST_UPDATED_COLUMN: st.column_config.TextColumn(
            "Last Updated", disabled=True, help="When this part was last changed (read-only)."
        ),
    }
    for column in attribute_columns:
        settings = column_settings.get(column) or {}
        column_type = settings.get("type", "text")
        if column_type == "choice":
            choices = [str(c) for c in settings.get("choices") or []]
            options = sorted(set(choices) | _existing_column_values(parts, column))
            config[column] = st.column_config.SelectboxColumn(column, options=options)
        elif column_type == "number":
            config[column] = st.column_config.NumberColumn(column)
        else:
            config[column] = st.column_config.TextColumn(column)
    return config


def _bom_column_config() -> dict[str, Any]:
    return {
        "parent_part_number": st.column_config.TextColumn(
            "Parent", required=True, help="The assembly part number."
        ),
        "child_part_number": st.column_config.TextColumn(
            "Child", required=True, help="The part that goes into the parent."
        ),
        "qty": st.column_config.NumberColumn(
            "Qty", min_value=0.0001, max_value=QTY_MAX, format="%.4f", required=True
        ),
    }


# ── committing helpers ────────────────────────────────────────────────────────
def _auto_version(ctx: AppContext, notes: list[str]) -> None:
    """Append a deduplicated whole-project version to history after a commit."""
    result = ctx.live_backend.snapshots.create_snapshot(deduplicate_if_identical=True)
    if not result.get("ok"):
        for err in result.get("errors", []):
            notes.append(f"History: {err}")


def _finish_commit(ctx: AppContext, errors: list[str], notes: list[str], version: int) -> None:
    _auto_version(ctx, notes)
    for note in notes:
        st.info(note)
    if errors:
        st.error("Some changes could not be applied:")
        for err in errors:
            st.write(f"- {err}")
    else:
        st.session_state[GRID_VERSION_KEY] = version + 1
        st.session_state.pop(BULK_PREVIEW_KEY, None)
        st.rerun()


def _apply_changes(ctx: AppContext, parts_plan, bom_plan) -> tuple[list[str], list[str]]:
    backend = ctx.live_backend
    errors: list[str] = []
    notes: list[str] = []

    def _collect(label: str, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            for err in result.get("errors", []):
                errors.append(f"{label}: {err}")
        for warn in result.get("warnings", []):
            notes.append(f"{label}: {warn}")

    with backend.store.batch():
        # 1. Create/update parts (so links added below can reference them).
        for op in parts_plan.creates + parts_plan.updates:
            _collect(
                f"Part {op.part_number or '(blank)'}",
                backend.parts.add_or_update_part(
                    part_number=op.part_number,
                    name=op.name,
                    attributes=op.attributes,
                    merge_attributes=False,
                ),
            )
        # 2. Renames: create the new number, then drop the old one.
        for op in parts_plan.renames:
            _collect(
                f"Rename {op.old_part_number}→{op.part_number}",
                backend.parts.add_or_update_part(
                    part_number=op.part_number,
                    name=op.name,
                    attributes=op.attributes,
                    merge_attributes=False,
                ),
            )
        # 3. Relationship deletes.
        for rel_id in bom_plan.deletes:
            _collect(f"Remove link {rel_id}", backend.bom.delete_relationship(rel_id))
        # 4. Relationship upserts (allow_dangling so a same-save part+link ordering is forgiving).
        for op in bom_plan.upserts:
            _collect(
                f"Link {op.parent_part_number}→{op.child_part_number}",
                backend.bom.add_or_update_relationship(
                    parent_part_number=op.parent_part_number,
                    child_part_number=op.child_part_number,
                    qty=op.qty,
                    rel_id=op.rel_id,
                    attributes=op.attributes,
                    allow_dangling=True,
                    merge_attributes=False,
                ),
            )
        # 5. Old numbers from renames (forced), then deletes with their links removed too.
        for op in parts_plan.renames:
            backend.parts.delete_part(op.old_part_number, allow_if_referenced=True)
            notes.append(
                f"Renamed {op.old_part_number}→{op.part_number}. Check any links that still point at {op.old_part_number}."
            )
        for part_number in parts_plan.deletes:
            _collect(
                f"Delete part {part_number}",
                backend.parts.delete_part(part_number, cascade=True),
            )

    return errors, notes


# ── expander tools ────────────────────────────────────────────────────────────
def _render_manage_columns(ctx: AppContext, version: int) -> None:
    columns = _column_settings(ctx)
    with st.expander("Manage columns"):
        st.caption(
            "Define your own part columns for whatever your program tracks — for example a "
            "`weight_basis` dropdown (measured / Creo estimate / vendor quote), a "
            "structural vs non-structural `category`, `zone`, `supplier`… Any column you add "
            "can also be used to group the weight rollup."
        )
        with st.form(f"add_col_{version}"):
            name_col, type_col = st.columns(2)
            with name_col:
                column_name = st.text_input("Column name", placeholder="weight_basis")
            with type_col:
                column_type = st.selectbox("Type", ["text", "dropdown (choices)", "number"])
            choices_text = st.text_input(
                "Choices (comma-separated — only for dropdown)",
                placeholder="measured, Creo estimate, vendor quote",
            )
            submitted = st.form_submit_button("Add / update column")

        if submitted:
            name = column_name.strip()
            if not name:
                st.error("Give the column a name.")
            elif name in ("part_number", "name", UNIT_WEIGHT_KEY, MATURITY_FACTOR_KEY, LAST_UPDATED_COLUMN):
                st.error(f"'{name}' is a built-in column.")
            else:
                entry: dict[str, Any] = {"type": "text"}
                if column_type.startswith("dropdown"):
                    choices = [c.strip() for c in choices_text.split(",") if c.strip()]
                    if not choices:
                        st.error("List at least one choice for a dropdown column.")
                        return
                    entry = {"type": "choice", "choices": choices}
                elif column_type == "number":
                    entry = {"type": "number"}
                columns[name] = entry
                _save_column_settings(ctx, columns)
                st.rerun()

        if columns:
            st.markdown("**Your columns**")
            for column in sorted(columns):
                settings = columns[column]
                info_col, del_col = st.columns([4, 1])
                with info_col:
                    kind = settings.get("type", "text")
                    detail = f" — {', '.join(settings.get('choices', []))}" if kind == "choice" else ""
                    st.write(f"`{column}` ({kind}{detail})")
                with del_col:
                    if st.button(
                        "Delete",
                        key=f"del_col_{column}_{version}",
                        help="Removes this column and its values from every part. A version is saved first, so this can be reviewed in History.",
                    ):
                        del columns[column]
                        notes: list[str] = []
                        with ctx.live_backend.store.batch():
                            _save_column_settings(ctx, columns)
                            parts_result = ctx.live_backend.parts.list_parts()
                            for part in parts_result["data"]["parts"] if parts_result.get("ok") else []:
                                attributes = dict(part.get("attributes") or {})
                                if column in attributes:
                                    attributes.pop(column)
                                    ctx.live_backend.parts.update_attributes(
                                        part["part_number"], attributes, merge_attributes=False
                                    )
                        notes.append(f"Removed column '{column}' from all parts.")
                        _finish_commit(ctx, [], notes, version)


def _rel_lookup(relationships: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child = str(rel.get("child_part_number", "")).strip()
        key = (parent, child)
        if key not in lookup:
            lookup[key] = str(rel.get("rel_id", "")).strip()
    return lookup


def _render_quick_add(ctx: AppContext, part_numbers: list[str], default_parent: str, version: int) -> None:
    with st.expander("Quick add a part"):
        st.caption("Add one part and link it under an assembly in a single step. Saves immediately.")
        with st.form(f"quick_add_{version}"):
            parent = st.selectbox(
                "Under assembly (parent)",
                options=part_numbers,
                index=part_numbers.index(default_parent) if default_parent in part_numbers else 0,
            )
            pn_col, name_col = st.columns(2)
            with pn_col:
                part_number = st.text_input("Part number", placeholder="20547099-101")
            with name_col:
                name = st.text_input("Name", placeholder="BRACKET, UPPER")
            qty_col, weight_col = st.columns(2)
            with qty_col:
                qty = st.number_input("Qty", min_value=0.0001, value=1.0, step=1.0, format="%.4f")
            with weight_col:
                weight_text = st.text_input("Unit weight (optional)", placeholder="1.25")
            submitted = st.form_submit_button("Add part", type="primary")

        if submitted:
            line = "\t".join([part_number.strip(), name.strip(), str(qty), weight_text.strip()])
            existing_links = set(_rel_lookup(ctx.relationships).keys())
            result = parse_bulk_lines(line, set(part_numbers), existing_links, parent)
            if result.error_rows:
                st.error(result.error_rows[0].error)
            elif not result.ok_rows:
                st.error("Enter a part number.")
            else:
                errors, notes = apply_bulk_add(
                    ctx.live_backend, parent, result.ok_rows, _rel_lookup(ctx.relationships)
                )
                _finish_commit(ctx, errors, notes, version)


def _render_bulk_add(ctx: AppContext, part_numbers: list[str], default_parent: str, version: int) -> None:
    with st.expander("Bulk add parts (paste from Excel)"):
        st.caption(
            "Paste one part per line: **part number, name, qty, unit weight** (qty and weight "
            "optional). Copying columns straight out of Excel works — cells arrive tab-separated. "
            "Preview first, then add. Saves immediately."
        )
        parent = st.selectbox(
            "Under assembly (parent)",
            options=part_numbers,
            index=part_numbers.index(default_parent) if default_parent in part_numbers else 0,
            key=f"bulk_parent_{version}",
        )
        with st.form(f"bulk_form_{version}"):
            text = st.text_area(
                "Rows",
                height=140,
                placeholder=(
                    "20547099-101\tBRACKET, UPPER\t2\t1.25\n"
                    "20547099-102, BRACKET, 4, 0.8\n"
                    "20547099-103"
                ),
            )
            preview_clicked = st.form_submit_button("Preview")

        if preview_clicked and text.strip():
            result = parse_bulk_lines(
                text,
                set(part_numbers),
                set(_rel_lookup(ctx.relationships).keys()),
                parent,
            )
            st.session_state[BULK_PREVIEW_KEY] = {"parent": parent, "result": result}

        stored = st.session_state.get(BULK_PREVIEW_KEY)
        if not stored or stored.get("parent") != parent:
            return

        result = stored["result"]
        if result.header_skipped:
            st.caption("First line looked like a header — skipped.")
        if not result.rows:
            st.info("Nothing to add yet.")
            return

        preview_rows = [
            {
                "Line": row.line_no,
                "Part Number": row.part_number,
                "Name": row.name,
                "Qty": row.qty,
                "Unit Weight": row.unit_weight,
                "Status": ("❌ " + row.error) if row.error else ("⚠ " + "; ".join(row.warnings) if row.warnings else "OK"),
            }
            for row in result.rows
        ]
        st.dataframe(preview_rows, width="stretch", hide_index=True)

        error_count = len(result.error_rows)
        if error_count:
            st.error(f"{error_count} row(s) have problems — fix them and press Preview again.")
        commit_clicked = st.button(
            f"Add {len(result.ok_rows)} part(s) under {parent}",
            type="primary",
            disabled=bool(error_count) or not result.ok_rows,
            key=f"bulk_commit_{version}",
        )
        if commit_clicked:
            errors, notes = apply_bulk_add(
                ctx.live_backend, parent, result.ok_rows, _rel_lookup(ctx.relationships)
            )
            _finish_commit(ctx, errors, notes, version)


def _render_replace_assembly(ctx: AppContext, version: int) -> None:
    assemblies = sorted(
        {
            str(rel.get("parent_part_number", "")).strip()
            for rel in ctx.relationships
            if str(rel.get("parent_part_number", "")).strip()
        }
    )
    if not assemblies:
        return

    with st.expander("Replace an assembly"):
        st.caption(
            "Swap out a subassembly for a new design. The new assembly takes the old one's "
            "place in the BOM, keeps the subparts you choose, and the old assembly is removed. "
            "Saves immediately."
        )
        old_pn = st.selectbox(
            "Assembly being replaced", options=assemblies, key=f"swap_old_{version}"
        )
        children = sorted(
            {
                str(rel.get("child_part_number", "")).strip()
                for rel in ctx.relationships
                if str(rel.get("parent_part_number", "")).strip() == old_pn
            }
        )
        pn_col, name_col = st.columns(2)
        with pn_col:
            new_pn = st.text_input("New assembly part number", key=f"swap_new_pn_{version}")
        with name_col:
            new_name = st.text_input("New assembly name", key=f"swap_new_name_{version}")
        carry = st.multiselect(
            "Subparts to carry over to the new assembly",
            options=children,
            default=children,
            key=f"swap_carry_{version}",
        )

        plan = plan_assembly_swap(
            old_pn, new_pn, new_name, carry, ctx.parts, ctx.relationships
        )
        if new_pn.strip():
            for error in plan.errors:
                st.warning(error)
            if not plan.errors:
                dropped = f"; {len(plan.dropped_children)} subpart(s) dropped" if plan.dropped_children else ""
                action = "create" if plan.create_new else "reuse existing part"
                st.caption(
                    f"Will {action} **{plan.new_part_number}**, put it in {len(plan.parent_links)} "
                    f"place(s) where **{old_pn}** was used, carry over {len(plan.carried_links)} "
                    f"subpart link(s){dropped}, and remove {old_pn}."
                )

        if st.button(
            "Replace assembly",
            type="primary",
            disabled=bool(plan.errors) or not new_pn.strip(),
            key=f"swap_apply_{version}",
        ):
            errors, notes = apply_assembly_swap(ctx.live_backend, plan)
            _finish_commit(ctx, errors, notes, version)


# ── the tab ───────────────────────────────────────────────────────────────────
def render_edit_tab(ctx: AppContext, root_part_number: str = "") -> None:
    read_only = ctx.snapshot_mode

    st.subheader("Edit BOM")
    st.caption(
        "Edit the tables like a spreadsheet — click a cell, type, paste, or add/delete rows — "
        "then press **Save changes**."
    )
    if read_only:
        st.warning(
            "You're viewing a saved version (read-only). Switch back to **Live Data** in the "
            "History tab to make edits.",
            icon="🔒",
        )

    # ── Optional focus ────────────────────────────────────────────────────────
    part_numbers = _part_number_set(ctx.parts)
    focus_options = [SHOW_EVERYTHING] + part_numbers
    default_focus = root_part_number if root_part_number in part_numbers else SHOW_EVERYTHING
    focus = st.selectbox(
        "Focus on assembly (optional)",
        options=focus_options,
        index=focus_options.index(default_focus) if default_focus in focus_options else 0,
        help="Narrow both tables to one assembly and everything under it. Leave on 'show everything' to edit the whole BOM.",
    )

    if focus != SHOW_EVERYTHING:
        parts, relationships = _filter_to_subgraph(ctx, focus)
    else:
        parts, relationships = ctx.parts, ctx.relationships

    # ── Build baseline grids ──────────────────────────────────────────────────
    column_settings = _column_settings(ctx)
    parts_grid: PartsGrid = build_parts_grid(parts)
    settings_only_cols = [c for c in sorted(column_settings) if c not in parts_grid.attribute_columns]
    parts_grid.attribute_columns = parts_grid.attribute_columns + settings_only_cols
    bom_grid: BomGrid = build_bom_grid(relationships)

    parts_visible = [
        "part_number",
        "name",
        UNIT_WEIGHT_KEY,
        MATURITY_FACTOR_KEY,
        *parts_grid.attribute_columns,
        LAST_UPDATED_COLUMN,
    ]
    parts_columns = [ROW_ID, *parts_visible]
    parts_df = pd.DataFrame(parts_grid.rows, columns=parts_columns)
    # Pin numeric columns to a numeric dtype so NumberColumn stays compatible even when
    # every current value is blank; keep text columns as object/string.
    numeric_cols = [UNIT_WEIGHT_KEY, MATURITY_FACTOR_KEY] + [
        c for c in parts_grid.attribute_columns if (column_settings.get(c) or {}).get("type") == "number"
    ]
    for numeric_col in numeric_cols:
        parts_df[numeric_col] = pd.to_numeric(parts_df[numeric_col], errors="coerce")
    for text_col in ("part_number", "name", *[c for c in parts_grid.attribute_columns if c not in numeric_cols]):
        parts_df[text_col] = parts_df[text_col].astype("object")
    parts_df[LAST_UPDATED_COLUMN] = parts_df[LAST_UPDATED_COLUMN].map(format_timestamp).astype("object")

    bom_visible = ["parent_part_number", "child_part_number", "qty"]
    bom_df = pd.DataFrame(bom_grid.rows, columns=["rel_id", *bom_visible])
    bom_df["qty"] = pd.to_numeric(bom_df["qty"], errors="coerce")
    for text_col in ("parent_part_number", "child_part_number"):
        bom_df[text_col] = bom_df[text_col].astype("object")

    version = st.session_state.get(GRID_VERSION_KEY, 0)
    key_suffix = f"{ctx.data_dir}|{focus}|{ctx.loaded_snapshot_id}|{version}"

    # ── Parts grid ────────────────────────────────────────────────────────────
    st.markdown("#### Parts")
    edited_parts = st.data_editor(
        parts_df,
        key=f"parts_editor_{key_suffix}",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        disabled=read_only,
        column_order=parts_visible,
        column_config=_parts_column_config(parts_grid.attribute_columns, column_settings, parts),
    )

    if not read_only:
        _render_manage_columns(ctx, version)

    # ── BOM grid ──────────────────────────────────────────────────────────────
    st.markdown("#### BOM structure (which parts go into which)")
    edited_bom = st.data_editor(
        bom_df,
        key=f"bom_editor_{key_suffix}",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        disabled=read_only,
        column_order=bom_visible,
        column_config=_bom_column_config(),
    )

    if read_only:
        return

    # ── One-step tools (each saves immediately) ───────────────────────────────
    if part_numbers:
        default_parent = focus if focus != SHOW_EVERYTHING else (root_part_number or part_numbers[0])
        _render_quick_add(ctx, part_numbers, default_parent, version)
        _render_bulk_add(ctx, part_numbers, default_parent, version)
        _render_replace_assembly(ctx, version)

    # ── Save row for grid edits ───────────────────────────────────────────────
    parts_plan = reconcile_parts(parts_grid, edited_parts.to_dict("records"))
    bom_plan = reconcile_bom(bom_grid, edited_bom.to_dict("records"))
    dirty = not (parts_plan.is_empty and bom_plan.is_empty)

    st.divider()
    status_col, button_col = st.columns([3, 1])
    with status_col:
        if dirty:
            st.markdown("**● Unsaved changes**")
            st.caption(_summarize_plans(parts_plan, bom_plan))
        else:
            st.caption("All changes saved.")
    with button_col:
        save_clicked = st.button(
            "💾 Save changes", type="primary", disabled=not dirty, width="stretch"
        )

    if save_clicked:
        errors, notes = _apply_changes(ctx, parts_plan, bom_plan)
        _finish_commit(ctx, errors, notes, version)


def _summarize_plans(parts_plan, bom_plan) -> str:
    bits: list[str] = []
    p_add = len(parts_plan.creates)
    p_upd = len(parts_plan.updates) + len(parts_plan.renames)
    p_del = len(parts_plan.deletes) + len(parts_plan.renames)
    b_add = sum(1 for op in bom_plan.upserts if op.rel_id is None)
    b_upd = sum(1 for op in bom_plan.upserts if op.rel_id is not None)
    b_del = len(bom_plan.deletes)
    if p_add:
        bits.append(f"{p_add} part(s) added")
    if p_upd:
        bits.append(f"{p_upd} part(s) changed")
    if p_del:
        bits.append(f"{p_del} part(s) removed")
    if b_add:
        bits.append(f"{b_add} link(s) added")
    if b_upd:
        bits.append(f"{b_upd} link(s) changed")
    if b_del:
        bits.append(f"{b_del} link(s) removed")
    return ", ".join(bits) if bits else "No changes."
