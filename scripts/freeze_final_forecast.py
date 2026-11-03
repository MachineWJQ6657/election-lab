"""Seal an auditable pre-result forecast without refitting production parameters."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from election_forecast.http_cache import CachedHTTPClient
from election_forecast.lineage import fingerprint, verify_forecast_manifest, verify_table_report

ROOT = Path(__file__).resolve().parents[1]


def require_fresh_observations(observations: list[str], start: datetime, end: datetime) -> None:
    if not observations or start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Freshness gate requires observations and timezone-aware bounds")
    for value in observations:
        observed = datetime.fromisoformat(value)
        if observed.tzinfo is None or not start <= observed <= end:
            raise ValueError(f"Source was not observed inside the final refresh window: {value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-start", required=True, help="UTC ISO timestamp before forced fetch"
    )
    args = parser.parse_args()
    start, cutoff = datetime.fromisoformat(args.refresh_start), datetime.now(UTC)
    artifacts, processed = ROOT / "artifacts", ROOT / "data/processed"
    forecast = verify_forecast_manifest(artifacts, processed)
    collection = json.loads((artifacts / "latest_collection_report.json").read_text("utf-8"))
    early = json.loads((artifacts / "early_voting_report.json").read_text("utf-8"))
    # A failed parsing pass may be resumed from payloads freshly downloaded in
    # this same refresh window. The timestamp gate, not the cache flag, decides.
    if early["as_of"] != forecast["as_of"]:
        raise ValueError("Early-vote and forecast as-of dates must match")
    verify_table_report(
        collection, processed, required=("polls_latest", "polls_latest_raw_sources")
    )
    verify_table_report(
        early, processed, required=("early_voting_latest", "early_voting_demographics")
    )
    observations = [r["observed_at"] for r in collection["requests"] if r["status"] != "failed"]
    markets = pd.read_parquet(processed / "prediction_markets_latest.parquet")
    observations.extend(pd.to_datetime(markets.fetched_at, utc=True).astype(str).unique().tolist())
    client = CachedHTTPClient()
    early_sources = []
    frame = pd.read_parquet(processed / "early_voting_latest.parquet")
    for url, group in frame.groupby("source_url"):
        payload = client.get_cached(url)
        _, path = client._paths(url)
        metadata = json.loads(path.read_text("utf-8"))
        if set(group.source_sha256) != {metadata["sha256"]}:
            raise ValueError(f"Early-vote source payload changed after parsing: {url}")
        if not payload:
            raise ValueError("Empty early-vote source payload")
        observations.append(metadata["fetched_at"])
        early_sources.append(
            {
                "url": url,
                "sha256": metadata["sha256"],
                "observed_at": metadata["fetched_at"],
                "latest_report_date": str(group.snapshot_date.max()),
            }
        )
    require_fresh_observations(observations, start, cutoff)
    stamp = cutoff.strftime("%Y%m%dT%H%M%SZ")
    directory = artifacts / f"final_2026_{stamp}"
    directory.mkdir(exist_ok=False)
    table_names = set(forecast["source_sha256"]) | {
        "early_voting_latest",
        "early_voting_demographics",
        "mit_results_2024",
        "fec_candidates_2026",
        "prediction_markets_latest",
    }
    inputs = {name: fingerprint(processed / f"{name}.parquet") for name in sorted(table_names)}
    outputs = forecast["output_sha256"]
    for name in table_names:
        shutil.copy2(processed / f"{name}.parquet", directory / f"{name}.parquet")
    for name in set(outputs) | {
        "forecast_manifest.json",
        "early_voting_report.json",
        "latest_collection_report.json",
        "authenticity_report.json",
        "model_card.json",
    }:
        shutil.copy2(artifacts / name, directory / name)
    release = {
        "release_kind": "final_pre_result_forecast",
        "as_of": forecast["as_of"],
        "frozen_at": cutoff.isoformat(),
        "refresh_started_at": start.isoformat(),
        "polls_latest_sha256": inputs["polls_latest"],
        "input_table_sha256": inputs,
        "forecast_output_sha256": outputs,
        "engine_sha256": forecast["engine_sha256"],
        "source_observations": len(observations),
        "archived_primary_review_urls": [
            r["url"]
            for r in collection.get("primary_release_reviews", [])
            if r.get("verification_origin") == "archived_review_source_unavailable"
        ],
        "early_vote_sources": early_sources,
        "failed_poll_requests": [
            r["url"] for r in collection["requests"] if r["status"] == "failed"
        ],
        "historical_validation_floor_days": 7,
        "scope": "No 2026 election-night result feed. Same production rules; election-day "
        "probabilities use nearest available 7-day historical calibration, not a "
        "validated 0-day backtest. Early-vote scenarios do not change official win odds.",
        "archive_directory": directory.name,
    }
    encoded = json.dumps(release, indent=2, allow_nan=False)
    (directory / "release.json").write_text(encoded, encoding="utf-8")
    (artifacts / "final_release.json").write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "frozen_at": release["frozen_at"],
                "archive": str(directory),
                "fresh_source_observations": len(observations),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
