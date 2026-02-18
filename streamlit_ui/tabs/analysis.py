from __future__ import annotations

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import part_rows, relationship_rows, show_service_result


def render_analysis_tab(ctx: AppContext, root_part_number: str) -> None:
    analysis_backend = ctx.backend
    snapshot_backend = ctx.live_backend
    selected_root = root_part_number.strip()
    if ctx.snapshot_mode:
        st.info(
            "Snapshot mode is active. Subgraph/Rollup use the loaded snapshot data; "
            "snapshot create/list/diff use live snapshot storage."
        )

    st.subheader("Subgraph Explorer")
    st.caption(f"Root from sidebar: `{selected_root or '(none selected)'}`")
    if st.button("Load Subgraph", key="load_subgraph_btn", disabled=not selected_root):
        subgraph_result = analysis_backend.bom.get_subgraph(selected_root)
        show_service_result("Get subgraph", subgraph_result)
        if subgraph_result.get("ok"):
            st.markdown("**Subgraph Parts**")
            st.dataframe(part_rows(subgraph_result["data"]["parts"]), width="stretch", hide_index=True)
            st.markdown("**Subgraph Relationships**")
            st.dataframe(
                relationship_rows(subgraph_result["data"]["relationships"]),
                width="stretch",
                hide_index=True,
            )

    st.divider()
    st.subheader("Rollup")
    with st.form("rollup_form"):
        st.caption(f"Root from sidebar: `{selected_root or '(none selected)'}`")
        rollup_attribute = st.text_input("Numeric attribute key", value="weight_kg")
        include_root = st.checkbox("Include root part contribution", value=True)
        submit_rollup = st.form_submit_button("Run Rollup", disabled=not selected_root)

    if submit_rollup:
        rollup_result = analysis_backend.rollups.rollup_numeric_attribute(
            root_part_number=selected_root,
            attribute_key=rollup_attribute,
            include_root=include_root,
        )
        show_service_result("Rollup attribute", rollup_result)
        if rollup_result.get("ok"):
            st.metric("Total", f"{rollup_result['data']['total']:.4f}")
            st.dataframe(rollup_result["data"]["breakdown"], width="stretch", hide_index=True)

    st.divider()
    st.subheader("Snapshots")
    create_col, list_col = st.columns([1, 1.2])

    with create_col:
        with st.form("snapshot_create_form"):
            st.caption(f"Root from sidebar: `{selected_root or '(none selected)'}`")
            snapshot_label = st.text_input("Snapshot label", placeholder="baseline")
            deduplicate = st.checkbox("Deduplicate if identical", value=True)
            submit_snapshot = st.form_submit_button("Create Snapshot", disabled=not selected_root)

        if submit_snapshot:
            create_result = snapshot_backend.snapshots.create_snapshot(
                root_part_number=selected_root,
                label=snapshot_label or None,
                deduplicate_if_identical=deduplicate,
            )
            show_service_result("Create snapshot", create_result, show_data=True)

    with list_col:
        use_sidebar_root_filter = st.checkbox(
            "Filter list to sidebar root",
            value=True,
            key="snapshot_filter_use_sidebar_root",
        )
        manual_snapshot_filter = ""
        if not use_sidebar_root_filter:
            manual_snapshot_filter = st.text_input("Filter by root part (optional)", key="snapshot_filter")
        snapshot_filter = selected_root if use_sidebar_root_filter else manual_snapshot_filter.strip()
        if use_sidebar_root_filter and not selected_root:
            st.caption("No root selected. Listing all snapshots.")
        filtered_snapshots = snapshot_backend.snapshots.list_snapshots(
            root_part_number=snapshot_filter or None
        )
        if filtered_snapshots.get("ok"):
            st.dataframe(
                [
                    {
                        "snapshot_id": item["snapshot_id"],
                        "root_part_number": item["root_part_number"],
                        "created_at": item["created_at"],
                        "label": item.get("label"),
                    }
                    for item in filtered_snapshots["data"]["snapshots"]
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            show_service_result("List snapshots", filtered_snapshots)

    st.divider()
    st.subheader("Compare Snapshots")
    latest_snapshots_result = snapshot_backend.snapshots.list_snapshots()
    if latest_snapshots_result.get("ok"):
        latest_snapshots = latest_snapshots_result["data"]["snapshots"]
        if len(latest_snapshots) < 2:
            st.info("Create at least two snapshots to run a diff.")
        else:
            snapshot_labels = [
                f"{item['snapshot_id']} | {item['root_part_number']} | {item['created_at']}"
                for item in latest_snapshots
            ]
            default_a = max(0, len(snapshot_labels) - 2)
            default_b = max(0, len(snapshot_labels) - 1)
            selection_a = st.selectbox("Snapshot A", options=snapshot_labels, index=default_a)
            selection_b = st.selectbox("Snapshot B", options=snapshot_labels, index=default_b)

            map_label_to_id = {
                label: snapshot["snapshot_id"]
                for label, snapshot in zip(snapshot_labels, latest_snapshots)
            }
            if st.button("Run Snapshot Diff", key="run_snapshot_diff_btn"):
                compare_result = snapshot_backend.diff.compare_snapshots(
                    map_label_to_id[selection_a],
                    map_label_to_id[selection_b],
                )
                show_service_result("Compare snapshots", compare_result)
                if compare_result.get("ok"):
                    data = compare_result["data"]
                    diff_col_1, diff_col_2, diff_col_3 = st.columns(3)
                    diff_col_1.metric("Part Changes", len(data["part_changes"]["modified"]))
                    diff_col_2.metric("Relationship Changes", len(data["relationship_changes"]["modified"]))
                    diff_col_3.metric("Signatures Equal", "Yes" if data["signature_equal"] else "No")
                    st.json(data)
    else:
        show_service_result("List snapshots", latest_snapshots_result)
