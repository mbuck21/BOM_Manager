from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# The one-file project format. Everything for a data directory lives here:
#   - "parts":         the current parts catalog
#   - "relationships": the current parent -> child BOM edges
#   - "snapshots":     the saved version history (each a frozen copy)
#   - "settings":      project preferences (e.g. user-defined column types/choices)
SECTIONS = ("parts", "relationships", "snapshots")
SETTINGS_KEY = "settings"
CURRENT_VERSION = 2
PROJECT_FILENAME = "project.bom.json"


def _empty_document() -> dict[str, Any]:
    return {
        "version": CURRENT_VERSION,
        "parts": [],
        "relationships": [],
        "snapshots": [],
        SETTINGS_KEY: {},
    }


class ProjectStore:
    """Single-file JSON store holding parts, relationships, and snapshot history.

    All three repositories share one ``ProjectStore`` so the current breakdown and
    its save history live in one file. Each ``write_section`` reads the whole file,
    replaces only the named section, and writes atomically (``.tmp`` + ``replace``),
    so writing one section never clobbers the others.

    ``batch()`` defers section writes and flushes once, so a grid Save that touches
    many sections commits as a single atomic file write.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._batch_depth = 0
        self._batch_doc: dict[str, Any] | None = None
        self._ensure_file()

    # ── file-level helpers ────────────────────────────────────────────────────
    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_document(_empty_document())

    def _read_document(self) -> dict[str, Any]:
        if self._batch_doc is not None:
            return self._batch_doc

        self._ensure_file()
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        document = _empty_document()
        if isinstance(payload, dict):
            if isinstance(payload.get("version"), int):
                document["version"] = payload["version"]
            for section in SECTIONS:
                items = payload.get(section)
                if isinstance(items, list):
                    document[section] = [dict(item) for item in items]
            settings = payload.get(SETTINGS_KEY)
            if isinstance(settings, dict):
                document[SETTINGS_KEY] = dict(settings)
        return document

    def _write_document(self, document: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")
        tmp.replace(self.path)

    # ── section access ────────────────────────────────────────────────────────
    def read_section(self, name: str) -> list[dict[str, Any]]:
        if name not in SECTIONS:
            raise ValueError(f"Unknown section '{name}'")
        return [dict(item) for item in self._read_document().get(name, [])]

    def write_section(self, name: str, records: list[dict[str, Any]]) -> None:
        if name not in SECTIONS:
            raise ValueError(f"Unknown section '{name}'")
        document = self._read_document()
        document[name] = [dict(item) for item in records]

        if self._batch_depth > 0:
            self._batch_doc = document
        else:
            self._write_document(document)

    # ── settings (dict section) ───────────────────────────────────────────────
    def read_settings(self) -> dict[str, Any]:
        settings = self._read_document().get(SETTINGS_KEY, {})
        return dict(settings) if isinstance(settings, dict) else {}

    def write_settings(self, settings: dict[str, Any]) -> None:
        document = self._read_document()
        document[SETTINGS_KEY] = dict(settings)

        if self._batch_depth > 0:
            self._batch_doc = document
        else:
            self._write_document(document)

    @contextmanager
    def batch(self) -> Iterator["ProjectStore"]:
        """Defer section writes until the block exits cleanly, then flush once atomically.

        If the block raises, buffered changes are discarded (nothing is written), giving
        all-or-nothing semantics for a multi-section save.
        """
        self._batch_depth += 1
        if self._batch_doc is None:
            self._batch_doc = self._read_document()
        try:
            yield self
        except BaseException:
            if self._batch_depth == 1:
                self._batch_doc = None
            self._batch_depth -= 1
            raise
        else:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                document = self._batch_doc
                self._batch_doc = None
                if document is not None:
                    self._write_document(document)
