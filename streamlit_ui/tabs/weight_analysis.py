from __future__ import annotations

from typing import Any

import streamlit as st

from bom_backend.constants import UNIT_WEIGHT_KEY


def _build_opportunity_table(
    part_totals: list[dict[str, Any]],
    total_weight: float,
    part_lookup: dict[str, dict[str, Any]],
    exclude_non_optimizable: bool,
) -> list[dict[str, Any]]:
    """Build the optimization opportunity table rows.

    Savings are based on reducing the part's *unit_weight* attribute. Because
    contribution = unit_weight * maturity_factor * total_qty, an X% reduction in
    unit_weight yields an assembly savings of total_contribution * X%.
    """
    rows: list[dict[str, Any]] = []
    for item in part_totals:
        pn = item["part_number"]
        part = part_lookup.get(pn) or {}
        attributes = part.get("attributes") or {}
        name = part.get("name", pn)
        can_optimize = True
        raw = attributes.get("can_weight_optimized")
        if raw is not None:
            can_optimize = bool(raw)
        unit_weight = None
        raw_uw = attributes.get(UNIT_WEIGHT_KEY)
        if raw_uw is not None:
            try:
                unit_weight = float(raw_uw)
            except (TypeError, ValueError):
                pass

        if exclude_non_optimizable and not can_optimize:
            continue

        contribution = float(item.get("total_contribution", 0.0))
        pct = (contribution / total_weight * 100) if total_weight else 0.0
        # Total qty in assembly = contribution / unit_weight — the leverage: how many
        # times this part's weight counts.
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
    return [
        {
            "Part Number": item["part_number"],
            "Path": " -> ".join(item.get("path", [])),
            "Multiplier": item["multiplier"],
            "Unit Weight": item["unit_weight"],
            "Maturity Factor": item["maturity_factor"],
            "Effective Weight": item["effective_unit_weight"],
            "Contribution": item["contribution"],
        }
        for item in rows
    ]


def render_reduction(
    rollup_data: dict[str, Any],
    part_lookup: dict[str, dict[str, Any]],
) -> None:
    """Rank parts by how much assembly weight a redesign of each could save."""
    st.caption(
        "Parts ranked by their total contribution to the assembly weight — the bigger the "
        "contribution, the more a redesign of that part is worth."
    )

    filter_col, slider_col = st.columns(2)
    with filter_col:
        exclude_non_optimizable = st.checkbox(
            "Exclude parts marked as non-optimizable",
            value=False,
            help="Hide parts where can_weight_optimized = false",
        )
    total_weight = float(rollup_data.get("total", 0) or 0)
    opp_rows = _build_opportunity_table(
        rollup_data.get("part_totals", []),
        total_weight,
        part_lookup,
        exclude_non_optimizable,
    )
    with slider_col:
        top_n = st.slider(
            "Top contributors to show",
            min_value=1,
            max_value=max(2, len(opp_rows)),
            value=min(15, max(2, len(opp_rows))),
        )

    optimizable_weight = sum(r["Assy Contribution"] for r in opp_rows if r["Optimizable"] == "Yes")
    non_optimizable_weight = sum(r["Assy Contribution"] for r in opp_rows if r["Optimizable"] == "No")

    m1, m2, m3 = st.columns(3)
    m1.metric("Assembly Weight", f"{total_weight:,.2f}")
    m2.metric("Optimizable Weight", f"{optimizable_weight:,.2f}")
    m3.metric("Not Optimizable", f"{non_optimizable_weight:,.2f}")

    # ── Bar chart: top contributors ───────────────────────────────────────────
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
        bar_chart = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("Contribution:Q", title="Weight Contribution"),
                y=alt.Y("Part:N", sort="-x", title=None),
                color=alt.Color(
                    "Optimizable:N",
                    scale=alt.Scale(domain=["Yes", "No"], range=["#2196F3", "#9E9E9E"]),
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
        st.altair_chart(bar_chart, width="stretch")
    else:
        st.info("No contributors to display with current filters.")
        return

    # ── Opportunity table ─────────────────────────────────────────────────────
    st.markdown("**Optimization Opportunity Ranking**")
    st.caption(
        "'If UW' columns show how much assembly weight drops if that part's unit weight is "
        "reduced by 5%, 10%, or 20%. Total Qty shows how many times the part's weight counts."
    )
    import pandas as pd

    st.dataframe(
        pd.DataFrame(opp_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "% of Assembly": st.column_config.ProgressColumn(
                "% of Assembly", format="%.1f%%", min_value=0, max_value=100
            ),
            "Unit Weight": st.column_config.NumberColumn(format="%.3f"),
            "Assy Contribution": st.column_config.NumberColumn(format="%.3f"),
            "If UW -5%": st.column_config.NumberColumn(format="%.3f"),
            "If UW -10%": st.column_config.NumberColumn(format="%.3f"),
            "If UW -20%": st.column_config.NumberColumn(format="%.3f"),
        },
    )

    with st.expander("Path Breakdown (all nodes)"):
        bd = _breakdown_rows(rollup_data.get("breakdown", []))
        if bd:
            st.dataframe(bd, width="stretch", hide_index=True)
        else:
            st.info("No breakdown data.")
