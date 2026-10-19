"""Leakage-resistant probability calibration for held-out election forecasts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

MIN_EFFECTIVE_RACES = 80
MIN_GATE_RACES = 40
MIN_GATE_BRIER_GAIN = 0.001
OFFICE_SHRINKAGE_RACES = 200.0
MIN_SLOPE = 0.60
MAX_SLOPE = 1.25
MAX_ABS_INTERCEPT = 0.45


@dataclass(frozen=True)
class CalibrationFit:
    intercept: float = 0.0
    slope: float = 1.0
    effective_races: float = 0.0
    scope: str = "identity"


def _logit(probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(probability, dtype=float), 0.01, 0.99)
    return np.log(clipped / (1.0 - clipped))


def _expit(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(value, dtype=float), -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _independent_weights(frame: pd.DataFrame) -> np.ndarray:
    """Keep repeated forecast horizons from masquerading as independent races."""
    repeats = frame.groupby(["race_id", "cycle"])["horizon"].transform("nunique")
    return 1.0 / repeats.clip(lower=1).to_numpy(float)


def _fit_one(
    frame: pd.DataFrame,
    *,
    probability_column: str,
    min_effective_races: int = MIN_EFFECTIVE_RACES,
) -> CalibrationFit:
    if frame.empty or probability_column not in frame:
        return CalibrationFit()
    usable = frame.dropna(subset=[probability_column, "actual_margin"]).copy()
    if usable.empty:
        return CalibrationFit()
    weights = _independent_weights(usable)
    effective = float(weights.sum())
    outcome = (usable["actual_margin"].to_numpy(float) > 0).astype(int)
    if effective < min_effective_races or np.unique(outcome).size < 2:
        return CalibrationFit(effective_races=effective)
    model = LogisticRegression(C=0.25, solver="lbfgs", max_iter=1_000)
    model.fit(
        _logit(usable[probability_column].to_numpy(float)).reshape(-1, 1),
        outcome,
        sample_weight=weights,
    )
    return CalibrationFit(
        intercept=float(np.clip(model.intercept_[0], -MAX_ABS_INTERCEPT, MAX_ABS_INTERCEPT)),
        slope=float(np.clip(model.coef_[0, 0], MIN_SLOPE, MAX_SLOPE)),
        effective_races=effective,
        scope="global",
    )


def fit_probability_calibrator(
    predictions: pd.DataFrame,
    *,
    model: str,
    office: str | None = None,
    probability_column: str = "raw_dem_win_probability",
) -> CalibrationFit:
    """Fit a guarded office calibration, partially pooled toward all offices."""
    model_rows = predictions[predictions["model"] == model].copy()
    global_fit = _fit_one(model_rows, probability_column=probability_column)
    if office is None or global_fit.scope == "identity":
        return global_fit
    office_rows = model_rows[model_rows["office"] == office]
    office_fit = _fit_one(office_rows, probability_column=probability_column)
    if office_fit.scope == "identity":
        return global_fit
    office_weight = office_fit.effective_races / (
        office_fit.effective_races + OFFICE_SHRINKAGE_RACES
    )
    return CalibrationFit(
        intercept=(
            office_weight * office_fit.intercept + (1.0 - office_weight) * global_fit.intercept
        ),
        slope=office_weight * office_fit.slope + (1.0 - office_weight) * global_fit.slope,
        effective_races=office_fit.effective_races,
        scope="partially_pooled_office",
    )


def fit_validated_probability_calibrator(
    predictions: pd.DataFrame,
    *,
    model: str,
    office: str,
    probability_column: str = "raw_dem_win_probability",
) -> CalibrationFit:
    """Deploy calibration only after it improves later, untouched cycles.

    The two most recent available cycles serve as a second-level temporal gate.
    Parameters fitted on all history are returned only when older-history fits beat
    the raw probabilities on those later cycles by a material amount.
    """
    model_rows = predictions[predictions["model"] == model].copy()
    office_rows = model_rows[model_rows["office"] == office]
    cycles = sorted(int(cycle) for cycle in office_rows["cycle"].unique())
    validation_cycles = cycles[-2:]
    weighted_raw_error = 0.0
    weighted_calibrated_error = 0.0
    validation_weight = 0.0
    for cycle in validation_cycles:
        training = model_rows[model_rows["cycle"] < cycle]
        validation = office_rows[office_rows["cycle"] == cycle]
        fit = fit_probability_calibrator(
            training,
            model=model,
            office=office,
            probability_column=probability_column,
        )
        if fit.scope == "identity" or validation.empty:
            continue
        weights = _independent_weights(validation)
        raw = validation[probability_column].to_numpy(float)
        calibrated = apply_calibration(raw, fit)
        outcome = (validation["actual_margin"].to_numpy(float) > 0).astype(float)
        weighted_raw_error += float(np.sum(weights * np.square(raw - outcome)))
        weighted_calibrated_error += float(np.sum(weights * np.square(calibrated - outcome)))
        validation_weight += float(weights.sum())
    if validation_weight < MIN_GATE_RACES:
        return CalibrationFit(
            effective_races=validation_weight,
            scope="identity_insufficient_calibration_validation",
        )
    brier_gain = (weighted_raw_error - weighted_calibrated_error) / validation_weight
    if brier_gain < MIN_GATE_BRIER_GAIN:
        return CalibrationFit(
            effective_races=validation_weight,
            scope="identity_no_calibration_gain",
        )
    fit = fit_probability_calibrator(
        model_rows,
        model=model,
        office=office,
        probability_column=probability_column,
    )
    if fit.scope == "identity":
        return fit
    return CalibrationFit(
        intercept=fit.intercept,
        slope=fit.slope,
        effective_races=fit.effective_races,
        scope=f"validated_{fit.scope}",
    )


def apply_calibration(probability: np.ndarray, fit: CalibrationFit) -> np.ndarray:
    return np.clip(
        _expit(fit.intercept + fit.slope * _logit(probability)),
        0.01,
        0.99,
    )


def walk_forward_calibrate_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    """Calibrate each validation cycle using only earlier held-out cycles."""
    output = predictions.copy()
    output["raw_dem_win_probability"] = output["dem_win_probability"].to_numpy(float)
    output["probability_calibration_scope"] = "identity_insufficient_history"
    output["calibration_intercept"] = 0.0
    output["calibration_slope"] = 1.0
    cycles = sorted(int(cycle) for cycle in output["cycle"].unique())
    for cycle in cycles:
        earlier = output[output["cycle"] < cycle]
        if earlier.empty:
            continue
        current = output[output["cycle"] == cycle]
        for (model, office), indexes in current.groupby(["model", "office"]).groups.items():
            fit = fit_validated_probability_calibrator(
                earlier,
                model=str(model),
                office=str(office),
                probability_column="raw_dem_win_probability",
            )
            raw = output.loc[indexes, "raw_dem_win_probability"].to_numpy(float)
            output.loc[indexes, "dem_win_probability"] = apply_calibration(raw, fit)
            output.loc[indexes, "probability_calibration_scope"] = fit.scope
            output.loc[indexes, "calibration_intercept"] = fit.intercept
            output.loc[indexes, "calibration_slope"] = fit.slope
    # Local gates can still win one office/cycle and lose elsewhere. Require a
    # material model-level gain across the complete sequential record before the
    # calibration layer is considered deployable.
    outcome = (output["actual_margin"] > 0).astype(float)
    for _, indexes in output.groupby("model").groups.items():
        raw = output.loc[indexes, "raw_dem_win_probability"].to_numpy(float)
        calibrated = output.loc[indexes, "dem_win_probability"].to_numpy(float)
        target = outcome.loc[indexes].to_numpy(float)
        gain = float(np.mean(np.square(raw - target) - np.square(calibrated - target)))
        if gain < MIN_GATE_BRIER_GAIN:
            output.loc[indexes, "dem_win_probability"] = raw
            output.loc[indexes, "probability_calibration_scope"] = "identity_no_model_level_gain"
            output.loc[indexes, "calibration_intercept"] = 0.0
            output.loc[indexes, "calibration_slope"] = 1.0
    return output


def calibrate_latest_probabilities(
    probability: np.ndarray,
    rows: pd.DataFrame,
    validation_predictions: pd.DataFrame | None,
    *,
    model: str,
) -> tuple[np.ndarray, list[CalibrationFit]]:
    """Apply all available held-out history to current race probabilities."""
    raw = np.asarray(probability, dtype=float)
    if validation_predictions is None or validation_predictions.empty:
        return raw, [CalibrationFit() for _ in range(len(rows))]
    calibration_history = validation_predictions.copy()
    if "raw_dem_win_probability" not in calibration_history:
        calibration_history["raw_dem_win_probability"] = calibration_history["dem_win_probability"]
    model_history = calibration_history[calibration_history["model"] == model]
    if "probability_calibration_scope" in model_history:
        deployed = (
            model_history["probability_calibration_scope"].astype(str).str.startswith("validated_")
        )
        if not deployed.any():
            identity = CalibrationFit(scope="identity_no_model_level_gain")
            return raw, [identity for _ in range(len(rows))]
    reset_rows = rows.reset_index(drop=True)
    calibrated = raw.copy()
    fits: list[CalibrationFit] = [CalibrationFit() for _ in range(len(reset_rows))]
    for office, indexes in reset_rows.groupby("office").groups.items():
        fit = fit_validated_probability_calibrator(
            calibration_history,
            model=model,
            office=str(office),
            probability_column="raw_dem_win_probability",
        )
        positions = np.asarray(list(indexes), dtype=int)
        calibrated[positions] = apply_calibration(raw[positions], fit)
        for position in positions:
            fits[int(position)] = fit
    return calibrated, fits
