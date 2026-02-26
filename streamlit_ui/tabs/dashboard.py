from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import show_service_result


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
) -> list[dict[str, Any]]:
    """Build display rows with weight_plus_maturity and pct_of_total.

    pct_of_total is relative to the sum of weight_plus_maturity across ALL rows passed in,
    so pass the full (unfiltered) rollup_rows to get correct percentages.
    """
    # effective_weight already equals base_weight + maturity_added_weight (maturity is baked in
    # by the rollup service).  weight_plus_maturity is therefore just effective_weight; we
    # derive base_weight by subtracting the maturity portion back out.
    with_totals = []
    for row in rollup_rows:
        effective_weight = float(row["effective_weight"])
        maturity_added_weight = float(row["maturity_added_weight"])
        with_totals.append(
            {
                "_rel_id": row["relationship_id"],
                "part_number": row["part_number"],
                "name": row["name"],
                "base_weight": effective_weight - maturity_added_weight,
                "maturity_added_weight": maturity_added_weight,
                # weight_plus_maturity == effective_weight (not effective + maturity, which
                # would double-count maturity).
                "weight_plus_maturity": effective_weight,
            }
        )

    total_w_plus_m = sum(r["weight_plus_maturity"] for r in with_totals)

    # Second pass: attach pct_of_total
    display_rows: list[dict[str, Any]] = []
    for row in with_totals:
        display_rows.append(
            {
                **row,
                "pct_of_total": (
                    (row["weight_plus_maturity"] / total_w_plus_m * 100.0)
                    if total_w_plus_m > 0
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


def render_dashboard_tab(
    ctx: AppContext,
    root_part_number: str,
    root_state_key: str = "universal_root_part_number",
) -> None:
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
    root_options = sorted(part_lookup.keys())
    if root_part_number not in root_options and root_options:
        fallback_root = root_options[0]
        st.info(
            "The selected root is not available in the loaded dataset. "
            f"Falling back to `{fallback_root}`."
        )
        root_part_number = fallback_root
        if st.session_state.get(root_state_key) != fallback_root:
            st.session_state[root_state_key] = fallback_root
            st.rerun()

    root_part = part_lookup.get(root_part_number, {})
    children = _child_rows(root_part_number, ctx.relationships, part_lookup)
    rollup_rows: list[dict[str, Any]] = []
    unique_warnings: list[str] = []
    if children:
        rollup_rows, rollup_warnings = _direct_child_weight_breakdown(ctx, root_part_number, children)
        unique_warnings = list(dict.fromkeys(rollup_warnings))

    hide_zero_weight = st.checkbox(
        "Hide children with zero effective weight",
        value=True,
        help="Applies to both the Weight Breakdown table and the chart.",
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

    if not children:
        st.info("No direct children to analyze for this root.")
        return

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

    # Compute display rows from ALL rollup_rows so pct is correct even when filtered.
    all_display_rows = _rollup_display_rows(rollup_rows)
    visible_rel_ids = {r["relationship_id"] for r in visible_rollup_rows}
    visible_display_rows = [r for r in all_display_rows if r["_rel_id"] in visible_rel_ids]

    # ── Summary metrics ──────────────────────────────────────────────────────
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    total_base_weight = total_effective_weight - total_maturity_weight
    metric_col1.metric("Total Weight (Base)", f"{total_base_weight:.4f}")
    metric_col2.metric("Total Maturity Added", f"{total_maturity_weight:.4f}")
    metric_col3.metric("Total Weight + Maturity", f"{total_effective_weight:.4f}")

    # ── Stacked bar chart ─────────────────────────────────────────────────────
    st.markdown("**Weight & Maturity by Child Part**")
    visual_limit = st.number_input(
        "Children shown",
        min_value=1,
        max_value=max(1, len(visible_display_rows)),
        value=min(12, len(visible_display_rows)),
        step=1,
        key=f"dashboard_visual_limit_{root_part_number}",
    )

    sorted_display = sorted(
        visible_display_rows,
        key=lambda row: row["weight_plus_maturity"],
        reverse=True,
    )

    # Build one row per part per segment (Weight / Maturity) for the stacked bars,
    # plus a parallel single-row list for the pct text annotations.
    chart_bars: list[dict[str, Any]] = []
    chart_labels: list[dict[str, Any]] = []
    for row in sorted_display[: int(visual_limit)]:
        label = _chart_label(row["part_number"], row["name"])
        pct_text = f"{row['pct_of_total']:.1f}%"
        w_plus_m = row["weight_plus_maturity"]

        chart_bars.append(
            {
                "part_label": label,
                "part_number": row["part_number"],
                "name": row["name"],
                "segment": "Weight",
                "value": row["base_weight"],
                "weight_plus_maturity": w_plus_m,
                "pct_label": pct_text,
            }
        )
        chart_bars.append(
            {
                "part_label": label,
                "part_number": row["part_number"],
                "name": row["name"],
                "segment": "Maturity",
                "value": row["maturity_added_weight"],
                "weight_plus_maturity": w_plus_m,
                "pct_label": pct_text,
            }
        )
        chart_labels.append(
            {
                "part_label": label,
                "weight_plus_maturity": w_plus_m,
                "pct_label": pct_text,
            }
        )

    # Explicit domain order: largest weight_plus_maturity first → renders at the top of the
    # y-axis.  Passing this list as `sort` in the bar layer's y-encoding is more reliable than
    # "-x" in a layered spec where each layer has a different x field.
    y_order = [row["part_label"] for row in chart_labels]

    chart_height = min(700, max(220, 38 * len(chart_labels)))

    st.vega_lite_chart(
        chart_bars,
        {
            "layer": [
                # ── Stacked bars (Weight + Maturity) ──
                {
                    "mark": {"type": "bar", "cornerRadiusEnd": 3},
                    "encoding": {
                        "y": {
                            "field": "part_label",
                            "type": "nominal",
                            "sort": y_order,
                            "title": "Child Part",
                            "axis": {"labelAngle": 0, "labelPadding": 4},
                        },
                        "x": {
                            "field": "value",
                            "type": "quantitative",
                            "stack": "zero",
                            "title": "Weight",
                        },
                        "color": {
                            "field": "segment",
                            "type": "nominal",
                            "scale": {
                                "domain": ["Weight", "Maturity"],
                                "range": ["#4C78A8", "#F58518"],
                            },
                            "legend": {"title": "Segment"},
                        },
                        "tooltip": [
                            {"field": "part_number", "type": "nominal", "title": "Part #"},
                            {"field": "name", "type": "nominal", "title": "Name"},
                            {"field": "segment", "type": "nominal", "title": "Segment"},
                            {
                                "field": "value",
                                "type": "quantitative",
                                "title": "Value",
                                "format": ",.4f",
                            },
                            {
                                "field": "weight_plus_maturity",
                                "type": "quantitative",
                                "title": "Weight + Maturity",
                                "format": ",.4f",
                            },
                            {"field": "pct_label", "type": "nominal", "title": "% of Total"},
                        ],
                    },
                },
                # ── Pct-of-total text annotation (one label per bar, at the bar end) ──
                {
                    "transform": [{"filter": "datum.segment === 'Weight'"}],
                    "mark": {
                        "type": "text",
                        "align": "left",
                        "dx": 5,
                        "color": "#888888",
                        "fontSize": 11,
                    },
                    "encoding": {
                        "y": {
                            "field": "part_label",
                            "type": "nominal",
                            "sort": y_order,
                        },
                        "x": {
                            "field": "weight_plus_maturity",
                            "type": "quantitative",
                        },
                        "text": {"field": "pct_label", "type": "nominal"},
                    },
                },
            ],
            "height": chart_height,
            "config": {
                "axisY": {"minExtent": 180},
                "axis": {"labelLimit": 0},
            },
        },
        width="stretch",
    )

    # ── Weight Breakdown table ────────────────────────────────────────────────
    st.markdown(f"**Weight Breakdown for Children of `{root_part_number}`**")
    table_rows = [
        {
            "part_number": row["part_number"],
            "name": row["name"],
            "base_weight": row["base_weight"],
            "maturity_added_weight": row["maturity_added_weight"],
            "weight_plus_maturity": row["weight_plus_maturity"],
            "pct_of_total": row["pct_of_total"],
        }
        for row in visible_display_rows
    ]
    st.dataframe(
        table_rows,
        width="stretch",
        hide_index=True,
        column_order=[
            "part_number",
            "name",
            "base_weight",
            "maturity_added_weight",
            "weight_plus_maturity",
            "pct_of_total",
        ],
        column_config={
            "part_number": st.column_config.TextColumn("Part Number"),
            "name": st.column_config.TextColumn("Name"),
            "base_weight": st.column_config.NumberColumn("Weight", format="%.4f"),
            "maturity_added_weight": st.column_config.NumberColumn("Maturity", format="%.4f"),
            "weight_plus_maturity": st.column_config.NumberColumn(
                "Weight + Maturity", format="%.4f"
            ),
            "pct_of_total": st.column_config.NumberColumn("Pct of Total", format="%.2f%%"),
        },
    )

    # ── Debug footer ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Root Context Debug")
    st.markdown(f"**Root Context:** `{root_part_number}` | {root_part.get('name', '(missing)')}")
    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("Direct Children", f"{len(visible_children)}/{len(children)}")
    summary_col2.metric(
        "Analyzed Children", f"{len(visible_display_rows)}/{len(all_display_rows)}"
    )
    summary_col3.metric("Warnings", len(unique_warnings))
    if unique_warnings:
        st.caption(f"{len(unique_warnings)} warning(s) while computing child rollups.")
        with st.expander("View warning details", expanded=False):
            for warning in unique_warnings:
                st.markdown(f"- {warning}")
