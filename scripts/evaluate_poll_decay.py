"""Predeclared recency experiment; write research artifacts, not production inputs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from election_forecast.backtest import (
    BacktestResult,
    backtest_selection_policy,
    run_walk_forward_backtest,
)
from election_forecast.features import build_race_snapshots
from election_forecast.history import merge_historical_sources
from election_forecast.validation_cache import cache_key, cached_validation
from election_forecast.warehouse import Warehouse

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "decay_experiment_20261019"
HALF_LIVES = (21.0, 30.0, 45.0)
TARGET_HORIZON = 15
MIN_PRIOR_RACES = 100
MIN_PRIOR_CYCLES = 3
MIN_BRIER_GAIN = 0.002


def score(frame: pd.DataFrame) -> dict:
    y = frame.actual_margin.gt(0).astype(float)
    return {
        "races": len(frame),
        "brier": float(np.mean(np.square(frame.dem_win_probability - y))),
        "mae": float(np.mean(np.abs(frame.predicted_margin - frame.actual_margin))),
        "accuracy": float(np.mean(frame.predicted_margin.gt(0) == y.astype(bool))),
    }


def load_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    warehouse = Warehouse()
    history = warehouse.read("polls_history")
    archive = warehouse.read("polls_archive")
    history = merge_historical_sources(history, archive, min_cycle=2008)
    outcomes = warehouse.read("house_national_history")[["cycle", "generic_house_margin"]]
    outcomes = outcomes.rename(columns={"generic_house_margin": "actual_margin"})
    outcomes["office"], outcomes["location"] = "generic_ballot", "US"
    return history, outcomes


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    history, outcomes = load_history()
    engine_key = cache_key(history, outcomes)
    engine_directory = OUTPUT / engine_key
    engine_directory.mkdir(exist_ok=True)
    details, summary = {}, []
    for half_life in HALF_LIVES:
        target = engine_directory / f"predictions_{half_life:g}.parquet"
        if target.exists():
            predictions = pd.read_parquet(target)
        elif half_life == 30:
            _, baseline_result, _ = cached_validation(history, outcomes)
            predictions = baseline_result.predictions
            predictions.to_parquet(target, index=False)
        else:
            print(f"Begin half-life {half_life:g} days", flush=True)
            snapshots = build_race_snapshots(
                history,
                (7, 14, 30, 60, 90),
                half_life_days=half_life,
                supplemental_outcomes=outcomes,
            )
            predictions = run_walk_forward_backtest(snapshots).predictions
            predictions.to_parquet(target, index=False)
        result = BacktestResult(predictions, pd.DataFrame(), pd.DataFrame())
        detail, aggregate = backtest_selection_policy(result, target_horizon=TARGET_HORIZON)
        detail.to_parquet(engine_directory / f"selected_{half_life:g}.parquet", index=False)
        aggregate.to_csv(engine_directory / f"summary_{half_life:g}.csv", index=False)
        details[half_life] = detail
        summary.append({"half_life_days": half_life, **score(detail)})
        print(summary[-1], flush=True)

    # Outer selection: choose a recency setting using earlier held-out cycles
    # only, then judge it on a cycle the choice could not inspect.
    folds, decisions = [], []
    baseline = details[30.0]
    for cycle in sorted(baseline.cycle.unique()):
        prior = baseline[baseline.cycle.lt(cycle)]
        chosen = 30.0
        prior_scores = {}
        if prior.cycle.nunique() >= MIN_PRIOR_CYCLES and len(prior) >= MIN_PRIOR_RACES:
            for half_life, detail in details.items():
                subset = detail[detail.cycle.lt(cycle)]
                common = prior[["race_id", "cycle"]].merge(subset, on=["race_id", "cycle"])
                prior_scores[half_life] = score(common)["brier"]
            best = min(prior_scores, key=prior_scores.get)
            if prior_scores[30.0] - prior_scores[best] >= MIN_BRIER_GAIN:
                chosen = best
        current = details[chosen][details[chosen].cycle.eq(cycle)].copy()
        current["half_life_days"] = chosen
        folds.append(current)
        decisions.append(
            {"cycle": int(cycle), "half_life_days": chosen, "earlier_cycle_brier": prior_scores}
        )
    outer = pd.concat(folds, ignore_index=True)
    outer.to_parquet(OUTPUT / "outer_policy_predictions.parquet", index=False)
    report = {
        "research_only": True,
        "engine_key": engine_key,
        "design": "21/30/45-day half-lives; identical expanding-cycle training; office selection "
        "at nearest current horizon; outer decay selection uses earlier cycles only.",
        "target_horizon": TARGET_HORIZON,
        "adoption_gate": {
            "min_prior_races": MIN_PRIOR_RACES,
            "min_prior_cycles": MIN_PRIOR_CYCLES,
            "earlier_brier_gain_to_switch": MIN_BRIER_GAIN,
        },
        "challengers": summary,
        "outer_policy": score(outer),
        "baseline_30": score(baseline),
        "decisions": decisions,
        "scope": "Historical poll-model races only; not current rating priors, markets, early "
        "vote corrections or 2026 accuracy. No production parameter is changed here.",
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({"outer_policy": report["outer_policy"], "baseline_30": report["baseline_30"]}),
        flush=True,
    )


if __name__ == "__main__":
    main()
