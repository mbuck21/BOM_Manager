from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bom_backend import BOMBackend
from streamlit_ui.context import build_app_context
from streamlit_ui.graph import _escape_dot_label, build_bom_graph_dot
from streamlit_ui.seed import seed_demo_data


# ---------------------------------------------------------------------------
# helpers.py — pure-Python helpers (no running Streamlit session required)
# ---------------------------------------------------------------------------

# We import helpers carefully: `import streamlit as st` at module top is fine
# in a non-running Streamlit context; only st.* calls inside functions fail.
# We only test functions that do NOT call st.*.
from streamlit_ui.helpers import (
    parse_csv_whitelist,
    parse_json_object,
    part_rows,
    relationship_rows,
    resolve_data_dir,
)


class TestHelpers(unittest.TestCase):
    # ---------------------------------------------------------------- resolve_data_dir

    def test_resolve_data_dir_relative(self) -> None:
        result = resolve_data_dir("demo_data")
        self.assertIsInstance(result, Path)
        self.assertTrue(result.is_absolute())

    def test_resolve_data_dir_absolute(self) -> None:
        import os

        abs_path = os.path.abspath("demo_data")
        result = resolve_data_dir(abs_path)
        self.assertEqual(result, Path(abs_path).resolve())

    def test_resolve_data_dir_empty_string_defaults_to_demo_data(self) -> None:
        result = resolve_data_dir("")
        self.assertTrue(result.is_absolute())
        self.assertTrue(str(result).endswith("demo_data"))

    # ---------------------------------------------------------------- parse_json_object

    def test_parse_json_object_valid(self) -> None:
        result = parse_json_object('{"key": "value", "num": 42}', "test")
        self.assertEqual(result, {"key": "value", "num": 42})

    def test_parse_json_object_empty_string_returns_empty_dict(self) -> None:
        result = parse_json_object("", "test")
        self.assertEqual(result, {})

    def test_parse_json_object_non_object_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_json_object("[1, 2, 3]", "myfield")
        self.assertIn("myfield", str(ctx.exception))

    def test_parse_json_object_invalid_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_object("{bad json}", "test")

    # ---------------------------------------------------------------- parse_csv_whitelist

    def test_parse_csv_whitelist_basic(self) -> None:
        result = parse_csv_whitelist("weight_kg, material, cost")
        self.assertEqual(result, ["weight_kg", "material", "cost"])

    def test_parse_csv_whitelist_empty_string(self) -> None:
        result = parse_csv_whitelist("")
        self.assertEqual(result, [])

    def test_parse_csv_whitelist_trailing_comma(self) -> None:
        result = parse_csv_whitelist("a, b, ")
        self.assertEqual(result, ["a", "b"])

    # ---------------------------------------------------------------- part_rows / relationship_rows

    def test_part_rows_format(self) -> None:
        parts = [
            {
                "part_number": "P1",
                "name": "Widget",
                "last_updated": "2026-01-01T00:00:00Z",
                "attributes": {"color": "red"},
            }
        ]
        rows = part_rows(parts)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["part_number"], "P1")
        self.assertIn("color", rows[0]["attributes"])  # attributes is JSON string

    def test_relationship_rows_format(self) -> None:
        rels = [
            {
                "rel_id": "R1",
                "parent_part_number": "A",
                "child_part_number": "B",
                "qty": 2.0,
                "last_updated": "2026-01-01T00:00:00Z",
                "attributes": {"find_no": 10},
            }
        ]
        rows = relationship_rows(rels)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rel_id"], "R1")
        self.assertEqual(rows[0]["qty"], 2.0)


# ---------------------------------------------------------------------------
# graph.py — DOT generation (no Streamlit dependency at all)
# ---------------------------------------------------------------------------


class TestGraphDOT(unittest.TestCase):
    def test_escape_dot_label_backslash(self) -> None:
        self.assertEqual(_escape_dot_label("a\\b"), "a\\\\b")

    def test_escape_dot_label_quote(self) -> None:
        self.assertEqual(_escape_dot_label('say "hello"'), 'say \\"hello\\"')

    def test_escape_dot_label_newline(self) -> None:
        result = _escape_dot_label("line1\nline2")
        self.assertNotIn("\n", result)
        self.assertIn("\\n", result)

    def test_escape_dot_label_tab(self) -> None:
        result = _escape_dot_label("col1\tcol2")
        self.assertNotIn("\t", result)
        self.assertIn("\\t", result)

    def test_escape_dot_label_carriage_return(self) -> None:
        result = _escape_dot_label("a\rb")
        self.assertNotIn("\r", result)
        self.assertIn("\\r", result)

    def test_empty_graph_returns_valid_dot(self) -> None:
        result = build_bom_graph_dot([], [], max_nodes=50)
        self.assertIn("digraph", result["dot"])
        self.assertEqual(result["shown_nodes"], 0)
        self.assertEqual(result["total_nodes"], 0)

    def test_single_part_no_relationships(self) -> None:
        parts = [{"part_number": "P1", "name": "Widget"}]
        result = build_bom_graph_dot(parts, [], max_nodes=50)
        self.assertEqual(result["shown_nodes"], 1)
        self.assertIn("P1", result["dot"])

    def test_graph_with_relationships_shows_edges(self) -> None:
        parts = [
            {"part_number": "A", "name": "Assembly"},
            {"part_number": "B", "name": "Bracket"},
        ]
        rels = [{"parent_part_number": "A", "child_part_number": "B", "qty": 2}]
        result = build_bom_graph_dot(parts, rels, max_nodes=50)
        self.assertEqual(result["shown_nodes"], 2)
        self.assertEqual(result["shown_edges"], 1)
        self.assertIn("qty: 2", result["dot"])

    def test_max_nodes_limits_output(self) -> None:
        parts = [{"part_number": str(i), "name": f"Part {i}"} for i in range(20)]
        result = build_bom_graph_dot(parts, [], max_nodes=5)
        self.assertEqual(result["shown_nodes"], 5)
        self.assertEqual(result["total_nodes"], 20)

    def test_part_name_with_newline_escapes_in_dot(self) -> None:
        parts = [{"part_number": "P1", "name": "Line1\nLine2"}]
        result = build_bom_graph_dot(parts, [], max_nodes=50)
        self.assertNotIn('"Line1\nLine2"', result["dot"])


# ---------------------------------------------------------------------------
# seed.py — demo data creation
# ---------------------------------------------------------------------------


class TestSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = BOMBackend(data_dir=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_seed_demo_data_creates_4_parts_3_relationships(self) -> None:
        operations = seed_demo_data(self.backend)
        self.assertEqual(len(operations), 7)  # 4 parts + 3 relationships

        parts_result = self.backend.parts.list_parts()
        self.assertTrue(parts_result["ok"])
        self.assertEqual(len(parts_result["data"]["parts"]), 4)

        part_numbers = [p["part_number"] for p in parts_result["data"]["parts"]]
        self.assertIn("A-100", part_numbers)
        self.assertIn("D-400", part_numbers)

        subgraph = self.backend.bom.get_subgraph("A-100")
        self.assertEqual(len(subgraph["data"]["relationships"]), 3)

    def test_seed_all_operations_succeed(self) -> None:
        operations = seed_demo_data(self.backend)
        for label, result in operations:
            self.assertTrue(result["ok"], f"Operation '{label}' failed: {result.get('errors')}")


# ---------------------------------------------------------------------------
# context.py — AppContext building (no Streamlit dependency)
# ---------------------------------------------------------------------------


class TestContext(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.backend = BOMBackend(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_app_context_live_mode_no_snapshots(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")

        ctx = build_app_context(self.data_dir, selected_snapshot_id=None, default_to_latest=False)
        self.assertFalse(ctx.snapshot_mode)
        self.assertIsNone(ctx.loaded_snapshot_id)
        self.assertEqual(len(ctx.parts), 1)

    def test_build_app_context_with_snapshot(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")
        self.backend.parts.add_or_update_part("B", "Part B")
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")

        snap = self.backend.snapshots.create_snapshot("A", label="test snap")
        snap_id = snap["data"]["snapshot"]["snapshot_id"]

        ctx = build_app_context(self.data_dir, selected_snapshot_id=snap_id)
        self.assertTrue(ctx.snapshot_mode)
        self.assertEqual(ctx.loaded_snapshot_id, snap_id)

    def test_build_app_context_snapshot_mode_flag(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")
        snap = self.backend.snapshots.create_snapshot("A")
        snap_id = snap["data"]["snapshot"]["snapshot_id"]

        ctx_live = build_app_context(self.data_dir, selected_snapshot_id=None, default_to_latest=False)
        ctx_snap = build_app_context(self.data_dir, selected_snapshot_id=snap_id)

        self.assertFalse(ctx_live.snapshot_mode)
        self.assertTrue(ctx_snap.snapshot_mode)

    def test_build_app_context_invalid_snapshot_id_falls_back_to_live(self) -> None:
        ctx = build_app_context(
            self.data_dir, selected_snapshot_id="nonexistent_snap", default_to_latest=False
        )
        self.assertFalse(ctx.snapshot_mode)
        self.assertIsNone(ctx.loaded_snapshot_id)

    def test_build_app_context_default_to_latest_loads_last_snapshot(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")
        snap = self.backend.snapshots.create_snapshot("A", label="auto")
        snap_id = snap["data"]["snapshot"]["snapshot_id"]

        ctx = build_app_context(self.data_dir, selected_snapshot_id=None, default_to_latest=True)
        self.assertTrue(ctx.snapshot_mode)
        self.assertEqual(ctx.loaded_snapshot_id, snap_id)


if __name__ == "__main__":
    unittest.main()
