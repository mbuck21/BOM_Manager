from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


def format_timestamp(iso_str: str) -> str:
    """Convert an ISO-8601 timestamp like '2026-02-26T14:30:00Z' to 'Feb 26, 2026  2:30 PM'."""
    if not iso_str or iso_str == "—":
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # %#I on Windows, %-I on Unix — fall back gracefully
        try:
            return dt.strftime("%b %d, %Y  %#I:%M %p")
        except ValueError:
            return dt.strftime("%b %d, %Y  %-I:%M %p")
    except (ValueError, TypeError):
        return iso_str


def resolve_data_dir(raw_value: str) -> Path:
    candidate = Path(raw_value.strip() or "demo_data").expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def part_key(record: dict[str, Any]) -> str:
    """Normalized part number of a part/relationship-side record."""
    return str(record.get("part_number", "")).strip()


def build_part_lookup(parts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """part_number -> part record, skipping records with a blank part number."""
    return {part_key(part): part for part in parts if part_key(part)}


def collect_service_result(
    label: str,
    result: dict[str, Any],
    errors: list[str],
    notes: list[str],
) -> None:
    """Fold one backend `{ok,errors,warnings}` result into shared error/note lists."""
    if not result.get("ok"):
        for error in result.get("errors", []):
            errors.append(f"{label}: {error}")
    for warning in result.get("warnings", []):
        notes.append(f"{label}: {warning}")


def show_service_result(title: str, result: dict[str, Any]) -> None:
    if result.get("ok"):
        st.success(f"{title} succeeded")
    else:
        st.error(f"{title} failed")

    for warning in result.get("warnings", []):
        st.warning(warning)
    for error in result.get("errors", []):
        st.error(error)
