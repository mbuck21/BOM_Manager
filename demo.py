from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from bom_backend import BOMBackend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BOM backend demo workflow")
    parser.add_argument(
        "--data-dir",
        default="demo_data",
        help="Directory where JSON source-of-truth and demo artifacts are written",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear demo data directory before running",
    )
    return parser.parse_args()


def reset_data_dir(data_dir: Path) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)


def print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def summarize(result: dict[str, Any], show_full: bool = False) -> None:
    if result.get("warnings"):
        print("warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")

    if show_full:
        print(json.dumps(result.get("data", {}), indent=2, sort_keys=True))


def require_ok(step: str, result: dict[str, Any], show_full: bool = False) -> dict[str, Any]:
    if not result.get("ok"):
        print(f"\n[FAIL] {step}")
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(1)

    print(f"[OK] {step}")
    summarize(result, show_full=show_full)
    return result.get("data", {})


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)

    if args.reset:
        reset_data_dir(data_dir)

    backend = BOMBackend(data_dir=data_dir)

    print_section("Seed Parts")
    require_ok(
        "add A-100",
        backend.parts.add_or_update_part(
            "A-100",
            "Top Assembly",
            {"weight_kg": 12.0, "material": "Aluminum"},
        ),
    )
    require_ok(
        "add B-200",
        backend.parts.add_or_update_part(
            "B-200",
            "Bracket",
            {"weight_kg": 1.2, "material": "Steel"},
        ),
    )
    require_ok(
        "add C-300",
        backend.parts.add_or_update_part(
            "C-300",
            "Panel",
            {"weight_kg": 0.8, "material": "Composite"},
        ),
    )
    require_ok(
        "add D-400",
        backend.parts.add_or_update_part(
            "D-400",
            "Fastener Kit",
            {"weight_kg": 0.05},
        ),
    )

    parts_list = require_ok("list parts", backend.parts.list_parts())
    print(f"part_count={len(parts_list['parts'])}")

    print_section("Build BOM")
    require_ok(
        "add relationship R-A-B-10",
        backend.bom.add_or_update_relationship(
            parent_part_number="A-100",
            child_part_number="B-200",
            qty=2,
            rel_id="R-A-B-10",
            attributes={"find_number": "10"},
        ),
    )
    require_ok(
        "add relationship R-A-B-20 (repeated child)",
        backend.bom.add_or_update_relationship(
            parent_part_number="A-100",
            child_part_number="B-200",
            qty=1,
            rel_id="R-A-B-20",
            attributes={"find_number": "20", "note": "alternate placement"},
        ),
    )
    require_ok(
        "add relationship R-A-C",
        backend.bom.add_or_update_relationship(
            parent_part_number="A-100",
            child_part_number="C-300",
            qty=3,
            rel_id="R-A-C",
            attributes={"find_number": "30"},
        ),
    )
    require_ok(
        "add relationship R-B-D",
        backend.bom.add_or_update_relationship(
            parent_part_number="B-200",
            child_part_number="D-400",
            qty=4,
            rel_id="R-B-D",
            attributes={"find_number": "40"},
        ),
    )

    children = require_ok("get children of A-100", backend.bom.get_children("A-100"))
    print(f"children_of_A100={len(children['children'])}")

    subgraph = require_ok("get subgraph for A-100", backend.bom.get_subgraph("A-100"))
    print(
        "subgraph_counts="
        f"parts:{len(subgraph['parts'])}, relationships:{len(subgraph['relationships'])}"
    )

    print_section("Cycle Prevention")
    cycle_attempt = backend.bom.add_or_update_relationship(
        parent_part_number="D-400",
        child_part_number="A-100",
        qty=1,
        rel_id="R-D-A",
    )
    if cycle_attempt["ok"]:
        print("[UNEXPECTED] cycle prevention should have rejected D-400 -> A-100")
        raise SystemExit(1)
    print("[OK] cycle attempt rejected")
    print("errors:")
    for error in cycle_attempt["errors"]:
        print(f"- {error}")

    print_section("Rollup")
    rollup = require_ok(
        "rollup weight_kg from A-100",
        backend.rollups.rollup_numeric_attribute("A-100", "weight_kg"),
    )
    print(f"total_weight_kg={rollup['total']:.3f}")

    print_section("Snapshots + Diff")
    baseline = require_ok(
        "create baseline snapshot",
        backend.snapshots.create_snapshot("A-100", label="baseline"),
    )
    baseline_id = baseline["snapshot"]["snapshot_id"]
    print(f"baseline_snapshot_id={baseline_id}")

    require_ok(
        "update B-200 attributes",
        backend.parts.update_attributes("B-200", {"weight_kg": 1.5, "cost_usd": 12.75}),
    )
    require_ok(
        "update R-A-C qty",
        backend.bom.add_or_update_relationship(
            parent_part_number="A-100",
            child_part_number="C-300",
            qty=5,
            rel_id="R-A-C",
            attributes={"find_number": "30"},
        ),
    )

    updated = require_ok(
        "create updated snapshot",
        backend.snapshots.create_snapshot("A-100", label="updated"),
    )
    updated_id = updated["snapshot"]["snapshot_id"]
    print(f"updated_snapshot_id={updated_id}")

    diff = require_ok(
        f"compare snapshots {baseline_id} vs {updated_id}",
        backend.diff.compare_snapshots(baseline_id, updated_id),
    )
    print(
        "diff_counts="
        f"part_modified:{len(diff['part_changes']['modified'])}, "
        f"rel_modified:{len(diff['relationship_changes']['modified'])}"
    )

    print_section("Whole-project version")
    project_version = require_ok(
        "create whole-project version",
        backend.snapshots.create_snapshot(label="project baseline"),
    )
    print(f"project_version_id={project_version['snapshot']['snapshot_id']}")

    print_section("Done")
    print("Demo completed successfully.")
    print(f"JSON data directory: {data_dir}")


if __name__ == "__main__":
    main()
