"""Measure sensitivity to missing release timestamps, without changing live forecasts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from evaluate_poll_decay import load_history, score

from election_forecast.backtest import (
    BacktestResult,
    backtest_selection_policy,
    run_walk_forward_backtest,
)
from election_forecast.features import build_race_snapshots
from election_forecast.validation_cache import cache_key, cached_validation

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "publication_lag_experiment_20261019"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    history, outcomes = load_history()
    engine_key = cache_key(history, outcomes)
    _, baseline_result, _ = cached_validation(history, outcomes)
    baseline_predictions = baseline_result.predictions
    baseline, _ = backtest_selection_policy(
        BacktestResult(baseline_predictions, pd.DataFrame(), pd.DataFrame()), target_horizon=15
    )
    directory = OUTPUT / engine_key
    directory.mkdir(exist_ok=True)
    path = directory / "predictions_3day_lag.parquet"
    if path.exists():
        predictions = pd.read_parquet(path)
    else:
        print("Begin conservative 3-day publication-lag sensitivity", flush=True)
        snapshots = build_race_snapshots(
            history,
            (7, 14, 30, 60, 90),
            publication_lag_days=3,
            supplemental_outcomes=outcomes,
        )
        predictions = run_walk_forward_backtest(snapshots).predictions
        predictions.to_parquet(path, index=False)
    delayed, summary = backtest_selection_policy(
        BacktestResult(predictions, pd.DataFrame(), pd.DataFrame()), target_horizon=15
    )
    delayed.to_parquet(OUTPUT / "selected_3day_lag.parquet", index=False)
    summary.to_csv(OUTPUT / "summary_3day_lag.csv", index=False)
    keys = ["cycle", "race_id", "office", "horizon"]
    common_keys = baseline[keys].merge(delayed[keys], on=keys)
    original_common = baseline.merge(common_keys, on=keys)
    delayed_common = delayed.merge(common_keys, on=keys)
    report = {
        "research_only": True,
        "engine_key": engine_key,
        "design": "Three days of conservative delay after fieldwork ends, applied consistently "
        "to historical training and held-out snapshots. Compare identical races at "
        "the nearest current horizon with nested office-model selection.",
        "baseline_all": score(baseline),
        "delayed_all": score(delayed),
        "baseline_common_races": score(original_common),
        "delayed_common_races": score(delayed_common),
        "scope": "A delay assumption is a sensitivity analysis, not recovered publication "
        "history. Backfilled/revised data can have longer delays. Live forecasts remain "
        "unchanged; actual as-published timestamps are the preferred future input.",
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
