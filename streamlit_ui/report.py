"""Pure logic for the weekly change report, part history, and staleness views.

Nothing here touches Streamlit or the filesystem: callers pass in snapshot records,
rollup results, and diff output; these functions shape them into report rows and a
copy-ready text block for the weekly program update.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bom_backend.constants import UNIT_WEIGHT_KEY

MOVER_THRESHOLD = 0.001


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _totals_by_part(part_totals: list[dict[str, Any]]) -> dict[str, float]:
    return {
        str(row.get("part_number", "")).strip(): float(row.get("total_contribution", 0) or 0)
        for row in part_totals
    }


def default_baseline_index(snapshots: list[dict[str, Any]], now_iso: str, min_age_days: int = 6) -> int:
    """Index (into a newest-first list) of the newest version at least min_age_days old.

    Falls back to the oldest version when nothing is old enough.
    """
    now = _parse_iso(now_iso)
    if now is None or not snapshots:
        return 0
    for index, snapshot in enumerate(snapshots):
        created = _parse_iso(snapshot.get("created_at", ""))
        if created is not None and (now - created).days >= min_age_days:
            return index
    return len(snapshots) - 1


def build_weekly_report(
    baseline_snapshot: dict[str, Any],
    baseline_rollup: dict[str, Any],
    live_rollup: dict[str, Any],
    diff_data: dict[str, Any],
    part_lookup: dict[str, dict[str, Any]],
    budget: float | None,
    now_iso: str,
    top_movers: int = 10,
) -> dict[str, Any]:
    """Shape 'what changed since the baseline' into one report dict."""
    total_before = float(baseline_rollup.get("total", 0) or 0)
    total_after = float(live_rollup.get("total", 0) or 0)
    delta = total_after - total_before
    delta_pct = (delta / total_before * 100.0) if total_before else 0.0

    before_by_part = _totals_by_part(baseline_rollup.get("part_totals") or [])
    after_by_part = _totals_by_part(live_rollup.get("part_totals") or [])

    def part_name(part_number: str) -> str:
        return str(part_lookup.get(part_number, {}).get("name", "")).strip()

    movers: list[dict[str, Any]] = []
    for part_number in set(before_by_part) | set(after_by_part):
        before = before_by_part.get(part_number, 0.0)
        after = after_by_part.get(part_number, 0.0)
        part_delta = after - before
        if abs(part_delta) < MOVER_THRESHOLD:
            continue
        movers.append(
            {
                "part_number": part_number,
                "name": part_name(part_number),
                "before": before,
                "after": after,
                "delta": part_delta,
            }
        )
    movers.sort(key=lambda item: (-abs(item["delta"]), item["part_number"]))
    movers = movers[:top_movers]

    part_changes = diff_data.get("part_changes") or {}
    rel_changes = diff_data.get("relationship_changes") or {}

    def _part_rows(records: list[dict[str, Any]], weights: dict[str, float]) -> list[dict[str, Any]]:
        rows = []
        for record in records:
            part_number = str(record.get("part_number", "")).strip()
            rows.append(
                {
                    "part_number": part_number,
                    "name": str(record.get("name", "")).strip(),
                    "weight": weights.get(part_number, 0.0),
                }
            )
        rows.sort(key=lambda item: (-item["weight"], item["part_number"]))
        return rows

    budget_info = None
    if budget is not None:
        margin = budget - total_after
        budget_info = {"budget": budget, "margin": margin, "over": margin < 0}

    return {
        "generated_at": now_iso,
        "baseline": {
            "snapshot_id": str(baseline_snapshot.get("snapshot_id", "")).strip(),
            "created_at": str(baseline_snapshot.get("created_at", "")).strip(),
            "label": str(baseline_snapshot.get("label") or "").strip(),
        },
        "total_before": total_before,
        "total_after": total_after,
        "delta": delta,
        "delta_pct": delta_pct,
        "budget": budget_info,
        "movers": movers,
        "added_parts": _part_rows(part_changes.get("added") or [], after_by_part),
        "removed_parts": _part_rows(part_changes.get("removed") or [], before_by_part),
        "modified_parts_count": len(part_changes.get("modified") or []),
        "links_added": len(rel_changes.get("added") or []),
        "links_removed": len(rel_changes.get("removed") or []),
        "links_modified": len(rel_changes.get("modified") or []),
    }


def report_to_text(report: dict[str, Any]) -> str:
    """Plain-text weekly status block, ready to paste into an email or slide."""

    def _date(iso: str) -> str:
        parsed = _parse_iso(iso)
        return parsed.strftime("%b %d, %Y") if parsed else (iso or "—")

    baseline = report.get("baseline") or {}
    baseline_bits = _date(baseline.get("created_at", ""))
    if baseline.get("label"):
        baseline_bits += f" ({baseline['label']})"

    lines = [
        f"WEIGHT STATUS — {_date(report.get('generated_at', ''))}",
        f"Baseline: {baseline_bits}",
        "",
        (
            f"Total weight: {report['total_after']:,.2f}"
            f"  (was {report['total_before']:,.2f}, "
            f"{report['delta']:+,.2f} / {report['delta_pct']:+.1f}%)"
        ),
    ]

    budget = report.get("budget")
    if budget:
        status = "OVER budget" if budget["over"] else "under budget"
        lines.append(
            f"Budget: {budget['budget']:,.2f} — margin {budget['margin']:+,.2f} ({status})"
        )

    movers = report.get("movers") or []
    if movers:
        lines.append("")
        lines.append("Top movers:")
        for mover in movers:
            arrow = "^" if mover["delta"] > 0 else "v"
            name = f"  {mover['name']}" if mover["name"] else ""
            lines.append(
                f"  {arrow} {mover['delta']:+,.2f}  {mover['part_number']}{name}"
                f"  ({mover['before']:,.2f} -> {mover['after']:,.2f})"
            )

    for title, key in (("Added parts", "added_parts"), ("Removed parts", "removed_parts")):
        rows = report.get(key) or []
        if rows:
            listed = ", ".join(f"{r['part_number']} {r['name']}".strip() for r in rows[:8])
            suffix = f" (+{len(rows) - 8} more)" if len(rows) > 8 else ""
            lines.append("")
            lines.append(f"{title} ({len(rows)}): {listed}{suffix}")

    other = (
        f"{report.get('modified_parts_count', 0)} part(s) modified, "
        f"{report.get('links_added', 0)} link(s) added, "
        f"{report.get('links_removed', 0)} removed, "
        f"{report.get('links_modified', 0)} changed"
    )
    lines.append("")
    lines.append(f"Other changes: {other}")
    return "\n".join(lines)


def part_history(snapshots: list[dict[str, Any]], part_number: str) -> list[dict[str, Any]]:
    """Timeline of changes to one part across saved versions.

    Walks versions oldest-first and diffs the part's record between consecutive
    versions. Returns one row per change: {created_at, label, change}.
    """
    part_number = (part_number or "").strip()
    ordered = sorted(
        snapshots,
        key=lambda s: (str(s.get("created_at", "")), str(s.get("snapshot_id", ""))),
    )

    def find_part(snapshot: dict[str, Any]) -> dict[str, Any] | None:
        for record in snapshot.get("parts") or []:
            if str(record.get("part_number", "")).strip() == part_number:
                return record
        return None

    events: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    seen_before = False

    for snapshot in ordered:
        current = find_part(snapshot)
        stamp = {
            "created_at": str(snapshot.get("created_at", "")).strip(),
            "label": str(snapshot.get("label") or "").strip(),
        }

        if current is None:
            if previous is not None:
                events.append({**stamp, "change": "removed from project"})
            previous = None
            continue

        if previous is None:
            events.append(
                {**stamp, "change": "first appears" if not seen_before else "re-added to project"}
            )
            seen_before = True
            previous = current
            continue

        old_name = str(previous.get("name", "")).strip()
        new_name = str(current.get("name", "")).strip()
        if old_name != new_name:
            events.append({**stamp, "change": f"name: {old_name} -> {new_name}"})

        old_attrs = previous.get("attributes") or {}
        new_attrs = current.get("attributes") or {}
        for key in sorted(set(old_attrs) | set(new_attrs)):
            if key not in old_attrs:
                events.append({**stamp, "change": f"{key} set to {new_attrs[key]}"})
            elif key not in new_attrs:
                events.append({**stamp, "change": f"{key} removed (was {old_attrs[key]})"})
            elif old_attrs[key] != new_attrs[key]:
                events.append(
                    {**stamp, "change": f"{key}: {old_attrs[key]} -> {new_attrs[key]}"}
                )

        previous = current

    events.reverse()  # newest first for display
    return events


def stale_parts(
    parts: list[dict[str, Any]],
    now_iso: str,
    weighted_only: bool = True,
) -> list[dict[str, Any]]:
    """Parts sorted oldest-updated-first, with age in days.

    weighted_only limits to parts carrying a unit weight — the ones whose staleness
    actually distorts the rollup.
    """
    now = _parse_iso(now_iso) or datetime.now(timezone.utc)

    rows: list[dict[str, Any]] = []
    for part in parts:
        attributes = part.get("attributes") or {}
        if weighted_only and attributes.get(UNIT_WEIGHT_KEY) is None:
            continue
        updated = _parse_iso(str(part.get("last_updated", "")))
        age_days = (now - updated).days if updated else None
        try:
            unit_weight = float(attributes.get(UNIT_WEIGHT_KEY))
        except (TypeError, ValueError):
            unit_weight = None
        rows.append(
            {
                "part_number": str(part.get("part_number", "")).strip(),
                "name": str(part.get("name", "")).strip(),
                "last_updated": str(part.get("last_updated", "")).strip(),
                "age_days": age_days,
                "unit_weight": unit_weight,
            }
        )

    rows.sort(key=lambda item: (-(item["age_days"] if item["age_days"] is not None else -1), item["part_number"]))
    return rows
