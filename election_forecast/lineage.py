"""Version fingerprints prevent mixed-age website snapshots after partial runs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from .settings import settings

FORECAST_OUTPUTS = (
    "latest_forecast.csv",
    "forecast_2026_control.json",
    "latest_poll_evidence.csv",
    "latest_model_selection.csv",
    "prediction_market_consensus.csv",
    "forecast_2026_seat_distributions.csv",
)
INPUT_TABLES = ("polls_latest", "polls_latest_raw_sources", "race_catalog_latest")
OPTIONAL_TRAINING_TABLES = ("polls_history", "polls_archive", "house_national_history")
FORECAST_ENGINE_FILES = (
    "cli.py",
    "features.py",
    "pollsters.py",
    "validation_cache.py",
    "backtest.py",
    "history.py",
    "coverage.py",
    "house_seats.py",
    "simulation.py",
    "market_calibration.py",
    "probability_calibration.py",
    "names.py",
    "contest_scope.py",
    "evidence.py",
    "explain.py",
    "lineage.py",
)


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_table_report(report: dict, processed_dir: Path, *, required: tuple[str, ...]) -> None:
    """An audit of a different table snapshot must not decorate today's forecast."""
    expected = report.get("dataset_sha256", {})
    if not set(required).issubset(expected):
        raise ValueError("Audit report lacks dataset fingerprints; regenerate the audit")
    for name in required:
        if fingerprint(processed_dir / f"{name}.parquet") != expected[name]:
            raise ValueError(f"Audit dataset snapshot mismatch: {name}; regenerate the audit")


def engine_fingerprints() -> dict[str, str]:
    return {name: fingerprint(Path(__file__).parent / name) for name in FORECAST_ENGINE_FILES}


def verify_engine(expected: dict[str, str]) -> None:
    if engine_fingerprints() != expected:
        raise ValueError("Forecast engine changed during computation; rerun before exporting")


def source_fingerprints() -> dict[str, str]:
    names = list(INPUT_TABLES) + [
        name
        for name in OPTIONAL_TRAINING_TABLES
        if (settings.processed_dir / f"{name}.parquet").exists()
    ]
    return {name: fingerprint(settings.processed_dir / f"{name}.parquet") for name in names}


def verify_observed_cutoff(frame: pd.DataFrame, as_of: date, label: str) -> None:
    """A fieldwork cutoff cannot backdate our first observation of live data."""
    if "fetched_at" not in frame:
        raise ValueError(f"{label} lacks observation timestamps; an archived snapshot is required")
    observed = pd.to_datetime(frame["fetched_at"], utc=True, format="mixed", errors="coerce")
    if observed.isna().any():
        raise ValueError(f"{label} has invalid observation timestamps")
    latest = observed.dt.tz_convert("America/New_York").dt.date.max()
    if latest > as_of:
        raise ValueError(
            f"{label} was observed on {latest}, after requested as-of {as_of}; "
            "use a retained historical snapshot instead of today's live tables"
        )


def verify_sources(expected: dict[str, str]) -> None:
    if source_fingerprints() != expected:
        raise ValueError("Source tables changed during forecasting; rerun before exporting")


def write_forecast_manifest(
    *,
    as_of: str,
    sources: dict[str, str],
    validation_engine_key: str | None = None,
    engine_versions: dict[str, str] | None = None,
) -> None:
    verify_sources(sources)
    versions = engine_versions if engine_versions is not None else engine_fingerprints()
    verify_engine(versions)
    manifest = {
        "as_of": as_of,
        "generated_at": datetime.now(UTC).isoformat(),
        "validation_engine_key": validation_engine_key,
        "engine_sha256": versions,
        "source_sha256": sources,
        "output_sha256": {
            name: fingerprint(settings.artifact_dir / name) for name in FORECAST_OUTPUTS
        },
        "scope": "File version and integrity checks; not proof of underlying survey accuracy.",
    }
    path = settings.artifact_dir / "forecast_manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(path)


def verify_forecast_manifest(artifact_dir: Path, processed_dir: Path) -> dict:
    manifest = json.loads((artifact_dir / "forecast_manifest.json").read_text(encoding="utf-8"))
    if "engine_sha256" in manifest:
        verify_engine(manifest["engine_sha256"])
    for name, expected in manifest["source_sha256"].items():
        if fingerprint(processed_dir / f"{name}.parquet") != expected:
            raise ValueError(f"Forecast source snapshot mismatch: {name}; regenerate forecast")
    for name, expected in manifest["output_sha256"].items():
        if fingerprint(artifact_dir / name) != expected:
            raise ValueError(f"Forecast output snapshot mismatch: {name}; regenerate forecast")
    return manifest
