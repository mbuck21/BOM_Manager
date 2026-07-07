from __future__ import annotations

from pathlib import Path

from bom_backend.migration import migrate_legacy_if_needed
from bom_backend.repositories import PartRepository, RelationshipRepository, SnapshotRepository
from bom_backend.services.bom_structure import BOMStructureService
from bom_backend.services.part_catalog import PartCatalogService
from bom_backend.services.rollups import RollupService
from bom_backend.services.snapshot_diff import SnapshotDiffService, SnapshotService
from bom_backend.store import PROJECT_FILENAME, ProjectStore


class BOMBackend:
    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)

        # Fold any legacy multi-file data into the single project file before opening it.
        migrate_legacy_if_needed(self.data_dir)
        self.store = ProjectStore(self.data_dir / PROJECT_FILENAME)

        self.part_repo = PartRepository(self.store)
        self.relationship_repo = RelationshipRepository(self.store)
        self.snapshot_repo = SnapshotRepository(self.store)

        self.parts = PartCatalogService(self.part_repo, self.relationship_repo)
        self.bom = BOMStructureService(self.relationship_repo, self.part_repo)
        self.rollups = RollupService(self.part_repo, self.relationship_repo)
        self.snapshots = SnapshotService(
            self.snapshot_repo,
            self.part_repo,
            self.relationship_repo,
            self.bom,
        )
        self.diff = SnapshotDiffService(self.snapshot_repo)
