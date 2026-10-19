"""National House seats-vote calibration for sparse district-poll coverage."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

# The provisional rating map is approximately a normal margin model with a
# nine-point standard deviation. Use the same scale when the national seat
# calibration shifts fallback probabilities so displayed margins and win odds
# continue to name the same favorite.
RATING_MARGIN_SIGMA = 9.0


@dataclass(frozen=True)
class HouseSeatCurve:
    slope: float
    intercept: float
    loo_rmse: float
    cycles: tuple[int, ...]

    def expected_seats(self, generic_margin: float) -> float:
        return float(np.clip(self.intercept + self.slope * generic_margin, 0.0, 435.0))


def fit_house_seat_curve(history: pd.DataFrame, *, min_cycle: int = 2012) -> HouseSeatCurve:
    """Fit a recent-era national vote-to-seat line with leave-one-cycle-out error."""
    frame = history[
        history["cycle"].ge(min_cycle)
        & history["generic_house_margin"].notna()
        & history["dem_seats"].notna()
    ].sort_values("cycle")
    if len(frame) < 5:
        raise ValueError("House seat curve requires at least five completed cycles")
    x = frame["generic_house_margin"].to_numpy(float)
    y = frame["dem_seats"].to_numpy(float)
    slope, intercept = np.polyfit(x, y, 1)
    loo_predictions = []
    for index in range(len(frame)):
        loo_slope, loo_intercept = np.polyfit(np.delete(x, index), np.delete(y, index), 1)
        loo_predictions.append(loo_intercept + loo_slope * x[index])
    loo_rmse = float(np.sqrt(np.mean(np.square(y - np.asarray(loo_predictions, dtype=float)))))
    return HouseSeatCurve(
        slope=float(slope),
        intercept=float(intercept),
        loo_rmse=loo_rmse,
        cycles=tuple(frame["cycle"].astype(int)),
    )


def _central_house_rows(forecast: pd.DataFrame) -> pd.DataFrame:
    frame = forecast[forecast["office"].eq("house")].copy()
    frame["poll_model_priority"] = frame["probability_source"].eq("poll_model").astype(int)
    frame["candidate_priority"] = (
        ~frame["dem_candidate"].str.contains("TBD", case=False, na=False)
        & ~frame["rep_candidate"].str.contains("TBD", case=False, na=False)
    ).astype(int)
    return (
        frame.sort_values(
            [
                "location",
                "poll_model_priority",
                "poll_count",
                "candidate_priority",
            ],
            ascending=[True, False, False, False],
        )
        .drop_duplicates("location", keep="first")
        .copy()
    )


def _shift_probability(probability: pd.Series, shift: float) -> pd.Series:
    normal = NormalDist()
    clipped = probability.astype(float).clip(0.001, 0.999)
    return clipped.map(lambda item: normal.cdf(normal.inv_cdf(float(item)) + shift))


def calibrate_house_forecast(
    forecast: pd.DataFrame,
    history: pd.DataFrame,
    *,
    generic_ballot_projection: float,
    generic_forecast_mae: float = 3.24,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Rake unpolled House rating priors to a backtested national seat expectation.

    Directly polled district probabilities are left unchanged. A uniform latent-normal
    shift is applied only to fallback rating priors, preserving their ordering while
    making the chamber total agree with the historical seats-vote relationship.
    """
    output = forecast.copy()
    curve = fit_house_seat_curve(history)
    target = curve.expected_seats(generic_ballot_projection)
    central = _central_house_rows(output)
    if central.empty:
        raise ValueError("cannot calibrate House forecast without House races")
    fixed = central["probability_source"].eq("poll_model")
    fixed_expected = float(central.loc[fixed, "dem_win_probability"].sum())
    fallback = central.loc[~fixed]
    fallback_target = float(
        np.clip(target - fixed_expected, 0.001, max(len(fallback) - 0.001, 0.001))
    )

    low, high = -8.0, 8.0
    for _ in range(80):
        midpoint = (low + high) / 2.0
        shifted_sum = float(_shift_probability(fallback["dem_win_probability"], midpoint).sum())
        if shifted_sum < fallback_target:
            low = midpoint
        else:
            high = midpoint
    z_shift = (low + high) / 2.0

    is_house = output["office"].eq("house")
    is_fallback = is_house & output["probability_source"].eq("external_rating_prior")
    output["pre_house_calibration_dem_win_probability"] = output["dem_win_probability"]
    output.loc[is_fallback, "dem_win_probability"] = _shift_probability(
        output.loc[is_fallback, "dem_win_probability"], z_shift
    )
    if "predicted_margin" in output:
        output.loc[is_fallback, "predicted_margin"] = (
            output.loc[is_fallback, "predicted_margin"].astype(float)
            + RATING_MARGIN_SIGMA * z_shift
        )
    output.loc[is_house, "rep_win_probability"] = 1.0 - output.loc[is_house, "dem_win_probability"]

    seat_sigma = float(np.sqrt(curve.loo_rmse**2 + (curve.slope * generic_forecast_mae) ** 2))
    metadata: dict[str, object] = {
        "method": "2012-2024 national House seats-vote curve plus rating-prior raking",
        "generic_ballot_projection": float(generic_ballot_projection),
        "target_expected_dem_seats": target,
        "rating_prior_z_shift": z_shift,
        "rating_prior_margin_shift": RATING_MARGIN_SIGMA * z_shift,
        "direct_poll_expected_dem_seats": fixed_expected,
        "curve_slope_seats_per_margin_point": curve.slope,
        "curve_intercept_dem_seats": curve.intercept,
        "curve_loo_rmse_seats": curve.loo_rmse,
        "generic_forecast_mae_points": generic_forecast_mae,
        "combined_seat_sigma": seat_sigma,
        "calibration_cycles": list(curve.cycles),
    }
    for column, value in {
        "house_generic_ballot_projection": generic_ballot_projection,
        "house_target_expected_dem_seats": target,
        "house_rating_prior_z_shift": z_shift,
        "house_seat_sigma": seat_sigma,
        "house_curve_loo_rmse": curve.loo_rmse,
    }.items():
        output[column] = np.nan
        output.loc[is_house, column] = value
    output["house_calibration_source"] = ""
    output.loc[is_house, "house_calibration_source"] = (
        "official_house_seats+fte_national_house_vote"
    )

    calibrated_central = _central_house_rows(output)
    metadata["calibrated_expected_dem_seats"] = float(
        calibrated_central["dem_win_probability"].sum()
    )
    return output, metadata
