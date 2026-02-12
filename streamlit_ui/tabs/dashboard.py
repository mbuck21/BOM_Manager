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
    rows.sort(key=lambda row: (-row["qty"], row["child_part_number"], row["rel_id"] or ""))
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


def _rollup_display_rows(
    rollup_rows: list[dict[str, Any]],
    total_effective_weight: float,
    total_maturity_weight: float,
) -> list[dict[str, Any]]:
    display_rows: list[dict[str, Any]] = []
    for row in rollup_rows:
        effective_weight = float(row["effective_weight"])
        maturity_added_weight = float(row["maturity_added_weight"])
        qty = float(row["qty"])
        display_rows.append(
            {
                "part_number": row["part_number"],
                "name": row["name"],
                "qty": qty,
                "effective_weight": effective_weight,
                "effective_weight_pct": (
                    (effective_weight / total_effective_weight) * 100.0
                    if total_effective_weight > 0
                    else 0.0
                ),
                "maturity_added_weight": maturity_added_weight,
                "maturity_added_pct": (
                    (maturity_added_weight / total_maturity_weight) * 100.0
                    if total_maturity_weight > 0
                    else 0.0
                ),
            }
        )
    return display_rows


def _chart_label(part_number: str, name: str) -> str:
    clean_name = str(name).strip() or "(missing)"
    if len(clean_name) > 32:
        clean_name = f"{clean_name[:29]}..."
    return f"{part_number} | {clean_name}"


def render_dashboard_tab(ctx: AppContext) -> None:
    if ctx.snapshot_mode:
        st.caption("Snapshot mode active: analysis uses loaded snapshot data.")
    st.subheader("Interactive Root Breakdown")
    st.caption(
        "Engineer workflow: choose a root, review direct children, and prioritize high-weight branches."
    )

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
    children = _child_rows(root_part_number, ctx.relationships, part_lookup)
    total_child_qty = sum(float(child["qty"]) for child in children)
    rollup_rows: list[dict[str, Any]] = []
    unique_warnings: list[str] = []
    if children:
        rollup_rows, rollup_warnings = _direct_child_weight_breakdown(ctx, root_part_number, children)
        unique_warnings = list(dict.fromkeys(rollup_warnings))

    hide_zero_weight = st.checkbox(
        "Hide children with zero effective weight",
        value=True,
        help="Applies to both Direct Children and Weight Breakdown tables.",
        key="dashboard_hide_zero_weight",
    )

    effective_weight_by_child_key = {
        (row["relationship_id"], row["part_number"]): float(row["effective_weight"])
        for row in rollup_rows
    }
    visible_children = children
    visible_rollup_rows = rollup_rows
    if hide_zero_weight:
        visible_rollup_rows = [
            row for row in rollup_rows if float(row["effective_weight"]) > 0
        ]
        visible_children = []
        for child in children:
            child_key = (child["rel_id"], child["child_part_number"])
            effective_weight = effective_weight_by_child_key.get(child_key)
            if effective_weight is None or effective_weight > 0:
                visible_children.append(child)

    st.markdown(f"**Root Context:** `{root_part_number}` | {root_part.get('name', '(missing)')}")
    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    summary_col1.metric("Direct Children", f"{len(visible_children)}/{len(children)}")
    summary_col2.metric("Analyzed Children", f"{len(visible_rollup_rows)}/{len(rollup_rows)}")
    summary_col3.metric("Warnings", len(unique_warnings))
    summary_col4.metric("Total Child Qty", f"{total_child_qty:.3f}")

    left_col, right_col = st.columns([1, 2], gap="large")

    with left_col:
        st.markdown("**Direct Children**")
        if not children:
            st.info("This root has no direct children.")
        elif not visible_children:
            st.info(
                "All children are hidden by the zero-weight filter. Disable the filter to view all children."
            )
        else:
            children_table_rows = [
                {
                    "child_part_number": child["child_part_number"],
                    "child_name": child["child_name"],
                    "qty": child["qty"],
                }
                for child in visible_children
            ]
            st.dataframe(
                children_table_rows,
                width="stretch",
                hide_index=True,
                column_config={
                    "qty": st.column_config.NumberColumn("qty", format="%.3f"),
                },
            )
            child_target_index = st.selectbox(
                "Drill into child",
                options=list(range(len(visible_children))),
                format_func=lambda index: (
                    f"{visible_children[index]['child_part_number']} | "
                    f"{visible_children[index]['child_name']} (qty={visible_children[index]['qty']:.3f})"
                ),
                key=f"dashboard_child_target_{root_part_number}",
            )
            if st.button("Set child as new root", key=f"dashboard_child_nav_apply_{root_part_number}"):
                st.session_state["dashboard_root_part_number"] = visible_children[child_target_index][
                    "child_part_number"
                ]
                st.rerun()

    with right_col:
        if not children:
            st.info("No direct children to analyze for this root.")
            return

        if unique_warnings:
            st.caption(f"{len(unique_warnings)} warning(s) while computing child rollups.")
            with st.expander("View warning details", expanded=False):
                for warning in unique_warnings:
                    st.markdown(f"- {warning}")

        if not rollup_rows:
            st.info("No child weight contributions could be computed.")
            return

        total_effective_weight = sum(row["effective_weight"] for row in rollup_rows)
        total_maturity_weight = sum(row["maturity_added_weight"] for row in rollup_rows)
        if hide_zero_weight and not visible_rollup_rows:
            st.info(
                "No non-zero child weight contributions to display. Disable the filter to view all children."
            )
            return

        average_effective_weight = total_effective_weight / len(rollup_rows)
        display_rows = _rollup_display_rows(
            rollup_rows=visible_rollup_rows,
            total_effective_weight=total_effective_weight,
            total_maturity_weight=total_maturity_weight,
        )

        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric("Total Effective Weight", f"{total_effective_weight:.4f}")
        metric_col2.metric("Total Maturity Added", f"{total_maturity_weight:.4f}")
        metric_col3.metric("Avg Child Effective Weight", f"{average_effective_weight:.4f}")

        st.markdown("**Contribution Visual**")
        visual_col1, visual_col2 = st.columns([3, 2])
        with visual_col1:
            visual_metric = st.radio(
                "Visual metric",
                options=["Effective Weight", "Maturity Added Weight"],
                horizontal=True,
                key=f"dashboard_visual_metric_{root_part_number}",
            )
        with visual_col2:
            visual_limit = st.number_input(
                "Children shown",
                min_value=1,
                max_value=len(display_rows),
                value=min(12, len(display_rows)),
                step=1,
                key=f"dashboard_visual_limit_{root_part_number}",
            )

        if visual_metric == "Maturity Added Weight":
            chart_field = "maturity_added_weight"
            chart_pct_field = "maturity_added_pct"
            chart_title = "Maturity Added Weight"
            sorted_rows = sorted(
                display_rows,
                key=lambda row: float(row["maturity_added_weight"]),
                reverse=True,
            )
        else:
            chart_field = "effective_weight"
            chart_pct_field = "effective_weight_pct"
            chart_title = "Effective Weight"
            sorted_rows = sorted(
                display_rows,
                key=lambda row: float(row["effective_weight"]),
                reverse=True,
            )

        chart_rows = []
        for row in sorted_rows[: int(visual_limit)]:
            chart_rows.append(
                {
                    "part_number": row["part_number"],
                    "name": row["name"],
                    "part_label": _chart_label(row["part_number"], row["name"]),
                    "effective_weight": row["effective_weight"],
                    "effective_weight_pct": row["effective_weight_pct"],
                    "maturity_added_weight": row["maturity_added_weight"],
                    "maturity_added_pct": row["maturity_added_pct"],
                }
            )

        st.vega_lite_chart(
            chart_rows,
            {
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "height": min(700, max(220, 36 * len(chart_rows))),
                "encoding": {
                    "y": {
                        "field": "part_label",
                        "type": "nominal",
                        "sort": "-x",
                        "title": "Child Part",
                    },
                    "x": {
                        "field": chart_field,
                        "type": "quantitative",
                        "title": chart_title,
                    },
                    "color": {
                        "field": chart_pct_field,
                        "type": "quantitative",
                        "title": "Contribution %",
                        "scale": {"scheme": "blues"},
                    },
                    "tooltip": [
                        {"field": "part_number", "type": "nominal"},
                        {"field": "name", "type": "nominal"},
                        {"field": "effective_weight", "type": "quantitative", "format": ".4f"},
                        {"field": "effective_weight_pct", "type": "quantitative", "format": ".2f"},
                        {"field": "maturity_added_weight", "type": "quantitative", "format": ".4f"},
                        {"field": "maturity_added_pct", "type": "quantitative", "format": ".2f"},
                    ],
                },
            },
            width="stretch",
        )

        st.markdown(f"**Weight Breakdown for Children of `{root_part_number}`**")
        st.dataframe(
            display_rows,
            width="stretch",
            hide_index=True,
            column_order=[
                "part_number",
                "name",
                "qty",
                "effective_weight",
                "effective_weight_pct",
                "maturity_added_weight",
                "maturity_added_pct",
            ],
            column_config={
                "qty": st.column_config.NumberColumn("qty", format="%.3f"),
                "effective_weight": st.column_config.NumberColumn(
                    "effective_weight",
                    format="%.4f",
                ),
                "effective_weight_pct": st.column_config.NumberColumn(
                    "effective_weight_pct",
                    format="%.2f%%",
                ),
                "maturity_added_weight": st.column_config.NumberColumn(
                    "maturity_added_weight",
                    format="%.4f",
                ),
                "maturity_added_pct": st.column_config.NumberColumn(
                    "maturity_added_pct",
                    format="%.2f%%",
                ),
            },
        )
