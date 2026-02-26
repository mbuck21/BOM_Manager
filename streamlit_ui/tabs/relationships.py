from __future__ import annotations

import json
from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import format_timestamp, parse_json_object, show_service_result


def _parse_attr_value(raw: str) -> Any:
    """Try to preserve numeric/bool types; fall back to string."""
    text = raw.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def _build_part_lookup(ctx: AppContext) -> dict[str, dict[str, Any]]:
    return {
        str(p.get("part_number", "")).strip(): p
        for p in ctx.parts
        if str(p.get("part_number", "")).strip()
    }


def _child_rel_label(rel: dict[str, Any], part_lookup: dict[str, dict[str, Any]]) -> str:
    child_pn = str(rel.get("child_part_number", "")).strip()
    child_name = part_lookup.get(child_pn, {}).get("name", "(missing)")
    qty = rel.get("qty", 0)
    rel_id = rel.get("rel_id", "")
    return f"{child_pn} — {child_name}  (qty: {qty})  [{rel_id}]"


def render_relationships_tab(ctx: AppContext, root_part_number: str = "") -> None:
    backend = ctx.live_backend
    if ctx.snapshot_mode:
        st.info("Snapshot mode is active. Edits run against live data.")

    selected_root = root_part_number.strip()
    part_lookup = _build_part_lookup(ctx)

    if not selected_root:
        st.warning("No root part selected. Use the sidebar directory to pick one.")
        _render_create_relationship(backend, "")
        return

    root_data = part_lookup.get(selected_root, {})
    root_name = root_data.get("name", "")

    # Safe key prefix so widgets reset when the selected root changes
    rk = "".join(c if c.isalnum() else "_" for c in selected_root)

    # ── Header ────────────────────────────────────────────────────────────────
    if root_name:
        st.subheader(f"Relationships — {selected_root} — {root_name}")
    else:
        st.subheader(f"Relationships — {selected_root}")

    # ── Gather child relationships ────────────────────────────────────────────
    child_rels: list[dict[str, Any]] = []
    for rel in ctx.relationships:
        if str(rel.get("parent_part_number", "")).strip() == selected_root:
            child_rels.append(rel)
    child_rels.sort(
        key=lambda r: (
            str(r.get("child_part_number", "")),
            str(r.get("rel_id", "")),
        )
    )

    # ── Children table ────────────────────────────────────────────────────────
    st.markdown("**Children of Root**")
    if child_rels:
        display_rows: list[dict[str, Any]] = []
        for rel in child_rels:
            child_pn = str(rel.get("child_part_number", "")).strip()
            child_info = part_lookup.get(child_pn, {})
            rel_attrs = rel.get("attributes", {})
            display_rows.append(
                {
                    "Rel ID": rel.get("rel_id", ""),
                    "Child Part": child_pn,
                    "Child Name": child_info.get("name", "(missing)"),
                    "Qty": float(rel.get("qty", 0)),
                    "Last Updated": format_timestamp(rel.get("last_updated", "—")),
                    "Attributes": json.dumps(rel_attrs, sort_keys=True) if rel_attrs else "{}",
                }
            )
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No children for this root part.")

    # ── Where used (parents of root) ──────────────────────────────────────────
    parent_rels: list[dict[str, Any]] = []
    for rel in ctx.relationships:
        if str(rel.get("child_part_number", "")).strip() == selected_root:
            parent_rels.append(rel)
    if parent_rels:
        parent_rels.sort(key=lambda r: str(r.get("parent_part_number", "")))
        st.markdown("**Where Used (Parents of Root)**")
        parent_rows: list[dict[str, Any]] = []
        for rel in parent_rels:
            parent_pn = str(rel.get("parent_part_number", "")).strip()
            parent_info = part_lookup.get(parent_pn, {})
            parent_rows.append(
                {
                    "Rel ID": rel.get("rel_id", ""),
                    "Parent Part": parent_pn,
                    "Parent Name": parent_info.get("name", "(missing)"),
                    "Qty": float(rel.get("qty", 0)),
                    "Last Updated": format_timestamp(rel.get("last_updated", "—")),
                }
            )
        st.dataframe(parent_rows, use_container_width=True, hide_index=True)

    st.divider()

    # ── Edit existing relationship ────────────────────────────────────────────
    if child_rels:
        with st.expander("Edit Relationship", expanded=False):
            fv = st.session_state.get("_rel_form_v", 0)
            rel_labels = [_child_rel_label(r, part_lookup) for r in child_rels]
            selected_idx = st.selectbox(
                "Select relationship",
                options=range(len(rel_labels)),
                format_func=lambda i: rel_labels[i],
                key=f"edit_rel_select_{rk}_{fv}",
            )
            sel_rel = child_rels[selected_idx]
            sel_rel_id = sel_rel.get("rel_id", "")
            sel_child_pn = str(sel_rel.get("child_part_number", "")).strip()
            sel_qty = float(sel_rel.get("qty", 1))
            sel_last_updated = sel_rel.get("last_updated", "—")
            sel_attrs = sel_rel.get("attributes", {})
            sorted_rel_attr_keys = sorted(sel_attrs.keys())

            with st.form(f"edit_rel_form_{rk}_{fv}"):
                info_col, qty_col = st.columns([2, 1])
                with info_col:
                    st.text_input("Relationship ID", value=sel_rel_id, disabled=True, key=f"erel_id_{rk}_{fv}")
                    st.text_input("Parent", value=selected_root, disabled=True, key=f"erel_parent_{rk}_{fv}")
                    st.text_input("Child", value=sel_child_pn, disabled=True, key=f"erel_child_{rk}_{fv}")
                with qty_col:
                    edit_qty = st.number_input(
                        "Quantity",
                        min_value=0.0001,
                        value=sel_qty,
                        step=1.0,
                        format="%.4f",
                        key=f"erel_qty_{rk}_{fv}",
                    )
                    st.caption(f"Last updated: {format_timestamp(sel_last_updated)}")

                if sorted_rel_attr_keys:
                    st.markdown("**Attributes**")
                    rel_attr_inputs: dict[str, str] = {}
                    attr_cols = st.columns(min(len(sorted_rel_attr_keys), 3))
                    for i, attr_key in enumerate(sorted_rel_attr_keys):
                        with attr_cols[i % len(attr_cols)]:
                            rel_attr_inputs[attr_key] = st.text_input(
                                attr_key,
                                value=str(sel_attrs[attr_key]),
                                key=f"erel_attr_{rk}_{attr_key}_{fv}",
                            )
                else:
                    rel_attr_inputs = {}

                submit_edit = st.form_submit_button("Save Relationship", use_container_width=True)

            if submit_edit:
                updated_attrs = {k: _parse_attr_value(v) for k, v in rel_attr_inputs.items()}
                result = backend.bom.add_or_update_relationship(
                    parent_part_number=selected_root,
                    child_part_number=sel_child_pn,
                    qty=edit_qty,
                    rel_id=sel_rel_id,
                    attributes=updated_attrs,
                    merge_attributes=False,
                )
                if result.get("ok"):
                    st.session_state["_rel_form_v"] = fv + 1
                    st.rerun()
                else:
                    show_service_result("Save relationship", result)

    # ── Add child relationship ────────────────────────────────────────────────
    _render_create_relationship(backend, selected_root, rk)

    # ── Delete relationship ───────────────────────────────────────────────────
    if child_rels:
        with st.expander("Delete Relationship"):
            del_labels = [_child_rel_label(r, part_lookup) for r in child_rels]
            del_idx = st.selectbox(
                "Select relationship to delete",
                options=range(len(del_labels)),
                format_func=lambda i: del_labels[i],
                key=f"delete_rel_select_{rk}",
            )
            if st.button("Delete Relationship", key=f"delete_rel_btn_{rk}", type="primary"):
                del_rel_id = child_rels[del_idx].get("rel_id", "")
                result = backend.bom.delete_relationship(del_rel_id)
                show_service_result("Delete relationship", result, show_data=True)
                if result.get("ok"):
                    st.rerun()


def _render_create_relationship(backend: Any, default_parent: str, root_key: str = "") -> None:
    with st.expander("Add Child Relationship", expanded=False):
        with st.form(f"rel_create_form_{root_key}"):
            col_parent, col_child = st.columns(2)
            with col_parent:
                parent_pn = st.text_input(
                    "Parent Part Number",
                    value=default_parent,
                    disabled=bool(default_parent),
                )
            with col_child:
                child_pn = st.text_input("Child Part Number", placeholder="B-200")

            col_qty, col_id = st.columns(2)
            with col_qty:
                qty = st.number_input(
                    "Quantity", min_value=0.0001, value=1.0, step=1.0, format="%.4f"
                )
            with col_id:
                rel_id = st.text_input("Relationship ID (optional)", placeholder="R-A-B-10")

            attrs_raw = st.text_area("Attributes (JSON)", value="{}", height=80)
            allow_dangling = st.checkbox("Allow dangling (child part not in catalog)", value=False)
            submit_create = st.form_submit_button("Add Relationship", use_container_width=True)

        if submit_create:
            try:
                rel_attrs = parse_json_object(attrs_raw, "Attributes JSON")
            except ValueError as exc:
                st.error(str(exc))
            else:
                result = backend.bom.add_or_update_relationship(
                    parent_part_number=parent_pn,
                    child_part_number=child_pn,
                    qty=qty,
                    rel_id=rel_id or None,
                    attributes=rel_attrs,
                    allow_dangling=allow_dangling,
                    merge_attributes=True,
                )
                show_service_result("Add relationship", result, show_data=True)
                if result.get("ok"):
                    st.rerun()
