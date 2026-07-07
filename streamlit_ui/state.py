"""Shared session-state keys and app-wide constants.

Kept in one tiny module so the entry point, sidebar, and tab modules can share them
without circular imports.
"""

from __future__ import annotations

# ── session-state keys ────────────────────────────────────────────────────────
DATA_DIR_KEY = "data_dir"
DATA_DIR_INPUT_KEY = "data_dir_input"
ACTIVE_SNAPSHOT_ID_KEY = "active_snapshot_id"
SNAPSHOT_SELECTION_INITIALIZED_KEY = "snapshot_selection_initialized"
SNAPSHOT_SELECTION_DATA_DIR_KEY = "snapshot_selection_data_dir"
UNIVERSAL_ROOT_PART_KEY = "universal_root_part_number"
ROOT_DIRECTORY_FILTER_KEY = "root_directory_filter"

# Sentinel option in the version selector meaning "the editable live data".
LIVE_DATA_OPTION = "__live_data__"

# ── point of contact ──────────────────────────────────────────────────────────
POC_NAME = "Matt Buckley"
POC_EMAIL = "matthew.p.buckley@lmco.com"
POC_LINE = f"{POC_NAME} — {POC_EMAIL}"
