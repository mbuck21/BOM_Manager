"""Pure (Streamlit-free) transforms over weight-rollup output.

These functions turn the result of ``rollup_weight_with_maturity`` — its ``breakdown``
(per-path contributions) and ``part_totals`` (per-part aggregates) — into the row
shapes the Weight & Rollup views render. Keeping them pure makes the math unit-testable
and lets every sub-tab share ONE rollup call.
"""

from __future__ import annotations

from typing import Any

from bom_backend.constants import UNIT_WEIGHT_KEY, WEIGHT_BUDGET_KEY
from bom_backend.utils.parsing import base_number

FAMILY_MODE = "family"
ATTR_MODE_PREFIX = "attr:"
NO_VALUE_BUCKET = "(none)"


def direct_child_totals(
    breakdown: list[dict[str, Any]],
    root_part_number: str,
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate a whole-root rollup breakdown into per-direct-child rows.

    Each breakdown row's path starts at the root; the row is attributed to path[1]
    (the direct child it descends through). A path of length 1 means the root itself
    carries a unit weight (an allocation covering the entire assembly).

    Returns {"rows": [...], "root_self_weight": float, "root_self_maturity": float}.
    Rows are per child part; multiple links to the same child merge into one row.
    """
    per_child: dict[str, dict[str, float]] = {}
    root_self_weight = 0.0
    root_self_maturity = 0.0

    for row in breakdown:
        path = row.get("path") or []
        contribution = float(row.get("contribution", 0) or 0)
        unit_weight = float(row.get("unit_weight", 0) or 0)
        effective = float(row.get("effective_unit_weight", unit_weight) or 0)
        multiplier = float(row.get("multiplier", 1) or 1)
        maturity_added = (effective - unit_weight) * multiplier

        if len(path) < 2:
            root_self_weight += contribution
            root_self_maturity += maturity_added
            continue

        child = str(path[1]).strip()
        bucket = per_child.setdefault(
            child, {"effective_weight": 0.0, "maturity_added": 0.0}
        )
        bucket["effective_weight"] += contribution
        bucket["maturity_added"] += maturity_added

    qty_by_child: dict[str, float] = {}
    for rel in relationships:
        if str(rel.get("parent_part_number", "")).strip() == root_part_number:
            child = str(rel.get("child_part_number", "")).strip()
            try:
                qty_by_child[child] = qty_by_child.get(child, 0.0) + float(rel.get("qty", 0) or 0)
            except (TypeError, ValueError):
                continue

    rows = [
        {
            "part_number": child,
            "qty": qty_by_child.get(child, 0.0),
            "effective_weight": bucket["effective_weight"],
            "maturity_added": bucket["maturity_added"],
            "base_weight": bucket["effective_weight"] - bucket["maturity_added"],
        }
        for child, bucket in per_child.items()
    ]
    # Direct children with no weighted descendants still deserve a (zero) row.
    for child, qty in qty_by_child.items():
        if child not in per_child:
            rows.append(
                {
                    "part_number": child,
                    "qty": qty,
                    "effective_weight": 0.0,
                    "maturity_added": 0.0,
                    "base_weight": 0.0,
                }
            )

    rows.sort(key=lambda item: (-item["effective_weight"], item["part_number"]))
    return {
        "rows": rows,
        "root_self_weight": root_self_weight,
        "root_self_maturity": root_self_maturity,
    }


def group_contributions(
    part_totals: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    """Group per-part rollup contributions.

    mode: "family" groups by drawing base number; "attr:<key>" groups by the value of
    any part attribute (missing/blank values land in the "(none)" bucket).

    Weight is counted where a part carries its own unit weight — assemblies that roll
    up from children appear through their weighted descendants' groups.
    """
    part_lookup = {
        str(p.get("part_number", "")).strip(): p
        for p in parts
        if str(p.get("part_number", "")).strip()
    }

    def group_key(part_number: str) -> str:
        if mode == FAMILY_MODE:
            return base_number(part_number)
        if mode.startswith(ATTR_MODE_PREFIX):
            attr_key = mode[len(ATTR_MODE_PREFIX):]
            value = (part_lookup.get(part_number, {}).get("attributes") or {}).get(attr_key)
            text = "" if value is None else str(value).strip()
            return text or NO_VALUE_BUCKET
        raise ValueError(f"Unknown grouping mode '{mode}'")

    total_weight = sum(float(row.get("total_contribution", 0) or 0) for row in part_totals)

    groups: dict[str, dict[str, Any]] = {}
    for row in part_totals:
        part_number = str(row.get("part_number", "")).strip()
        contribution = float(row.get("total_contribution", 0) or 0)
        occurrences = int(row.get("occurrences", 0) or 0)
        key = group_key(part_number)

        group = groups.setdefault(
            key,
            {"group": key, "total": 0.0, "occurrences": 0, "members": []},
        )
        group["total"] += contribution
        group["occurrences"] += occurrences
        group["members"].append(
            {
                "part_number": part_number,
                "name": part_lookup.get(part_number, {}).get("name", ""),
                "contribution": contribution,
                "occurrences": occurrences,
            }
        )

    rows: list[dict[str, Any]] = []
    for group in groups.values():
        members = sorted(group["members"], key=lambda m: (-m["contribution"], m["part_number"]))
        label = members[0]["name"] if members else ""
        if mode == FAMILY_MODE:
            # Prefer the name of the member equal to the base itself if one exists.
            for member in members:
                if member["part_number"] == group["group"]:
                    label = member["name"]
                    break
        rows.append(
            {
                "group": group["group"],
                "label": label,
                "total": group["total"],
                "part_count": len({m["part_number"] for m in members}),
                "occurrences": group["occurrences"],
                "pct": (group["total"] / total_weight * 100.0) if total_weight > 0 else 0.0,
                "members": members,
            }
        )

    rows.sort(key=lambda item: (-item["total"], item["group"]))
    return rows


def attribute_coverage(
    part_totals: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    attribute_keys: list[str],
) -> list[dict[str, Any]]:
    """For each attribute column: how much of the rolled-up weight has a value set.

    Generic data-quality readout — works for any user-defined column (weight basis,
    category, zone, ...). Returns one row per key with covered weight, total, pct,
    and the number of contributing parts missing the value.
    """
    attrs_by_part = {
        str(p.get("part_number", "")).strip(): (p.get("attributes") or {})
        for p in parts
    }
    total_weight = sum(float(row.get("total_contribution", 0) or 0) for row in part_totals)

    rows: list[dict[str, Any]] = []
    for key in attribute_keys:
        covered = 0.0
        missing_parts = 0
        for row in part_totals:
            part_number = str(row.get("part_number", "")).strip()
            contribution = float(row.get("total_contribution", 0) or 0)
            value = attrs_by_part.get(part_number, {}).get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_parts += 1
            else:
                covered += contribution
        rows.append(
            {
                "attribute": key,
                "covered_weight": covered,
                "total_weight": total_weight,
                "pct": (covered / total_weight * 100.0) if total_weight > 0 else 0.0,
                "missing_parts": missing_parts,
            }
        )

    rows.sort(key=lambda item: item["attribute"])
    return rows


def read_weight_budget(root_part: dict[str, Any] | None) -> float | None:
    if not root_part:
        return None
    raw = (root_part.get("attributes") or {}).get(WEIGHT_BUDGET_KEY)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def allocation_overrides(
    parts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Parts that carry a unit weight AND have children — their children are not
    counted in the rollup (the unit weight is an allocation/override)."""
    child_counts: dict[str, int] = {}
    for rel in relationships:
        parent = str(rel.get("parent_part_number", "")).strip()
        child_counts[parent] = child_counts.get(parent, 0) + 1

    rows: list[dict[str, Any]] = []
    for part in parts:
        part_number = str(part.get("part_number", "")).strip()
        attributes = part.get("attributes") or {}
        if attributes.get(UNIT_WEIGHT_KEY) is None:
            continue
        children = child_counts.get(part_number, 0)
        if children > 0:
            try:
                weight = float(attributes.get(UNIT_WEIGHT_KEY))
            except (TypeError, ValueError):
                weight = None
            rows.append(
                {
                    "part_number": part_number,
                    "name": part.get("name", ""),
                    "unit_weight": weight,
                    "children_not_counted": children,
                }
            )

    rows.sort(key=lambda item: (-(item["unit_weight"] or 0), item["part_number"]))
    return rows
