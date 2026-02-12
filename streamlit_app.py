from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext, build_app_context
from streamlit_ui.helpers import resolve_data_dir
from streamlit_ui.tabs import (
    render_analysis_tab,
    render_csv_tab,
    render_dashboard_tab,
    render_parts_tab,
    render_relationships_tab,
    render_weight_analysis_tab,
)

LIVE_DATA_OPTION = "__live_data__"
ACTIVE_SNAPSHOT_ID_KEY = "active_snapshot_id"
SNAPSHOT_SELECTION_INITIALIZED_KEY = "snapshot_selection_initialized"
SNAPSHOT_SELECTION_DATA_DIR_KEY = "snapshot_selection_data_dir"


def render_sidebar() -> Path:
    default_data_dir = st.session_state.get("data_dir", "demo_data")
    entered_data_dir = st.sidebar.text_input("Data directory", value=default_data_dir)
    st.session_state["data_dir"] = entered_data_dir
    data_dir = resolve_data_dir(entered_data_dir)

    repo_root = Path.cwd().resolve()
    st.sidebar.caption(f"Resolved path: `{data_dir}`")
    st.sidebar.code("streamlit run streamlit_app.py", language="bash")

    if st.sidebar.button("Reset Data Directory", key="reset_data_dir_btn"):
        if data_dir == repo_root:
            st.sidebar.error("Refusing to delete repository root.")
        elif repo_root not in data_dir.parents:
            st.sidebar.error("Reset is only allowed for directories inside this repository.")
        else:
            if data_dir.exists():
                shutil.rmtree(data_dir)
            st.sidebar.success(f"Cleared {data_dir}")
            st.rerun()

    return data_dir


def _snapshot_option_label(snapshot: dict[str, Any], latest_snapshot_id: str | None) -> str:
    snapshot_id = str(snapshot.get("snapshot_id", "")).strip()
    root_part_number = str(snapshot.get("root_part_number", "")).strip() or "(none)"
    created_at = str(snapshot.get("created_at", "")).strip() or "(unknown time)"
    label = str(snapshot.get("label", "")).strip()
    label_suffix = f" | label: {label}" if label else ""
    latest_suffix = " | latest" if snapshot_id == latest_snapshot_id else ""
    return f"{snapshot_id} | root: {root_part_number} | {created_at}{label_suffix}{latest_suffix}"


def render_snapshot_selector(ctx: AppContext) -> None:
    st.sidebar.divider()
    st.sidebar.subheader("Snapshot View")

    if not ctx.snapshots:
        st.sidebar.info("No snapshots found. Using live data.")
        return

    snapshot_lookup = {
        str(snapshot.get("snapshot_id", "")).strip(): snapshot
        for snapshot in ctx.snapshots
        if str(snapshot.get("snapshot_id", "")).strip()
    }
    snapshot_ids = [snapshot_id for snapshot_id in reversed(list(snapshot_lookup.keys()))]
    option_ids = [LIVE_DATA_OPTION] + snapshot_ids
    current_option = ctx.loaded_snapshot_id or LIVE_DATA_OPTION
    if current_option not in option_ids:
        current_option = LIVE_DATA_OPTION

    selected_option = st.sidebar.selectbox(
        "Loaded dataset",
        options=option_ids,
        index=option_ids.index(current_option),
        format_func=lambda option_id: (
            "Live Data (current repository state)"
            if option_id == LIVE_DATA_OPTION
            else _snapshot_option_label(snapshot_lookup[option_id], ctx.latest_snapshot_id)
        ),
    )

    selected_snapshot_id = None if selected_option == LIVE_DATA_OPTION else selected_option
    if selected_snapshot_id != ctx.loaded_snapshot_id:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = selected_snapshot_id
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = True
        st.rerun()

    if ctx.loaded_snapshot_id:
        latest_flag = "Yes" if ctx.is_latest_snapshot_loaded else "No"
        st.sidebar.caption(f"Loaded snapshot: `{ctx.loaded_snapshot_id}`")
        st.sidebar.caption(f"Is latest: `{latest_flag}`")
        if ctx.latest_snapshot_id and ctx.latest_snapshot_id != ctx.loaded_snapshot_id:
            st.sidebar.caption(f"Latest available: `{ctx.latest_snapshot_id}`")
    else:
        st.sidebar.caption("Loaded snapshot: `None (live data)`")
        if ctx.latest_snapshot_id:
            st.sidebar.caption(f"Latest available: `{ctx.latest_snapshot_id}`")


def render_metrics(parts_count: int, relationships_count: int, snapshots_count: int) -> None:
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Parts", parts_count)
    metric_col2.metric("Relationships", relationships_count)
    metric_col3.metric("Snapshots", snapshots_count)


def main() -> None:
    st.title("BOM Manager Demo Frontend")
    st.caption("Interactive Streamlit client for parts, relationships, rollups, snapshots, and CSV workflows.")

    data_dir = render_sidebar()
    data_dir_marker = str(data_dir.resolve())
    if st.session_state.get(SNAPSHOT_SELECTION_DATA_DIR_KEY) != data_dir_marker:
        st.session_state[SNAPSHOT_SELECTION_DATA_DIR_KEY] = data_dir_marker
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = False
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = None

    selection_initialized = bool(st.session_state.get(SNAPSHOT_SELECTION_INITIALIZED_KEY, False))
    selected_snapshot_id = st.session_state.get(ACTIVE_SNAPSHOT_ID_KEY)
    ctx = build_app_context(
        data_dir,
        selected_snapshot_id=selected_snapshot_id,
        default_to_latest=not selection_initialized,
    )

    if not selection_initialized:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = ctx.loaded_snapshot_id
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = True
    elif selected_snapshot_id != ctx.loaded_snapshot_id:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = ctx.loaded_snapshot_id

    render_snapshot_selector(ctx)

    if ctx.loaded_snapshot_id:
        latest_flag = "Yes" if ctx.is_latest_snapshot_loaded else "No"
        st.caption(f"Loaded snapshot: `{ctx.loaded_snapshot_id}` | Is latest: `{latest_flag}`")
    else:
        st.caption("Loaded snapshot: `None (live data)`")

    render_metrics(
        parts_count=len(ctx.parts),
        relationships_count=len(ctx.relationships),
        snapshots_count=len(ctx.snapshots),
    )

    tab_dashboard, tab_parts, tab_relationships, tab_analysis, tab_weight, tab_csv = st.tabs(
        ["Dashboard", "Parts", "Relationships", "Analysis", "Weight Analysis", "CSV"]
    )

    with tab_dashboard:
        render_dashboard_tab(ctx)

    with tab_parts:
        render_parts_tab(ctx)

    with tab_relationships:
        render_relationships_tab(ctx)

    with tab_analysis:
        render_analysis_tab(ctx)

    with tab_weight:
        render_weight_analysis_tab(ctx)

    with tab_csv:
        render_csv_tab(ctx)


if __name__ == "__main__":
    main()
