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


def render_parts_tab(ctx: AppContext, root_part_number: str = "") -> None:
    backend = ctx.live_backend
    if ctx.snapshot_mode:
        st.info("Snapshot mode is active. Edits run against live data.")

    selected_root = root_part_number.strip()
    part_lookup = _build_part_lookup(ctx)

    if not selected_root:
        st.warning("No root part selected. Use the sidebar directory to pick one.")
        _render_create_part(backend)
        return

    root_data = part_lookup.get(selected_root, {})
    root_name = root_data.get("name", "")
    root_last_updated = root_data.get("last_updated", "—")

    # Safe key prefix so widgets reset when the selected root changes
    rk = "".join(c if c.isalnum() else "_" for c in selected_root)

    # ── Header ────────────────────────────────────────────────────────────────
    header_col, ts_col = st.columns([3, 1])
    with header_col:
        if root_name:
            st.subheader(f"{selected_root} — {root_name}")
        else:
            st.subheader(f"{selected_root}")
    with ts_col:
        st.caption(f"Last updated: {format_timestamp(root_last_updated)}")

    # ── Part detail / edit ────────────────────────────────────────────────────
    existing_attrs = root_data.get("attributes", {})
    sorted_attr_keys = sorted(existing_attrs.keys())
    fv = st.session_state.get("_part_form_v", 0)

    with st.form(f"root_part_edit_form_{rk}_{fv}"):
        col_pn, col_name = st.columns(2)
        with col_pn:
            st.text_input("Part Number", value=selected_root, disabled=True, key=f"root_pn_{rk}_{fv}")
        with col_name:
            edit_name = st.text_input("Name", value=root_name, key=f"root_name_{rk}_{fv}")

        # Attribute editing in columns
        if sorted_attr_keys:
            st.markdown("**Attributes**")
            attr_inputs: dict[str, str] = {}
            attr_cols = st.columns(min(len(sorted_attr_keys), 3))
            for i, attr_key in enumerate(sorted_attr_keys):
                with attr_cols[i % len(attr_cols)]:
                    attr_inputs[attr_key] = st.text_input(
                        attr_key,
                        value=str(existing_attrs[attr_key]),
                        key=f"root_attr_{rk}_{attr_key}_{fv}",
                    )
        else:
            attr_inputs = {}

        save_col, _ = st.columns([1, 3])
        with save_col:
            submit_edit = st.form_submit_button("Save Changes", use_container_width=True)

    if submit_edit:
        updated_attrs = {k: _parse_attr_value(v) for k, v in attr_inputs.items()}
        result = backend.parts.add_or_update_part(
            part_number=selected_root,
            name=edit_name,
            attributes=updated_attrs,
            merge_attributes=False,
        )
        if result.get("ok"):
            st.session_state["_part_form_v"] = fv + 1
            st.rerun()
        else:
            show_service_result("Save part", result)

    # ── Add / Remove attributes ───────────────────────────────────────────────
    with st.expander("Manage Attributes"):
        add_col, remove_col = st.columns(2)
        with add_col:
            with st.form(f"attr_add_form_{rk}_{fv}"):
                st.markdown("**Add Attribute**")
                new_key = st.text_input("Key", placeholder="material", key=f"attr_add_key_{rk}_{fv}")
                new_val = st.text_input("Value", placeholder="Aluminum", key=f"attr_add_val_{rk}_{fv}")
                submit_add = st.form_submit_button("Add Attribute")

            if submit_add:
                key = new_key.strip()
                if not key:
                    st.error("Key cannot be empty.")
                else:
                    result = backend.parts.update_attributes(
                        part_number=selected_root,
                        attributes={key: _parse_attr_value(new_val)},
                        merge_attributes=True,
                    )
                    if result.get("ok"):
                        st.session_state["_part_form_v"] = fv + 1
                        st.rerun()
                    else:
                        show_service_result("Add attribute", result)

        with remove_col:
            st.markdown("**Remove Attribute**")
            if sorted_attr_keys:
                for ak in sorted_attr_keys:
                    st.caption(f"`{ak}`: {existing_attrs[ak]}")
                with st.form(f"attr_remove_form_{rk}_{fv}"):
                    keys_to_remove = st.multiselect(
                        "Select attributes to remove",
                        options=sorted_attr_keys,
                        key=f"attr_remove_select_{rk}_{fv}",
                    )
                    submit_remove = st.form_submit_button("Remove Selected")

                if submit_remove and keys_to_remove:
                    keep = {k: v for k, v in existing_attrs.items() if k not in keys_to_remove}
                    result = backend.parts.add_or_update_part(
                        part_number=selected_root,
                        name=root_name,
                        attributes=keep,
                        merge_attributes=False,
                    )
                    if result.get("ok"):
                        st.session_state["_part_form_v"] = fv + 1
                        st.rerun()
                    else:
                        show_service_result("Remove attributes", result)
            else:
                st.caption("No attributes to remove.")

    st.divider()

    # ── Children overview ─────────────────────────────────────────────────────
    st.markdown("**Direct Children**")
    child_rows: list[dict[str, Any]] = []
    for rel in ctx.relationships:
        if str(rel.get("parent_part_number", "")).strip() == selected_root:
            child_pn = str(rel.get("child_part_number", "")).strip()
            child_info = part_lookup.get(child_pn, {})
            child_attrs = child_info.get("attributes", {})
            child_rows.append(
                {
                    "Part Number": child_pn,
                    "Name": child_info.get("name", "(missing)"),
                    "Qty": float(rel.get("qty", 0)),
                    "Last Updated": format_timestamp(child_info.get("last_updated", "—")),
                    "Attributes": json.dumps(child_attrs, sort_keys=True) if child_attrs else "{}",
                }
            )
    child_rows.sort(key=lambda r: r["Part Number"])
    if child_rows:
        st.dataframe(child_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No direct children for this part.")

    # ── Where used (parents) ──────────────────────────────────────────────────
    parent_rows: list[dict[str, Any]] = []
    for rel in ctx.relationships:
        if str(rel.get("child_part_number", "")).strip() == selected_root:
            parent_pn = str(rel.get("parent_part_number", "")).strip()
            parent_info = part_lookup.get(parent_pn, {})
            parent_rows.append(
                {
                    "Parent Part Number": parent_pn,
                    "Parent Name": parent_info.get("name", "(missing)"),
                    "Qty": float(rel.get("qty", 0)),
                }
            )
    if parent_rows:
        parent_rows.sort(key=lambda r: r["Parent Part Number"])
        st.markdown("**Where Used (Parents)**")
        st.dataframe(parent_rows, use_container_width=True, hide_index=True)

    st.divider()

    # ── Quick create / Delete / Search ────────────────────────────────────────
    _render_create_part(backend)

    with st.expander("Delete Part"):
        with st.form("part_delete_form"):
            delete_pn = st.text_input("Part number to delete", placeholder="A-100")
            allow_ref = st.checkbox("Allow delete even if referenced", value=False)
            submit_del = st.form_submit_button("Delete Part")

        if submit_del:
            result = backend.parts.delete_part(
                part_number=delete_pn,
                allow_if_referenced=allow_ref,
            )
            show_service_result("Delete part", result, show_data=True)
            if result.get("ok"):
                st.rerun()

    with st.expander("Search All Parts"):
        query = st.text_input("Search by part number or name", key="part_search_q")
        query_result = backend.parts.list_parts(query=query or None)
        if query_result.get("ok"):
            rows = []
            for item in query_result["data"]["parts"]:
                rows.append(
                    {
                        "Part Number": item["part_number"],
                        "Name": item["name"],
                        "Last Updated": format_timestamp(item.get("last_updated", "—")),
                        "Attributes": json.dumps(item.get("attributes", {}), sort_keys=True),
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            show_service_result("Search parts", query_result)


def _render_create_part(backend: Any) -> None:
    with st.expander("Create New Part", expanded=False):
        with st.form("part_create_form"):
            col_pn, col_name = st.columns(2)
            with col_pn:
                new_pn = st.text_input("Part Number", placeholder="A-100")
            with col_name:
                new_name = st.text_input("Name", placeholder="Top Assembly")
            attrs_raw = st.text_area(
                "Attributes (JSON)",
                value='{"unit_weight": 0.0, "material": ""}',
                height=80,
            )
            merge = st.checkbox("Merge with existing attributes if part exists", value=True)
            submit_create = st.form_submit_button("Create Part", use_container_width=True)

        if submit_create:
            try:
                attributes = parse_json_object(attrs_raw, "Attributes JSON")
            except ValueError as exc:
                st.error(str(exc))
            else:
                result = backend.parts.add_or_update_part(
                    part_number=new_pn,
                    name=new_name,
                    attributes=attributes,
                    merge_attributes=merge,
                )
                show_service_result("Create part", result, show_data=True)
                if result.get("ok"):
                    st.rerun()
