from __future__ import annotations

from typing import Any

import streamlit as st

from bom_backend.serialization import (
    part_to_record,
    relationship_to_record,
    snapshot_from_record,
)
from bom_backend.utils.clock import now_iso_utc
from streamlit_ui.context import AppContext, _build_snapshot_backend
from streamlit_ui.helpers import build_part_lookup, format_timestamp
from streamlit_ui.report import (
    build_weekly_report,
    default_baseline_index,
    part_history,
    report_to_text,
)
from streamlit_ui.rollup_views import read_weight_budget


def _version_label(snapshot: dict[str, Any]) -> str:
    stamp = format_timestamp(snapshot.get("created_at", ""))
    label = str(snapshot.get("label") or "").strip()
    suffix = f" — {label}" if label else ""
    return f"{stamp}{suffix}"


def _live_snapshot_object(ctx: AppContext, root_part_number: str):
    """In-memory Snapshot of the current live data (never saved)."""
    parts = [part_to_record(p) for p in ctx.live_backend.part_repo.list_parts()]
    relationships = [
        relationship_to_record(r) for r in ctx.live_backend.relationship_repo.list_relationships()
    ]
    return snapshot_from_record(
        {
            "snapshot_id": "__live__",
            "root_part_number": root_part_number,
            "created_at": now_iso_utc(),
            "signature": "",
            "label": "current live data",
            "parts": parts,
            "relationships": relationships,
        }
    )


def render_weight_over_time(ctx: AppContext, root_part_number: str) -> None:
    """Line chart of the selected root's rollup weight across all saved versions."""
    if not root_part_number:
        return
    snapshots = list(ctx.snapshots)
    if len(snapshots) < 2:
        return

    points: list[dict[str, Any]] = []
    for record in snapshots:  # already oldest-first
        backend = _build_snapshot_backend(record)
        result = backend.rollups.rollup_weight_with_maturity(
            root_part_number=root_part_number, include_root=True, top_n=1
        )
        if not result.get("ok"):
            continue  # root not present in this version
        points.append(
            {
                "when": str(record.get("created_at", "")).strip(),
                "weight": float(result["data"].get("total", 0) or 0),
                "version": str(record.get("label") or "").strip() or "(auto-save)",
            }
        )

    # Close the line with the data as it is right now.
    live_result = ctx.live_backend.rollups.rollup_weight_with_maturity(
        root_part_number=root_part_number, include_root=True, top_n=1
    )
    if live_result.get("ok"):
        points.append(
            {
                "when": now_iso_utc(),
                "weight": float(live_result["data"].get("total", 0) or 0),
                "version": "now (live)",
            }
        )

    if len(points) < 2:
        return

    st.markdown(f"**Weight over time — {root_part_number}**")

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(points)
    df["when"] = pd.to_datetime(df["when"], errors="coerce", utc=True)
    df = df.dropna(subset=["when"])

    line = (
        alt.Chart(df)
        .mark_line(point=True, color="#4C78A8")
        .encode(
            x=alt.X("when:T", title=None),
            y=alt.Y("weight:Q", title="Weight (lbs)", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("when:T", title="When", format="%b %d, %Y %H:%M"),
                alt.Tooltip("weight:Q", title="Weight (lbs)", format=",.1f"),
                alt.Tooltip("version:N", title="Version"),
            ],
        )
    )
    layers = [line]

    live_root = next(
        (p for p in ctx.live_backend.part_repo.list_parts() if p.part_number == root_part_number),
        None,
    )
    budget = read_weight_budget(part_to_record(live_root)) if live_root else None
    if budget is not None:
        budget_df = pd.DataFrame([{"budget": budget}])
        layers.append(
            alt.Chart(budget_df)
            .mark_rule(color="#D62728", strokeDash=[6, 4])
            .encode(y="budget:Q", tooltip=[alt.Tooltip("budget:Q", title="Budget (lbs)", format=",.1f")])
        )

    st.altair_chart(alt.layer(*layers).properties(height=260), width="stretch")
    if budget is not None:
        st.caption("Dashed red line = weight budget.")


def render_weekly_report(ctx: AppContext, root_part_number: str) -> None:
    st.caption(
        "What changed between a saved version and the data as it is right now — "
        "made to paste straight into the weekly program update."
    )

    snapshots = list(ctx.snapshots)
    if not snapshots:
        st.info("No saved versions yet. Save your first change and come back.")
        return
    if not root_part_number:
        st.info("Pick a root assembly in the sidebar first.")
        return

    newest_first = list(reversed(snapshots))
    default_index = default_baseline_index(newest_first, now_iso_utc())
    baseline_record = newest_first[
        st.selectbox(
            "Compare against (baseline)",
            options=range(len(newest_first)),
            index=default_index,
            format_func=lambda i: _version_label(newest_first[i]),
            help="Defaults to the newest version at least a week old.",
        )
    ]

    # Rollups for both sides, scoped to the current root assembly.
    baseline_backend = _build_snapshot_backend(baseline_record)
    baseline_rollup = baseline_backend.rollups.rollup_weight_with_maturity(
        root_part_number=root_part_number, include_root=True, top_n=9999
    )
    live_rollup = ctx.live_backend.rollups.rollup_weight_with_maturity(
        root_part_number=root_part_number, include_root=True, top_n=9999
    )
    if not baseline_rollup.get("ok"):
        st.warning(
            f"`{root_part_number}` can't be rolled up in that baseline "
            "(it may not exist there yet). Pick another baseline or root."
        )
        return
    if not live_rollup.get("ok"):
        st.warning(f"`{root_part_number}` can't be rolled up in the live data.")
        return

    # Structural diff: baseline vs an in-memory snapshot of live data.
    diff_result = ctx.live_backend.diff.compare_snapshot_objects(
        snapshot_from_record(baseline_record),
        _live_snapshot_object(ctx, root_part_number),
    )
    if not diff_result.get("ok"):
        for err in diff_result.get("errors", []):
            st.error(err)
        return

    # Names from live + baseline (so removed parts still resolve).
    part_lookup = build_part_lookup(baseline_record.get("parts", []))
    for p in ctx.live_backend.part_repo.list_parts():
        part_lookup[p.part_number] = part_to_record(p)

    root_part = part_lookup.get(root_part_number)
    report = build_weekly_report(
        baseline_snapshot=baseline_record,
        baseline_rollup=baseline_rollup["data"],
        live_rollup=live_rollup["data"],
        diff_data=diff_result["data"],
        part_lookup=part_lookup,
        budget=read_weight_budget(root_part),
        now_iso=now_iso_utc(),
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.metric("Baseline Weight", f"{report['total_before']:,.1f} lbs")
    c2.metric("Current Weight", f"{report['total_after']:,.1f} lbs")
    c3.metric(
        "Change",
        f"{report['delta']:+,.1f} lbs",
        delta=f"{report['delta_pct']:+.1f}%",
        delta_color="inverse",  # weight going UP is bad news
    )
    if report["budget"]:
        status = "over" if report["budget"]["over"] else "under"
        st.caption(
            f"Budget {report['budget']['budget']:,.1f} lbs — currently "
            f"{abs(report['budget']['margin']):,.1f} lbs {status} budget."
        )

    # ── Movers ────────────────────────────────────────────────────────────────
    if report["movers"]:
        st.markdown("**Top movers**")
        st.dataframe(
            [
                {
                    "": "▲" if m["delta"] > 0 else "▼",
                    "Part Number": m["part_number"],
                    "Name": m["name"],
                    "Was": round(m["before"], 2),
                    "Now": round(m["after"], 2),
                    "Change": round(m["delta"], 2),
                }
                for m in report["movers"]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No per-part weight changes since this baseline.")

    added, removed = report["added_parts"], report["removed_parts"]
    if added or removed:
        add_col, remove_col = st.columns(2)
        with add_col:
            if added:
                st.markdown(f"**Added parts ({len(added)})**")
                st.dataframe(
                    [{"Part Number": r["part_number"], "Name": r["name"]} for r in added],
                    width="stretch",
                    hide_index=True,
                )
        with remove_col:
            if removed:
                st.markdown(f"**Removed parts ({len(removed)})**")
                st.dataframe(
                    [{"Part Number": r["part_number"], "Name": r["name"]} for r in removed],
                    width="stretch",
                    hide_index=True,
                )

    st.caption(
        f"{report['modified_parts_count']} part(s) modified · {report['links_added']} link(s) "
        f"added · {report['links_removed']} removed · {report['links_modified']} changed"
    )

    # ── Copy-ready text ───────────────────────────────────────────────────────
    st.markdown("**Copy for your weekly update** (copy button in the top-right of the block)")
    st.code(report_to_text(report), language=None)


def render_part_history(ctx: AppContext) -> None:
    st.caption("Every recorded change to one part, walked across the saved versions.")

    snapshots = list(ctx.snapshots)
    if not snapshots:
        st.info("No saved versions yet — history builds up as you save.")
        return

    # Offer every part number that exists now or ever appeared in a version.
    part_numbers: set[str] = {
        p.part_number for p in ctx.live_backend.part_repo.list_parts()
    }
    for snapshot in snapshots:
        for record in snapshot.get("parts") or []:
            pn = str(record.get("part_number", "")).strip()
            if pn:
                part_numbers.add(pn)
    if not part_numbers:
        st.info("No parts to show history for.")
        return

    picked = st.selectbox(
        "Part",
        options=sorted(part_numbers),
        help="Includes parts that were later removed — their history is still in the saved versions.",
    )
    events = part_history(snapshots, picked)
    if not events:
        st.info("This part has no recorded changes in the saved versions.")
        return

    st.dataframe(
        [
            {
                "When": format_timestamp(event["created_at"]),
                "Version": event["label"] or "(auto-save)",
                "Change": event["change"],
            }
            for event in events
        ],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Changes are recorded when a version is saved. Rollup totals always recompute live, "
        "so a weight change here flowed up into every parent assembly immediately."
    )
