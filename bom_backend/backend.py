from __future__ import annotations

from pathlib import Path

from bom_backend.repositories import PartRepository, RelationshipRepository, SnapshotRepository
from bom_backend.services.bom_structure import BOMStructureService
from bom_backend.services.csv_interchange import CSVInterchangeService
from bom_backend.services.part_catalog import PartCatalogService
from bom_backend.services.rollups import RollupService
from bom_backend.services.snapshot_diff import SnapshotDiffService, SnapshotService


class BOMBackend:
    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)

        self.part_repo = PartRepository(self.data_dir)
        self.relationship_repo = RelationshipRepository(self.data_dir)
        self.snapshot_repo = SnapshotRepository(self.data_dir)

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
        self.csv = CSVInterchangeService(
            self.parts,
            self.bom,
            self.part_repo,
            self.relationship_repo,
        )
