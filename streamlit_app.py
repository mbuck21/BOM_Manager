from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext, build_app_context
from streamlit_ui.helpers import resolve_data_dir
from streamlit_ui.tabs import (
    render_analysis_tab,
    render_csv_tab,
    render_dashboard_tab,
    render_parts_tab,
    render_relationships_tab,
    render_weight_analysis_tab,
)

LIVE_DATA_OPTION = "__live_data__"
DATA_DIR_KEY = "data_dir"
DATA_DIR_INPUT_KEY = "data_dir_input"
ACTIVE_SNAPSHOT_ID_KEY = "active_snapshot_id"
SNAPSHOT_SELECTION_INITIALIZED_KEY = "snapshot_selection_initialized"
SNAPSHOT_SELECTION_DATA_DIR_KEY = "snapshot_selection_data_dir"
UNIVERSAL_ROOT_PART_KEY = "universal_root_part_number"
ROOT_DIRECTORY_FILTER_KEY = "root_directory_filter"


def _safe_widget_key(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)


def _part_label(part_number: str, part_lookup: dict[str, dict[str, Any]]) -> str:
    part_name = str(part_lookup.get(part_number, {}).get("name", "")).strip()
    if part_name:
        return f"{part_number}  |  {part_name}"
    return part_number


def _compute_subtree_weights(
    part_numbers: list[str],
    part_lookup: dict[str, dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute effective subtree weight for each part, matching rollup_weight_with_maturity logic."""
    children_qty: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child = str(rel.get("child_part_number", "")).strip()
        if not parent or not child:
            continue
        try:
            qty = float(rel.get("qty", 1) or 1)
        except (TypeError, ValueError):
            qty = 1.0
        children_qty[parent].append((child, qty))

    def get_unit_weight(pn: str) -> float | None:
        attrs = part_lookup.get(pn, {}).get("attributes") or {}
        raw_uw = attrs.get("unit_weight")
        if raw_uw is None:
            return None
        try:
            uw = float(raw_uw)
        except (TypeError, ValueError):
            return None
        try:
            mf = float(attrs.get("maturity_factor") or 1.0)
        except (TypeError, ValueError):
            mf = 1.0
        return uw * (mf if mf > 0 else 1.0)

    memo: dict[str, float] = {}

    def dfs(pn: str, visiting: set[str]) -> float:
        if pn in memo:
            return memo[pn]
        if pn in visiting:
            return 0.0
        visiting.add(pn)
        uw = get_unit_weight(pn)
        if uw is not None:
            result = uw
        else:
            result = sum(qty * dfs(child, visiting) for child, qty in children_qty.get(pn, []))
        visiting.discard(pn)
        memo[pn] = result
        return result

    for pn in part_numbers:
        dfs(pn, set())
    return memo


def _root_candidates(
    part_numbers: list[str],
    relationships: list[dict[str, Any]],
) -> list[str]:
    if not part_numbers:
        return []

    indegree: dict[str, int] = {part_number: 0 for part_number in part_numbers}
    part_number_set = set(part_numbers)
    for relationship in relationships:
        parent = str(relationship.get("parent_part_number", "")).strip()
        child = str(relationship.get("child_part_number", "")).strip()
        if parent not in part_number_set or child not in part_number_set:
            continue
        indegree[child] += 1

    root_parts = sorted(
        part_number
        for part_number in part_numbers
        if indegree.get(part_number, 0) == 0
    )
    return root_parts or sorted(part_numbers)


def _children_by_parent(relationships: list[dict[str, Any]]) -> dict[str, list[str]]:
    child_map: dict[str, set[str]] = defaultdict(set)
    for relationship in relationships:
        parent = str(relationship.get("parent_part_number", "")).strip()
        child = str(relationship.get("child_part_number", "")).strip()
        if not parent or not child:
            continue
        child_map[parent].add(child)

    return {
        parent: sorted(children)
        for parent, children in child_map.items()
    }


def _set_universal_root(part_number: str) -> None:
    if part_number == st.session_state.get(UNIVERSAL_ROOT_PART_KEY):
        return
    st.session_state[UNIVERSAL_ROOT_PART_KEY] = part_number
    st.rerun()


def _render_directory_node(
    container: Any,
    part_number: str,
    part_lookup: dict[str, dict[str, Any]],
    children_map: dict[str, list[str]],
    path: tuple[str, ...],
    active_root: str = "",
    weight_map: dict[str, float] | None = None,
    depth: int = 0,
    max_depth: int = 12,
) -> None:
    label = _part_label(part_number, part_lookup)
    is_active = part_number == active_root
    display_label = f"★ {label}" if is_active else label
    node_key = "__".join(_safe_widget_key(item) for item in path)
    children = children_map.get(part_number, [])
    visible_children = [child for child in children if child in part_lookup and child not in path]
    if weight_map:
        visible_children = sorted(visible_children, key=lambda c: (-weight_map.get(c, 0), c))

    if visible_children and depth < max_depth:
        should_expand = depth == 0 or is_active
        expander = container.expander(display_label, expanded=should_expand)
        if is_active:
            expander.caption("Current root")
        elif expander.button("Use as root", key=f"root_pick_{node_key}"):
            _set_universal_root(part_number)
        for child in visible_children:
            _render_directory_node(
                expander,
                child,
                part_lookup,
                children_map,
                (*path, child),
                active_root=active_root,
                weight_map=weight_map,
                depth=depth + 1,
                max_depth=max_depth,
            )

        cycle_nodes = [child for child in children if child in path]
        if cycle_nodes:
            expander.caption("Cycle detected: " + ", ".join(cycle_nodes))
        return

    if is_active:
        container.markdown(f"**★ {label}**")
        container.caption("Current root")
    elif container.button(display_label, key=f"root_leaf_pick_{node_key}"):
        _set_universal_root(part_number)
    if depth >= max_depth and children:
        container.caption("Depth limit reached for this branch.")


def render_root_sidebar(ctx: AppContext) -> str:
    st.sidebar.subheader("Root Part Directory")

    part_lookup = {
        str(item.get("part_number", "")).strip(): item
        for item in ctx.parts
        if str(item.get("part_number", "")).strip()
    }
    part_numbers = sorted(part_lookup.keys())
    if not part_numbers:
        st.sidebar.info("No parts available. Add parts or load a snapshot first.")
        st.session_state[UNIVERSAL_ROOT_PART_KEY] = ""
        return ""

    available_roots = _root_candidates(part_numbers, ctx.relationships)
    active_root = st.session_state.get(UNIVERSAL_ROOT_PART_KEY)
    if active_root not in part_numbers:
        active_root = available_roots[0]
        st.session_state[UNIVERSAL_ROOT_PART_KEY] = active_root

    weight_map = _compute_subtree_weights(part_numbers, part_lookup, ctx.relationships)
    available_roots = sorted(available_roots, key=lambda pn: (-weight_map.get(pn, 0), pn))

    active_label = _part_label(active_root, part_lookup)
    st.sidebar.info(f"**Active root:**\n\n{active_label}", icon="📍")

    query = st.sidebar.text_input(
        "Find part",
        key=ROOT_DIRECTORY_FILTER_KEY,
        placeholder="Type to filter by number or name…",
    ).strip()
    if query:
        query_lower = query.lower()
        matches = [
            part_number
            for part_number in part_numbers
            if query_lower in part_number.lower()
            or query_lower in str(part_lookup.get(part_number, {}).get("name", "")).lower()
        ]
        if matches:
            n = len(matches)
            st.sidebar.caption(f"{n} match{'es' if n != 1 else ''} found")
            if n == 1:
                _set_universal_root(matches[0])
            else:
                selected_match = st.sidebar.selectbox(
                    "Matches",
                    options=matches,
                    format_func=lambda part_number: _part_label(part_number, part_lookup),
                    key="root_directory_match_selector",
                )
                if st.sidebar.button("Use as root", key="apply_root_match_selector"):
                    _set_universal_root(selected_match)
        else:
            st.sidebar.caption("No matches.")
        st.sidebar.divider()

    st.sidebar.caption("Browse the tree below. Click a part to set it as root.")
    children_map = _children_by_parent(ctx.relationships)
    for root_part_number in available_roots:
        _render_directory_node(
            st.sidebar,
            root_part_number,
            part_lookup,
            children_map,
            (root_part_number,),
            active_root=active_root,
            weight_map=weight_map,
        )

    return st.session_state.get(UNIVERSAL_ROOT_PART_KEY, "")


def _snapshot_option_label(snapshot: dict[str, Any], latest_snapshot_id: str | None) -> str:
    snapshot_id = str(snapshot.get("snapshot_id", "")).strip()
    root_part_number = str(snapshot.get("root_part_number", "")).strip() or "(none)"
    created_at = str(snapshot.get("created_at", "")).strip() or "(unknown time)"
    label = str(snapshot.get("label", "")).strip()
    label_suffix = f" | label: {label}" if label else ""
    latest_suffix = " | latest" if snapshot_id == latest_snapshot_id else ""
    return f"{snapshot_id} | root: {root_part_number} | {created_at}{label_suffix}{latest_suffix}"


def render_snapshot_selector(ctx: AppContext) -> None:
    st.subheader("Snapshot View")

    if not ctx.snapshots:
        st.info("No snapshots found. Using live data.")
        return

    snapshot_lookup = {
        str(snapshot.get("snapshot_id", "")).strip(): snapshot
        for snapshot in ctx.snapshots
        if str(snapshot.get("snapshot_id", "")).strip()
    }
    snapshot_ids = [snapshot_id for snapshot_id in reversed(list(snapshot_lookup.keys()))]
    option_ids = [LIVE_DATA_OPTION] + snapshot_ids
    current_option = ctx.loaded_snapshot_id or LIVE_DATA_OPTION
    if current_option not in option_ids:
        current_option = LIVE_DATA_OPTION

    selected_option = st.selectbox(
        "Loaded dataset",
        options=option_ids,
        index=option_ids.index(current_option),
        format_func=lambda option_id: (
            "Live Data (current repository state)"
            if option_id == LIVE_DATA_OPTION
            else _snapshot_option_label(snapshot_lookup[option_id], ctx.latest_snapshot_id)
        ),
    )

    selected_snapshot_id = None if selected_option == LIVE_DATA_OPTION else selected_option
    if selected_snapshot_id != ctx.loaded_snapshot_id:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = selected_snapshot_id
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = True
        st.rerun()

    if ctx.loaded_snapshot_id:
        latest_flag = "Yes" if ctx.is_latest_snapshot_loaded else "No"
        st.caption(f"Loaded snapshot: `{ctx.loaded_snapshot_id}`")
        st.caption(f"Is latest: `{latest_flag}`")
        if ctx.latest_snapshot_id and ctx.latest_snapshot_id != ctx.loaded_snapshot_id:
            st.caption(f"Latest available: `{ctx.latest_snapshot_id}`")
    else:
        st.caption("Loaded snapshot: `None (live data)`")
        if ctx.latest_snapshot_id:
            st.caption(f"Latest available: `{ctx.latest_snapshot_id}`")


def render_data_snapshot_tab(ctx: AppContext) -> None:
    st.subheader("Data Directory")

    if DATA_DIR_INPUT_KEY not in st.session_state:
        st.session_state[DATA_DIR_INPUT_KEY] = st.session_state.get(DATA_DIR_KEY, "demo_data")

    entered_data_dir = st.text_input("Data directory", key=DATA_DIR_INPUT_KEY)
    if entered_data_dir != st.session_state.get(DATA_DIR_KEY, "demo_data"):
        st.session_state[DATA_DIR_KEY] = entered_data_dir
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = None
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = False
        st.rerun()

    data_dir = resolve_data_dir(st.session_state.get(DATA_DIR_KEY, "demo_data"))
    repo_root = Path.cwd().resolve()
    st.caption(f"Resolved path: `{data_dir}`")
    st.code("streamlit run streamlit_app.py", language="bash")

    if st.button("Reset Data Directory", key="reset_data_dir_btn"):
        if data_dir == repo_root:
            st.error("Refusing to delete repository root.")
        elif repo_root not in data_dir.parents:
            st.error("Reset is only allowed for directories inside this repository.")
        else:
            if data_dir.exists():
                shutil.rmtree(data_dir)
            st.success(f"Cleared {data_dir}")
            st.rerun()

    st.divider()
    render_snapshot_selector(ctx)


def render_metrics(parts_count: int, relationships_count: int, snapshots_count: int) -> None:
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    metric_col1.metric("Parts", parts_count)
    metric_col2.metric("Relationships", relationships_count)
    metric_col3.metric("Snapshots", snapshots_count)


def main() -> None:
    st.set_page_config(page_title="Mass Allocation Tracking Tool", layout="wide")
    st.markdown(
        """
        <style>
        .main .block-container {
            max-width: 1600px;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        [data-testid="stSidebar"] {
            min-width: 380px;
            max-width: 380px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Mass Allocation Tracking Tool")
    st.caption("Interactive Tool for Mass Roll up, parts, relationships, and snapshots.")

    if DATA_DIR_KEY not in st.session_state:
        st.session_state[DATA_DIR_KEY] = "demo_data"
    if DATA_DIR_INPUT_KEY not in st.session_state:
        st.session_state[DATA_DIR_INPUT_KEY] = st.session_state[DATA_DIR_KEY]

    data_dir = resolve_data_dir(st.session_state[DATA_DIR_KEY])
    data_dir_marker = str(data_dir.resolve())
    if st.session_state.get(SNAPSHOT_SELECTION_DATA_DIR_KEY) != data_dir_marker:
        st.session_state[SNAPSHOT_SELECTION_DATA_DIR_KEY] = data_dir_marker
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = False
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = None

    selection_initialized = bool(st.session_state.get(SNAPSHOT_SELECTION_INITIALIZED_KEY, False))
    selected_snapshot_id = st.session_state.get(ACTIVE_SNAPSHOT_ID_KEY)
    ctx = build_app_context(
        data_dir,
        selected_snapshot_id=selected_snapshot_id,
        default_to_latest=not selection_initialized,
    )

    if not selection_initialized:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = ctx.loaded_snapshot_id
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = True
    elif selected_snapshot_id != ctx.loaded_snapshot_id:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = ctx.loaded_snapshot_id

    universal_root = render_root_sidebar(ctx)





    (
        tab_dashboard,
        tab_data_snapshot,
        tab_parts,
        tab_relationships,
        tab_analysis,
        tab_weight,
        tab_csv,
    ) = st.tabs(
        ["Dashboard", "Data & Snapshots", "Parts", "Relationships", "Analysis", "Weight Analysis", "CSV"]
    )

    with tab_dashboard:
        render_dashboard_tab(ctx, root_part_number=universal_root, root_state_key=UNIVERSAL_ROOT_PART_KEY)
    
    with tab_data_snapshot:
        render_data_snapshot_tab(ctx)

    with tab_parts:
        render_parts_tab(ctx)

    with tab_relationships:
        render_relationships_tab(ctx)

    with tab_analysis:
        render_analysis_tab(ctx, root_part_number=universal_root)

    with tab_weight:
        render_weight_analysis_tab(ctx, root_part_number=universal_root)

    with tab_csv:
        render_csv_tab(ctx)

    st.divider()
    st.subheader("Debug Metrics")

    render_metrics(
        parts_count=len(ctx.parts),
        relationships_count=len(ctx.relationships),
        snapshots_count=len(ctx.snapshots),
    )

    if ctx.loaded_snapshot_id:
        latest_flag = "Yes" if ctx.is_latest_snapshot_loaded else "No"
        st.caption(f"Loaded snapshot: `{ctx.loaded_snapshot_id}` | Is latest: `{latest_flag}`")
    else:
        st.caption("Loaded snapshot: `None (live data)`")
    if universal_root:
        st.caption(f"Universal root part: `{universal_root}`")
    else:
        st.caption("Universal root part: `None`")


if __name__ == "__main__":
    main()
