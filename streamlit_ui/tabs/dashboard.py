from __future__ import annotations

from collections import defaultdict
from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import show_service_result


def _find_default_root(parts: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> str:
    indegree: dict[str, int] = defaultdict(int)
    nodes: set[str] = set()
    for relationship in relationships:
        parent = str(relationship.get("parent_part_number", "")).strip()
        child = str(relationship.get("child_part_number", "")).strip()
        if not parent or not child:
            continue
        nodes.add(parent)
        nodes.add(child)
        indegree[parent] += 0
        indegree[child] += 1

    root_candidates = sorted(node for node in nodes if indegree.get(node, 0) == 0)
    if root_candidates:
        return root_candidates[0]

    if parts:
        return str(parts[0].get("part_number", "")).strip()
    return ""


def _child_rows(
    root_part_number: str,
    relationships: list[dict[str, Any]],
    part_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relationship in relationships:
        if relationship.get("parent_part_number") != root_part_number:
            continue
        child_number = str(relationship.get("child_part_number", "")).strip()
        child = part_lookup.get(child_number)
        rows.append(
            {
                "rel_id": relationship.get("rel_id"),
                "child_part_number": child_number,
                "child_name": (child or {}).get("name", "(missing)"),
                "qty": float(relationship.get("qty", 0)),
            }
        )
    rows.sort(key=lambda row: (row["child_part_number"], row["rel_id"] or ""))
    return rows


def _direct_child_weight_breakdown(
    ctx: AppContext,
    root_part_number: str,
    child_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for child in child_rows:
        qty = float(child["qty"])
        child_part_number = child["child_part_number"]
        result = ctx.backend.rollups.rollup_weight_with_maturity(
            root_part_number=child_part_number,
            include_root=True,
        )
        if not result.get("ok"):
            warnings.append(
                f"{root_part_number} -> {child_part_number}: " + "; ".join(result.get("errors", []))
            )
            continue

        branch_total_for_one = float(result["data"]["total"])
        breakdown = result["data"].get("breakdown", [])
        maturity_added_for_one = 0.0
        for item in breakdown:
            maturity_added_for_one += (
                float(item["effective_unit_weight"]) - float(item["unit_weight"])
            ) * float(item["multiplier"])

        rows.append(
            {
                "part_number": child_part_number,
                "name": child["child_name"],
                "qty": qty,
                "effective_weight": branch_total_for_one * qty,
                "maturity_added_weight": maturity_added_for_one * qty,
                "relationship_id": child["rel_id"],
            }
        )

        for warning in result.get("warnings", []):
            warnings.append(f"{root_part_number} -> {child_part_number}: {warning}")

    rows.sort(key=lambda row: (-row["effective_weight"], row["part_number"], row["relationship_id"]))
    return rows, warnings


def render_dashboard_tab(ctx: AppContext) -> None:
    if ctx.snapshot_mode:
        st.caption("Snapshot mode active: analysis uses loaded snapshot data.")
    st.subheader("Interactive Root Breakdown")

    if not ctx.parts_result.get("ok"):
        show_service_result("List parts", ctx.parts_result)
        return
    if not ctx.parts:
        st.info("No parts found. Add parts first or load a different snapshot.")
        return

    part_lookup = {str(item.get("part_number", "")).strip(): item for item in ctx.parts}
    default_root = _find_default_root(ctx.parts, ctx.relationships)
    if "dashboard_root_part_number" not in st.session_state:
        st.session_state["dashboard_root_part_number"] = default_root

    root_options = sorted(part_lookup.keys())
    if st.session_state["dashboard_root_part_number"] not in root_options and root_options:
        st.session_state["dashboard_root_part_number"] = root_options[0]

    left_col, right_col = st.columns([1, 2], gap="large")

    with left_col:
        selected_root = st.selectbox(
            "Current root part",
            options=root_options,
            index=root_options.index(st.session_state["dashboard_root_part_number"]),
            key="dashboard_root_selector",
        )
        if selected_root != st.session_state["dashboard_root_part_number"]:
            st.session_state["dashboard_root_part_number"] = selected_root
            st.rerun()

        root_part_number = st.session_state["dashboard_root_part_number"]
        root_part = part_lookup.get(root_part_number, {})
        st.markdown("**Root Part**")
        st.dataframe(
            [
                {
                    "part_number": root_part_number,
                    "name": root_part.get("name", "(missing)"),
                }
            ],
            use_container_width=True,
            hide_index=True,
        )

        children = _child_rows(root_part_number, ctx.relationships, part_lookup)
        st.markdown("**Direct Children**")
        if not children:
            st.info("This root has no direct children.")
        else:
            st.dataframe(children, use_container_width=True, hide_index=True)
            st.caption("Click a child to make it the new root.")
            for child in children:
                button_label = f"{child['child_part_number']} ({child['child_name']})"
                if st.button(button_label, key=f"dashboard_child_nav_{child['rel_id']}"):
                    st.session_state["dashboard_root_part_number"] = child["child_part_number"]
                    st.rerun()

    with right_col:
        root_part_number = st.session_state["dashboard_root_part_number"]
        children = _child_rows(root_part_number, ctx.relationships, part_lookup)
        if not children:
            st.info("No direct children to analyze for this root.")
            return

        rollup_rows, rollup_warnings = _direct_child_weight_breakdown(ctx, root_part_number, children)
        if rollup_warnings:
            for warning in rollup_warnings:
                st.warning(warning)

        if not rollup_rows:
            st.info("No child weight contributions could be computed.")
            return

        total_effective_weight = sum(row["effective_weight"] for row in rollup_rows)
        total_maturity_weight = sum(row["maturity_added_weight"] for row in rollup_rows)

        metric_col1, metric_col2 = st.columns(2)
        metric_col1.metric("Total Effective Weight", f"{total_effective_weight:.4f}")
        metric_col2.metric("Total Maturity Added", f"{total_maturity_weight:.4f}")

        st.markdown(f"**Weight Breakdown for Children of `{root_part_number}`**")
        st.dataframe(rollup_rows, use_container_width=True, hide_index=True)

        chart_rows = [
            {"part_number": row["part_number"], "effective_weight": row["effective_weight"]}
            for row in rollup_rows
            if row["effective_weight"] > 0
        ]
        if chart_rows:
            st.markdown("**Contribution Pie Chart**")
            st.vega_lite_chart(
                chart_rows,
                {
                    "mark": {"type": "arc", "outerRadius": 120},
                    "encoding": {
                        "theta": {"field": "effective_weight", "type": "quantitative"},
                        "color": {"field": "part_number", "type": "nominal"},
                        "tooltip": [
                            {"field": "part_number", "type": "nominal"},
                            {"field": "effective_weight", "type": "quantitative", "format": ".4f"},
                        ],
                    },
                },
                use_container_width=True,
            )
