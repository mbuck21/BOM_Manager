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


if __name__ == "__main__":
    unittest.main()
