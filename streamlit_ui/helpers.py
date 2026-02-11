from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


def resolve_data_dir(raw_value: str) -> Path:
    candidate = Path(raw_value.strip() or "demo_data").expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


def parse_csv_whitelist(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",")]
    return [item for item in values if item]


def part_rows(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "part_number": item["part_number"],
            "name": item["name"],
            "last_updated": item["last_updated"],
            "attributes": json.dumps(item.get("attributes", {}), sort_keys=True),
        }
        for item in parts
    ]


def relationship_rows(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rel_id": item["rel_id"],
            "parent_part_number": item["parent_part_number"],
            "child_part_number": item["child_part_number"],
            "qty": item["qty"],
            "last_updated": item["last_updated"],
            "attributes": json.dumps(item.get("attributes", {}), sort_keys=True),
        }
        for item in relationships
    ]


def show_service_result(title: str, result: dict[str, Any], *, show_data: bool = False) -> None:
    if result.get("ok"):
        st.success(f"{title} succeeded")
    else:
        st.error(f"{title} failed")

    for warning in result.get("warnings", []):
        st.warning(warning)
    for error in result.get("errors", []):
        st.error(error)

    if show_data and result.get("data"):
        st.json(result["data"])


def save_uploaded_csv(data_dir: Path, category: str, uploaded_file: Any) -> Path:
    import_dir = data_dir / "imports" / category
    import_dir.mkdir(parents=True, exist_ok=True)
    target = import_dir / Path(str(uploaded_file.name)).name
    target.write_bytes(uploaded_file.getvalue())
    return target
