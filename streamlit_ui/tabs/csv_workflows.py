from __future__ import annotations

from pathlib import Path

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import parse_csv_whitelist, save_uploaded_csv, show_service_result


def render_csv_tab(ctx: AppContext) -> None:
    backend = ctx.live_backend
    if ctx.snapshot_mode:
        st.info("Snapshot mode is active. CSV import/export operations are running against live data.")

    st.subheader("CSV Export")
    export_col_a, export_col_b = st.columns(2)

    with export_col_a:
        with st.form("export_parts_form"):
            export_parts_path = st.text_input(
                "Parts export path",
                value=str(ctx.data_dir / "exports" / "parts_export.csv"),
            )
            parts_whitelist_raw = st.text_input(
                "Parts attribute whitelist (comma-separated)",
                value="weight_kg,material,cost_usd",
            )
            parts_include_json = st.checkbox("Include attributes_json", value=True)
            submit_export_parts = st.form_submit_button("Export Parts CSV")

        if submit_export_parts:
            export_result = backend.csv.export_parts_csv(
                csv_path=Path(export_parts_path),
                attribute_whitelist=parse_csv_whitelist(parts_whitelist_raw),
                include_attributes_json=parts_include_json,
            )
            show_service_result("Export parts CSV", export_result, show_data=True)

    with export_col_b:
        with st.form("export_relationships_form"):
            export_rels_path = st.text_input(
                "Relationships export path",
                value=str(ctx.data_dir / "exports" / "relationships_export.csv"),
            )
            rels_whitelist_raw = st.text_input(
                "Relationship attribute whitelist (comma-separated)",
                value="find_number,note",
            )
            rels_include_json = st.checkbox("Include attributes_json", value=True)
            submit_export_rels = st.form_submit_button("Export Relationships CSV")

        if submit_export_rels:
            export_result = backend.csv.export_relationships_csv(
                csv_path=Path(export_rels_path),
                attribute_whitelist=parse_csv_whitelist(rels_whitelist_raw),
                include_attributes_json=rels_include_json,
            )
            show_service_result("Export relationships CSV", export_result, show_data=True)

    st.divider()
    st.subheader("CSV Import")
    import_col_a, import_col_b = st.columns(2)

    with import_col_a:
        uploaded_parts_csv = st.file_uploader("Upload parts CSV", type=["csv"], key="parts_csv_upload")
        merge_parts_attributes = st.checkbox("Merge imported part attributes", value=True)
        if st.button("Import Parts CSV", key="import_parts_csv_btn"):
            if uploaded_parts_csv is None:
                st.error("Choose a CSV file first.")
            else:
                csv_path = save_uploaded_csv(ctx.data_dir, "parts", uploaded_parts_csv)
                import_result = backend.csv.import_parts_csv(
                    csv_path=csv_path,
                    merge_attributes=merge_parts_attributes,
                )
                show_service_result("Import parts CSV", import_result, show_data=True)

    with import_col_b:
        uploaded_relationships_csv = st.file_uploader(
            "Upload relationships CSV",
            type=["csv"],
            key="relationships_csv_upload",
        )
        allow_dangling_csv = st.checkbox("Allow dangling relationships", value=False)
        merge_rel_csv_attributes = st.checkbox("Merge imported relationship attributes", value=True)
        if st.button("Import Relationships CSV", key="import_relationships_csv_btn"):
            if uploaded_relationships_csv is None:
                st.error("Choose a CSV file first.")
            else:
                csv_path = save_uploaded_csv(ctx.data_dir, "relationships", uploaded_relationships_csv)
                import_result = backend.csv.import_relationships_csv(
                    csv_path=csv_path,
                    allow_dangling=allow_dangling_csv,
                    merge_attributes=merge_rel_csv_attributes,
                )
                show_service_result("Import relationships CSV", import_result, show_data=True)
