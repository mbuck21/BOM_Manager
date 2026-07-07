"""Sidebar: the root-part directory tree, part search, and About box.

Clicking any part sets the "universal root" — the assembly the Weight & Rollup views
and report views are scoped to.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import streamlit as st

from streamlit_ui.context import AppContext
from streamlit_ui.helpers import build_part_lookup
from streamlit_ui.state import POC_LINE, ROOT_DIRECTORY_FILTER_KEY, UNIVERSAL_ROOT_PART_KEY


def _safe_widget_key(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)


def _part_label(part_number: str, part_lookup: dict[str, dict[str, Any]]) -> str:
    part_name = str(part_lookup.get(part_number, {}).get("name", "")).strip()
    return f"{part_number}  |  {part_name}" if part_name else part_number


def _root_candidates(
    part_numbers: list[str],
    relationships: list[dict[str, Any]],
) -> list[str]:
    """Parts nothing points at (indegree 0) — the natural tree roots."""
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
        part_number for part_number in part_numbers if indegree.get(part_number, 0) == 0
    )
    return root_parts or sorted(part_numbers)


def _children_by_parent(relationships: list[dict[str, Any]]) -> dict[str, list[str]]:
    child_map: dict[str, set[str]] = defaultdict(set)
    for relationship in relationships:
        parent = str(relationship.get("parent_part_number", "")).strip()
        child = str(relationship.get("child_part_number", "")).strip()
        if parent and child:
            child_map[parent].add(child)
    return {parent: sorted(children) for parent, children in child_map.items()}


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
    max_depth: int = 4,
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
        container.caption("Deeper levels hidden — click 'Use as root' to drill in.")


def _render_about() -> None:
    with st.sidebar.expander("ℹ️ About / getting help"):
        st.markdown(
            "**How to use:** pick a root assembly above, edit weights on the **Edit** tab, "
            "press **Save changes**, then check **Weight & Rollup**. Every save is kept as a "
            "version on the **History** tab.\n\n"
            f"**Questions, bugs, or feature ideas?**\nContact {POC_LINE}.\n\n"
            "Full guide: see `README.md`. Built with AI assistance."
        )


def render_root_sidebar(ctx: AppContext) -> str:
    st.sidebar.subheader("Root Part Directory")

    part_lookup = build_part_lookup(ctx.parts)
    part_numbers = sorted(part_lookup.keys())
    if not part_numbers:
        st.sidebar.info("No parts available. Add parts or load a snapshot first.")
        st.session_state[UNIVERSAL_ROOT_PART_KEY] = ""
        _render_about()
        return ""

    available_roots = _root_candidates(part_numbers, ctx.relationships)
    active_root = st.session_state.get(UNIVERSAL_ROOT_PART_KEY)
    if active_root not in part_numbers:
        active_root = available_roots[0]
        st.session_state[UNIVERSAL_ROOT_PART_KEY] = active_root

    weight_result = ctx.backend.rollups.subtree_weight_map()
    weight_map = weight_result["data"]["weights"] if weight_result.get("ok") else {}
    available_roots = sorted(available_roots, key=lambda pn: (-weight_map.get(pn, 0), pn))

    active_label = _part_label(active_root, part_lookup)
    st.sidebar.info(f"**Active root:**\n\n{active_label}", icon="📍")

    query = st.sidebar.text_input(
        "Find part",
        key=ROOT_DIRECTORY_FILTER_KEY,
        placeholder="Type to filter by number or name…",
        help="Search by part number or name. A single match becomes the root automatically.",
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
                    help="Pick which match to use as the root.",
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

    _render_about()
    return st.session_state.get(UNIVERSAL_ROOT_PART_KEY, "")
