from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bom_backend import BOMBackend
from streamlit_ui.context import build_app_context

# helpers.py imports `streamlit as st` at module top, which is fine outside a running
# Streamlit session; we only test the functions that never call st.*.
from streamlit_ui.helpers import (
    build_part_lookup,
    collect_service_result,
    part_key,
    resolve_data_dir,
)
from streamlit_ui.grid_edit import (
    build_bom_grid,
    build_parts_grid,
    reconcile_bom,
    reconcile_parts,
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

    # ---------------------------------------------------------------- part lookups

    def test_part_key_strips(self) -> None:
        self.assertEqual(part_key({"part_number": "  A-100 "}), "A-100")
        self.assertEqual(part_key({}), "")

    def test_build_part_lookup_skips_blank(self) -> None:
        lookup = build_part_lookup(
            [{"part_number": "A", "name": "a"}, {"part_number": "  ", "name": "blank"}]
        )
        self.assertEqual(set(lookup), {"A"})
        self.assertEqual(lookup["A"]["name"], "a")

    # ---------------------------------------------------------------- collect_service_result

    def test_collect_service_result(self) -> None:
        errors: list[str] = []
        notes: list[str] = []
        collect_service_result("step", {"ok": False, "errors": ["boom"], "warnings": ["hmm"]}, errors, notes)
        collect_service_result("fine", {"ok": True, "errors": [], "warnings": []}, errors, notes)
        self.assertEqual(errors, ["step: boom"])
        self.assertEqual(notes, ["step: hmm"])


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


class TestGridReconciliation(unittest.TestCase):
    """Pure diff-and-apply logic for the spreadsheet Edit tab (no Streamlit session)."""

    def _parts(self):
        return [
            {"part_number": "A", "name": "Assembly A", "attributes": {"unit_weight": 10.0, "material": "Steel"}},
            {"part_number": "B", "name": "Part B", "attributes": {"unit_weight": 2.0}},
        ]

    def test_parts_no_change(self) -> None:
        grid = build_parts_grid(self._parts())
        plan = reconcile_parts(grid, [dict(row) for row in grid.rows])
        self.assertTrue(plan.is_empty)

    def test_parts_edit_weight(self) -> None:
        grid = build_parts_grid(self._parts())
        edited = [dict(row) for row in grid.rows]
        edited[1]["unit_weight"] = 5.0  # change B's weight
        plan = reconcile_parts(grid, edited)
        self.assertEqual(len(plan.updates), 1)
        self.assertEqual(plan.updates[0].part_number, "B")
        self.assertEqual(plan.updates[0].attributes["unit_weight"], 5.0)

    def test_parts_add_row(self) -> None:
        grid = build_parts_grid(self._parts())
        edited = [dict(row) for row in grid.rows]
        edited.append({"part_number": "C", "name": "Part C", "unit_weight": 1.0})
        plan = reconcile_parts(grid, edited)
        self.assertEqual(len(plan.creates), 1)
        self.assertEqual(plan.creates[0].part_number, "C")

    def test_parts_delete_row(self) -> None:
        grid = build_parts_grid(self._parts())
        edited = [dict(grid.rows[0])]  # drop B
        plan = reconcile_parts(grid, edited)
        self.assertEqual(plan.deletes, ["B"])

    def test_parts_rename(self) -> None:
        grid = build_parts_grid(self._parts())
        edited = [dict(row) for row in grid.rows]
        edited[0]["part_number"] = "A2"
        plan = reconcile_parts(grid, edited)
        self.assertEqual(len(plan.renames), 1)
        self.assertEqual(plan.renames[0].old_part_number, "A")
        self.assertEqual(plan.renames[0].part_number, "A2")

    def test_parts_preserve_nested_attribute(self) -> None:
        parts = [{"part_number": "A", "name": "A", "attributes": {"nested": {"k": 1}}}]
        grid = build_parts_grid(parts)
        plan = reconcile_parts(grid, [dict(row) for row in grid.rows])
        self.assertTrue(plan.is_empty)  # nested value round-trips untouched

    def test_bom_add_and_change_and_delete(self) -> None:
        rels = [
            {"rel_id": "R1", "parent_part_number": "A", "child_part_number": "B", "qty": 2.0, "attributes": {}},
            {"rel_id": "R2", "parent_part_number": "A", "child_part_number": "C", "qty": 1.0, "attributes": {}},
        ]
        grid = build_bom_grid(rels)
        edited = [dict(grid.rows[0])]  # keep R1, drop R2
        edited[0]["qty"] = 3.0  # change R1 qty
        edited.append({"rel_id": "", "parent_part_number": "A", "child_part_number": "D", "qty": 4.0})
        plan = reconcile_bom(grid, edited)

        self.assertEqual(plan.deletes, ["R2"])
        upserts_by_id = {op.rel_id: op for op in plan.upserts}
        self.assertEqual(upserts_by_id["R1"].qty, 3.0)
        self.assertIn(None, upserts_by_id)  # the new A->D link
        self.assertEqual(upserts_by_id[None].child_part_number, "D")


if __name__ == "__main__":
    unittest.main()
