from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from bom_backend import BOMBackend


class TestBOMBackend(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = BOMBackend(data_dir=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parts_relationships_and_subgraph(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A", {"weight_kg": 10})
        self.backend.parts.add_or_update_part("B", "Part B", {"weight_kg": 2})
        self.backend.parts.add_or_update_part("C", "Part C", {"weight_kg": 3})

        rel1 = self.backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1")
        rel2 = self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R2")
        rel3 = self.backend.bom.add_or_update_relationship("B", "C", qty=4, rel_id="R3")

        self.assertTrue(rel1["ok"])
        self.assertTrue(rel2["ok"])
        self.assertTrue(rel3["ok"])

        subgraph = self.backend.bom.get_subgraph("A")
        self.assertTrue(subgraph["ok"])
        self.assertEqual(len(subgraph["data"]["relationships"]), 3)

        rel_ids = [item["rel_id"] for item in subgraph["data"]["relationships"]]
        self.assertEqual(set(rel_ids), {"R1", "R2", "R3"})

    def test_cycle_prevention(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")
        self.backend.parts.add_or_update_part("B", "Part B")
        self.backend.parts.add_or_update_part("C", "Part C")

        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")
        self.backend.bom.add_or_update_relationship("B", "C", qty=1, rel_id="R2")

        cycle_result = self.backend.bom.add_or_update_relationship("C", "A", qty=1, rel_id="R3")
        self.assertFalse(cycle_result["ok"])
        self.assertIn("Cycle detected", cycle_result["errors"][0])

    def test_snapshots_and_diff(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A", {"weight_kg": 10})
        self.backend.parts.add_or_update_part("B", "Part B", {"weight_kg": 2})
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")

        snap1 = self.backend.snapshots.create_snapshot("A", label="baseline")
        self.assertTrue(snap1["ok"])

        self.backend.parts.update_attributes("B", {"weight_kg": 2.5})

        snap2 = self.backend.snapshots.create_snapshot("A", label="updated")
        self.assertTrue(snap2["ok"])

        snap1_id = snap1["data"]["snapshot"]["snapshot_id"]
        snap2_id = snap2["data"]["snapshot"]["snapshot_id"]
        diff = self.backend.diff.compare_snapshots(snap1_id, snap2_id)

        self.assertTrue(diff["ok"])
        self.assertFalse(diff["data"]["signature_equal"])
        self.assertGreaterEqual(len(diff["data"]["part_changes"]["modified"]), 1)

    def test_csv_import_export(self) -> None:
        parts_csv = Path(self.tmp.name) / "parts.csv"
        with parts_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["part_number", "name", "weight_kg", "material", "attributes_json"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "part_number": "A",
                    "name": "Assembly A",
                    "weight_kg": "12.5",
                    "material": "Steel",
                    "attributes_json": '{"cost": 42.3}',
                }
            )

        rels_csv = Path(self.tmp.name) / "rels.csv"
        with rels_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["rel_id", "parent_part_number", "child_part_number", "qty", "find_no"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "rel_id": "R1",
                    "parent_part_number": "A",
                    "child_part_number": "B",
                    "qty": "2",
                    "find_no": "10",
                }
            )

        import_parts = self.backend.csv.import_parts_csv(parts_csv)
        self.assertTrue(import_parts["ok"])

        # Child B missing in catalog, but allowed for this CSV import call.
        import_relationships = self.backend.csv.import_relationships_csv(
            rels_csv,
            allow_dangling=True,
        )
        self.assertTrue(import_relationships["ok"])

        exported_parts_csv = Path(self.tmp.name) / "parts_out.csv"
        exported_rels_csv = Path(self.tmp.name) / "rels_out.csv"

        export_parts = self.backend.csv.export_parts_csv(
            exported_parts_csv,
            attribute_whitelist=["weight_kg", "material", "cost"],
        )
        export_relationships = self.backend.csv.export_relationships_csv(
            exported_rels_csv,
            attribute_whitelist=["find_no"],
        )

        self.assertTrue(export_parts["ok"])
        self.assertTrue(export_relationships["ok"])

        with exported_parts_csv.open("r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("weight_kg", text)
        self.assertIn("12.5", text)

    def test_rollup_numeric_attribute(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A", {"weight_kg": 10})
        self.backend.parts.add_or_update_part("B", "Part B", {"weight_kg": 2})
        self.backend.parts.add_or_update_part("C", "Part C", {"weight_kg": 1.5})
        self.backend.parts.add_or_update_part("D", "Part D", {})

        self.backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1")
        self.backend.bom.add_or_update_relationship("A", "C", qty=3, rel_id="R2")
        self.backend.bom.add_or_update_relationship("B", "D", qty=4, rel_id="R3")

        result = self.backend.rollups.rollup_numeric_attribute("A", "weight_kg")
        self.assertTrue(result["ok"])
        # A: 10 + B: (2 * 2) + C: (1.5 * 3) + D: missing -> warning only
        self.assertAlmostEqual(result["data"]["total"], 18.5)
        self.assertGreaterEqual(len(result["warnings"]), 1)

    def test_rollup_weight_with_maturity_uses_override(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")
        self.backend.parts.add_or_update_part(
            "B",
            "Weighted Subassembly",
            {"unit_weight": 100, "maturity_factor": 1.05},
        )
        self.backend.parts.add_or_update_part("C", "Fallback Branch")
        self.backend.parts.add_or_update_part("D", "Should be ignored", {"unit_weight": 8})
        self.backend.parts.add_or_update_part("E", "Leaf weight", {"unit_weight": 2})
        self.backend.parts.add_or_update_part("F", "Unresolved leaf")

        self.backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1")
        self.backend.bom.add_or_update_relationship("A", "C", qty=1, rel_id="R2")
        self.backend.bom.add_or_update_relationship("B", "D", qty=4, rel_id="R3")
        self.backend.bom.add_or_update_relationship("C", "E", qty=3, rel_id="R4")
        self.backend.bom.add_or_update_relationship("A", "F", qty=1, rel_id="R5")

        result = self.backend.rollups.rollup_weight_with_maturity("A")
        self.assertTrue(result["ok"])

        # B contributes as override: 2 * (100 * 1.05) = 210
        # C has no unit weight so E contributes: 1 * 3 * 2 = 6
        self.assertAlmostEqual(result["data"]["total"], 216.0)

        breakdown_parts = [item["part_number"] for item in result["data"]["breakdown"]]
        self.assertIn("B", breakdown_parts)
        self.assertIn("E", breakdown_parts)
        self.assertNotIn("D", breakdown_parts)  # ignored due to B override

        top_part = result["data"]["top_contributors"][0]
        self.assertEqual(top_part["part_number"], "B")
        self.assertAlmostEqual(top_part["total_contribution"], 210.0)

        unresolved_parts = [item["part_number"] for item in result["data"]["unresolved_nodes"]]
        self.assertIn("F", unresolved_parts)


    # ------------------------------------------------------------------ Parts --

    def test_get_nonexistent_part(self) -> None:
        result = self.backend.parts.get_part("DOES_NOT_EXIST")
        self.assertFalse(result["ok"])
        self.assertTrue(any("not found" in e for e in result["errors"]))

    def test_delete_nonexistent_part(self) -> None:
        result = self.backend.parts.delete_part("GHOST")
        self.assertFalse(result["ok"])

    def test_part_update_merges_attributes(self) -> None:
        self.backend.parts.add_or_update_part("X", "Part X", {"color": "red", "weight": 5})
        self.backend.parts.add_or_update_part("X", "Part X", {"weight": 7}, merge_attributes=True)

        result = self.backend.parts.get_part("X")
        attrs = result["data"]["part"]["attributes"]
        self.assertEqual(attrs["color"], "red")
        self.assertEqual(attrs["weight"], 7)

    def test_part_update_overwrites_when_disabled(self) -> None:
        self.backend.parts.add_or_update_part("X", "Part X", {"color": "red", "weight": 5})
        self.backend.parts.add_or_update_part("X", "Part X", {"weight": 7}, merge_attributes=False)

        result = self.backend.parts.get_part("X")
        attrs = result["data"]["part"]["attributes"]
        self.assertNotIn("color", attrs)
        self.assertEqual(attrs["weight"], 7)

    # --------------------------------------------------------- Relationships --

    def test_delete_relationship(self) -> None:
        self.backend.parts.add_or_update_part("A", "A")
        self.backend.parts.add_or_update_part("B", "B")
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")

        delete_result = self.backend.bom.delete_relationship("R1")
        self.assertTrue(delete_result["ok"])

        children = self.backend.bom.get_children("A")
        self.assertEqual(len(children["data"]["children"]), 0)

    def test_delete_nonexistent_relationship(self) -> None:
        result = self.backend.bom.delete_relationship("GHOST_REL")
        self.assertFalse(result["ok"])

    def test_add_relationship_self_loop_rejected(self) -> None:
        self.backend.parts.add_or_update_part("A", "A")
        result = self.backend.bom.add_or_update_relationship("A", "A", qty=1)
        self.assertFalse(result["ok"])

    def test_add_relationship_qty_zero_rejected(self) -> None:
        self.backend.parts.add_or_update_part("A", "A")
        self.backend.parts.add_or_update_part("B", "B")
        result = self.backend.bom.add_or_update_relationship("A", "B", qty=0)
        self.assertFalse(result["ok"])

    def test_add_relationship_qty_negative_rejected(self) -> None:
        self.backend.parts.add_or_update_part("A", "A")
        self.backend.parts.add_or_update_part("B", "B")
        result = self.backend.bom.add_or_update_relationship("A", "B", qty=-1)
        self.assertFalse(result["ok"])

    def test_add_relationship_qty_upper_bound_rejected(self) -> None:
        self.backend.parts.add_or_update_part("A", "A")
        self.backend.parts.add_or_update_part("B", "B")
        result = self.backend.bom.add_or_update_relationship("A", "B", qty=2_000_000)
        self.assertFalse(result["ok"])
        self.assertIn("1,000,000", result["errors"][0])

    def test_add_relationship_dangling_blocked_by_default(self) -> None:
        result = self.backend.bom.add_or_update_relationship("MISSING_A", "MISSING_B", qty=1)
        self.assertFalse(result["ok"])

    def test_get_children_correct_subset(self) -> None:
        for label in ("A", "B", "C", "D"):
            self.backend.parts.add_or_update_part(label, label)
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")
        self.backend.bom.add_or_update_relationship("A", "C", qty=2, rel_id="R2")
        self.backend.bom.add_or_update_relationship("B", "D", qty=3, rel_id="R3")

        children_a = self.backend.bom.get_children("A")
        child_numbers = [c["relationship"]["child_part_number"] for c in children_a["data"]["children"]]
        self.assertEqual(set(child_numbers), {"B", "C"})

    def test_get_parents_correct_subset(self) -> None:
        for label in ("A", "B", "C"):
            self.backend.parts.add_or_update_part(label, label)
        self.backend.bom.add_or_update_relationship("A", "C", qty=1, rel_id="R1")
        self.backend.bom.add_or_update_relationship("B", "C", qty=1, rel_id="R2")

        parents_c = self.backend.bom.get_parents("C")
        parent_numbers = [p["relationship"]["parent_part_number"] for p in parents_c["data"]["parents"]]
        self.assertEqual(set(parent_numbers), {"A", "B"})

    # ----------------------------------------------------------- Snapshots --

    def test_snapshot_deduplication(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A")
        self.backend.bom.add_or_update_relationship.__func__  # ensure it's loaded

        snap1 = self.backend.snapshots.create_snapshot("A", label="first")
        snap2 = self.backend.snapshots.create_snapshot("A", label="second")

        self.assertTrue(snap1["ok"])
        self.assertTrue(snap2["ok"])
        # Identical BOM means identical signature; same snapshot_id returned
        self.assertEqual(
            snap1["data"]["snapshot"]["snapshot_id"],
            snap2["data"]["snapshot"]["snapshot_id"],
        )

    # ------------------------------------------------------------ Rollups --

    def test_rollup_include_root_false(self) -> None:
        self.backend.parts.add_or_update_part("A", "Root", {"val": 100})
        self.backend.parts.add_or_update_part("B", "Child", {"val": 5})
        self.backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1")

        result = self.backend.rollups.rollup_numeric_attribute("A", "val", include_root=False)
        self.assertTrue(result["ok"])
        # A excluded; only B contributes: 5 * 2 = 10
        self.assertAlmostEqual(result["data"]["total"], 10.0)

    def test_rollup_non_numeric_attribute_warns(self) -> None:
        self.backend.parts.add_or_update_part("A", "A", {"val": "not-a-number"})
        result = self.backend.rollups.rollup_numeric_attribute("A", "val")
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["data"]["total"], 0.0)
        self.assertGreaterEqual(len(result["warnings"]), 1)
        self.assertTrue(any("non-numeric" in w for w in result["warnings"]))

    # ------------------------------------------------------- CSV edge cases --

    def test_csv_import_missing_required_column(self) -> None:
        bad_csv = Path(self.tmp.name) / "bad_parts.csv"
        with bad_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["part_number"])  # missing 'name'
            writer.writeheader()
            writer.writerow({"part_number": "X"})

        result = self.backend.csv.import_parts_csv(bad_csv)
        self.assertFalse(result["ok"])
        self.assertTrue(any("name" in e for e in result["errors"]))

    def test_csv_export_roundtrip_preserves_data(self) -> None:
        self.backend.parts.add_or_update_part("P1", "Widget", {"cost": 9.99, "material": "ABS"})
        self.backend.parts.add_or_update_part("P2", "Bolt", {"cost": 0.25})

        out_csv = Path(self.tmp.name) / "roundtrip.csv"
        self.backend.csv.export_parts_csv(out_csv, attribute_whitelist=["cost", "material"])

        # Import into a fresh backend and compare
        tmp2 = tempfile.TemporaryDirectory()
        try:
            backend2 = BOMBackend(data_dir=tmp2.name)
            result = backend2.csv.import_parts_csv(out_csv)
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["created"], 2)

            p1 = backend2.parts.get_part("P1")
            self.assertTrue(p1["ok"])
            self.assertAlmostEqual(float(p1["data"]["part"]["attributes"]["cost"]), 9.99)
            self.assertEqual(p1["data"]["part"]["attributes"]["material"], "ABS")
        finally:
            tmp2.cleanup()

    # ------------------------------------------------------- Part catalog --

    def test_delete_part_with_relationships_blocked(self) -> None:
        self.backend.parts.add_or_update_part("A", "A")
        self.backend.parts.add_or_update_part("B", "B")
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")

        result = self.backend.parts.delete_part("A")
        self.assertFalse(result["ok"])

    # -------------------------------------------------- BOM structure misc --

    def test_get_subgraph_single_node(self) -> None:
        self.backend.parts.add_or_update_part("LONE", "Lone Part")
        result = self.backend.bom.get_subgraph("LONE")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["data"]["parts"]), 1)
        self.assertEqual(len(result["data"]["relationships"]), 0)


if __name__ == "__main__":
    unittest.main()
