"""Temporal House-control research; do not confuse race accuracy with chamber accuracy."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from election_forecast.house_seats import fit_house_seat_curve

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "house_control_backtest_20261019"


def weighted_curve(history: pd.DataFrame, target_cycle: int) -> tuple[float, float, float]:
    x = history.generic_house_margin.to_numpy(float)
    y = history.dem_seats.to_numpy(float)
    weights = np.power(0.5, (target_cycle - history.cycle.to_numpy(float)) / 12.0)
    slope, intercept = np.polyfit(x, y, 1, w=np.sqrt(weights))
    errors = []
    for index in range(len(x)):
        sub_slope, sub_intercept = np.polyfit(
            np.delete(x, index), np.delete(y, index), 1, w=np.sqrt(np.delete(weights, index))
        )
        errors.append(y[index] - sub_intercept - sub_slope * x[index])
    return (
        float(slope),
        float(intercept),
        float(np.sqrt(np.average(np.square(errors), weights=weights))),
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    history = pd.read_parquet(ROOT / "data/processed/house_national_history.parquet")
    predictions = pd.read_parquet(ROOT / "artifacts/backtest_predictions.parquet")
    generic = predictions[
        predictions.office.eq("generic_ballot")
        & predictions.model.eq("house_effect_poll")
        & predictions.horizon.eq(14)
    ].sort_values("cycle")
    records = []
    for row in generic.itertuples():
        past = history[history.cycle.lt(row.cycle)].sort_values("cycle")
        actual = history[history.cycle.eq(row.cycle)]
        if len(past) < 5 or actual.empty:
            continue
        earlier_poll_errors = generic[generic.cycle.lt(row.cycle)]
        generic_mae = (
            float(
                (earlier_poll_errors.predicted_margin - earlier_poll_errors.actual_margin)
                .abs()
                .mean()
            )
            if len(earlier_poll_errors) >= 3
            else 3.24
        )
        for method in ("production_modern_2012", "pooled_2000", "recency_weighted_2000"):
            fit_data = past[past.cycle.ge(2012 if method == "production_modern_2012" else 2000)]
            if len(fit_data) < 5:
                continue
            if method == "recency_weighted_2000":
                slope, intercept, error = weighted_curve(fit_data, int(row.cycle))
            else:
                fit = fit_house_seat_curve(
                    fit_data, min_cycle=2012 if method == "production_modern_2012" else 2000
                )
                slope, intercept, error = fit.slope, fit.intercept, fit.loo_rmse
            mean = float(np.clip(intercept + slope * row.predicted_margin, 0, 435))
            # Reproduce the current production error rule for the modern baseline.
            # For research challengers, convert MAE to a Gaussian sigma explicitly.
            vote_sigma = generic_mae * (
                1.0 if method == "production_modern_2012" else np.sqrt(np.pi / 2)
            )
            sigma = max(15.0, float(np.sqrt(error**2 + (slope * vote_sigma) ** 2)))
            probability = NormalDist().cdf((mean - 217.5) / sigma)
            seats = int(actual.iloc[0].dem_seats)
            records.append(
                {
                    "cycle": int(row.cycle),
                    "method": method,
                    "training_cycles": fit_data.cycle.astype(int).tolist(),
                    "generic_forecast_margin": float(row.predicted_margin),
                    "actual_generic_margin": float(row.actual_margin),
                    "expected_dem_seats": mean,
                    "actual_dem_seats": seats,
                    "seat_sigma": sigma,
                    "dem_control_probability": probability,
                    "brier": (probability - int(seats >= 218)) ** 2,
                    "seat_absolute_error": abs(mean - seats),
                    "in_90pct_interval": mean - 1.645 * sigma <= seats <= mean + 1.645 * sigma,
                }
            )
    frame = pd.DataFrame(records)
    frame.to_json(OUTPUT / "predictions.json", orient="records", indent=2)
    summaries = []
    for method, group in frame.groupby("method"):
        summaries.append(
            {
                "method": method,
                "independent_cycles": len(group),
                "brier": float(group.brier.mean()),
                "seat_mae": float(group.seat_absolute_error.mean()),
                "interval_coverage": float(group.in_90pct_interval.mean()),
            }
        )
    report = {
        "research_only": True,
        "engine_key": json.loads((ROOT / "artifacts/model_card.json").read_text())[
            "validation_engine_key"
        ],
        "horizon": 14,
        "design": "National generic-ballot forecasts and seat curves trained on earlier "
        "cycles only. Fixed poll model avoids choosing a model with future labels.",
        "results": summaries,
        "predictions": records,
        "adopted": False,
        "scope": "Only a few independent chamber outcomes are available, especially with "
        "the production post-2012 curve. These results do not validate historical "
        "district rating priors or certify the live market context layer.",
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
