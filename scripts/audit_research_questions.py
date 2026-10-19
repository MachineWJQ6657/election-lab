"""Turn political/statistical/data-science questions into inspectable evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from election_forecast.backtest import BacktestResult, backtest_selection_policy
from election_forecast.diagnostics import (
    paired_cycle_bootstrap,
    probability_diagnostics,
    research_complexity_guard,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/research_audit_20261019"
CURRENT_OFFICES = ("house", "senate", "governor")


def main() -> None:
    predictions = pd.read_parquet(ROOT / "artifacts/backtest_predictions.parquet")
    forecast = pd.read_csv(ROOT / "artifacts/latest_forecast.csv")
    horizon = int(forecast.horizon.iloc[0])
    selected, _ = backtest_selection_policy(
        BacktestResult(predictions, pd.DataFrame(), pd.DataFrame()), target_horizon=horizon
    )
    if (selected.selection_training_cutoff >= selected.cycle).any():
        raise ValueError("Nested selection inspected a target-cycle label")
    current = selected[selected.office.isin(CURRENT_OFFICES)].copy()
    baseline = predictions[
        predictions.model.eq("weighted_poll") & predictions.office.isin(CURRENT_OFFICES)
    ]
    subsets = {
        "current_offices": current,
        "actual_margin_within_10": current[current.actual_margin.abs().le(10)],
        "forecast_probability_20_80": current[current.dem_win_probability.between(0.2, 0.8)],
        "safe_forecast_outside_20_80": current[~current.dem_win_probability.between(0.2, 0.8)],
    }
    guarded, decisions = research_complexity_guard(current, baseline)
    report = {
        "engine_key": json.loads((ROOT / "artifacts/model_card.json").read_text())[
            "validation_engine_key"
        ],
        "research_only": True,
        "production_parameters_changed": False,
        "target_horizon": horizon,
        "evaluated_horizons": sorted(current.horizon.unique().tolist()),
        "scope": "Nested earlier-cycle model selection, limited to House, Senate and governors. "
        "No presidential races, national generic-ballot outcomes, "
        "unpolled rating priors or markets.",
        "subsets": {name: probability_diagnostics(frame) for name, frame in subsets.items()},
        "by_office": {
            office: probability_diagnostics(frame) for office, frame in current.groupby("office")
        },
        "paired_weighted_poll_comparison": paired_cycle_bootstrap(current, baseline),
        "complexity_guard_experiment": {
            "adopted": False,
            "design": "Require at least 80 earlier office races, three earlier cycles and "
            "0.002 earlier Brier gain before allowing the selected policy over weighted polls.",
            "scores": probability_diagnostics(guarded),
            "comparison_with_selected_policy": paired_cycle_bootstrap(guarded, current),
            "decisions": decisions,
            "decision": "No production switch: the guard worsened held-out Brier. "
            "Neither complexity nor simplicity is adopted merely on intuition.",
        },
        "questions": [
            {
                "perspective": "political",
                "question": "Does winning an independent seat imply caucus control?",
                "decision": "No. MT is a multiway comparison, NE affiliation is unresolved; "
                "publish conditional caucus stress endpoints, not invented independent "
                "win/caucus probabilities.",
            },
            {
                "perspective": "political",
                "question": "Does a reused district number preserve its historical electorate?",
                "decision": "No. Verified TX-09 boundary change retires the old district "
                "vote prior. Other remapped districts still require comparable "
                "reconstructed baselines.",
            },
            {
                "perspective": "statistics",
                "question": "Does overall accuracy hide competitive-race difficulty?",
                "decision": "Report close-race and safe-race scores separately. "
                "Outcome-defined close subsets are retrospective diagnostics, "
                "not a deployable selection rule.",
            },
            {
                "perspective": "statistics",
                "question": "Are hundreds of races hundreds of independent error realizations?",
                "decision": "No. Compare matched races using whole-cycle bootstrap; "
                "inspect the interval before claiming improvement.",
            },
            {
                "perspective": "data_science",
                "question": "Can fieldwork end be treated as public availability?",
                "decision": "Only as a documented limitation where publication is unknown. "
                "Enforce verified release dates, retain first-observed source versions "
                "and publish a three-day delay sensitivity.",
            },
            {
                "perspective": "data_science",
                "question": "Can a generic-ballot archive be appended without source replacement?",
                "decision": "No. Replace office/cycle coverage cells to prevent "
                "double weighting; keep older uncovered history.",
            },
            {
                "perspective": "turnout",
                "question": "Do registered Democrats voting early identify net Democratic votes?",
                "decision": "No. Registration, vote choice, mode substitution and reporting "
                "lag differ. Early-vote data remains visible with zero central probability "
                "weight pending validated comparable history.",
            },
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    current.to_parquet(OUTPUT / "nested_current_offices.parquet", index=False)
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "current_offices": report["subsets"]["current_offices"],
                "paired_comparison": report["paired_weighted_poll_comparison"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
