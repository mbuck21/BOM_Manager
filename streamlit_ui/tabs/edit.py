from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from bom_backend.constants import MATURITY_FACTOR_KEY, QTY_MAX, UNIT_WEIGHT_KEY
from streamlit_ui.context import AppContext
from streamlit_ui.grid_edit import (
    ROW_ID,
    BomGrid,
    PartsGrid,
    build_bom_grid,
    build_parts_grid,
    reconcile_bom,
    reconcile_parts,
)

GRID_VERSION_KEY = "_edit_grid_v"
EXTRA_COLS_KEY = "_edit_extra_cols"


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


def _parts_column_config(attribute_columns: list[str]) -> dict[str, Any]:
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
    }
    for column in attribute_columns:
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
        # 5. Old numbers from renames (forced), then plain deletes.
        for op in parts_plan.renames:
            backend.parts.delete_part(op.old_part_number, allow_if_referenced=True)
            notes.append(
                f"Renamed {op.old_part_number}→{op.part_number}. Check any links that still point at {op.old_part_number}."
            )
        for part_number in parts_plan.deletes:
            _collect(f"Delete part {part_number}", backend.parts.delete_part(part_number))

    return errors, notes


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
    focus_options = ["(show everything)"] + part_numbers
    default_focus = root_part_number if root_part_number in part_numbers else "(show everything)"
    focus = st.selectbox(
        "Focus on assembly (optional)",
        options=focus_options,
        index=focus_options.index(default_focus) if default_focus in focus_options else 0,
        help="Narrow both tables to one assembly and everything under it. Leave on 'show everything' to edit the whole BOM.",
    )

    if focus != "(show everything)":
        parts, relationships = _filter_to_subgraph(ctx, focus)
    else:
        parts, relationships = ctx.parts, ctx.relationships

    # ── Build baseline grids ──────────────────────────────────────────────────
    parts_grid: PartsGrid = build_parts_grid(parts)
    extra_cols = [c for c in st.session_state.get(EXTRA_COLS_KEY, []) if c not in parts_grid.attribute_columns]
    parts_grid.attribute_columns = parts_grid.attribute_columns + extra_cols
    bom_grid: BomGrid = build_bom_grid(relationships)

    parts_visible = ["part_number", "name", UNIT_WEIGHT_KEY, MATURITY_FACTOR_KEY, *parts_grid.attribute_columns]
    parts_columns = [ROW_ID, *parts_visible]
    parts_df = pd.DataFrame(parts_grid.rows, columns=parts_columns)
    # Pin the weight columns to a numeric dtype so NumberColumn stays compatible even when
    # every current value is blank; keep text columns as object/string.
    for numeric_col in (UNIT_WEIGHT_KEY, MATURITY_FACTOR_KEY):
        parts_df[numeric_col] = pd.to_numeric(parts_df[numeric_col], errors="coerce")
    for text_col in ("part_number", "name", *parts_grid.attribute_columns):
        parts_df[text_col] = parts_df[text_col].astype("object")

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
        column_config=_parts_column_config(parts_grid.attribute_columns),
    )

    if not read_only:
        with st.expander("Add an attribute column"):
            with st.form(f"add_attr_col_{version}"):
                new_col = st.text_input("Column name", placeholder="material")
                if st.form_submit_button("Add column") and new_col.strip():
                    cols = st.session_state.setdefault(EXTRA_COLS_KEY, [])
                    if new_col.strip() not in cols:
                        cols.append(new_col.strip())
                    st.rerun()

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
        # Auto-append a whole-project version to history (deduped so identical saves add nothing).
        version_result = ctx.live_backend.snapshots.create_snapshot(deduplicate_if_identical=True)
        if not version_result.get("ok"):
            for err in version_result.get("errors", []):
                notes.append(f"History: {err}")

        for note in notes:
            st.info(note)
        if errors:
            st.error("Some changes could not be saved:")
            for err in errors:
                st.write(f"- {err}")
            # Keep the editor state so the user can fix and retry.
        else:
            st.session_state[GRID_VERSION_KEY] = version + 1
            st.session_state[EXTRA_COLS_KEY] = []
            st.success("Saved.")
            st.rerun()


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
