from __future__ import annotations

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.graph import build_bom_graph_dot
from streamlit_ui.helpers import part_rows, relationship_rows, show_service_result
from streamlit_ui.seed import seed_demo_data


def render_dashboard_tab(ctx: AppContext) -> None:
    st.subheader("Quick Demo Actions")
    if st.button("Seed Sample Data", key="seed_demo_data_btn"):
        for action_name, action_result in seed_demo_data(ctx.backend):
            show_service_result(action_name, action_result)

    st.divider()
    st.subheader("BOM Connection Graph")
    max_graph_nodes = st.slider(
        "Max displayed nodes",
        min_value=5,
        max_value=80,
        value=25,
        step=1,
        key="dashboard_graph_node_cap",
    )
    graph_data = build_bom_graph_dot(ctx.parts, ctx.relationships, max_nodes=max_graph_nodes)
    st.graphviz_chart(graph_data["dot"], use_container_width=True)
    st.caption(
        f"Showing {graph_data['shown_nodes']} of {graph_data['total_nodes']} nodes and "
        f"{graph_data['shown_edges']} of {graph_data['total_edges']} relationships."
    )

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Parts**")
        if ctx.parts_result.get("ok"):
            st.dataframe(part_rows(ctx.parts), use_container_width=True, hide_index=True)
        else:
            show_service_result("List parts", ctx.parts_result)

    with col_b:
        st.markdown("**Relationships**")
        st.dataframe(relationship_rows(ctx.relationships), use_container_width=True, hide_index=True)
