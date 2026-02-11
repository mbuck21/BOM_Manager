from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Part:
    part_number: str
    name: str
    last_updated: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relationship:
    rel_id: str
    parent_part_number: str
    child_part_number: str
    qty: float
    last_updated: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    snapshot_id: str
    root_part_number: str
    created_at: str
    signature: str
    parts: list[Part] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    label: str | None = None
