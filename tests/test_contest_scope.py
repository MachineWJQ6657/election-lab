import json

import pandas as pd

from election_forecast.contest_scope import annotate_contest_scope
from election_forecast.simulation import select_race_matchups


def test_independent_caucus_and_three_way_forecast_are_distinct():
    forecast = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "NE",
                "dem_candidate": "Dan Osborn",
                "as_of_date": "2026-10-19",
            },
            {
                "office": "senate",
                "location": "MT",
                "dem_candidate": "Bankhead",
                "as_of_date": "2026-10-19",
            },
        ]
    )
    catalog = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "NE",
                "nominees_json": json.dumps([{"p": "I", "n": "Dan Osborn"}]),
            },
            {"office": "senate", "location": "MT", "nominees_json": "[]"},
        ]
    )
    raw = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "MT",
                "end_date": "2026-10-12",
                "ind_candidate": "Bodnar",
                "ind_pct": 29,
            },
        ]
    )
    result = annotate_contest_scope(forecast, catalog, raw).set_index("location")
    assert result.loc["NE", "dem_side_party"] == "I"
    assert result.loc["NE", "probability_event"] == "candidate_win"
    assert result.loc["MT", "probability_event"] == "pairwise_comparison_only"
    assert result["unresolved_independent_seat"].all()


def test_future_independent_poll_does_not_change_contest_scope():
    forecast = pd.DataFrame(
        [{"office": "senate", "location": "MT", "dem_candidate": "A", "as_of_date": "2026-10-19"}]
    )
    catalog = pd.DataFrame([{"office": "senate", "location": "MT", "nominees_json": "[]"}])
    raw = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "MT",
                "end_date": "2026-10-20",
                "ind_candidate": "B",
                "ind_pct": 30,
            }
        ]
    )
    result = annotate_contest_scope(forecast, catalog, raw)
    assert result.iloc[0]["probability_event"] == "candidate_win"
    assert not result.iloc[0]["unresolved_independent_seat"]


def test_current_nominee_wins_central_selection_over_deeper_old_hypothetical():
    forecast = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "NH",
                "dem_candidate": "Pappas",
                "rep_candidate": "Sununu",
                "as_of_date": "2026-10-19",
                "poll_count": 3,
                "probability_source": "poll_model",
            },
            {
                "office": "senate",
                "location": "NH",
                "dem_candidate": "Pappas",
                "rep_candidate": "Brown",
                "as_of_date": "2026-10-19",
                "poll_count": 20,
                "probability_source": "poll_model",
            },
        ]
    )
    catalog = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "NH",
                "dem_candidate": "Chris Pappas",
                "rep_candidate": "John Sununu",
            }
        ]
    )
    raw = pd.DataFrame(columns=["office", "location"])
    annotated = annotate_contest_scope(forecast, catalog, raw)
    chosen, discarded = select_race_matchups(annotated)
    assert discarded == 1 and chosen.iloc[0]["rep_candidate"] == "Sununu"
