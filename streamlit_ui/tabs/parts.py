from __future__ import annotations

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import parse_json_object, part_rows, show_service_result


def render_parts_tab(ctx: AppContext) -> None:
    backend = ctx.live_backend
    if ctx.snapshot_mode:
        st.info("Snapshot mode is active. Parts tab edits and searches are running against live data.")

    st.subheader("Add or Update Part")
    with st.form("part_upsert_form"):
        part_number = st.text_input("Part number", placeholder="A-100")
        name = st.text_input("Part name", placeholder="Top Assembly")
        attributes_raw = st.text_area(
            "Attributes JSON",
            value='{"weight_kg": 12.0, "material": "Aluminum"}',
            height=120,
        )
        merge_attributes = st.checkbox("Merge with existing attributes", value=True)
        submit_part = st.form_submit_button("Save Part")

    if submit_part:
        try:
            attributes = parse_json_object(attributes_raw, "Attributes JSON")
        except ValueError as exc:
            st.error(str(exc))
        else:
            result = backend.parts.add_or_update_part(
                part_number=part_number,
                name=name,
                attributes=attributes,
                merge_attributes=merge_attributes,
            )
            show_service_result("Save part", result, show_data=True)

    st.divider()
    st.subheader("Delete Part")
    with st.form("part_delete_form"):
        delete_part_number = st.text_input("Part number to delete", placeholder="A-100")
        allow_if_referenced = st.checkbox("Allow delete even if referenced", value=False)
        submit_delete_part = st.form_submit_button("Delete Part")

    if submit_delete_part:
        result = backend.parts.delete_part(
            part_number=delete_part_number,
            allow_if_referenced=allow_if_referenced,
        )
        show_service_result("Delete part", result, show_data=True)

    st.divider()
    st.subheader("Search Parts")
    part_query = st.text_input("Search by part number or name", key="part_search_query")
    query_result = backend.parts.list_parts(query=part_query or None)
    if query_result.get("ok"):
        st.dataframe(
            part_rows(query_result["data"]["parts"]),
            width="stretch",
            hide_index=True,
        )
    else:
        show_service_result("Search parts", query_result)
