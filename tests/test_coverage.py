from datetime import date

import pandas as pd

from election_forecast.coverage import (
    RATING_PRIORS,
    combine_forecast_coverage,
    summarize_coverage,
)


def test_tilt_ratings_have_conservative_symmetric_priors():
    assert RATING_PRIORS["Tilt D"] == (2.5, 0.60)
    assert RATING_PRIORS["Tilt R"] == (-2.5, 0.40)


def test_polled_race_wins_and_unpolled_race_gets_labeled_prior():
    catalogs = pd.DataFrame(
        [
            {
                "race_id": "2026:house:PA-07",
                "cycle": 2026,
                "office": "house",
                "location": "PA-07",
                "dem_candidate": "D One",
                "rep_candidate": "R One",
                "rating": "Toss-up",
                "rating_source": "expert avg",
                "source_url": "https://example.test",
                "fetched_at": "2026-08-15T00:00:00Z",
            },
            {
                "race_id": "2026:house:PA-08",
                "cycle": 2026,
                "office": "house",
                "location": "PA-08",
                "dem_candidate": "D Two",
                "rep_candidate": "R Two",
                "rating": "Likely R",
                "rating_source": "expert avg",
                "source_url": "https://example.test",
                "fetched_at": "2026-08-15T00:00:00Z",
            },
        ]
    )
    poll_forecast = pd.DataFrame(
        [
            {
                "race_id": "2026:house:PA-07:d:r",
                "cycle": 2026,
                "office": "house",
                "location": "PA-07",
                "as_of_date": "2026-08-15",
                "horizon": 80,
                "dem_candidate": "D One",
                "rep_candidate": "R One",
                "poll_count": 3,
                "pollster_count": 2,
                "weighted_margin": 1.0,
                "predicted_margin": 0.5,
                "dem_win_probability": 0.54,
                "rep_win_probability": 0.46,
                "model": "fundamentals_blend",
            }
        ]
    )
    combined = combine_forecast_coverage(
        poll_forecast, catalogs, as_of_date=date(2026, 8, 15), horizon=80
    )
    assert len(combined) == 2
    polled = combined[combined["location"] == "PA-07"].iloc[0]
    fallback = combined[combined["location"] == "PA-08"].iloc[0]
    assert polled["probability_source"] == "poll_model"
    assert fallback["probability_source"] == "external_rating_prior"
    assert fallback["dem_win_probability"] == 0.12
    assert fallback["as_of_date"] == "2026-08-15"
    summary = summarize_coverage(combined).iloc[0]
    assert summary["races"] == 2
    assert summary["poll_model_races"] == 1
