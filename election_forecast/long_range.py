"""Candidate-agnostic 2028 presidential scenario simulation."""

from __future__ import annotations

import numpy as np
import pandas as pd

ELECTORAL_VOTES = {
    "AL": 9,
    "AK": 3,
    "AZ": 11,
    "AR": 6,
    "CA": 54,
    "CO": 10,
    "CT": 7,
    "DE": 3,
    "DC": 3,
    "FL": 30,
    "GA": 16,
    "HI": 4,
    "ID": 4,
    "IL": 19,
    "IN": 11,
    "IA": 6,
    "KS": 6,
    "KY": 8,
    "LA": 8,
    "ME": 2,
    "ME-01": 1,
    "ME-02": 1,
    "MD": 10,
    "MA": 11,
    "MI": 15,
    "MN": 10,
    "MS": 6,
    "MO": 10,
    "MT": 4,
    "NE": 2,
    "NE-01": 1,
    "NE-02": 1,
    "NE-03": 1,
    "NV": 6,
    "NH": 4,
    "NJ": 14,
    "NM": 5,
    "NY": 28,
    "NC": 16,
    "ND": 3,
    "OH": 17,
    "OK": 7,
    "OR": 8,
    "PA": 19,
    "RI": 4,
    "SC": 9,
    "SD": 3,
    "TN": 11,
    "TX": 40,
    "UT": 6,
    "VT": 3,
    "VA": 13,
    "WA": 12,
    "WV": 4,
    "WI": 10,
    "WY": 3,
}

REGIONS = {
    "ME": "northeast",
    "NH": "northeast",
    "VT": "northeast",
    "MA": "northeast",
    "RI": "northeast",
    "CT": "northeast",
    "NY": "northeast",
    "NJ": "northeast",
    "PA": "northeast",
    "DE": "northeast",
    "MD": "northeast",
    "DC": "northeast",
    "OH": "midwest",
    "IN": "midwest",
    "IL": "midwest",
    "MI": "midwest",
    "WI": "midwest",
    "IA": "midwest",
    "MN": "midwest",
    "MO": "midwest",
    "ND": "midwest",
    "SD": "midwest",
    "NE": "midwest",
    "KS": "midwest",
    "VA": "south",
    "WV": "south",
    "NC": "south",
    "SC": "south",
    "GA": "south",
    "FL": "south",
    "KY": "south",
    "TN": "south",
    "AL": "south",
    "MS": "south",
    "AR": "south",
    "LA": "south",
    "OK": "south",
    "TX": "south",
    "MT": "west",
    "ID": "west",
    "WY": "west",
    "CO": "west",
    "NM": "west",
    "AZ": "west",
    "UT": "west",
    "NV": "west",
    "WA": "west",
    "OR": "west",
    "CA": "west",
    "AK": "west",
    "HI": "west",
}


def _base_state(location: str) -> str:
    return location.split("-")[0]


def simulate_2028_scenarios(
    reference_2024: pd.DataFrame,
    *,
    simulations: int = 60_000,
    seed: int = 20280815,
    scenario_margins: dict[str, float] | None = None,
    national_sigma: float = 4.0,
    regional_sigma: float = 1.6,
    state_sigma: float = 1.4,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    """Simulate structural party scenarios, not named-candidate forecasts."""
    scenario_margins = scenario_margins or {
        "R+3 popular vote": -3.0,
        "Even popular vote": 0.0,
        "D+3 popular vote": 3.0,
    }
    president = reference_2024[reference_2024["office"] == "president"].copy()
    president = president.drop_duplicates("location").set_index("location")
    missing = sorted(set(ELECTORAL_VOTES) - set(president.index))
    if missing:
        raise ValueError(f"2024 presidential reference is missing EV units: {', '.join(missing)}")
    national_2024 = float(president.loc["US", "actual_margin"])
    units = list(ELECTORAL_VOTES)
    baseline_leans = np.array(
        [float(president.loc[unit, "actual_margin"]) - national_2024 for unit in units]
    )
    # Four-year partisan leans are persistent but not immutable.
    baseline_leans *= 0.90
    ev = np.array([ELECTORAL_VOTES[unit] for unit in units])
    if int(ev.sum()) != 538:
        raise AssertionError("electoral-vote map must sum to 538")
    region_names = sorted(set(REGIONS.values()))
    region_index = np.array([region_names.index(REGIONS[_base_state(unit)]) for unit in units])
    rng = np.random.default_rng(seed)
    summaries: dict[str, object] = {}
    state_rows: list[dict[str, object]] = []
    distribution_rows: list[pd.DataFrame] = []
    for scenario, mean_margin in scenario_margins.items():
        national = rng.normal(mean_margin, national_sigma, size=(simulations, 1))
        regional = rng.normal(0.0, regional_sigma, size=(simulations, len(region_names)))
        state = rng.normal(0.0, state_sigma, size=(simulations, len(units)))
        margins = national + baseline_leans + regional[:, region_index] + state
        dem_ev = ((margins > 0) * ev).sum(axis=1)
        summaries[scenario] = {
            "assumed_mean_dem_popular_vote_margin": mean_margin,
            "dem_popular_vote_win_probability": float(np.mean(national[:, 0] > 0)),
            "dem_electoral_college_win_probability": float(np.mean(dem_ev >= 270)),
            "electoral_college_tie_probability": float(np.mean(dem_ev == 269)),
            "expected_dem_electoral_votes": float(np.mean(dem_ev)),
            "median_dem_electoral_votes": int(np.median(dem_ev)),
            "p05_dem_electoral_votes": int(np.quantile(dem_ev, 0.05)),
            "p95_dem_electoral_votes": int(np.quantile(dem_ev, 0.95)),
        }
        for index, unit in enumerate(units):
            state_rows.append(
                {
                    "scenario": scenario,
                    "unit": unit,
                    "electoral_votes": int(ev[index]),
                    "dem_win_probability": float(np.mean(margins[:, index] > 0)),
                    "mean_dem_margin": float(np.mean(margins[:, index])),
                    "baseline_2024_margin": float(president.loc[unit, "actual_margin"]),
                }
            )
        values, frequencies = np.unique(dem_ev, return_counts=True)
        distribution_rows.append(
            pd.DataFrame(
                {
                    "scenario": scenario,
                    "dem_electoral_votes": values.astype(int),
                    "simulations": frequencies.astype(int),
                    "probability": frequencies / simulations,
                }
            )
        )
    summary: dict[str, object] = {
        "model_type": "candidate-agnostic structural party scenario",
        "forecast_cycle": 2028,
        "baseline_result_cycle": 2024,
        "simulations_per_scenario": simulations,
        "seed": seed,
        "2024_national_dem_margin": national_2024,
        "uncertainty_assumptions_points": {
            "national_sigma": national_sigma,
            "regional_sigma": regional_sigma,
            "state_sigma": state_sigma,
            "2024_state_lean_persistence": 0.90,
        },
        "scenarios": summaries,
        "important_limit": (
            "This is a conditional map model before nominees and 2028 polls exist. It must "
            "not be read as a named-candidate forecast or as a single unconditional probability."
        ),
    }
    return (
        summary,
        pd.DataFrame.from_records(state_rows),
        pd.concat(distribution_rows, ignore_index=True),
    )
