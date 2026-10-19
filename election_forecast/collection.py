"""Publish acquisition freshness without calling cached observations live updates."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from .lineage import verify_table_report


def summarize_collection(report: dict, processed_dir: Path) -> dict:
    verify_table_report(
        report, processed_dir, required=("polls_latest", "polls_latest_raw_sources")
    )
    statuses = Counter()
    observations = []
    failures = []
    for row in report["requests"]:
        status = row["status"]
        if status not in {"network", "cache", "failed"}:
            raise ValueError("Unknown acquisition status")
        statuses[status] += 1
        checked = datetime.fromisoformat(row["checked_at"])
        if checked.tzinfo is None:
            raise ValueError("Acquisition timestamps must include timezones")
        if status == "failed":
            failures.append({key: row.get(key) for key in ("url", "http_status", "error_class")})
        else:
            observed = datetime.fromisoformat(row["observed_at"])
            if observed.tzinfo is None or observed > checked:
                raise ValueError("Invalid or future acquisition observation")
            observations.append(observed)
    if dict(statuses) != report["request_status_counts"]:
        raise ValueError("Acquisition status totals do not reconcile")
    return {
        "checked_at": report["checked_at"],
        "request_status_counts": dict(statuses),
        "oldest_observed_at": min(observations).isoformat() if observations else None,
        "latest_observed_at": max(observations).isoformat() if observations else None,
        "raw_rows_by_source": report["raw_rows_by_source"],
        "failed_requests": failures,
        "scope": report["scope"],
    }
