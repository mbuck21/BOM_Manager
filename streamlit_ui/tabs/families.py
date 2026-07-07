from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_ui.rollup_views import (
    ATTR_MODE_PREFIX,
    FAMILY_MODE,
    group_contributions,
)

FAMILY_OPTION = "Part family (base number)"


def render_group_by(
    rollup_data: dict[str, Any],
    parts: list[dict[str, Any]],
    attribute_columns: list[str],
) -> None:
    """Weight rollup grouped by drawing family or by any user-defined column."""
    st.caption(
        "See where the weight sits by **drawing family** (parts sharing a base number are "
        "variants of one design) or by **any column you've added** — category, weight basis, "
        "zone… whatever your program tracks."
    )

    options = [FAMILY_OPTION] + [f"Column: {column}" for column in attribute_columns]
    choice = st.selectbox("Group parts by", options=options)
    mode = FAMILY_MODE if choice == FAMILY_OPTION else ATTR_MODE_PREFIX + choice.removeprefix("Column: ")

    part_totals = rollup_data.get("part_totals", [])
    if not part_totals:
        st.info("No weight contributions to group for this assembly.")
        return

    groups = group_contributions(part_totals, parts, mode)
    total_weight = float(rollup_data.get("total", 0) or 0)

    m1, m2, m3 = st.columns(3)
    m1.metric("Assembly Weight", f"{total_weight:,.2f}")
    m2.metric("Groups", len(groups))
    if groups:
        m3.metric(
            f"Largest: {groups[0]['group']}",
            f"{groups[0]['total']:,.2f}",
            f"{groups[0]['pct']:.1f}% of assembly",
            delta_color="off",
        )

    # ── Bar chart of top groups ───────────────────────────────────────────────
    chart_groups = groups[:15]
    if chart_groups:
        import altair as alt
        import pandas as pd

        labels = [
            f"{g['group']}" + (f" — {g['label']}" if g["label"] and mode == FAMILY_MODE else "")
            for g in chart_groups
        ]
        chart_df = pd.DataFrame(
            {
                "Group": labels,
                "Weight": [g["total"] for g in chart_groups],
                "Parts": [g["part_count"] for g in chart_groups],
            }
        )
        chart = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusEnd=4, color="#4C78A8")
            .encode(
                x=alt.X("Weight:Q", title="Weight Contribution"),
                y=alt.Y("Group:N", sort="-x", title=None),
                tooltip=[
                    alt.Tooltip("Group:N"),
                    alt.Tooltip("Weight:Q", format=",.3f"),
                    alt.Tooltip("Parts:Q"),
                ],
            )
            .properties(height=max(len(chart_groups) * 28, 200))
        )
        st.altair_chart(chart, width="stretch")

    # ── Group table ───────────────────────────────────────────────────────────
    table_rows = [
        {
            "Group": g["group"],
            "Name": g["label"],
            "Parts": g["part_count"],
            "Occurrences": g["occurrences"],
            "Weight": round(g["total"], 3),
            "% of Assembly": round(g["pct"], 2),
        }
        for g in groups
    ]
    st.dataframe(
        table_rows,
        width="stretch",
        hide_index=True,
        column_config={
            "% of Assembly": st.column_config.ProgressColumn(
                "% of Assembly", format="%.1f%%", min_value=0, max_value=100
            ),
            "Weight": st.column_config.NumberColumn(format="%.3f"),
        },
    )

    # ── Member drill-down ─────────────────────────────────────────────────────
    group_keys = [g["group"] for g in groups]
    picked = st.selectbox("Show the parts inside a group", options=group_keys)
    picked_group = next((g for g in groups if g["group"] == picked), None)
    if picked_group:
        member_rows = [
            {
                "Part Number": m["part_number"],
                "Name": m["name"],
                "Occurrences": m["occurrences"],
                "Weight": round(m["contribution"], 3),
                "% of Group": round(
                    (m["contribution"] / picked_group["total"] * 100.0)
                    if picked_group["total"] > 0
                    else 0.0,
                    1,
                ),
            }
            for m in picked_group["members"]
        ]
        st.dataframe(member_rows, width="stretch", hide_index=True)

    st.caption(
        "Weight is counted where a part carries its own unit weight. Assemblies that roll up "
        "from children appear through those children's groups."
    )
