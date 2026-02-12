from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import show_service_result


def _breakdown_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for item in rows:
        formatted.append(
            {
                "part_number": item["part_number"],
                "path": " -> ".join(item.get("path", [])),
                "multiplier": item["multiplier"],
                "unit_weight": item["unit_weight"],
                "maturity_factor": item["maturity_factor"],
                "effective_unit_weight": item["effective_unit_weight"],
                "contribution": item["contribution"],
            }
        )
    return formatted


def _opportunity_rows(part_totals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in part_totals:
        total_contribution = float(item.get("total_contribution", 0.0))
        rows.append(
            {
                "part_number": item["part_number"],
                "total_contribution": total_contribution,
                "occurrences": item.get("occurrences", 0),
                "savings_if_reduced_1pct": total_contribution * 0.01,
                "savings_if_reduced_5pct": total_contribution * 0.05,
            }
        )
    return rows


def render_weight_analysis_tab(ctx: AppContext) -> None:
    if ctx.snapshot_mode:
        st.info("Snapshot mode is active. Weight analysis is running against the loaded snapshot data.")

    st.subheader("Weight Analysis")
    st.caption(
        "Uses unit-weight override logic: when a node has unit weight, children below that node are "
        "excluded from rollup for that path."
    )

    with st.form("weight_analysis_form"):
        root_part_number = st.text_input("Root part", value="A-100")
        unit_weight_key = st.text_input("Unit weight attribute key", value="unit_weight")
        maturity_factor_key = st.text_input("Maturity factor attribute key", value="maturity_factor")
        default_maturity_factor = st.number_input(
            "Default maturity factor",
            min_value=0.01,
            value=1.0,
            step=0.01,
            format="%.2f",
        )
        include_root = st.checkbox("Include root part contribution", value=True)
        top_n = st.number_input(
            "Top contributors to show",
            min_value=1,
            value=10,
            step=1,
        )
        submit = st.form_submit_button("Run Weight Analysis")

    if not submit:
        return

    result = ctx.backend.rollups.rollup_weight_with_maturity(
        root_part_number=root_part_number,
        unit_weight_key=unit_weight_key,
        maturity_factor_key=maturity_factor_key,
        default_maturity_factor=default_maturity_factor,
        include_root=include_root,
        top_n=int(top_n),
    )
    show_service_result("Weight analysis", result)

    if not result.get("ok"):
        return

    data = result["data"]

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Total Effective Weight", f"{data['total']:.4f}")
    metric_col2.metric("Weighted Contributions", len(data.get("breakdown", [])))
    metric_col3.metric("Unresolved Nodes", len(data.get("unresolved_nodes", [])))

    st.markdown("**Top Contributors**")
    st.dataframe(data.get("top_contributors", []), width="stretch", hide_index=True)

    st.markdown("**Reduction Opportunity (Simple What-If)**")
    st.dataframe(
        _opportunity_rows(data.get("part_totals", [])),
        width="stretch",
        hide_index=True,
    )

    st.markdown("**Path Breakdown**")
    st.dataframe(
        _breakdown_rows(data.get("breakdown", [])),
        width="stretch",
        hide_index=True,
    )

    if data.get("unresolved_nodes"):
        st.markdown("**Unresolved Nodes**")
        st.dataframe(data["unresolved_nodes"], width="stretch", hide_index=True)
