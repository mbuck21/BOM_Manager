from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bom_backend import BOMBackend


@dataclass
class AppContext:
    backend: BOMBackend
    live_backend: BOMBackend
    data_dir: Path
    parts_result: dict[str, Any]
    parts: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    snapshots: list[dict[str, Any]]
    loaded_snapshot: dict[str, Any] | None
    loaded_snapshot_id: str | None
    latest_snapshot_id: str | None
    is_latest_snapshot_loaded: bool
    snapshot_mode: bool


def _relationships_from_backend(backend: BOMBackend) -> list[dict[str, Any]]:
    return [
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


def _snapshot_runtime_dir(snapshot_id: str) -> Path:
    safe_snapshot_id = "".join(
        char if (char.isalnum() or char in {"-", "_"}) else "_"
        for char in snapshot_id
    )
    return Path(tempfile.gettempdir()) / "bom_manager_snapshot_views" / safe_snapshot_id


def _build_snapshot_backend(snapshot_record: dict[str, Any]) -> BOMBackend:
    snapshot_id = str(snapshot_record.get("snapshot_id", "")).strip()
    runtime_dir = _snapshot_runtime_dir(snapshot_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    parts_payload = {"parts": list(snapshot_record.get("parts") or [])}
    relationships_payload = {"relationships": list(snapshot_record.get("relationships") or [])}

    with (runtime_dir / "parts.json").open("w", encoding="utf-8") as handle:
        json.dump(parts_payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")

    with (runtime_dir / "relationships.json").open("w", encoding="utf-8") as handle:
        json.dump(relationships_payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")

    return BOMBackend(data_dir=runtime_dir)


def build_app_context(
    data_dir: Path,
    selected_snapshot_id: str | None = None,
    default_to_latest: bool = True,
) -> AppContext:
    live_backend = BOMBackend(data_dir=data_dir)

    parts_result = live_backend.parts.list_parts()
    parts = parts_result["data"]["parts"] if parts_result.get("ok") else []
    relationships = _relationships_from_backend(live_backend)

    snapshots_result = live_backend.snapshots.list_snapshots()
    snapshots = snapshots_result["data"]["snapshots"] if snapshots_result.get("ok") else []
    latest_snapshot = snapshots[-1] if snapshots else None
    latest_snapshot_id = (
        str(latest_snapshot.get("snapshot_id", "")).strip() if latest_snapshot else None
    )

    requested_snapshot_id = (selected_snapshot_id or "").strip() or None
    if requested_snapshot_id is None and default_to_latest and latest_snapshot_id:
        requested_snapshot_id = latest_snapshot_id

    snapshot_lookup = {
        str(snapshot.get("snapshot_id", "")).strip(): snapshot
        for snapshot in snapshots
        if str(snapshot.get("snapshot_id", "")).strip()
    }
    loaded_snapshot = snapshot_lookup.get(requested_snapshot_id) if requested_snapshot_id else None

    backend = live_backend
    if loaded_snapshot:
        backend = _build_snapshot_backend(loaded_snapshot)
        snapshot_parts_result = backend.parts.list_parts()
        parts_result = snapshot_parts_result
        parts = snapshot_parts_result["data"]["parts"] if snapshot_parts_result.get("ok") else []
        relationships = _relationships_from_backend(backend)

    loaded_snapshot_id = (
        str(loaded_snapshot.get("snapshot_id", "")).strip() if loaded_snapshot else None
    )
    is_latest_snapshot_loaded = bool(
        loaded_snapshot_id and latest_snapshot_id and loaded_snapshot_id == latest_snapshot_id
    )

    return AppContext(
        backend=backend,
        live_backend=live_backend,
        data_dir=data_dir,
        parts_result=parts_result,
        parts=parts,
        relationships=relationships,
        snapshots=snapshots,
        loaded_snapshot=loaded_snapshot,
        loaded_snapshot_id=loaded_snapshot_id,
        latest_snapshot_id=latest_snapshot_id,
        is_latest_snapshot_loaded=is_latest_snapshot_loaded,
        snapshot_mode=loaded_snapshot is not None,
    )
