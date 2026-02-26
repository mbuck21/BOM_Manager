from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext, _build_snapshot_backend
from streamlit_ui.helpers import format_timestamp, show_service_result


def _run_weight_rollup(snapshot_record: dict[str, Any], root_part_number: str) -> dict[str, Any] | None:
    """Build a temp backend from snapshot data and run weight rollup."""
    backend = _build_snapshot_backend(snapshot_record)
    result = backend.rollups.rollup_weight_with_maturity(
        root_part_number=root_part_number,
        include_root=True,
    )
    if result.get("ok"):
        return result["data"]
    return None


def _part_name_lookup(snapshot_record: dict[str, Any]) -> dict[str, str]:
    """Build a part_number -> name map from a snapshot record."""
    return {
        p["part_number"]: p.get("name", "")
        for p in snapshot_record.get("parts", [])
    }


def _render_weight_impact(
    snapshot_backend: Any,
    snapshot_a: dict[str, Any],
    snapshot_b: dict[str, Any],
) -> None:
    """Compute and display weight rollup comparison between two snapshots."""
    snap_a_full = snapshot_backend.snapshots.get_snapshot(snapshot_a["snapshot_id"])
    snap_b_full = snapshot_backend.snapshots.get_snapshot(snapshot_b["snapshot_id"])

    if not snap_a_full.get("ok") or not snap_b_full.get("ok"):
        st.warning("Could not load full snapshot data for weight analysis.")
        return

    record_a = snap_a_full["data"]["snapshot"]
    record_b = snap_b_full["data"]["snapshot"]

    weight_a = _run_weight_rollup(record_a, snapshot_a["root_part_number"])
    weight_b = _run_weight_rollup(record_b, snapshot_b["root_part_number"])

    if not weight_a or not weight_b:
        st.warning("Could not compute weight rollup for one or both snapshots.")
        return

    total_a = weight_a["total"]
    total_b = weight_b["total"]
    delta = total_b - total_a
    pct = (delta / total_a * 100) if total_a != 0 else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Snapshot A Total Weight", f"{total_a:,.0f} lbs")
    col2.metric("Snapshot B Total Weight", f"{total_b:,.0f} lbs")
    col3.metric("Weight Delta", f"{delta:+,.0f} lbs", delta=f"{pct:+.1f}%")

    # Per-part weight comparison
    parts_a_weights = {p["part_number"]: p["total_contribution"] for p in weight_a.get("part_totals", [])}
    parts_b_weights = {p["part_number"]: p["total_contribution"] for p in weight_b.get("part_totals", [])}

    names_a = _part_name_lookup(record_a)
    names_b = _part_name_lookup(record_b)
    all_names = {**names_a, **names_b}

    all_part_numbers = sorted(set(parts_a_weights) | set(parts_b_weights))

    weight_changes = []
    for pn in all_part_numbers:
        wa = parts_a_weights.get(pn, 0.0)
        wb = parts_b_weights.get(pn, 0.0)
        d = wb - wa
        if abs(d) < 0.001:
            continue
        weight_changes.append({
            "Part Number": pn,
            "Name": all_names.get(pn, ""),
            "Weight A (lbs)": round(wa),
            "Weight B (lbs)": round(wb),
            "Delta (lbs)": round(d),
        })

    weight_changes.sort(key=lambda r: abs(r["Delta (lbs)"]), reverse=True)

    if weight_changes:
        st.markdown("**Parts with Weight Changes**")
        st.dataframe(weight_changes, use_container_width=True, hide_index=True)
    else:
        st.info("No per-part weight changes detected between snapshots.")


def _render_structural_changes(diff_data: dict[str, Any]) -> None:
    """Display the structural diff between two snapshots."""
    part_changes = diff_data["part_changes"]
    rel_changes = diff_data["relationship_changes"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Parts Added", len(part_changes["added"]))
    m2.metric("Parts Removed", len(part_changes["removed"]))
    m3.metric("Parts Modified", len(part_changes["modified"]))
    m4.metric("Rels Added", len(rel_changes["added"]))
    m5.metric("Rels Removed", len(rel_changes["removed"]))

    if part_changes["added"]:
        st.markdown("**Added Parts**")
        st.dataframe(
            [{"Part Number": p["part_number"], "Name": p["name"]} for p in part_changes["added"]],
            use_container_width=True,
            hide_index=True,
        )

    if part_changes["removed"]:
        st.markdown("**Removed Parts**")
        st.dataframe(
            [{"Part Number": p["part_number"], "Name": p["name"]} for p in part_changes["removed"]],
            use_container_width=True,
            hide_index=True,
        )

    if part_changes["modified"]:
        st.markdown("**Modified Parts**")
        mod_rows = []
        for mod in part_changes["modified"]:
            changes = mod["changes"]
            details: list[str] = []
            if changes.get("name"):
                details.append(f"Name: {changes['name']['before']} \u2192 {changes['name']['after']}")
            attrs = changes.get("attributes", {})
            for key, val in attrs.get("added", {}).items():
                details.append(f"+{key}: {val}")
            for key, val in attrs.get("removed", {}).items():
                details.append(f"-{key}: {val}")
            for key, val in attrs.get("modified", {}).items():
                details.append(f"{key}: {val['before']} \u2192 {val['after']}")
            mod_rows.append({
                "Part Number": mod["part_number"],
                "Changes": "; ".join(details) if details else "timestamps only",
            })
        st.dataframe(mod_rows, use_container_width=True, hide_index=True)

    if rel_changes["added"]:
        st.markdown("**Added Relationships**")
        st.dataframe(
            [
                {"Parent": r["parent_part_number"], "Child": r["child_part_number"], "Qty": r["qty"]}
                for r in rel_changes["added"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    if rel_changes["removed"]:
        st.markdown("**Removed Relationships**")
        st.dataframe(
            [
                {"Parent": r["parent_part_number"], "Child": r["child_part_number"], "Qty": r["qty"]}
                for r in rel_changes["removed"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    if rel_changes["modified"]:
        st.markdown("**Modified Relationships**")
        mod_rel_rows = []
        for mod in rel_changes["modified"]:
            changes = mod["changes"]
            details: list[str] = []
            if changes.get("qty"):
                details.append(f"Qty: {changes['qty']['before']} \u2192 {changes['qty']['after']}")
            if changes.get("parent_part_number"):
                details.append(
                    f"Parent: {changes['parent_part_number']['before']} \u2192 {changes['parent_part_number']['after']}"
                )
            if changes.get("child_part_number"):
                details.append(
                    f"Child: {changes['child_part_number']['before']} \u2192 {changes['child_part_number']['after']}"
                )
            attrs = changes.get("attributes", {})
            for key, val in attrs.get("added", {}).items():
                details.append(f"+{key}: {val}")
            for key, val in attrs.get("removed", {}).items():
                details.append(f"-{key}: {val}")
            for key, val in attrs.get("modified", {}).items():
                details.append(f"{key}: {val['before']} \u2192 {val['after']}")
            mod_rel_rows.append({
                "Rel ID": mod["rel_id"],
                "Changes": "; ".join(details) if details else "timestamps only",
            })
        st.dataframe(mod_rel_rows, use_container_width=True, hide_index=True)

    has_any = any([
        part_changes["added"], part_changes["removed"], part_changes["modified"],
        rel_changes["added"], rel_changes["removed"], rel_changes["modified"],
    ])
    if not has_any:
        st.info("No structural changes detected between these snapshots.")

    if diff_data["signature_equal"]:
        st.success("Snapshots are identical (signatures match).")


def render_analysis_tab(ctx: AppContext, root_part_number: str) -> None:
    snapshot_backend = ctx.live_backend

    st.subheader("Compare Snapshots")
    latest_snapshots_result = snapshot_backend.snapshots.list_snapshots()
    if not latest_snapshots_result.get("ok"):
        show_service_result("List snapshots", latest_snapshots_result)
        return

    latest_snapshots = latest_snapshots_result["data"]["snapshots"]
    if len(latest_snapshots) < 2:
        st.info("Create at least two snapshots to run a comparison.")
        return

    snapshot_labels = []
    for item in latest_snapshots:
        label_part = f" ({item['label']})" if item.get("label") else ""
        ts = format_timestamp(item["created_at"])
        snapshot_labels.append(
            f"{item['root_part_number']}{label_part} \u2014 {ts} [{item['snapshot_id'][-12:]}]"
        )

    default_a = max(0, len(snapshot_labels) - 2)
    default_b = max(0, len(snapshot_labels) - 1)

    col_a, col_b = st.columns(2)
    with col_a:
        selection_a = st.selectbox("Snapshot A (Before)", options=snapshot_labels, index=default_a)
    with col_b:
        selection_b = st.selectbox("Snapshot B (After)", options=snapshot_labels, index=default_b)

    map_label_to_snapshot = dict(zip(snapshot_labels, latest_snapshots))

    if not st.button("Run Comparison", key="run_comparison_btn"):
        return

    snapshot_a = map_label_to_snapshot[selection_a]
    snapshot_b = map_label_to_snapshot[selection_b]

    if snapshot_a["root_part_number"] != snapshot_b["root_part_number"]:
        st.warning(
            f"These snapshots have different roots: "
            f"**{snapshot_a['root_part_number']}** vs **{snapshot_b['root_part_number']}**. "
            f"Weight comparison may not be meaningful."
        )

    # Run structural diff
    compare_result = snapshot_backend.diff.compare_snapshots(
        snapshot_a["snapshot_id"],
        snapshot_b["snapshot_id"],
    )
    if not compare_result.get("ok"):
        show_service_result("Compare snapshots", compare_result)
        return

    # Weight impact
    st.divider()
    st.subheader("Weight Impact")
    _render_weight_impact(snapshot_backend, snapshot_a, snapshot_b)

    # Structural changes
    st.divider()
    st.subheader("Structural Changes")
    _render_structural_changes(compare_result["data"])
