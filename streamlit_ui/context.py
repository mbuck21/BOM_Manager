from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bom_backend import BOMBackend


@dataclass
class AppContext:
    backend: BOMBackend
    data_dir: Path
    parts_result: dict[str, Any]
    parts: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    snapshots: list[dict[str, Any]]


def build_app_context(data_dir: Path) -> AppContext:
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

    return AppContext(
        backend=backend,
        data_dir=data_dir,
        parts_result=parts_result,
        parts=parts,
        relationships=relationships,
        snapshots=snapshots,
    )
