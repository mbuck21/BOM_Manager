from __future__ import annotations

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import parse_json_object, show_service_result


def render_relationships_tab(ctx: AppContext) -> None:
    st.subheader("Add or Update Relationship")
    with st.form("relationship_upsert_form"):
        parent_part_number = st.text_input("Parent part number", value="A-100")
        child_part_number = st.text_input("Child part number", value="B-200")
        qty = st.number_input("Quantity", min_value=0.0001, value=1.0, step=1.0, format="%.4f")
        rel_id = st.text_input("Relationship ID (optional)", placeholder="R-A-B-10")
        rel_attributes_raw = st.text_area(
            "Relationship attributes JSON",
            value='{"find_number": "10"}',
            height=100,
        )
        allow_dangling = st.checkbox("Allow dangling relationships", value=False)
        merge_rel_attributes = st.checkbox("Merge with existing attributes", value=True)
        submit_relationship = st.form_submit_button("Save Relationship")

    if submit_relationship:
        try:
            rel_attributes = parse_json_object(rel_attributes_raw, "Relationship attributes JSON")
        except ValueError as exc:
            st.error(str(exc))
        else:
            result = ctx.backend.bom.add_or_update_relationship(
                parent_part_number=parent_part_number,
                child_part_number=child_part_number,
                qty=qty,
                rel_id=rel_id or None,
                attributes=rel_attributes,
                allow_dangling=allow_dangling,
                merge_attributes=merge_rel_attributes,
            )
            show_service_result("Save relationship", result, show_data=True)

    st.divider()
    st.subheader("Delete Relationship")
    with st.form("relationship_delete_form"):
        delete_rel_id = st.text_input("Relationship ID to delete", placeholder="R-A-B-10")
        submit_delete_relationship = st.form_submit_button("Delete Relationship")

    if submit_delete_relationship:
        result = ctx.backend.bom.delete_relationship(delete_rel_id)
        show_service_result("Delete relationship", result, show_data=True)

    st.divider()
    st.subheader("Children and Parents Lookup")
    lookup_col_a, lookup_col_b = st.columns(2)
    with lookup_col_a:
        lookup_parent = st.text_input("Get children for parent", value="A-100")
        if st.button("Load Children", key="load_children_btn"):
            children_result = ctx.backend.bom.get_children(lookup_parent)
            show_service_result("Get children", children_result)
            if children_result.get("ok"):
                rows = []
                for item in children_result["data"]["children"]:
                    relationship = item["relationship"]
                    rows.append(
                        {
                            "rel_id": relationship["rel_id"],
                            "parent": relationship["parent_part_number"],
                            "child": relationship["child_part_number"],
                            "qty": relationship["qty"],
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)

    with lookup_col_b:
        lookup_child = st.text_input("Get parents for child", value="B-200")
        if st.button("Load Parents", key="load_parents_btn"):
            parents_result = ctx.backend.bom.get_parents(lookup_child)
            show_service_result("Get parents", parents_result)
            if parents_result.get("ok"):
                rows = []
                for item in parents_result["data"]["parents"]:
                    relationship = item["relationship"]
                    rows.append(
                        {
                            "rel_id": relationship["rel_id"],
                            "parent": relationship["parent_part_number"],
                            "child": relationship["child_part_number"],
                            "qty": relationship["qty"],
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
