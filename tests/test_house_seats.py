import pandas as pd
import pytest

from election_forecast.house_seats import (
    calibrate_house_forecast,
    fit_house_seat_curve,
)


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cycle": [2012, 2014, 2016, 2018, 2020, 2022, 2024],
            "generic_house_margin": [1.09, -5.62, -1.03, 8.51, 2.96, -2.64, -2.62],
            "dem_seats": [201, 188, 194, 235, 222, 213, 215],
        }
    )


def test_house_curve_is_recent_era_and_leave_one_cycle_out():
    curve = fit_house_seat_curve(_history())
    assert curve.cycles == (2012, 2014, 2016, 2018, 2020, 2022, 2024)
    assert curve.slope == pytest.approx(2.78, abs=0.05)
    assert curve.loo_rmse > 10


def test_house_calibration_leaves_direct_polls_and_rakes_priors():
    rows = [
        {
            "race_id": "house:polled",
            "office": "house",
            "location": "PA-01",
            "dem_candidate": "D",
            "rep_candidate": "R",
            "probability_source": "poll_model",
            "poll_count": 3,
            "dem_win_probability": 0.6,
            "rep_win_probability": 0.4,
            "predicted_margin": 2.0,
        }
    ]
    for index in range(434):
        rows.append(
            {
                "race_id": f"house:{index}",
                "office": "house",
                "location": f"X-{index:03}",
                "dem_candidate": "D",
                "rep_candidate": "R",
                "probability_source": "external_rating_prior",
                "poll_count": 0,
                "dem_win_probability": 0.48,
                "rep_win_probability": 0.52,
                "predicted_margin": -0.5,
            }
        )
    result, metadata = calibrate_house_forecast(
        pd.DataFrame(rows), _history(), generic_ballot_projection=5.0
    )
    polled = result[result["location"] == "PA-01"].iloc[0]
    assert polled["dem_win_probability"] == 0.6
    assert polled["predicted_margin"] == 2.0
    fallback = result[result["location"] == "X-000"].iloc[0]
    assert (fallback["predicted_margin"] > 0.0) == (
        fallback["dem_win_probability"] > 0.5
    )
    assert metadata["rating_prior_margin_shift"] == pytest.approx(
        metadata["rating_prior_z_shift"] * 9.0
    )
    assert metadata["calibrated_expected_dem_seats"] == pytest.approx(
        metadata["target_expected_dem_seats"], abs=1e-6
    )
    assert metadata["combined_seat_sigma"] > metadata["curve_loo_rmse_seats"]
