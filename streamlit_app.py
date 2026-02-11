from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import streamlit as st

from bom_backend import BOMBackend


def resolve_data_dir(raw_value: str) -> Path:
    candidate = Path(raw_value.strip() or "demo_data").expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


def parse_csv_whitelist(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",")]
    return [item for item in values if item]


def part_rows(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "part_number": item["part_number"],
            "name": item["name"],
            "last_updated": item["last_updated"],
            "attributes": json.dumps(item.get("attributes", {}), sort_keys=True),
        }
        for item in parts
    ]


def relationship_rows(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rel_id": item["rel_id"],
            "parent_part_number": item["parent_part_number"],
            "child_part_number": item["child_part_number"],
            "qty": item["qty"],
            "last_updated": item["last_updated"],
            "attributes": json.dumps(item.get("attributes", {}), sort_keys=True),
        }
        for item in relationships
    ]


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


def show_service_result(title: str, result: dict[str, Any], *, show_data: bool = False) -> None:
    if result.get("ok"):
        st.success(f"{title} succeeded")
    else:
        st.error(f"{title} failed")

    for warning in result.get("warnings", []):
        st.warning(warning)
    for error in result.get("errors", []):
        st.error(error)

    if show_data and result.get("data"):
        st.json(result["data"])


def save_uploaded_csv(data_dir: Path, category: str, uploaded_file: Any) -> Path:
    import_dir = data_dir / "imports" / category
    import_dir.mkdir(parents=True, exist_ok=True)
    target = import_dir / Path(str(uploaded_file.name)).name
    target.write_bytes(uploaded_file.getvalue())
    return target


def seed_demo_data(backend: BOMBackend) -> list[tuple[str, dict[str, Any]]]:
    operations: list[tuple[str, dict[str, Any]]] = []

    operations.append(
        (
            "Seed part A-100",
            backend.parts.add_or_update_part(
                "A-100",
                "Top Assembly",
                {"weight_kg": 12.0, "material": "Aluminum"},
            ),
        )
    )
    operations.append(
        (
            "Seed part B-200",
            backend.parts.add_or_update_part(
                "B-200",
                "Bracket",
                {"weight_kg": 1.2, "material": "Steel"},
            ),
        )
    )
    operations.append(
        (
            "Seed part C-300",
            backend.parts.add_or_update_part(
                "C-300",
                "Panel",
                {"weight_kg": 0.8, "material": "Composite"},
            ),
        )
    )
    operations.append(
        (
            "Seed part D-400",
            backend.parts.add_or_update_part(
                "D-400",
                "Fastener Kit",
                {"weight_kg": 0.05},
            ),
        )
    )
    operations.append(
        (
            "Seed relationship R-A-B-10",
            backend.bom.add_or_update_relationship(
                parent_part_number="A-100",
                child_part_number="B-200",
                qty=2,
                rel_id="R-A-B-10",
                attributes={"find_number": "10"},
            ),
        )
    )
    operations.append(
        (
            "Seed relationship R-A-C",
            backend.bom.add_or_update_relationship(
                parent_part_number="A-100",
                child_part_number="C-300",
                qty=3,
                rel_id="R-A-C",
                attributes={"find_number": "30"},
            ),
        )
    )
    operations.append(
        (
            "Seed relationship R-B-D",
            backend.bom.add_or_update_relationship(
                parent_part_number="B-200",
                child_part_number="D-400",
                qty=4,
                rel_id="R-B-D",
                attributes={"find_number": "40"},
            ),
        )
    )

    return operations


st.set_page_config(
    page_title="BOM Manager Demo",
    page_icon=":triangular_ruler:",
    layout="wide",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap');

:root {
  --bg-soft: #f7f3e9;
  --ink: #1f2937;
  --teal: #0f766e;
  --teal-soft: #ccfbf1;
  --amber: #f59e0b;
}

html, body, [class*="css"]  {
  font-family: "Space Grotesk", "Avenir Next", sans-serif;
}

.main .block-container {
  padding-top: 1.25rem;
  max-width: 1240px;
}

[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 15% 20%, #111827 0%, var(--bg-soft) 60%);
}

[data-testid="stSidebar"] {
  background: linear-gradient(170deg, #111827 0%, #115e59 100%);
}

[data-testid="stSidebar"] * {
  color: #f8fafc !important;
}

div[data-baseweb="tab"] {
  border-radius: 999px;
  background: #e5e7eb;
  border: 1px solid #d1d5db;
  padding: 0.35rem 0.85rem;
}

div[data-baseweb="tab"][aria-selected="true"] {
  background: var(--teal);
  color: white;
}

.stButton > button {
  border-radius: 999px;
  border: 1px solid var(--teal);
  background: var(--teal-soft);
  color: #0f172a;
}

.stButton > button:hover {
  border-color: #0d9488;
  background: #99f6e4;
  color: #022c22;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("BOM Manager Demo Frontend")
st.caption("Interactive Streamlit client for parts, relationships, rollups, snapshots, and CSV workflows.")

default_data_dir = st.session_state.get("data_dir", "demo_data")
entered_data_dir = st.sidebar.text_input("Data directory", value=default_data_dir)
st.session_state["data_dir"] = entered_data_dir
data_dir = resolve_data_dir(entered_data_dir)
repo_root = Path.cwd().resolve()

st.sidebar.caption(f"Resolved path: `{data_dir}`")
st.sidebar.code("streamlit run streamlit_app.py", language="bash")

if st.sidebar.button("Reset Data Directory", key="reset_data_dir_btn"):
    if data_dir == repo_root:
        st.sidebar.error("Refusing to delete repository root.")
    elif repo_root not in data_dir.parents:
        st.sidebar.error("Reset is only allowed for directories inside this repository.")
    else:
        if data_dir.exists():
            shutil.rmtree(data_dir)
        st.sidebar.success(f"Cleared {data_dir}")
        st.rerun()

backend = BOMBackend(data_dir=data_dir)

parts_result = backend.parts.list_parts()
parts = parts_result["data"]["parts"] if parts_result.get("ok") else []
relationships = [
    {
        "rel_id": rel.rel_id,
        "parent_part_number": rel.parent_part_number,
        "child_part_number": rel.child_part_number,
        "qty": rel.qty,
        "last_updated": rel.last_updated,
        "attributes": rel.attributes,
    }
    for rel in backend.relationship_repo.list_relationships()
]
snapshots_result = backend.snapshots.list_snapshots()
snapshots = snapshots_result["data"]["snapshots"] if snapshots_result.get("ok") else []

metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("Parts", len(parts))
metric_col2.metric("Relationships", len(relationships))
metric_col3.metric("Snapshots", len(snapshots))

tab_dashboard, tab_parts, tab_relationships, tab_analysis, tab_csv = st.tabs(
    ["Dashboard", "Parts", "Relationships", "Analysis", "CSV"]
)

with tab_dashboard:
    st.subheader("Quick Demo Actions")
    if st.button("Seed Sample Data", key="seed_demo_data_btn"):
        for action_name, action_result in seed_demo_data(backend):
            show_service_result(action_name, action_result)

    st.divider()
    st.subheader("BOM Connection Graph")
    max_graph_nodes = st.slider(
        "Max displayed nodes",
        min_value=5,
        max_value=80,
        value=25,
        step=1,
        key="dashboard_graph_node_cap",
    )
    graph_data = build_bom_graph_dot(parts, relationships, max_nodes=max_graph_nodes)
    st.graphviz_chart(graph_data["dot"], use_container_width=True)
    st.caption(
        f"Showing {graph_data['shown_nodes']} of {graph_data['total_nodes']} nodes and "
        f"{graph_data['shown_edges']} of {graph_data['total_edges']} relationships."
    )

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Parts**")
        if parts_result.get("ok"):
            st.dataframe(part_rows(parts), use_container_width=True, hide_index=True)
        else:
            show_service_result("List parts", parts_result)
    with col_b:
        st.markdown("**Relationships**")
        st.dataframe(relationship_rows(relationships), use_container_width=True, hide_index=True)

with tab_parts:
    st.subheader("Add or Update Part")
    with st.form("part_upsert_form"):
        part_number = st.text_input("Part number", placeholder="A-100")
        name = st.text_input("Part name", placeholder="Top Assembly")
        attributes_raw = st.text_area(
            "Attributes JSON",
            value='{"weight_kg": 12.0, "material": "Aluminum"}',
            height=120,
        )
        merge_attributes = st.checkbox("Merge with existing attributes", value=True)
        submit_part = st.form_submit_button("Save Part")

    if submit_part:
        try:
            attributes = parse_json_object(attributes_raw, "Attributes JSON")
        except ValueError as exc:
            st.error(str(exc))
        else:
            result = backend.parts.add_or_update_part(
                part_number=part_number,
                name=name,
                attributes=attributes,
                merge_attributes=merge_attributes,
            )
            show_service_result("Save part", result, show_data=True)

    st.divider()
    st.subheader("Delete Part")
    with st.form("part_delete_form"):
        delete_part_number = st.text_input("Part number to delete", placeholder="A-100")
        allow_if_referenced = st.checkbox("Allow delete even if referenced", value=False)
        submit_delete_part = st.form_submit_button("Delete Part")

    if submit_delete_part:
        result = backend.parts.delete_part(
            part_number=delete_part_number,
            allow_if_referenced=allow_if_referenced,
        )
        show_service_result("Delete part", result, show_data=True)

    st.divider()
    st.subheader("Search Parts")
    part_query = st.text_input("Search by part number or name", key="part_search_query")
    query_result = backend.parts.list_parts(query=part_query or None)
    if query_result.get("ok"):
        st.dataframe(
            part_rows(query_result["data"]["parts"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        show_service_result("Search parts", query_result)

with tab_relationships:
    st.subheader("Add or Update Relationship")
    with st.form("relationship_upsert_form"):
        parent_part_number = st.text_input("Parent part number", value="A-100")
        child_part_number = st.text_input("Child part number", value="B-200")
        qty = st.number_input("Quantity", min_value=0.0001, value=1.0, step=1.0, format="%.4f")
        rel_id = st.text_input("Relationship ID (optional)", placeholder="R-A-B-10")
        rel_attributes_raw = st.text_area(
            "Relationship attributes JSON",
            value='{"find_number": "10"}',
            height=100,
        )
        allow_dangling = st.checkbox("Allow dangling relationships", value=False)
        merge_rel_attributes = st.checkbox("Merge with existing attributes", value=True)
        submit_relationship = st.form_submit_button("Save Relationship")

    if submit_relationship:
        try:
            rel_attributes = parse_json_object(rel_attributes_raw, "Relationship attributes JSON")
        except ValueError as exc:
            st.error(str(exc))
        else:
            result = backend.bom.add_or_update_relationship(
                parent_part_number=parent_part_number,
                child_part_number=child_part_number,
                qty=qty,
                rel_id=rel_id or None,
                attributes=rel_attributes,
                allow_dangling=allow_dangling,
                merge_attributes=merge_rel_attributes,
            )
            show_service_result("Save relationship", result, show_data=True)

    st.divider()
    st.subheader("Delete Relationship")
    with st.form("relationship_delete_form"):
        delete_rel_id = st.text_input("Relationship ID to delete", placeholder="R-A-B-10")
        submit_delete_relationship = st.form_submit_button("Delete Relationship")

    if submit_delete_relationship:
        result = backend.bom.delete_relationship(delete_rel_id)
        show_service_result("Delete relationship", result, show_data=True)

    st.divider()
    st.subheader("Children and Parents Lookup")
    lookup_col_a, lookup_col_b = st.columns(2)
    with lookup_col_a:
        lookup_parent = st.text_input("Get children for parent", value="A-100")
        if st.button("Load Children", key="load_children_btn"):
            children_result = backend.bom.get_children(lookup_parent)
            show_service_result("Get children", children_result)
            if children_result.get("ok"):
                rows = []
                for item in children_result["data"]["children"]:
                    relationship = item["relationship"]
                    rows.append(
                        {
                            "rel_id": relationship["rel_id"],
                            "parent": relationship["parent_part_number"],
                            "child": relationship["child_part_number"],
                            "qty": relationship["qty"],
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
    with lookup_col_b:
        lookup_child = st.text_input("Get parents for child", value="B-200")
        if st.button("Load Parents", key="load_parents_btn"):
            parents_result = backend.bom.get_parents(lookup_child)
            show_service_result("Get parents", parents_result)
            if parents_result.get("ok"):
                rows = []
                for item in parents_result["data"]["parents"]:
                    relationship = item["relationship"]
                    rows.append(
                        {
                            "rel_id": relationship["rel_id"],
                            "parent": relationship["parent_part_number"],
                            "child": relationship["child_part_number"],
                            "qty": relationship["qty"],
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)

with tab_analysis:
    st.subheader("Subgraph Explorer")
    root_part_number = st.text_input("Root part number", value="A-100", key="subgraph_root_part")
    if st.button("Load Subgraph", key="load_subgraph_btn"):
        subgraph_result = backend.bom.get_subgraph(root_part_number)
        show_service_result("Get subgraph", subgraph_result)
        if subgraph_result.get("ok"):
            st.markdown("**Subgraph Parts**")
            st.dataframe(part_rows(subgraph_result["data"]["parts"]), use_container_width=True, hide_index=True)
            st.markdown("**Subgraph Relationships**")
            st.dataframe(
                relationship_rows(subgraph_result["data"]["relationships"]),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.subheader("Rollup")
    with st.form("rollup_form"):
        rollup_root = st.text_input("Root part", value="A-100")
        rollup_attribute = st.text_input("Numeric attribute key", value="weight_kg")
        include_root = st.checkbox("Include root part contribution", value=True)
        submit_rollup = st.form_submit_button("Run Rollup")

    if submit_rollup:
        rollup_result = backend.rollups.rollup_numeric_attribute(
            root_part_number=rollup_root,
            attribute_key=rollup_attribute,
            include_root=include_root,
        )
        show_service_result("Rollup attribute", rollup_result)
        if rollup_result.get("ok"):
            st.metric("Total", f"{rollup_result['data']['total']:.4f}")
            st.dataframe(rollup_result["data"]["breakdown"], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Snapshots")
    create_col, list_col = st.columns([1, 1.2])

    with create_col:
        with st.form("snapshot_create_form"):
            snapshot_root = st.text_input("Snapshot root part", value="A-100")
            snapshot_label = st.text_input("Snapshot label", placeholder="baseline")
            deduplicate = st.checkbox("Deduplicate if identical", value=True)
            submit_snapshot = st.form_submit_button("Create Snapshot")

        if submit_snapshot:
            create_result = backend.snapshots.create_snapshot(
                root_part_number=snapshot_root,
                label=snapshot_label or None,
                deduplicate_if_identical=deduplicate,
            )
            show_service_result("Create snapshot", create_result, show_data=True)

    with list_col:
        snapshot_filter = st.text_input("Filter by root part (optional)", key="snapshot_filter")
        filtered_snapshots = backend.snapshots.list_snapshots(
            root_part_number=snapshot_filter or None
        )
        if filtered_snapshots.get("ok"):
            st.dataframe(
                [
                    {
                        "snapshot_id": item["snapshot_id"],
                        "root_part_number": item["root_part_number"],
                        "created_at": item["created_at"],
                        "label": item.get("label"),
                    }
                    for item in filtered_snapshots["data"]["snapshots"]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            show_service_result("List snapshots", filtered_snapshots)

    st.divider()
    st.subheader("Compare Snapshots")
    latest_snapshots_result = backend.snapshots.list_snapshots()
    if latest_snapshots_result.get("ok"):
        latest_snapshots = latest_snapshots_result["data"]["snapshots"]
        if len(latest_snapshots) < 2:
            st.info("Create at least two snapshots to run a diff.")
        else:
            snapshot_labels = [
                f"{item['snapshot_id']} | {item['root_part_number']} | {item['created_at']}"
                for item in latest_snapshots
            ]
            default_a = max(0, len(snapshot_labels) - 2)
            default_b = max(0, len(snapshot_labels) - 1)
            selection_a = st.selectbox("Snapshot A", options=snapshot_labels, index=default_a)
            selection_b = st.selectbox("Snapshot B", options=snapshot_labels, index=default_b)

            map_label_to_id = {
                label: snapshot["snapshot_id"]
                for label, snapshot in zip(snapshot_labels, latest_snapshots)
            }
            if st.button("Run Snapshot Diff", key="run_snapshot_diff_btn"):
                compare_result = backend.diff.compare_snapshots(
                    map_label_to_id[selection_a],
                    map_label_to_id[selection_b],
                )
                show_service_result("Compare snapshots", compare_result)
                if compare_result.get("ok"):
                    data = compare_result["data"]
                    diff_col_1, diff_col_2, diff_col_3 = st.columns(3)
                    diff_col_1.metric("Part Changes", len(data["part_changes"]["modified"]))
                    diff_col_2.metric("Relationship Changes", len(data["relationship_changes"]["modified"]))
                    diff_col_3.metric("Signatures Equal", "Yes" if data["signature_equal"] else "No")
                    st.json(data)
    else:
        show_service_result("List snapshots", latest_snapshots_result)

with tab_csv:
    st.subheader("CSV Export")
    export_col_a, export_col_b = st.columns(2)

    with export_col_a:
        with st.form("export_parts_form"):
            export_parts_path = st.text_input(
                "Parts export path",
                value=str(data_dir / "exports" / "parts_export.csv"),
            )
            parts_whitelist_raw = st.text_input(
                "Parts attribute whitelist (comma-separated)",
                value="weight_kg,material,cost_usd",
            )
            parts_include_json = st.checkbox("Include attributes_json", value=True)
            submit_export_parts = st.form_submit_button("Export Parts CSV")

        if submit_export_parts:
            export_result = backend.csv.export_parts_csv(
                csv_path=Path(export_parts_path),
                attribute_whitelist=parse_csv_whitelist(parts_whitelist_raw),
                include_attributes_json=parts_include_json,
            )
            show_service_result("Export parts CSV", export_result, show_data=True)

    with export_col_b:
        with st.form("export_relationships_form"):
            export_rels_path = st.text_input(
                "Relationships export path",
                value=str(data_dir / "exports" / "relationships_export.csv"),
            )
            rels_whitelist_raw = st.text_input(
                "Relationship attribute whitelist (comma-separated)",
                value="find_number,note",
            )
            rels_include_json = st.checkbox("Include attributes_json", value=True)
            submit_export_rels = st.form_submit_button("Export Relationships CSV")

        if submit_export_rels:
            export_result = backend.csv.export_relationships_csv(
                csv_path=Path(export_rels_path),
                attribute_whitelist=parse_csv_whitelist(rels_whitelist_raw),
                include_attributes_json=rels_include_json,
            )
            show_service_result("Export relationships CSV", export_result, show_data=True)

    st.divider()
    st.subheader("CSV Import")
    import_col_a, import_col_b = st.columns(2)

    with import_col_a:
        uploaded_parts_csv = st.file_uploader("Upload parts CSV", type=["csv"], key="parts_csv_upload")
        merge_parts_attributes = st.checkbox("Merge imported part attributes", value=True)
        if st.button("Import Parts CSV", key="import_parts_csv_btn"):
            if uploaded_parts_csv is None:
                st.error("Choose a CSV file first.")
            else:
                csv_path = save_uploaded_csv(data_dir, "parts", uploaded_parts_csv)
                import_result = backend.csv.import_parts_csv(
                    csv_path=csv_path,
                    merge_attributes=merge_parts_attributes,
                )
                show_service_result("Import parts CSV", import_result, show_data=True)

    with import_col_b:
        uploaded_relationships_csv = st.file_uploader(
            "Upload relationships CSV",
            type=["csv"],
            key="relationships_csv_upload",
        )
        allow_dangling_csv = st.checkbox("Allow dangling relationships", value=False)
        merge_rel_csv_attributes = st.checkbox("Merge imported relationship attributes", value=True)
        if st.button("Import Relationships CSV", key="import_relationships_csv_btn"):
            if uploaded_relationships_csv is None:
                st.error("Choose a CSV file first.")
            else:
                csv_path = save_uploaded_csv(data_dir, "relationships", uploaded_relationships_csv)
                import_result = backend.csv.import_relationships_csv(
                    csv_path=csv_path,
                    allow_dangling=allow_dangling_csv,
                    merge_attributes=merge_rel_csv_attributes,
                )
                show_service_result("Import relationships CSV", import_result, show_data=True)
