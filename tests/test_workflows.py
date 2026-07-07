from __future__ import annotations

import tempfile
import unittest

from bom_backend import BOMBackend
from streamlit_ui.bulk_add import apply_bulk_add, parse_bulk_lines
from streamlit_ui.report import (
    build_weekly_report,
    default_baseline_index,
    part_history,
    plan_version_edits,
    report_to_text,
    stale_parts,
)
from streamlit_ui.restructure import (
    apply_assembly_dissolve,
    apply_assembly_swap,
    plan_assembly_dissolve,
    plan_assembly_swap,
)
from streamlit_ui.rollup_views import (
    attribute_coverage,
    direct_child_totals,
    group_contributions,
    read_weight_budget,
)


# ── bulk add parsing ──────────────────────────────────────────────────────────
class TestParseBulkLines(unittest.TestCase):
    def parse(self, text: str, existing=None, links=None, parent="TOP"):
        return parse_bulk_lines(text, existing or set(), links or set(), parent)

    def test_tab_separated_full_row(self) -> None:
        result = self.parse("B-1\tBracket, upper\t2\t1.25")
        row = result.rows[0]
        self.assertEqual((row.part_number, row.name, row.qty, row.unit_weight), ("B-1", "Bracket, upper", 2.0, 1.25))
        self.assertFalse(row.error)

    def test_comma_separated_and_defaults(self) -> None:
        result = self.parse("B-1, Bracket\nB-2")
        self.assertEqual(result.rows[0].qty, 1.0)
        self.assertIsNone(result.rows[0].unit_weight)
        # Name defaults to the part number with a warning.
        self.assertEqual(result.rows[1].name, "B-2")
        self.assertTrue(result.rows[1].warnings)

    def test_header_skipped(self) -> None:
        result = self.parse("part number\tname\tqty\tweight\nB-1\tBracket\t1\t2.0")
        self.assertTrue(result.header_skipped)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0].part_number, "B-1")

    def test_bad_qty_and_weight(self) -> None:
        result = self.parse("B-1, Bracket, two\nB-2, Widget, 1, heavy\nB-3, Neg, 1, -4")
        self.assertIn("not a number", result.rows[0].error)
        self.assertIn("not a number", result.rows[1].error)
        self.assertIn("negative", result.rows[2].error)

    def test_duplicate_in_paste(self) -> None:
        result = self.parse("B-1, Bracket\nB-1, Again")
        self.assertFalse(result.rows[0].error)
        self.assertIn("duplicate", result.rows[1].error)

    def test_existing_part_and_link_warn(self) -> None:
        result = self.parse("B-1, Bracket", existing={"B-1"}, links={("TOP", "B-1")})
        warnings = " ".join(result.rows[0].warnings)
        self.assertIn("existing part", warnings)
        self.assertIn("link", warnings)

    def test_part_under_itself(self) -> None:
        result = self.parse("TOP, Top")
        self.assertIn("itself", result.rows[0].error)

    def test_blank_lines_skipped(self) -> None:
        result = self.parse("\n  \nB-1, Bracket\n\n")
        self.assertEqual(len(result.rows), 1)


class TestApplyBulkAdd(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = BOMBackend(data_dir=self.tmp.name)
        self.backend.parts.add_or_update_part("TOP", "Top Assembly")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_creates_parts_and_links(self) -> None:
        result = parse_bulk_lines("B-1\tBracket\t2\t1.5\nB-2\tWidget", set(), set(), "TOP")
        errors, _ = apply_bulk_add(self.backend, "TOP", result.ok_rows, {})
        self.assertEqual(errors, [])
        parts = {p.part_number for p in self.backend.part_repo.list_parts()}
        self.assertEqual(parts, {"TOP", "B-1", "B-2"})
        rels = self.backend.relationship_repo.list_relationships()
        self.assertEqual(len(rels), 2)
        b1 = self.backend.part_repo.get("B-1")
        self.assertEqual(b1.attributes["unit_weight"], 1.5)

    def test_existing_link_qty_updated_not_duplicated(self) -> None:
        self.backend.parts.add_or_update_part("B-1", "Bracket")
        self.backend.bom.add_or_update_relationship("TOP", "B-1", qty=2, rel_id="R1")
        result = parse_bulk_lines("B-1\tBracket\t5", {"B-1"}, {("TOP", "B-1")}, "TOP")
        errors, _ = apply_bulk_add(self.backend, "TOP", result.ok_rows, {("TOP", "B-1"): "R1"})
        self.assertEqual(errors, [])
        rels = self.backend.relationship_repo.list_relationships()
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].qty, 5.0)


# ── grouping and coverage ─────────────────────────────────────────────────────
class TestGrouping(unittest.TestCase):
    PARTS = [
        {"part_number": "100-1", "name": "Plate A", "attributes": {"category": "structural"}},
        {"part_number": "100-2", "name": "Plate B", "attributes": {"category": "structural"}},
        {"part_number": "200-1", "name": "Cable", "attributes": {}},
    ]
    PART_TOTALS = [
        {"part_number": "100-1", "total_contribution": 6.0, "occurrences": 2},
        {"part_number": "100-2", "total_contribution": 4.0, "occurrences": 1},
        {"part_number": "200-1", "total_contribution": 10.0, "occurrences": 1},
    ]

    def test_family_mode(self) -> None:
        groups = group_contributions(self.PART_TOTALS, self.PARTS, "family")
        by_key = {g["group"]: g for g in groups}
        self.assertEqual(by_key["100"]["total"], 10.0)
        self.assertEqual(by_key["100"]["part_count"], 2)
        self.assertEqual(by_key["100"]["occurrences"], 3)
        self.assertAlmostEqual(by_key["100"]["pct"], 50.0)
        self.assertEqual(by_key["200"]["total"], 10.0)
        # Members sorted heaviest first.
        self.assertEqual(by_key["100"]["members"][0]["part_number"], "100-1")

    def test_attribute_mode_with_none_bucket(self) -> None:
        groups = group_contributions(self.PART_TOTALS, self.PARTS, "attr:category")
        by_key = {g["group"]: g for g in groups}
        self.assertEqual(by_key["structural"]["total"], 10.0)
        self.assertEqual(by_key["(none)"]["total"], 10.0)

    def test_attribute_coverage(self) -> None:
        rows = attribute_coverage(self.PART_TOTALS, self.PARTS, ["category"])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["pct"], 50.0)
        self.assertEqual(rows[0]["missing_parts"], 1)

    def test_read_weight_budget(self) -> None:
        self.assertEqual(read_weight_budget({"attributes": {"weight_budget": "120.5"}}), 120.5)
        self.assertIsNone(read_weight_budget({"attributes": {}}))
        self.assertIsNone(read_weight_budget({"attributes": {"weight_budget": "n/a"}}))


class TestDirectChildTotals(unittest.TestCase):
    def test_matches_per_child_rollups(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            b = BOMBackend(data_dir=tmp.name)
            b.parts.add_or_update_part("TOP", "Top")
            b.parts.add_or_update_part("M1", "Mid")
            b.parts.add_or_update_part("LEAF", "Leaf", {"unit_weight": 2.0, "maturity_factor": 1.5})
            b.bom.add_or_update_relationship("TOP", "M1", qty=2, rel_id="R1")
            b.bom.add_or_update_relationship("M1", "LEAF", qty=3, rel_id="R2")
            b.bom.add_or_update_relationship("TOP", "LEAF", qty=1, rel_id="R3")

            rollup = b.rollups.rollup_weight_with_maturity("TOP", include_root=True, top_n=9999)["data"]
            rels = [
                {
                    "parent_part_number": r.parent_part_number,
                    "child_part_number": r.child_part_number,
                    "qty": r.qty,
                }
                for r in b.relationship_repo.list_relationships()
            ]
            result = direct_child_totals(rollup["breakdown"], "TOP", rels)
            rows = {row["part_number"]: row for row in result["rows"]}

            # M1 branch: 2 * 3 * (2.0*1.5) = 18; direct LEAF: 1 * 3.0 = 3.
            self.assertAlmostEqual(rows["M1"]["effective_weight"], 18.0)
            self.assertAlmostEqual(rows["LEAF"]["effective_weight"], 3.0)
            # maturity added: leaf effective 3.0 vs unit 2.0 → 1.0 per unit.
            self.assertAlmostEqual(rows["M1"]["maturity_added"], 6.0)
            self.assertAlmostEqual(rows["LEAF"]["maturity_added"], 1.0)
            self.assertAlmostEqual(
                sum(r["effective_weight"] for r in result["rows"]) + result["root_self_weight"],
                rollup["total"],
            )
        finally:
            tmp.cleanup()

    def test_root_override(self) -> None:
        breakdown = [
            {
                "part_number": "TOP",
                "path": ["TOP"],
                "multiplier": 1.0,
                "unit_weight": 10.0,
                "effective_unit_weight": 12.0,
                "contribution": 12.0,
            }
        ]
        result = direct_child_totals(breakdown, "TOP", [])
        self.assertEqual(result["rows"], [])
        self.assertAlmostEqual(result["root_self_weight"], 12.0)
        self.assertAlmostEqual(result["root_self_maturity"], 2.0)


# ── assembly swap ─────────────────────────────────────────────────────────────
class TestAssemblySwap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.b = BOMBackend(data_dir=self.tmp.name)
        for pn, name in (("TOP", "Top"), ("OLD", "Old assy"), ("C1", "Kept"), ("C2", "Dropped")):
            self.b.parts.add_or_update_part(pn, name)
        self.b.bom.add_or_update_relationship("TOP", "OLD", qty=2, rel_id="R_TOP_OLD")
        self.b.bom.add_or_update_relationship("OLD", "C1", qty=3, rel_id="R_OLD_C1")
        self.b.bom.add_or_update_relationship("OLD", "C2", qty=4, rel_id="R_OLD_C2")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _records(self):
        parts = [
            {"part_number": p.part_number, "name": p.name, "attributes": p.attributes}
            for p in self.b.part_repo.list_parts()
        ]
        rels = [
            {
                "rel_id": r.rel_id,
                "parent_part_number": r.parent_part_number,
                "child_part_number": r.child_part_number,
                "qty": r.qty,
            }
            for r in self.b.relationship_repo.list_relationships()
        ]
        return parts, rels

    def test_swap_carries_subset(self) -> None:
        parts, rels = self._records()
        plan = plan_assembly_swap("OLD", "NEW", "New assy", ["C1"], parts, rels)
        self.assertEqual(plan.errors, [])
        self.assertTrue(plan.create_new)
        self.assertEqual(plan.dropped_children, ["C2"])

        errors, notes = apply_assembly_swap(self.b, plan)
        self.assertEqual(errors, [])
        self.assertTrue(any("C2" in n for n in notes))

        rels_after = {r.rel_id: r for r in self.b.relationship_repo.list_relationships()}
        # NEW took OLD's place under TOP with the same rel_id and qty.
        self.assertEqual(rels_after["R_TOP_OLD"].child_part_number, "NEW")
        self.assertEqual(rels_after["R_TOP_OLD"].qty, 2.0)
        # Carried child re-parented under NEW.
        self.assertEqual(rels_after["R_OLD_C1"].parent_part_number, "NEW")
        # Dropped child link gone; OLD gone; C2 part still exists (just unlinked).
        self.assertNotIn("R_OLD_C2", rels_after)
        self.assertIsNone(self.b.part_repo.get("OLD"))
        self.assertIsNotNone(self.b.part_repo.get("C2"))

    def test_plan_validation(self) -> None:
        parts, rels = self._records()
        self.assertTrue(plan_assembly_swap("OLD", "OLD", "x", [], parts, rels).errors)
        self.assertTrue(plan_assembly_swap("OLD", "NEW", "", [], parts, rels).errors)  # new needs name
        self.assertTrue(plan_assembly_swap("OLD", "NEW", "x", ["NOPE"], parts, rels).errors)
        self.assertTrue(plan_assembly_swap("MISSING", "NEW", "x", [], parts, rels).errors)


# ── assembly dissolve ─────────────────────────────────────────────────────────
class TestAssemblyDissolve(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.b = BOMBackend(data_dir=self.tmp.name)
        for pn, name, attrs in (
            ("TOP", "Top", {}),
            ("GROUP", "Manual group", {}),
            ("C1", "Child 1", {"unit_weight": 2.0}),
            ("C2", "Child 2", {"unit_weight": 5.0}),
        ):
            self.b.parts.add_or_update_part(pn, name, attrs)
        self.b.bom.add_or_update_relationship("TOP", "GROUP", qty=2, rel_id="R_TG")
        self.b.bom.add_or_update_relationship("GROUP", "C1", qty=3, rel_id="R_G1")
        self.b.bom.add_or_update_relationship("GROUP", "C2", qty=4, rel_id="R_G2")
        # TOP also links C1 directly — dissolve must fold quantities together.
        self.b.bom.add_or_update_relationship("TOP", "C1", qty=1, rel_id="R_T1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _records(self):
        parts = [
            {"part_number": p.part_number, "name": p.name, "attributes": p.attributes}
            for p in self.b.part_repo.list_parts()
        ]
        rels = [
            {
                "rel_id": r.rel_id,
                "parent_part_number": r.parent_part_number,
                "child_part_number": r.child_part_number,
                "qty": r.qty,
            }
            for r in self.b.relationship_repo.list_relationships()
        ]
        return parts, rels

    def test_dissolve_preserves_rollup_and_merges_quantities(self) -> None:
        before = self.b.rollups.rollup_weight_with_maturity("TOP", include_root=True)["data"]["total"]
        parts, rels = self._records()
        plan = plan_assembly_dissolve("GROUP", parts, rels)
        self.assertEqual(plan.errors, [])

        errors, notes = apply_assembly_dissolve(self.b, plan)
        self.assertEqual(errors, [])
        self.assertTrue(any("GROUP" in n for n in notes))

        after = self.b.rollups.rollup_weight_with_maturity("TOP", include_root=True)["data"]["total"]
        self.assertAlmostEqual(before, after)  # 2*3*2 + 2*4*5 + 1*2 = 54

        self.assertIsNone(self.b.part_repo.get("GROUP"))
        rels_after = {
            (r.parent_part_number, r.child_part_number): r.qty
            for r in self.b.relationship_repo.list_relationships()
        }
        # C1: existing direct qty 1 + through-group 2*3 = 7; C2: 2*4 = 8.
        self.assertEqual(rels_after, {("TOP", "C1"): 7.0, ("TOP", "C2"): 8.0})

    def test_dissolve_validation(self) -> None:
        parts, rels = self._records()
        self.assertTrue(plan_assembly_dissolve("TOP", parts, rels).errors)   # no parents
        self.assertTrue(plan_assembly_dissolve("C2", parts, rels).errors)    # no children
        self.assertTrue(plan_assembly_dissolve("NOPE", parts, rels).errors)  # missing
        self.assertTrue(plan_assembly_dissolve("", parts, rels).errors)


# ── weekly report / part history / staleness ─────────────────────────────────
class TestWeeklyReport(unittest.TestCase):
    def test_report_and_text(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            b = BOMBackend(data_dir=tmp.name)
            b.parts.add_or_update_part("TOP", "Top")
            b.parts.add_or_update_part("B-1", "Bracket", {"unit_weight": 10.0})
            b.bom.add_or_update_relationship("TOP", "B-1", qty=1, rel_id="R1")
            baseline = b.snapshots.create_snapshot(label="baseline")["data"]["snapshot"]
            baseline_rollup = b.rollups.rollup_weight_with_maturity("TOP", top_n=9999)["data"]

            # A week of changes: weight up, a part added, one removed... (add C, bump B-1)
            b.parts.update_attributes("B-1", {"unit_weight": 12.0})
            b.parts.add_or_update_part("C-1", "Cable", {"unit_weight": 1.0})
            b.bom.add_or_update_relationship("TOP", "C-1", qty=2, rel_id="R2")
            live_rollup = b.rollups.rollup_weight_with_maturity("TOP", top_n=9999)["data"]

            from bom_backend.serialization import (
                part_to_record,
                relationship_to_record,
                snapshot_from_record,
            )

            live_snapshot = snapshot_from_record(
                {
                    "snapshot_id": "__live__",
                    "root_part_number": "TOP",
                    "created_at": "2026-07-07T00:00:00Z",
                    "signature": "",
                    "parts": [part_to_record(p) for p in b.part_repo.list_parts()],
                    "relationships": [
                        relationship_to_record(r) for r in b.relationship_repo.list_relationships()
                    ],
                }
            )
            diff = b.diff.compare_snapshot_objects(snapshot_from_record(baseline), live_snapshot)
            part_lookup = {p.part_number: part_to_record(p) for p in b.part_repo.list_parts()}

            report = build_weekly_report(
                baseline_snapshot=baseline,
                baseline_rollup=baseline_rollup,
                live_rollup=live_rollup,
                diff_data=diff["data"],
                part_lookup=part_lookup,
                budget=11.0,
                now_iso="2026-07-07T12:00:00Z",
            )
            self.assertAlmostEqual(report["total_before"], 10.0)
            self.assertAlmostEqual(report["total_after"], 14.0)
            self.assertAlmostEqual(report["delta"], 4.0)
            self.assertTrue(report["budget"]["over"])
            movers = {m["part_number"]: m for m in report["movers"]}
            self.assertAlmostEqual(movers["B-1"]["delta"], 2.0)
            self.assertEqual([p["part_number"] for p in report["added_parts"]], ["C-1"])

            text = report_to_text(report)
            self.assertIn("WEIGHT STATUS", text)
            self.assertIn("B-1", text)
            self.assertIn("OVER budget", text)
            self.assertIn("Added parts (1)", text)
        finally:
            tmp.cleanup()

    def test_default_baseline_index(self) -> None:
        newest_first = [
            {"created_at": "2026-07-07T00:00:00Z"},
            {"created_at": "2026-07-05T00:00:00Z"},
            {"created_at": "2026-06-28T00:00:00Z"},
        ]
        # Newest version >= 6 days old is the June 28 one.
        self.assertEqual(default_baseline_index(newest_first, "2026-07-07T12:00:00Z"), 2)
        # Nothing old enough → oldest.
        recent = newest_first[:2]
        self.assertEqual(default_baseline_index(recent, "2026-07-07T12:00:00Z"), 1)


class TestPartHistory(unittest.TestCase):
    def test_change_timeline(self) -> None:
        snapshots = [
            {
                "snapshot_id": "s1",
                "created_at": "2026-06-01T00:00:00Z",
                "label": "first",
                "parts": [{"part_number": "B-1", "name": "Bracket", "attributes": {"unit_weight": 10}}],
            },
            {
                "snapshot_id": "s2",
                "created_at": "2026-06-08T00:00:00Z",
                "label": "",
                "parts": [{"part_number": "B-1", "name": "Bracket", "attributes": {"unit_weight": 12, "category": "structural"}}],
            },
            {
                "snapshot_id": "s3",
                "created_at": "2026-06-15T00:00:00Z",
                "label": "removed it",
                "parts": [],
            },
        ]
        events = part_history(snapshots, "B-1")
        changes = [e["change"] for e in events]  # newest first
        self.assertEqual(changes[0], "removed from project")
        self.assertIn("unit_weight: 10 -> 12", changes)
        self.assertIn("category set to structural", changes)
        self.assertEqual(changes[-1], "first appears")


class TestPlanVersionEdits(unittest.TestCase):
    BASELINE = [
        {"snapshot_id": "s1", "created_at": "2026-06-01T00:00:00Z", "label": "first"},
        {"snapshot_id": "s2", "created_at": "2026-06-08T00:00:00Z", "label": ""},
    ]

    def test_no_change(self) -> None:
        plan = plan_version_edits(self.BASELINE, [dict(r) for r in self.BASELINE])
        self.assertEqual(plan, {"updates": [], "deletes": []})

    def test_label_and_date_edits(self) -> None:
        edited = [dict(r) for r in self.BASELINE]
        edited[0]["label"] = "renamed"
        edited[1]["created_at"] = "2026-06-09T12:00:00Z"
        plan = plan_version_edits(self.BASELINE, edited)
        self.assertEqual(len(plan["updates"]), 2)
        by_id = {u["snapshot_id"]: u for u in plan["updates"]}
        self.assertEqual(by_id["s1"]["label"], "renamed")
        self.assertEqual(by_id["s2"]["created_at"], "2026-06-09T12:00:00Z")
        self.assertEqual(plan["deletes"], [])

    def test_deleted_row_and_ignored_added_row(self) -> None:
        edited = [dict(self.BASELINE[0]), {"snapshot_id": "", "label": "new", "created_at": ""}]
        plan = plan_version_edits(self.BASELINE, edited)
        self.assertEqual(plan["deletes"], ["s2"])
        self.assertEqual(plan["updates"], [])

    def test_blank_date_keeps_original(self) -> None:
        edited = [dict(r) for r in self.BASELINE]
        edited[0]["created_at"] = ""
        edited[0]["label"] = "renamed"
        plan = plan_version_edits(self.BASELINE, edited)
        self.assertEqual(plan["updates"][0]["created_at"], "2026-06-01T00:00:00Z")


class TestStaleParts(unittest.TestCase):
    def test_oldest_first_weighted_only(self) -> None:
        parts = [
            {"part_number": "A", "name": "a", "last_updated": "2026-07-01T00:00:00Z", "attributes": {"unit_weight": 1}},
            {"part_number": "B", "name": "b", "last_updated": "2026-01-01T00:00:00Z", "attributes": {"unit_weight": 2}},
            {"part_number": "C", "name": "c", "last_updated": "2020-01-01T00:00:00Z", "attributes": {}},
        ]
        rows = stale_parts(parts, "2026-07-07T00:00:00Z")
        self.assertEqual([r["part_number"] for r in rows], ["B", "A"])  # C skipped (no weight)
        self.assertGreater(rows[0]["age_days"], 180)


if __name__ == "__main__":
    unittest.main()
