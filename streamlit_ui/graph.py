from __future__ import annotations

from typing import Any


def _escape_dot_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_bom_graph_dot(
    parts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    max_nodes: int,
) -> dict[str, Any]:
    if max_nodes < 1:
        max_nodes = 1

    part_name_by_number = {
        str(item.get("part_number", "")).strip(): str(item.get("name", "")).strip()
        for item in parts
        if str(item.get("part_number", "")).strip()
    }

    adjacency: dict[str, list[str]] = {}
    indegree: dict[str, int] = {}
    all_nodes: set[str] = set()
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child = str(rel.get("child_part_number", "")).strip()
        if not parent or not child:
            continue
        all_nodes.add(parent)
        all_nodes.add(child)
        adjacency.setdefault(parent, []).append(child)
        indegree.setdefault(parent, 0)
        indegree[child] = indegree.get(child, 0) + 1

    all_nodes.update(part_name_by_number.keys())

    if not all_nodes:
        return {
            "dot": 'digraph BOM { label="No data"; labelloc="t"; fontsize=14; }',
            "shown_nodes": 0,
            "total_nodes": 0,
            "shown_edges": 0,
            "total_edges": len(relationships),
        }

    root_candidates = sorted([node for node in all_nodes if indegree.get(node, 0) == 0])
    traversal_seed = root_candidates if root_candidates else sorted(all_nodes)

    ordered_nodes: list[str] = []
    selected: set[str] = set()
    queue = list(traversal_seed)
    queue_index = 0

    while queue_index < len(queue) and len(ordered_nodes) < max_nodes:
        node = queue[queue_index]
        queue_index += 1
        if node in selected:
            continue
        selected.add(node)
        ordered_nodes.append(node)
        for child in sorted(adjacency.get(node, [])):
            if child not in selected:
                queue.append(child)

    if len(ordered_nodes) < max_nodes:
        for node in sorted(all_nodes):
            if len(ordered_nodes) >= max_nodes:
                break
            if node in selected:
                continue
            selected.add(node)
            ordered_nodes.append(node)

    edge_lines: list[str] = []
    shown_edges = 0
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child = str(rel.get("child_part_number", "")).strip()
        if parent not in selected or child not in selected:
            continue
        shown_edges += 1
        qty = rel.get("qty")
        qty_label = "" if qty is None else f' [label="qty: {_escape_dot_label(str(qty))}"]'
        edge_lines.append(f'  "{_escape_dot_label(parent)}" -> "{_escape_dot_label(child)}"{qty_label};')

    node_lines: list[str] = []
    for node in ordered_nodes:
        node_name = part_name_by_number.get(node, "")
        label = node if not node_name else f"{node}\\n{node_name}"
        node_lines.append(f'  "{_escape_dot_label(node)}" [label="{_escape_dot_label(label)}"];')

    dot = "\n".join(
        [
            "digraph BOM {",
            "  rankdir=LR;",
            '  graph [bgcolor="transparent"];',
            '  node [shape=box style="rounded,filled" fillcolor="#E6FFFA" color="#0f766e" fontname="Helvetica"];',
            '  edge [color="#334155" fontname="Helvetica"];',
            *node_lines,
            *edge_lines,
            "}",
        ]
    )

    return {
        "dot": dot,
        "shown_nodes": len(ordered_nodes),
        "total_nodes": len(all_nodes),
        "shown_edges": shown_edges,
        "total_edges": len(relationships),
    }
