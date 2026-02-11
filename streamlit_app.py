from __future__ import annotations

import shutil
from pathlib import Path

import streamlit as st

from streamlit_ui.context import build_app_context
from streamlit_ui.helpers import resolve_data_dir
from streamlit_ui.tabs import (
    render_analysis_tab,
    render_csv_tab,
    render_dashboard_tab,
    render_parts_tab,
    render_relationships_tab,
    render_weight_analysis_tab,
)
from streamlit_ui.theme import configure_page


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


def render_metrics(parts_count: int, relationships_count: int, snapshots_count: int) -> None:
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Parts", parts_count)
    metric_col2.metric("Relationships", relationships_count)
    metric_col3.metric("Snapshots", snapshots_count)


def main() -> None:
    configure_page()
    st.title("BOM Manager Demo Frontend")
    st.caption("Interactive Streamlit client for parts, relationships, rollups, snapshots, and CSV workflows.")

    data_dir = render_sidebar()
    ctx = build_app_context(data_dir)

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
