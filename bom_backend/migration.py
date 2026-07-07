from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bom_backend.serialization import (
    part_from_record,
    part_to_record,
    relationship_from_record,
    relationship_to_record,
    snapshot_from_record,
    snapshot_to_record,
)
from bom_backend.store import CURRENT_VERSION, PROJECT_FILENAME


def _load_legacy_collection(path: Path, root_key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        items = payload.get(root_key, [])
        return list(items) if isinstance(items, list) else []
    if isinstance(payload, list):
        return list(payload)
    return []


def _load_legacy_snapshots(snapshot_dir: Path) -> list[dict[str, Any]]:
    if not snapshot_dir.is_dir():
        return []
    snapshots: list[dict[str, Any]] = []
    for file_path in sorted(snapshot_dir.glob("*.json")):
        with file_path.open("r", encoding="utf-8") as handle:
            snapshots.append(json.load(handle))
    return snapshots


def migrate_legacy_if_needed(data_dir: str | Path) -> bool:
    """Fold legacy ``parts.json`` + ``relationships.json`` + ``snapshots/`` into the
    single ``project.bom.json`` if it does not exist yet.

    Non-destructive: legacy files are left in place. Returns True if a migration was
    performed (a new project file was written from legacy data), else False.
    """
    base = Path(data_dir)
    project_path = base / PROJECT_FILENAME
    if project_path.exists():
        return False

    legacy_parts = base / "parts.json"
    legacy_relationships = base / "relationships.json"
    legacy_snapshots = base / "snapshots"

    has_legacy = (
        legacy_parts.exists()
        or legacy_relationships.exists()
        or legacy_snapshots.is_dir()
    )
    if not has_legacy:
        return False

    # Round-trip through the record converters so any field normalization the app
    # relies on is applied consistently to migrated data.
    parts = [
        part_to_record(part_from_record(record))
        for record in _load_legacy_collection(legacy_parts, "parts")
    ]
    relationships = [
        relationship_to_record(relationship_from_record(record))
        for record in _load_legacy_collection(legacy_relationships, "relationships")
    ]
    snapshots = [
        snapshot_to_record(snapshot_from_record(record))
        for record in _load_legacy_snapshots(legacy_snapshots)
    ]

    document = {
        "version": CURRENT_VERSION,
        "parts": parts,
        "relationships": relationships,
        "snapshots": snapshots,
    }

    base.mkdir(parents=True, exist_ok=True)
    tmp = project_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
    tmp.replace(project_path)
    return True
