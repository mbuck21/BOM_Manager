"""History tab: save named baselines, load past versions, and reporting sub-tabs."""

from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import format_timestamp, show_service_result
from streamlit_ui.state import (
    ACTIVE_SNAPSHOT_ID_KEY,
    LIVE_DATA_OPTION,
    SNAPSHOT_SELECTION_INITIALIZED_KEY,
    UNIVERSAL_ROOT_PART_KEY,
)
from streamlit_ui.tabs.analysis import render_analysis_tab
from streamlit_ui.tabs.reports import (
    render_part_history,
    render_weekly_report,
    render_weight_over_time,
)


def _snapshot_option_label(snapshot: dict[str, Any], latest_snapshot_id: str | None) -> str:
    stamp = format_timestamp(snapshot.get("created_at", ""))
    scope = str(snapshot.get("root_part_number", "")).strip() or "whole project"
    label = str(snapshot.get("label", "")).strip()
    label_suffix = f" — {label}" if label else ""
    latest_suffix = " (latest)" if snapshot.get("snapshot_id") == latest_snapshot_id else ""
    return f"{stamp} | {scope}{label_suffix}{latest_suffix}"


def render_snapshot_selector(ctx: AppContext) -> None:
    st.subheader("View a Saved Version")

    if not ctx.snapshots:
        st.info("No saved versions yet. Using live data.")
        return

    snapshot_lookup = {
        str(snapshot.get("snapshot_id", "")).strip(): snapshot
        for snapshot in ctx.snapshots
        if str(snapshot.get("snapshot_id", "")).strip()
    }
    snapshot_ids = list(reversed(list(snapshot_lookup.keys())))
    option_ids = [LIVE_DATA_OPTION] + snapshot_ids
    current_option = ctx.loaded_snapshot_id or LIVE_DATA_OPTION
    if current_option not in option_ids:
        current_option = LIVE_DATA_OPTION

    selected_option = st.selectbox(
        "Loaded dataset",
        options=option_ids,
        index=option_ids.index(current_option),
        format_func=lambda option_id: (
            "Live Data (editable, current state)"
            if option_id == LIVE_DATA_OPTION
            else _snapshot_option_label(snapshot_lookup[option_id], ctx.latest_snapshot_id)
        ),
        help=(
            "Pick a saved version to view the whole app as it was then (read-only). "
            "Switch back to Live Data to edit."
        ),
    )

    selected_snapshot_id = None if selected_option == LIVE_DATA_OPTION else selected_option
    if selected_snapshot_id != ctx.loaded_snapshot_id:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = selected_snapshot_id
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = True
        st.rerun()

    if ctx.loaded_snapshot_id:
        st.caption(
            f"Viewing saved version `{ctx.loaded_snapshot_id}` (read-only). "
            "Everything in the app reflects that point in time."
        )
    else:
        st.caption("Viewing live data (editable).")


def render_history_tab(ctx: AppContext) -> None:
    st.subheader("Save a Version")
    st.caption(
        "Every time you press Save on the Edit tab a version is kept automatically. "
        "Use this to save a **named baseline** you can compare against later."
    )

    if ctx.snapshot_mode:
        st.info("You're viewing a saved version. Load **Live Data** below to save a new one.")

    with st.form("save_version_form"):
        version_label = st.text_input(
            "Version label",
            placeholder="PDR baseline",
            help="A name you'll recognize later — e.g. 'PDR baseline' or 'post bracket redesign'.",
        )
        submit_version = st.form_submit_button(
            "Save version now", type="primary", disabled=ctx.snapshot_mode
        )
    if submit_version:
        create_result = ctx.live_backend.snapshots.create_snapshot(
            label=version_label or None,
            deduplicate_if_identical=True,
        )
        show_service_result("Save version", create_result)

    st.divider()
    render_snapshot_selector(ctx)

    st.divider()
    universal_root = st.session_state.get(UNIVERSAL_ROOT_PART_KEY, "")
    render_weight_over_time(ctx, universal_root)

    st.divider()
    sub_report, sub_compare, sub_part = st.tabs(
        ["Weekly report", "Compare versions", "Part history"]
    )
    with sub_report:
        render_weekly_report(ctx, universal_root)
    with sub_compare:
        render_analysis_tab(ctx, root_part_number=universal_root)
    with sub_part:
        render_part_history(ctx)
