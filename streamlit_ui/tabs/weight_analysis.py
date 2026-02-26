from __future__ import annotations

from typing import Any

import streamlit as st

from bom_backend.constants import MATURITY_FACTOR_KEY, UNIT_WEIGHT_KEY
from streamlit_ui.context import AppContext


def _build_opportunity_table(
    part_totals: list[dict[str, Any]],
    total_weight: float,
    part_lookup: dict[str, Any],
    exclude_non_optimizable: bool,
    unit_weight_key: str,
) -> list[dict[str, Any]]:
    """Build the optimization opportunity table rows.

    Savings are based on reducing the part's *unit_weight* attribute.
    Because contribution = unit_weight * maturity_factor * total_qty,
    a X% reduction in unit_weight yields an assembly savings of
    total_contribution * X%.
    """
    rows: list[dict[str, Any]] = []
    for item in part_totals:
        pn = item["part_number"]
        part = part_lookup.get(pn)
        name = part.name if part else pn
        can_optimize = True
        unit_weight = None
        if part:
            raw = part.attributes.get("can_weight_optimized")
            if raw is not None:
                can_optimize = bool(raw)
            raw_uw = part.attributes.get(unit_weight_key)
            if raw_uw is not None:
                try:
                    unit_weight = float(raw_uw)
                except (TypeError, ValueError):
                    pass

        if exclude_non_optimizable and not can_optimize:
            continue

        contribution = float(item.get("total_contribution", 0.0))
        pct = (contribution / total_weight * 100) if total_weight else 0.0
        # Total qty in assembly = contribution / effective_unit_weight.
        # This shows the leverage: how many times this part's weight counts.
        total_qty = round(contribution / unit_weight, 2) if unit_weight else None
        rows.append(
            {
                "Part Number": pn,
                "Name": name,
                "Optimizable": "Yes" if can_optimize else "No",
                "Unit Weight": unit_weight,
                "Total Qty": total_qty,
                "Assy Contribution": round(contribution, 3),
                "% of Assembly": round(pct, 2),
                "If UW -5%": round(contribution * 0.05, 3),
                "If UW -10%": round(contribution * 0.10, 3),
                "If UW -20%": round(contribution * 0.20, 3),
            }
        )
    return rows


def _breakdown_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for item in rows:
        formatted.append(
            {
                "Part Number": item["part_number"],
                "Path": " -> ".join(item.get("path", [])),
                "Multiplier": item["multiplier"],
                "Unit Weight": item["unit_weight"],
                "Maturity Factor": item["maturity_factor"],
                "Effective Weight": item["effective_unit_weight"],
                "Contribution": item["contribution"],
            }
        )
    return formatted


def render_weight_analysis_tab(ctx: AppContext, root_part_number: str) -> None:
    if ctx.snapshot_mode:
        st.info("Snapshot mode is active. Weight analysis is running against the loaded snapshot data.")

    selected_root = root_part_number.strip()
    st.subheader("Weight Optimization Opportunities")
    st.caption(
        "Identifies which parts deliver the most assembly-level weight savings. "
        "Parts are ranked by their total contribution to the top-level assembly weight."
    )

    with st.form("weight_analysis_form"):
        st.caption(f"Root from sidebar: **{selected_root or '(none selected)'}**")

        col_left, col_right = st.columns(2)
        with col_left:
            exclude_non_optimizable = st.checkbox(
                "Exclude parts marked as non-optimizable",
                value=False,
                help="Hide parts where can_weight_optimized = false",
            )
            include_root = st.checkbox("Include root part contribution", value=True)
        with col_right:
            top_n = st.number_input(
                "Top contributors to show",
                min_value=1,
                value=15,
                step=1,
            )

        with st.expander("Advanced settings"):
            unit_weight_key = st.text_input("Unit weight attribute key", value=UNIT_WEIGHT_KEY)
            maturity_factor_key = st.text_input("Maturity factor attribute key", value=MATURITY_FACTOR_KEY)
            default_maturity_factor = st.number_input(
                "Default maturity factor",
                min_value=0.01,
                value=1.0,
                step=0.01,
                format="%.2f",
            )

        submit = st.form_submit_button("Analyze Weight Opportunities", disabled=not selected_root)

    if not submit:
        return

    result = ctx.backend.rollups.rollup_weight_with_maturity(
        root_part_number=selected_root,
        unit_weight_key=unit_weight_key,
        maturity_factor_key=maturity_factor_key,
        default_maturity_factor=default_maturity_factor,
        include_root=include_root,
        top_n=9999,  # get all contributors; we filter in the UI
    )
    if not result.get("ok"):
        for error in result.get("errors", []):
            st.error(error)
        return

    data = result["data"]
    total_weight = data["total"]

    # Build a lookup of all parts for name / attribute enrichment.
    part_lookup: dict[str, Any] = {}
    for part in ctx.backend.part_repo.list_parts():
        part_lookup[part.part_number] = part

    # --- Summary metrics ---
    opp_rows = _build_opportunity_table(
        data.get("part_totals", []),
        total_weight,
        part_lookup,
        exclude_non_optimizable,
        unit_weight_key,
    )

    optimizable_weight = sum(r["Assy Contribution"] for r in opp_rows if r["Optimizable"] == "Yes")
    non_optimizable_weight = total_weight - optimizable_weight if not exclude_non_optimizable else (
        total_weight - sum(r["Assy Contribution"] for r in opp_rows)
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Assembly Weight", f"{total_weight:,.2f}")
    m2.metric("Visible Contributors", len(opp_rows))
    m3.metric("Optimizable Weight", f"{optimizable_weight:,.2f}")
    m4.metric("Unresolved Nodes", len(data.get("unresolved_nodes", [])))

    st.divider()

    # --- Bar chart: top contributors ---
    chart_rows = opp_rows[: int(top_n)]
    if chart_rows:
        import altair as alt
        import pandas as pd

        chart_df = pd.DataFrame(
            {
                "Part": [f"{r['Part Number']} - {r['Name']}" for r in chart_rows],
                "Contribution": [r["Assy Contribution"] for r in chart_rows],
                "Optimizable": [r["Optimizable"] for r in chart_rows],
            }
        )

        color_scale = alt.Scale(
            domain=["Yes", "No"],
            range=["#2196F3", "#9E9E9E"],
        )

        bar_chart = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("Contribution:Q", title="Weight Contribution"),
                y=alt.Y("Part:N", sort="-x", title=None),
                color=alt.Color(
                    "Optimizable:N",
                    scale=color_scale,
                    legend=alt.Legend(title="Can Optimize?"),
                ),
                tooltip=[
                    alt.Tooltip("Part:N"),
                    alt.Tooltip("Contribution:Q", format=",.3f"),
                    alt.Tooltip("Optimizable:N"),
                ],
            )
            .properties(height=max(len(chart_rows) * 28, 200))
        )
        st.altair_chart(bar_chart, use_container_width=True)
    else:
        st.warning("No contributors to display.")

    st.divider()

    # --- Opportunity table ---
    st.markdown("**Optimization Opportunity Ranking**")
    st.caption(
        "Parts sorted by assembly weight contribution. "
        "'If UW' columns show how much assembly weight drops if that part's **unit_weight** is reduced by 5%, 10%, or 20%. "
        "Total Qty reflects how many times the part's unit weight counts in the assembly (qty x maturity)."
    )
    if opp_rows:
        import pandas as pd

        opp_df = pd.DataFrame(opp_rows)
        st.dataframe(
            opp_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "% of Assembly": st.column_config.ProgressColumn(
                    "% of Assembly",
                    format="%.1f%%",
                    min_value=0,
                    max_value=100,
                ),
                "Unit Weight": st.column_config.NumberColumn(format="%.3f"),
                "Assy Contribution": st.column_config.NumberColumn(format="%.3f"),
                "If UW -5%": st.column_config.NumberColumn(format="%.3f"),
                "If UW -10%": st.column_config.NumberColumn(format="%.3f"),
                "If UW -20%": st.column_config.NumberColumn(format="%.3f"),
            },
        )
    else:
        st.info("No parts to display with current filters.")

    # --- Detailed breakdown in expander ---
    with st.expander("Path Breakdown (all nodes)"):
        bd = _breakdown_rows(data.get("breakdown", []))
        if bd:
            st.dataframe(bd, use_container_width=True, hide_index=True)
        else:
            st.info("No breakdown data.")

    warnings = result.get("warnings", [])
    unresolved = data.get("unresolved_nodes", [])
    if unresolved or warnings:
        with st.expander(f"Unresolved Nodes & Warnings ({len(unresolved)} nodes, {len(warnings)} warnings)"):
            if unresolved:
                st.dataframe(unresolved, use_container_width=True, hide_index=True)
            for w in warnings:
                st.caption(f"- {w}")
