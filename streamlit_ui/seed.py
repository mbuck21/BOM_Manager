from __future__ import annotations

from typing import Any

from bom_backend import BOMBackend


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
