from __future__ import annotations

from typing import Any

import streamlit as st

from bom_backend.constants import WEIGHT_BUDGET_KEY
from bom_backend.utils.clock import now_iso_utc
from streamlit_ui.context import AppContext
from streamlit_ui.grid_edit import collect_attribute_columns
from streamlit_ui.report import stale_parts
from streamlit_ui.rollup_views import (
    allocation_overrides,
    attribute_coverage,
    read_weight_budget,
)
from streamlit_ui.tabs.dashboard import render_overview
from streamlit_ui.tabs.families import render_group_by
from streamlit_ui.tabs.weight_analysis import render_reduction
from streamlit_ui.helpers import show_service_result


def _grouping_columns(ctx: AppContext, parts: list[dict[str, Any]]) -> list[str]:
    """User-defined part columns: settings-declared plus any seen on parts."""
    settings = ctx.live_backend.store.read_settings()
    declared = settings.get("columns") if isinstance(settings.get("columns"), dict) else {}
    columns = set(declared) | set(collect_attribute_columns(parts))
    columns.discard(WEIGHT_BUDGET_KEY)
    return sorted(columns)


def _render_budget_row(ctx: AppContext, root_part: dict[str, Any], root_pn: str, total: float) -> None:
    budget = read_weight_budget(root_part)

    if budget is not None:
        margin = budget - total
        b_col, a_col, m_col = st.columns(3)
        b_col.metric("Weight Budget", f"{budget:,.1f} lbs")
        a_col.metric("Current Rollup", f"{total:,.1f} lbs")
        m_col.metric(
            "Margin",
            f"{margin:+,.1f} lbs",
            delta=f"{(margin / budget * 100.0):+.1f}% of budget" if budget else None,
            delta_color="normal" if margin >= 0 else "inverse",
        )
        if margin < 0:
            st.error(f"Over budget by {-margin:,.1f} lbs.", icon="🚨")
    else:
        st.caption(f"No weight budget set for `{root_pn}` yet.")

    if not ctx.snapshot_mode:
        with st.expander("Set / change budget"):
            with st.form(f"budget_form_{root_pn}"):
                new_budget = st.number_input(
                    f"Weight budget for {root_pn} (lbs)",
                    min_value=0.0,
                    value=float(budget) if budget is not None else float(round(total, 1)),
                    step=10.0,
                    format="%.1f",
                )
                save_col, clear_col = st.columns(2)
                save_clicked = save_col.form_submit_button("Save budget", type="primary")
                clear_clicked = clear_col.form_submit_button("Clear budget")

            if save_clicked or clear_clicked:
                attributes = dict(root_part.get("attributes") or {})
                if clear_clicked:
                    attributes.pop(WEIGHT_BUDGET_KEY, None)
                else:
                    attributes[WEIGHT_BUDGET_KEY] = float(new_budget)
                result = ctx.live_backend.parts.update_attributes(
                    root_pn, attributes, merge_attributes=False
                )
                if result.get("ok"):
                    ctx.live_backend.snapshots.create_snapshot(deduplicate_if_identical=True)
                    st.rerun()
                else:
                    show_service_result("Save budget", result)


def _render_data_health(
    ctx: AppContext,
    rollup_data: dict[str, Any],
    rollup_warnings: list[str],
    parts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    grouping_columns: list[str],
) -> None:
    st.caption(
        "Where the rollup needs attention: stale weights, parts that can't roll up, "
        "columns with gaps, and allocations that hide their children."
    )

    # ── Most out-of-date weighted parts ───────────────────────────────────────
    st.markdown("**Most out-of-date weights**")
    stale_rows = stale_parts(parts, now_iso_utc(), weighted_only=True)
    if stale_rows:
        st.dataframe(
            [
                {
                    "Part Number": row["part_number"],
                    "Name": row["name"],
                    "Unit Weight": row["unit_weight"],
                    "Age (days)": row["age_days"],
                }
                for row in stale_rows[:15]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No parts carry a unit weight yet.")

    # ── Unresolved nodes ──────────────────────────────────────────────────────
    unresolved = rollup_data.get("unresolved_nodes", [])
    st.markdown("**Parts that can't roll up**")
    if unresolved:
        st.caption("No unit weight of their own and no children to derive one from — they contribute 0.")
        st.dataframe(
            [
                {
                    "Part Number": row.get("part_number", ""),
                    "Where": " -> ".join(row.get("path", [])),
                    "Why": row.get("reason", ""),
                }
                for row in unresolved
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.success("Every part in this assembly resolves to a weight.")

    # ── Attribute coverage ────────────────────────────────────────────────────
    if grouping_columns:
        st.markdown("**Column coverage** (how much of the weight has each column filled in)")
        coverage = attribute_coverage(rollup_data.get("part_totals", []), parts, grouping_columns)
        st.dataframe(
            [
                {
                    "Column": row["attribute"],
                    "% of weight covered": round(row["pct"], 1),
                    "Contributing parts missing it": row["missing_parts"],
                }
                for row in coverage
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "% of weight covered": st.column_config.ProgressColumn(
                    "% of weight covered", format="%.1f%%", min_value=0, max_value=100
                ),
            },
        )

    # ── Allocations overriding children ───────────────────────────────────────
    overrides = allocation_overrides(parts, relationships)
    if overrides:
        st.markdown("**Allocated weights overriding children**")
        st.caption(
            "These parts have their own unit weight AND children. The unit weight wins "
            "(an allocation) — the children are not counted. Clear the unit weight to roll "
            "up from the children instead."
        )
        st.dataframe(
            [
                {
                    "Part Number": row["part_number"],
                    "Name": row["name"],
                    "Allocated Weight": row["unit_weight"],
                    "Children not counted": row["children_not_counted"],
                }
                for row in overrides
            ],
            width="stretch",
            hide_index=True,
        )

    # ── Rollup warnings ───────────────────────────────────────────────────────
    if rollup_warnings:
        with st.expander(f"Rollup warnings ({len(rollup_warnings)})"):
            for warning in rollup_warnings:
                st.caption(f"- {warning}")


def render_weight_tab(
    ctx: AppContext,
    root_part_number: str,
    root_state_key: str = "universal_root_part_number",
) -> None:
    if not ctx.parts_result.get("ok"):
        show_service_result("List parts", ctx.parts_result)
        return
    if not ctx.parts:
        st.info("No parts found. Add parts first or load a different version.")
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
    root_name = root_part.get("name", "")
    title = f"{root_part_number} — {root_name}" if root_name else root_part_number
    st.subheader(f"Weight Rollup for {title}")

    # ONE rollup shared by every sub-tab below.
    result = ctx.backend.rollups.rollup_weight_with_maturity(
        root_part_number=root_part_number,
        include_root=True,
        top_n=9999,
    )
    if not result.get("ok"):
        show_service_result("Weight rollup", result)
        return
    rollup_data = result["data"]
    rollup_warnings = list(result.get("warnings") or [])

    _render_budget_row(ctx, root_part, root_part_number, float(rollup_data.get("total", 0) or 0))

    grouping_columns = _grouping_columns(ctx, ctx.parts)

    tab_overview, tab_reduction, tab_groups, tab_health = st.tabs(
        ["Overview", "Reduction opportunities", "Group by", "Data health"]
    )
    with tab_overview:
        render_overview(root_part_number, rollup_data, ctx.relationships, part_lookup)
    with tab_reduction:
        render_reduction(rollup_data, part_lookup)
    with tab_groups:
        render_group_by(rollup_data, ctx.parts, grouping_columns)
    with tab_health:
        _render_data_health(
            ctx, rollup_data, rollup_warnings, ctx.parts, ctx.relationships, grouping_columns
        )
