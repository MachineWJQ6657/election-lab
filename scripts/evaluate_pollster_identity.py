"""Test alias-pooled organization weights without changing production labels."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from evaluate_poll_decay import load_history

from election_forecast.backtest import BacktestResult, backtest_selection_policy
from election_forecast.diagnostics import paired_cycle_bootstrap, probability_diagnostics
from election_forecast.pollsters import pollster_key
from election_forecast.validation_cache import cache_key, cached_validation

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/pollster_identity_experiment_20261019"


def main() -> None:
    history, outcomes = load_history()
    baseline_key = cache_key(history, outcomes)
    forecast = pd.read_csv(ROOT / "artifacts/latest_forecast.csv")
    horizon = int(forecast.horizon.iloc[0])
    _, baseline, _ = cached_validation(history, outcomes)
    canonical = history.copy()
    canonical["pollster"] = canonical.pollster.map(pollster_key)
    _, challenger, _ = cached_validation(canonical, outcomes, cache_dir=OUTPUT / "validation_cache")
    records = {}
    for name, result in (
        ("reported_labels", baseline),
        ("normalized_organization_keys", challenger),
    ):
        selected, _ = backtest_selection_policy(
            BacktestResult(result.predictions, pd.DataFrame(), pd.DataFrame()),
            target_horizon=horizon,
        )
        records[name] = selected[selected.office.isin(["house", "senate", "governor"])].copy()
    left, right = records["normalized_organization_keys"], records["reported_labels"]
    comparison = paired_cycle_bootstrap(left, right)
    baseline_score = probability_diagnostics(right)
    challenger_score = probability_diagnostics(left)
    close = right.dem_win_probability.between(0.2, 0.8)
    keys = ["race_id", "cycle", "office", "horizon"]
    challenger_close = left.merge(right.loc[close, keys], on=keys, validate="one_to_one")
    evidence = pd.read_csv(ROOT / "artifacts/latest_poll_evidence.csv")
    evidence["normalized_organization"] = evidence.pollster.map(pollster_key)
    labels = evidence.groupby(["office", "location"], as_index=False).agg(
        polls=("pollster", "size"),
        reported_labels=("pollster", "nunique"),
        normalized_organization_keys=("normalized_organization", "nunique"),
    )
    labels["label_gap"] = labels.reported_labels - labels.normalized_organization_keys
    # The study is a diagnostic, not automatic policy adoption. Pooling sponsors
    # with fieldwork firms can hide client/mode differences even with shared firms.
    report = {
        "engine_key": baseline_key,
        "challenger_key": cache_key(canonical, outcomes),
        "research_only": True,
        "adopted": False,
        "design": "Replace pollster labels with the existing conservative alias keys in "
        "historical training and validation only. This jointly changes frequency caps, "
        "pollster counts and historical house-effect pooling. Outcomes remain untouched.",
        "target_horizon": horizon,
        "baseline": baseline_score,
        "challenger": challenger_score,
        "paired_comparison": comparison,
        "baseline_competitive": probability_diagnostics(right.loc[close]),
        "challenger_on_same_competitive_races": probability_diagnostics(challenger_close),
        "current_label_audit": labels.sort_values("label_gap", ascending=False).to_dict("records"),
        "scope": "Alias-normalized organization keys are not a count of statistically "
        "independent polls. Publisher, sponsor, fieldwork, panel and weighting roles differ. "
        "No live probabilities or production parameters changed by this script.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "baseline_brier": baseline_score["brier"],
                "challenger_brier": challenger_score["brier"],
                "paired_comparison": comparison,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
