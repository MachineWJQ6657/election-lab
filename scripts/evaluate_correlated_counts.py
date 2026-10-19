"""Evaluate shared election errors on polled subsets, not full chambers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from election_forecast.diagnostics import integer_distribution_score
from election_forecast.simulation import _simulate_wins

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/correlation_experiment_20261019"
CORRELATIONS = (0.0, 0.15, 0.30, 0.45)
SIMULATIONS = 50000


def main() -> None:
    audit = json.loads((ROOT / "artifacts/research_audit_20261019/report.json").read_text())
    source = pd.read_parquet(
        ROOT / "artifacts/research_audit_20261019/nested_current_offices.parquet"
    )
    card = json.loads((ROOT / "artifacts/model_card.json").read_text())
    if audit["engine_key"] != card["validation_engine_key"]:
        raise ValueError("Nested predictions are stale")
    rows = []
    for (office, cycle), group in source.groupby(["office", "cycle"]):
        if office not in ("senate", "governor") or len(group) < 5:
            continue
        if group.duplicated(["race_id", "horizon"]).any():
            raise ValueError("Repeated forecasts inflate the simulated contest count")
        actual = int(group.actual_margin.gt(0).sum())
        for rho in CORRELATIONS:
            # Within one office covariance is national + office components.
            counts = _simulate_wins(
                group,
                simulations=SIMULATIONS,
                seed=20261019 + int(cycle),
                national_correlation=rho,
                office_correlation=0.0,
            )[office]
            low, high = np.quantile(counts, [0.05, 0.95])
            score = integer_distribution_score(counts, actual, len(group))
            rows.append(
                {
                    "office": office,
                    "cycle": int(cycle),
                    "correlation": rho,
                    "polled_contests": len(group),
                    "actual_dem_wins": actual,
                    "expected_dem_wins": float(group.dem_win_probability.sum()),
                    "simulated_mean_wins": float(counts.mean()),
                    "count_rps": score,
                    "rps_per_contest": score / len(group),
                    "p05_wins": int(low),
                    "p95_wins": int(high),
                    "observed_in_90pct_interval": bool(low <= actual <= high),
                }
            )
    fixed = pd.DataFrame(rows)
    policy_rows = []
    for (office, cycle), group in fixed.groupby(["office", "cycle"]):
        past = fixed[fixed.office.eq(office) & fixed.cycle.lt(cycle)]
        rho = 0.30
        if past.cycle.nunique() >= 3:
            scores = past.groupby("correlation").rps_per_contest.mean()
            best = float(scores.idxmin())
            if float(scores.loc[0.30] - scores.loc[best]) >= 0.002:
                rho = best
        selected = group[group.correlation.eq(rho)].iloc[0].to_dict()
        selected["method"] = "earlier_cycles_only_policy"
        selected["training_cycles"] = sorted(past.cycle.unique().astype(int).tolist())
        policy_rows.append(selected)
    summary_rows = []
    for office in ("senate", "governor"):
        for rho in CORRELATIONS:
            subset = fixed[fixed.office.eq(office) & fixed.correlation.eq(rho)]
            summary_rows.append(
                {
                    "office": office,
                    "method": f"fixed_rho_{rho:g}",
                    "independent_cycles": len(subset),
                    "mean_count_rps": float(subset.count_rps.mean()),
                    "mean_rps_per_contest": float(subset.rps_per_contest.mean()),
                    "interval_coverage": float(subset.observed_in_90pct_interval.mean()),
                }
            )
        subset = pd.DataFrame(policy_rows)
        subset = subset[subset.office.eq(office)]
        summary_rows.append(
            {
                "office": office,
                "method": "earlier_cycles_only_policy",
                "independent_cycles": len(subset),
                "mean_count_rps": float(subset.count_rps.mean()),
                "mean_rps_per_contest": float(subset.rps_per_contest.mean()),
                "interval_coverage": float(subset.observed_in_90pct_interval.mean()),
            }
        )
    report = {
        "engine_key": audit["engine_key"],
        "research_only": True,
        "adopted": False,
        "simulations_per_office_cycle": SIMULATIONS,
        "design": "Fixed correlations 0/.15/.30/.45 plus an earlier-cycle selection rule. "
        "Evaluate predictive count distributions using ranked probability loss.",
        "results": summary_rows,
        "fixed_predictions": rows,
        "outer_policy_predictions": policy_rows,
        "scope": "Historical poll-covered Senate/governor subsets with at least five contests; "
        "not full chambers, not caucus-aligned control or validation of unpolled priors. "
        "Few cycles and changing poll coverage limit generalization. No production rho change.",
        "reference": "https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary_rows, indent=2))


if __name__ == "__main__":
    main()
