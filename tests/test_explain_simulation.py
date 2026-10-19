import json
from datetime import date

import pandas as pd

from election_forecast.evidence import build_poll_evidence
from election_forecast.explain import build_forecast_explanations
from election_forecast.long_range import ELECTORAL_VOTES, simulate_2028_scenarios
from election_forecast.simulation import simulate_2026_control


def test_fundamentals_explanation_is_exact():
    forecast = pd.DataFrame(
        [
            {
                "race_id": "race",
                "office": "senate",
                "location": "PA",
                "dem_candidate": "D",
                "rep_candidate": "R",
                "model": "fundamentals_blend",
                "probability_source": "poll_model",
                "predicted_margin": 1.5,
                "weighted_margin": 2.0,
                "dem_win_probability": 0.6,
                "horizon": 60,
                "poll_count": 2,
            }
        ]
    )
    snapshots = pd.DataFrame(
        [
            {
                "race_id": "race",
                "previous_margin": 0.0,
                "has_previous_margin": 1,
                "generic_ballot_margin": 1.0,
                "has_generic_ballot": 1,
                "trend_per_30d": 0.2,
                "poll_std": 1.0,
                "days_since_latest": 2,
            }
        ]
    )
    polls = pd.DataFrame(
        [
            {
                "race_id": "race",
                "pollster": "Example",
                "end_date": "2026-08-01",
                "margin": 2.0,
                "source_url": "https://example.test/poll",
            }
        ]
    )
    result = build_forecast_explanations(forecast, snapshots, polls).iloc[0]
    assert result["explanation_kind"] == "exact_rule_decomposition"
    assert result["prior_weight"] == 0.25
    assert result["poll_component"] + result["prior_component"] == 1.5
    assert json.loads(result["recent_source_evidence"])[0]["pollster"] == "Example"


def test_control_simulation_has_correlated_outputs():
    forecasts = []
    catalogs = []
    for office, location, probability, incumbent in [
        ("house", "PA-01", 0.7, "R"),
        ("senate", "PA", 0.6, "D"),
        ("governor", "PA", 0.8, "D"),
    ]:
        forecasts.append(
            {
                "race_id": f"{office}:{location}",
                "office": office,
                "location": location,
                "dem_candidate": "D",
                "rep_candidate": "R",
                "probability_source": "poll_model",
                "poll_count": 3,
                "dem_win_probability": probability,
            }
        )
        catalogs.append({"office": office, "location": location, "incumbent_party": incumbent})
    summary, distribution = simulate_2026_control(
        pd.DataFrame(forecasts), pd.DataFrame(catalogs), simulations=2_000, seed=7
    )
    assert summary["coverage"]["house_races"] == 1
    assert summary["assumptions"]["national_correlation"] > 0
    assert set(distribution["office"]) == {"house", "senate_total", "governor_elections"}


def test_2028_scenario_uses_all_538_electoral_votes():
    rows = [{"office": "president", "location": "US", "actual_margin": -1.4}] + [
        {"office": "president", "location": unit, "actual_margin": -1.4} for unit in ELECTORAL_VOTES
    ]
    summary, states, distribution = simulate_2028_scenarios(
        pd.DataFrame(rows), simulations=1_000, seed=9
    )
    assert states.groupby("scenario")["electoral_votes"].sum().eq(538).all()
    assert len(summary["scenarios"]) == 3
    assert not distribution.empty


def test_poll_evidence_discounts_partisan_and_older_polls():
    polls = pd.DataFrame(
        [
            {
                "race_id": "race",
                "office": "senate",
                "location": "TX",
                "dem_candidate": "D",
                "rep_candidate": "R",
                "pollster": pollster,
                "end_date": end_date,
                "sample_size": 600,
                "population": "lv",
                "partisan": partisan,
                "pollster_grade": None,
                "dem_pct": 48.0,
                "rep_pct": 46.0,
                "margin": 2.0,
                "source": "test",
                "source_url": "https://example.test/poll",
            }
            for pollster, end_date, partisan in [
                ("Recent", "2026-08-14", None),
                ("Old partisan", "2026-07-15", "D"),
            ]
        ]
    )
    result = build_poll_evidence(polls, as_of_date=date(2026, 8, 15))
    weights = result.set_index("pollster")["normalized_race_weight"]
    assert weights["Recent"] > weights["Old partisan"]
    assert abs(weights.sum() - 1.0) < 1e-12
