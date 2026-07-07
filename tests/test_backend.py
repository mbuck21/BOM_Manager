from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bom_backend import BOMBackend
from bom_backend.store import PROJECT_FILENAME, ProjectStore


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

    def test_whole_project_snapshot_and_dedup(self) -> None:
        self.backend.parts.add_or_update_part("A", "Assembly A", {"weight_kg": 10})
        self.backend.parts.add_or_update_part("B", "Part B", {"weight_kg": 2})
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")

        v1 = self.backend.snapshots.create_snapshot(label="project baseline")
        self.assertTrue(v1["ok"])
        self.assertFalse(v1["data"]["deduplicated"])
        snap = v1["data"]["snapshot"]
        self.assertEqual(snap["root_part_number"], "")
        self.assertEqual(len(snap["parts"]), 2)
        self.assertEqual(len(snap["relationships"]), 1)

        # Identical save is deduplicated (no history bloat).
        v2 = self.backend.snapshots.create_snapshot()
        self.assertTrue(v2["ok"])
        self.assertTrue(v2["data"]["deduplicated"])
        self.assertEqual(
            v2["data"]["snapshot"]["snapshot_id"], snap["snapshot_id"]
        )

        # A real change produces a distinct version and a usable diff.
        self.backend.parts.update_attributes("B", {"weight_kg": 3})
        v3 = self.backend.snapshots.create_snapshot()
        self.assertTrue(v3["ok"])
        self.assertFalse(v3["data"]["deduplicated"])
        diff = self.backend.diff.compare_snapshots(
            snap["snapshot_id"], v3["data"]["snapshot"]["snapshot_id"]
        )
        self.assertTrue(diff["ok"])
        self.assertFalse(diff["data"]["signature_equal"])

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
        # With the root excluded, its own unit weight does not override the children.
        self.backend.parts.add_or_update_part("A", "Root", {"unit_weight": 100})
        self.backend.parts.add_or_update_part("B", "Child", {"unit_weight": 5})
        self.backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1")

        result = self.backend.rollups.rollup_weight_with_maturity("A", include_root=False)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["data"]["total"], 10.0)

    def test_rollup_non_numeric_unit_weight_warns(self) -> None:
        self.backend.parts.add_or_update_part("A", "A", {"unit_weight": "not-a-number"})
        result = self.backend.rollups.rollup_weight_with_maturity("A")
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["data"]["total"], 0.0)
        self.assertTrue(any("non-numeric" in w for w in result["warnings"]))

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


class TestBaseNumber(unittest.TestCase):
    def test_base_number(self) -> None:
        from bom_backend.utils.parsing import base_number

        self.assertEqual(base_number("20547015-101"), "20547015")
        self.assertEqual(base_number("20553750"), "20553750")
        self.assertEqual(base_number("a-b-c"), "a-b")  # only the last dash is the suffix
        self.assertEqual(base_number("  20541500-508  "), "20541500")
        self.assertEqual(base_number(""), "")


class TestCascadeDelete(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = BOMBackend(data_dir=self.tmp.name)
        self.backend.parts.add_or_update_part("A", "Assembly A")
        self.backend.parts.add_or_update_part("B", "Part B")
        self.backend.parts.add_or_update_part("C", "Part C")
        self.backend.bom.add_or_update_relationship("A", "B", qty=1, rel_id="R1")
        self.backend.bom.add_or_update_relationship("B", "C", qty=2, rel_id="R2")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cascade_removes_links_both_directions(self) -> None:
        result = self.backend.parts.delete_part("B", cascade=True)
        self.assertTrue(result["ok"])
        # B is a child of A (R1) and a parent of C (R2) — both links must go.
        self.assertEqual(sorted(result["data"]["removed_relationships"]), ["R1", "R2"])
        self.assertTrue(any("2 BOM link" in w for w in result["warnings"]))
        self.assertEqual(len(self.backend.relationship_repo.list_relationships()), 0)
        self.assertIsNone(self.backend.part_repo.get("B"))
        # Unrelated parts survive.
        self.assertIsNotNone(self.backend.part_repo.get("A"))

    def test_without_cascade_still_blocks(self) -> None:
        result = self.backend.parts.delete_part("B")
        self.assertFalse(result["ok"])

    def test_cascade_inside_batch(self) -> None:
        with self.backend.store.batch():
            result = self.backend.parts.delete_part("B", cascade=True)
        self.assertTrue(result["ok"])
        fresh = BOMBackend(data_dir=self.tmp.name)
        self.assertEqual(len(fresh.relationship_repo.list_relationships()), 0)


class TestSubtreeWeightMap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = BOMBackend(data_dir=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_agrees_with_rollup(self) -> None:
        b = self.backend
        # Diamond with maturity + override + repeated child:
        #   TOP -> M1 (x2), TOP -> M2 (x1); M1 -> LEAF (x3), M2 -> LEAF (x1)
        #   OVR has unit_weight AND children (override wins).
        b.parts.add_or_update_part("TOP", "Top")
        b.parts.add_or_update_part("M1", "Mid 1")
        b.parts.add_or_update_part("M2", "Mid 2")
        b.parts.add_or_update_part("LEAF", "Leaf", {"unit_weight": 2.0, "maturity_factor": 1.5})
        b.parts.add_or_update_part("OVR", "Override", {"unit_weight": 10.0})
        b.parts.add_or_update_part("HIDDEN", "Hidden", {"unit_weight": 99.0})
        b.bom.add_or_update_relationship("TOP", "M1", qty=2, rel_id="R1")
        b.bom.add_or_update_relationship("TOP", "M2", qty=1, rel_id="R2")
        b.bom.add_or_update_relationship("M1", "LEAF", qty=3, rel_id="R3")
        b.bom.add_or_update_relationship("M2", "LEAF", qty=1, rel_id="R4")
        b.bom.add_or_update_relationship("TOP", "OVR", qty=1, rel_id="R5")
        b.bom.add_or_update_relationship("OVR", "HIDDEN", qty=5, rel_id="R6")

        weights = b.rollups.subtree_weight_map()["data"]["weights"]
        for root in ("TOP", "M1", "M2", "OVR", "LEAF"):
            rollup_total = b.rollups.rollup_weight_with_maturity(root, include_root=True)["data"]["total"]
            self.assertAlmostEqual(weights[root], rollup_total, places=9, msg=root)

    def test_cycle_contributes_zero(self) -> None:
        b = self.backend
        b.parts.add_or_update_part("X", "X")
        b.parts.add_or_update_part("Y", "Y")
        # Force a cycle directly at the repo layer (service would refuse).
        from bom_backend.models import Relationship

        b.relationship_repo.upsert(Relationship("RX", "X", "Y", 1.0, "2026-01-01T00:00:00Z", {}))
        b.relationship_repo.upsert(Relationship("RY", "Y", "X", 1.0, "2026-01-01T00:00:00Z", {}))
        result = b.rollups.subtree_weight_map()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["weights"]["X"], 0.0)


class TestCompareSnapshotObjects(unittest.TestCase):
    def test_matches_compare_snapshots(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            backend = BOMBackend(data_dir=tmp.name)
            backend.parts.add_or_update_part("A", "Assembly A", {"unit_weight": 5})
            snap1 = backend.snapshots.create_snapshot(label="one")["data"]["snapshot"]
            backend.parts.update_attributes("A", {"unit_weight": 7})
            snap2 = backend.snapshots.create_snapshot(label="two")["data"]["snapshot"]

            by_id = backend.diff.compare_snapshots(snap1["snapshot_id"], snap2["snapshot_id"])
            from bom_backend.serialization import snapshot_from_record

            by_obj = backend.diff.compare_snapshot_objects(
                snapshot_from_record(snap1), snapshot_from_record(snap2)
            )
            self.assertTrue(by_id["ok"] and by_obj["ok"])
            self.assertEqual(by_id["data"], by_obj["data"])
        finally:
            tmp.cleanup()


class TestSettingsSection(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / PROJECT_FILENAME

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_settings_roundtrip_and_default(self) -> None:
        store = ProjectStore(self.path)
        self.assertEqual(store.read_settings(), {})
        store.write_settings({"columns": {"category": {"type": "choice", "choices": ["a"]}}})
        fresh = ProjectStore(self.path)
        self.assertEqual(fresh.read_settings()["columns"]["category"]["choices"], ["a"])

    def test_settings_survive_section_writes_and_batch(self) -> None:
        store = ProjectStore(self.path)
        store.write_settings({"columns": {"zone": {"type": "text"}}})
        store.write_section("parts", [{"part_number": "A"}])
        self.assertEqual(store.read_settings()["columns"]["zone"]["type"], "text")

        with store.batch():
            store.write_settings({"columns": {}})
            store.write_section("parts", [])
        fresh = ProjectStore(self.path)
        self.assertEqual(fresh.read_settings(), {"columns": {}})
        self.assertEqual(fresh.read_section("parts"), [])

    def test_missing_settings_key_defaults_empty(self) -> None:
        # A v2 file written before the settings section existed.
        self.path.write_text(
            json.dumps({"version": 2, "parts": [], "relationships": [], "snapshots": []})
        )
        store = ProjectStore(self.path)
        self.assertEqual(store.read_settings(), {})


class TestProjectStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / PROJECT_FILENAME

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_section_roundtrip(self) -> None:
        store = ProjectStore(self.path)
        store.write_section("parts", [{"part_number": "A"}])
        self.assertEqual(store.read_section("parts"), [{"part_number": "A"}])

    def test_writing_one_section_preserves_others(self) -> None:
        store = ProjectStore(self.path)
        store.write_section("snapshots", [{"snapshot_id": "S1"}])
        store.write_section("parts", [{"part_number": "A"}])
        # Writing parts must not drop the snapshots section.
        self.assertEqual(store.read_section("snapshots"), [{"snapshot_id": "S1"}])
        self.assertEqual(store.read_section("parts"), [{"part_number": "A"}])

    def test_batch_single_write(self) -> None:
        store = ProjectStore(self.path)
        with store.batch():
            store.write_section("parts", [{"part_number": "A"}])
            store.write_section("relationships", [{"rel_id": "R1"}])
        fresh = ProjectStore(self.path)
        self.assertEqual(fresh.read_section("parts"), [{"part_number": "A"}])
        self.assertEqual(fresh.read_section("relationships"), [{"rel_id": "R1"}])

    def test_backend_uses_single_file(self) -> None:
        backend = BOMBackend(data_dir=self.tmp.name)
        backend.parts.add_or_update_part("A", "Assembly A", {"unit_weight": 1.0})
        backend.bom.add_or_update_relationship("A", "B", qty=2, rel_id="R1", allow_dangling=True)
        backend.snapshots.create_snapshot(label="v1")

        self.assertTrue(self.path.exists())
        with self.path.open() as handle:
            document = json.load(handle)
        self.assertEqual(
            set(document.keys()), {"version", "parts", "relationships", "snapshots", "settings"}
        )
        self.assertEqual(len(document["parts"]), 1)
        self.assertEqual(len(document["relationships"]), 1)
        self.assertEqual(len(document["snapshots"]), 1)


class TestLegacyMigration(unittest.TestCase):
    def test_migrates_legacy_files_into_one_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(tmp.name)
            (base / "parts.json").write_text(
                json.dumps({"parts": [{"part_number": "A", "name": "Assembly A", "attributes": {}}]})
            )
            (base / "relationships.json").write_text(
                json.dumps(
                    {
                        "relationships": [
                            {"rel_id": "R1", "parent_part_number": "A", "child_part_number": "B", "qty": 2}
                        ]
                    }
                )
            )
            snap_dir = base / "snapshots"
            snap_dir.mkdir()
            (snap_dir / "snap_x.json").write_text(
                json.dumps(
                    {
                        "snapshot_id": "snap_x",
                        "root_part_number": "A",
                        "created_at": "2026-01-01T00:00:00Z",
                        "signature": "sig",
                        "label": "legacy",
                        "parts": [],
                        "relationships": [],
                    }
                )
            )

            backend = BOMBackend(data_dir=base)
            self.assertTrue((base / PROJECT_FILENAME).exists())
            parts = backend.parts.list_parts()
            self.assertTrue(parts["ok"])
            self.assertEqual(len(parts["data"]["parts"]), 1)
            snapshots = backend.snapshots.list_snapshots()
            self.assertEqual(len(snapshots["data"]["snapshots"]), 1)
            self.assertEqual(snapshots["data"]["snapshots"][0]["snapshot_id"], "snap_x")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
