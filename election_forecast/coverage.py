"""Combine validated poll forecasts with explicitly labeled coverage priors."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

# These deliberately conservative values are provisional coverage priors, not outputs from
# the poll backtest. Keeping them here makes the assumption visible and easy to recalibrate.
RATING_PRIORS = {
    "Safe D": (18.0, 0.97),
    "Likely D": (10.0, 0.88),
    "Lean D": (5.0, 0.70),
    "Tilt D": (2.5, 0.60),
    "Toss-up": (0.0, 0.50),
    "Tilt R": (-2.5, 0.40),
    "Lean R": (-5.0, 0.30),
    "Likely R": (-10.0, 0.12),
    "Safe R": (-18.0, 0.03),
}


def build_rating_prior_forecast(
    catalogs: pd.DataFrame, *, as_of_date: date, horizon: int
) -> pd.DataFrame:
    """Turn race ratings into a clearly non-backtested fallback forecast."""
    unknown = sorted(set(catalogs["rating"]) - set(RATING_PRIORS))
    if unknown:
        raise ValueError(f"unrecognized race ratings: {', '.join(unknown)}")
    output = catalogs[
        [
            "race_id",
            "cycle",
            "office",
            "location",
            "dem_candidate",
            "rep_candidate",
            "rating",
            "rating_source",
            "source_url",
            "fetched_at",
        ]
    ].copy()
    mapped = output["rating"].map(RATING_PRIORS)
    output["as_of_date"] = as_of_date.isoformat()
    output["horizon"] = horizon
    output["poll_count"] = 0
    output["pollster_count"] = 0
    output["weighted_margin"] = np.nan
    output["predicted_margin"] = mapped.map(lambda item: item[0])
    output["dem_win_probability"] = mapped.map(lambda item: item[1])
    output["rep_win_probability"] = 1.0 - output["dem_win_probability"]
    output["model"] = "external_rating_prior"
    output["probability_source"] = "external_rating_prior"
    output["validation_scope"] = "not_in_poll_model_backtest"
    return output


def combine_forecast_coverage(
    poll_forecast: pd.DataFrame,
    catalogs: pd.DataFrame,
    *,
    as_of_date: date,
    horizon: int,
) -> pd.DataFrame:
    """Prefer poll-model matchups and fill otherwise uncovered races with ratings."""
    polled = poll_forecast.copy()
    polled["as_of_date"] = pd.to_datetime(polled["as_of_date"]).dt.date.astype(str)
    catalog_details = catalogs[
        ["office", "location", "rating", "rating_source", "source_url", "fetched_at"]
    ].drop_duplicates(["office", "location"])
    polled = polled.merge(catalog_details, on=["office", "location"], how="left")
    polled["probability_source"] = "poll_model"
    polled["validation_scope"] = "walk_forward_poll_model"

    covered = pd.MultiIndex.from_frame(polled[["office", "location"]])
    catalog_index = pd.MultiIndex.from_frame(catalogs[["office", "location"]])
    fallback_catalog = catalogs.loc[~catalog_index.isin(covered)].copy()
    fallback = build_rating_prior_forecast(fallback_catalog, as_of_date=as_of_date, horizon=horizon)
    combined = pd.concat([polled, fallback], ignore_index=True, sort=False)
    return combined.sort_values(
        ["office", "location", "probability_source"], ascending=[True, True, False]
    ).reset_index(drop=True)


def summarize_coverage(forecast: pd.DataFrame) -> pd.DataFrame:
    """Describe race coverage without conflating model and fallback forecasts."""
    rows = []
    for office, group in forecast.groupby("office", sort=True):
        race_keys = group[["office", "location"]].drop_duplicates()
        poll_races = group.loc[group["probability_source"] == "poll_model", "location"].nunique()
        rows.append(
            {
                "office": office,
                "races": len(race_keys),
                "poll_model_races": int(poll_races),
                "rating_prior_races": int(len(race_keys) - poll_races),
                "matchup_rows": len(group),
            }
        )
    return pd.DataFrame(rows)
