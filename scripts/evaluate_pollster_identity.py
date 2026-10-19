"""Test alias-pooled organization weights without changing production labels."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import pandas as pd
from evaluate_poll_decay import load_history

from election_forecast.backtest import BacktestResult, backtest_selection_policy
from election_forecast.diagnostics import paired_cycle_bootstrap, probability_diagnostics
from election_forecast.features import POLLSTER_POOLING_COMPONENTS
from election_forecast.pollsters import pollster_key
from election_forecast.validation_cache import cache_key, cached_validation

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/pollster_identity_experiment_20261019"
MIN_PRIOR_CYCLES = 3
MIN_PRIOR_RACES = 100
MIN_BRIER_GAIN = 0.002


def main() -> None:
    history, outcomes = load_history()
    baseline_key = cache_key(history, outcomes)
    forecast = pd.read_csv(ROOT / "artifacts/latest_forecast.csv")
    horizon = int(forecast.horizon.iloc[0])
    records = {}
    policies = {"reported_labels": ()}
    components = sorted(POLLSTER_POOLING_COMPONENTS)
    for size in range(1, len(components) + 1):
        for subset in combinations(components, size):
            policies["+".join(subset)] = subset
    summaries = {}
    for name, pooling in policies.items():
        print(f"Begin identity policy: {name}", flush=True)
        _, result, hit = cached_validation(
            history,
            outcomes,
            cache_dir=None if not pooling else OUTPUT / "validation_cache",
            pollster_pooling=pooling,
        )
        selected, _ = backtest_selection_policy(
            BacktestResult(result.predictions, pd.DataFrame(), pd.DataFrame()),
            target_horizon=horizon,
        )
        records[name] = selected[selected.office.isin(["house", "senate", "governor"])].copy()
        summaries[name] = probability_diagnostics(records[name])
        print(
            json.dumps({"policy": name, "cache_hit": hit, "brier": summaries[name]["brier"]}),
            flush=True,
        )
    full_policy = "+".join(components)
    left, right = records[full_policy], records["reported_labels"]
    # A policy may switch only using already completed cycles. Do not promote
    # the best in-sample policy from this eight-way comparison as a live winner.
    folds, decisions = [], []
    for cycle in sorted(right.cycle.unique()):
        prior = right[right.cycle.lt(cycle)]
        chosen, prior_scores = "reported_labels", {}
        if prior.cycle.nunique() >= MIN_PRIOR_CYCLES and len(prior) >= MIN_PRIOR_RACES:
            prior_scores = {
                name: probability_diagnostics(detail[detail.cycle.lt(cycle)])["brier"]
                for name, detail in records.items()
            }
            best = min(prior_scores, key=prior_scores.get)
            if prior_scores["reported_labels"] - prior_scores[best] >= MIN_BRIER_GAIN:
                chosen = best
        folds.append(records[chosen].loc[records[chosen].cycle.eq(cycle)].assign(identity_policy=chosen))
        decisions.append({"cycle": int(cycle), "chosen": chosen, "earlier_brier": prior_scores})
    outer = pd.concat(folds, ignore_index=True)
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
        "challenger_key": cache_key(history, outcomes, pollster_pooling=components),
        "study_version": 2,
        "research_only": True,
        "adopted": False,
        "design": "Eight-way factorial ablation of alias pooling for frequency caps, "
        "organization counts and prior-cycle house effects. Reported labels and outcomes "
        "remain intact. Policy selection uses earlier cycles only, with the same nested "
        "office/model selection inside each identity policy.",
        "target_horizon": horizon,
        "baseline": baseline_score,
        "challenger": challenger_score,
        "paired_comparison": comparison,
        "ablation": summaries,
        "outer_policy": probability_diagnostics(outer),
        "outer_paired_comparison": paired_cycle_bootstrap(outer, right),
        "outer_decisions": decisions,
        "selection_gate": {
            "min_prior_cycles": MIN_PRIOR_CYCLES,
            "min_prior_races": MIN_PRIOR_RACES,
            "min_earlier_brier_gain": MIN_BRIER_GAIN,
        },
        "baseline_competitive": probability_diagnostics(right.loc[close]),
        "challenger_on_same_competitive_races": probability_diagnostics(challenger_close),
        "current_label_audit": labels.sort_values("label_gap", ascending=False).to_dict("records"),
        "scope": "Alias-normalized organization keys are not a count of statistically "
        "independent polls. Publisher, sponsor, fieldwork, panel and weighting roles differ. "
        "No live probabilities or production parameters changed by this script.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    outer.to_parquet(OUTPUT / "outer_policy_predictions.parquet", index=False)
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
