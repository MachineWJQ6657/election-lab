"""Reuse historical validation only when data, configuration and engine agree."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from .backtest import BacktestResult, run_walk_forward_backtest, summarize_predictions
from .features import build_race_snapshots
from .lineage import fingerprint
from .settings import settings


def _frame_digest(frame: pd.DataFrame | None) -> str | None:
    if frame is None:
        return None
    digest = hashlib.sha256()
    digest.update(str([(name, str(dtype)) for name, dtype in frame.dtypes.items()]).encode())
    # Row order matters; incidental pandas index labels are not model features.
    digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def cache_key(
    history: pd.DataFrame,
    outcomes: pd.DataFrame | None,
    *,
    pollster_pooling: Iterable[str] = (),
) -> str:
    directory = Path(__file__).parent
    signature = {
        "history": _frame_digest(history),
        "outcomes": _frame_digest(outcomes),
        "engine": {
            name: fingerprint(directory / name)
            for name in (
                "features.py",
                "backtest.py",
                "probability_calibration.py",
                "pollsters.py",
                "names.py",
                "validation_cache.py",
            )
        },
        "horizons": [7, 14, 30, 60, 90],
        "half_life": 30,
        "lookback": 120,
        "publication_lag": 0,
        "min_polls": 2,
        "pollster_pooling": sorted(set(pollster_pooling)),
        "runtime": [sys.version, np.__version__, pd.__version__, sklearn.__version__],
    }
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()


def cached_validation(
    history: pd.DataFrame,
    outcomes: pd.DataFrame | None,
    *,
    cache_dir: Path | None = None,
    pollster_pooling: Iterable[str] = (),
) -> tuple[pd.DataFrame, BacktestResult, bool]:
    pooling = tuple(sorted(set(pollster_pooling)))
    key = cache_key(history, outcomes, pollster_pooling=pooling)
    directory = (cache_dir or settings.artifact_dir / "validation_cache") / key
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            if set(manifest) == {"snapshots.parquet", "predictions.parquet"} and all(
                fingerprint(directory / name) == digest for name, digest in manifest.items()
            ):
                snapshots = pd.read_parquet(directory / "snapshots.parquet")
                predictions = pd.read_parquet(directory / "predictions.parquet")
                return snapshots, summarize_predictions(predictions), True
        except (OSError, ValueError):
            pass  # Recompute rather than silently accepting an incomplete/corrupt cache.
    snapshots = build_race_snapshots(
        history,
        (7, 14, 30, 60, 90),
        supplemental_outcomes=outcomes,
        pollster_pooling=pooling,
    )
    result = run_walk_forward_backtest(snapshots)
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in [
        ("snapshots.parquet", snapshots),
        ("predictions.parquet", result.predictions),
    ]:
        temporary = directory / f"{name}.{os.getpid()}.tmp"
        frame.to_parquet(temporary, index=False)
        temporary.replace(directory / name)
    manifest = {
        name: fingerprint(directory / name) for name in ("snapshots.parquet", "predictions.parquet")
    }
    temporary_manifest = manifest_path.with_suffix(f".{os.getpid()}.tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary_manifest.replace(manifest_path)
    return snapshots, result, False
