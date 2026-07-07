from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_ui.rollup_views import direct_child_totals


def _chart_label(part_number: str, name: str) -> str:
    clean_name = str(name).strip() or "(missing)"
    if len(clean_name) > 32:
        clean_name = f"{clean_name[:29]}..."
    return f"{part_number} | {clean_name}"


def render_overview(
    root_part_number: str,
    rollup_data: dict[str, Any],
    relationships: list[dict[str, Any]],
    part_lookup: dict[str, dict[str, Any]],
) -> None:
    """Per-direct-child weight breakdown of the shared whole-root rollup."""
    breakdown = rollup_data.get("breakdown", [])
    total_effective = float(rollup_data.get("total", 0) or 0)
    total_maturity = sum(
        (float(item.get("effective_unit_weight", 0)) - float(item.get("unit_weight", 0)))
        * float(item.get("multiplier", 1))
        for item in breakdown
    )

    # ── Summary metrics ──────────────────────────────────────────────────────
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Total Weight (Base)", f"{total_effective - total_maturity:,.0f} lbs")
    metric_col2.metric("Total Maturity Added", f"{total_maturity:,.0f} lbs")
    metric_col3.metric("Total Weight + Maturity", f"{total_effective:,.0f} lbs")

    child_data = direct_child_totals(breakdown, root_part_number, relationships)
    child_rows = child_data["rows"]

    if child_data["root_self_weight"] > 0:
        st.info(
            f"`{root_part_number}` carries its own unit weight "
            f"({child_data['root_self_weight']:,.1f} lbs) — an allocation. Its children are "
            "not counted in the rollup while that unit weight is set.",
            icon="⚖️",
        )

    if not child_rows:
        if child_data["root_self_weight"] <= 0:
            st.info("No direct children to analyze for this root.")
        return

    display_rows = [
        {
            "part_number": row["part_number"],
            "name": part_lookup.get(row["part_number"], {}).get("name", "(missing)"),
            "qty": row["qty"],
            "base_weight": row["base_weight"],
            "maturity_added_weight": row["maturity_added"],
            "weight_plus_maturity": row["effective_weight"],
            "pct_of_total": (row["effective_weight"] / total_effective * 100.0) if total_effective > 0 else 0.0,
        }
        for row in child_rows
    ]

    # ── Chart settings ───────────────────────────────────────────────────────
    st.markdown("**Weight & Maturity by Child Part**")
    with st.expander("Chart Settings", expanded=False):
        hide_zero_weight = st.checkbox(
            "Hide children with zero effective weight",
            value=True,
            help="Applies to both the Weight Breakdown table and the chart.",
            key="dashboard_hide_zero_weight",
        )
        visible_count = sum(1 for r in display_rows if r["weight_plus_maturity"] > 0) or 1
        visual_limit = st.number_input(
            "Children shown",
            help="How many bars to draw. The table below always shows every child.",
            min_value=1,
            max_value=max(1, len(display_rows)),
            value=min(12, visible_count),
            step=1,
            key=f"dashboard_visual_limit_{root_part_number}",
        )

    visible_rows = (
        [r for r in display_rows if r["weight_plus_maturity"] > 0]
        if hide_zero_weight
        else display_rows
    )
    if not visible_rows:
        st.info("No non-zero child weight contributions to display. Disable the filter to view all children.")
        return

    # ── Stacked bar chart ─────────────────────────────────────────────────────
    chart_bars: list[dict[str, Any]] = []
    chart_labels: list[dict[str, Any]] = []
    for row in visible_rows[: int(visual_limit)]:
        label = _chart_label(row["part_number"], row["name"])
        pct_text = f"{row['pct_of_total']:.1f}%"
        w_plus_m = row["weight_plus_maturity"]

        for segment, value in (("Weight", row["base_weight"]), ("Maturity", row["maturity_added_weight"])):
            chart_bars.append(
                {
                    "part_label": label,
                    "part_number": row["part_number"],
                    "name": row["name"],
                    "segment": segment,
                    "value": value,
                    "weight_plus_maturity": w_plus_m,
                    "pct_label": pct_text,
                }
            )
        chart_labels.append(
            {"part_label": label, "weight_plus_maturity": w_plus_m, "pct_label": pct_text}
        )

    y_order = [row["part_label"] for row in chart_labels]
    chart_height = min(900, max(300, 50 * len(chart_labels)))

    st.vega_lite_chart(
        chart_bars,
        {
            "layer": [
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
                            "title": "Weight (lbs)",
                            "axis": {"format": ",.0f"},
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
                            {"field": "value", "type": "quantitative", "title": "Value (lbs)", "format": ",.0f"},
                            {
                                "field": "weight_plus_maturity",
                                "type": "quantitative",
                                "title": "Weight + Maturity (lbs)",
                                "format": ",.0f",
                            },
                            {"field": "pct_label", "type": "nominal", "title": "% of Total"},
                        ],
                    },
                },
                {
                    "transform": [{"filter": "datum.segment === 'Weight'"}],
                    "mark": {"type": "text", "align": "left", "dx": 5, "color": "#888888", "fontSize": 11},
                    "encoding": {
                        "y": {"field": "part_label", "type": "nominal", "sort": y_order},
                        "x": {"field": "weight_plus_maturity", "type": "quantitative"},
                        "text": {"field": "pct_label", "type": "nominal"},
                    },
                },
            ],
            "height": chart_height,
            "config": {"axisY": {"minExtent": 260}, "axis": {"labelLimit": 0}},
        },
        width="stretch",
    )

    # ── Weight Breakdown table ────────────────────────────────────────────────
    table_rows = [
        {
            "part_number": row["part_number"],
            "name": row["name"],
            "qty": row["qty"],
            "base_weight": f"{row['base_weight']:,.1f}",
            "maturity_added_weight": f"{row['maturity_added_weight']:,.1f}",
            "weight_plus_maturity": f"{row['weight_plus_maturity']:,.1f}",
            "pct_of_total": row["pct_of_total"],
        }
        for row in visible_rows
    ]
    st.dataframe(
        table_rows,
        width="stretch",
        hide_index=True,
        column_config={
            "part_number": st.column_config.TextColumn("Part Number"),
            "name": st.column_config.TextColumn("Name"),
            "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
            "base_weight": st.column_config.TextColumn("Weight (lbs)"),
            "maturity_added_weight": st.column_config.TextColumn("Maturity (lbs)"),
            "weight_plus_maturity": st.column_config.TextColumn("Weight + Maturity (lbs)"),
            "pct_of_total": st.column_config.NumberColumn("% of Total", format="%.1f%%"),
        },
    )
