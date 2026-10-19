"""Walk-forward model comparison and calibrated race probabilities."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import RegressorMixin
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import MODEL_FEATURES
from .probability_calibration import (
    calibrate_latest_probabilities,
    walk_forward_calibrate_predictions,
)


@dataclass(frozen=True)
class BacktestResult:
    predictions: pd.DataFrame
    metrics: pd.DataFrame
    by_office: pd.DataFrame


def _fundamentals_blend(rows: pd.DataFrame) -> np.ndarray:
    polling = rows["weighted_margin"].to_numpy(float)
    previous = rows["previous_margin"].fillna(rows["weighted_margin"]).to_numpy(float)
    has_previous = rows["has_previous_margin"].to_numpy(float)
    # The historical anchor fades as Election Day approaches.
    prior_weight = np.clip(rows["horizon"].to_numpy(float) / 240.0, 0.03, 0.35)
    prior_weight *= has_previous
    return (1.0 - prior_weight) * polling + prior_weight * previous


def _house_effect_fundamentals_blend(rows: pd.DataFrame) -> np.ndarray:
    """Apply the fixed historical anchor to house-effect-adjusted local polling."""
    polling = rows["house_effect_adjusted_margin"].to_numpy(float)
    previous = rows["previous_margin"].fillna(rows["weighted_margin"]).to_numpy(float)
    has_previous = rows["has_previous_margin"].to_numpy(float)
    prior_weight = np.clip(rows["horizon"].to_numpy(float) / 240.0, 0.03, 0.35)
    prior_weight *= has_previous
    return (1.0 - prior_weight) * polling + prior_weight * previous


def _adaptive_fundamentals_blend(rows: pd.DataFrame) -> np.ndarray:
    """Let independent local evidence retire an old election result quickly."""
    polling = rows["house_effect_adjusted_margin"].to_numpy(float)
    previous = rows["previous_margin"].fillna(rows["weighted_margin"]).to_numpy(float)
    has_previous = rows["has_previous_margin"].to_numpy(float)
    base_prior_weight = np.clip(rows["horizon"].to_numpy(float) / 240.0, 0.03, 0.35)
    evidence_discount = 1.0 / np.sqrt(np.maximum(rows["pollster_count"].to_numpy(float), 1.0))
    prior_weight = base_prior_weight * evidence_discount * has_previous
    return (1.0 - prior_weight) * polling + prior_weight * previous


def _candidate_aware_blend(rows: pd.DataFrame) -> np.ndarray:
    """Retain state history while recognizing new nominees and strong local evidence."""
    polling = rows["house_effect_adjusted_margin"].to_numpy(float)
    previous = rows["previous_margin"].fillna(rows["weighted_margin"]).to_numpy(float)
    has_previous = rows["has_previous_margin"].to_numpy(float)
    base_prior_weight = np.clip(rows["horizon"].to_numpy(float) / 240.0, 0.03, 0.35)
    evidence_discount = 1.0 / np.sqrt(np.maximum(rows["pollster_count"].to_numpy(float), 1.0))
    continuity = rows["candidate_continuity"].to_numpy(float)
    continuity_discount = 0.25 + 0.75 * continuity
    prior_weight = base_prior_weight * evidence_discount * continuity_discount * has_previous
    return (1.0 - prior_weight) * polling + prior_weight * previous


def _conditional_candidate_blend(rows: pd.DataFrame) -> np.ndarray:
    """Use candidate-aware shrinkage only when a new matchup has deep local evidence."""
    fundamentals = _fundamentals_blend(rows)
    candidate_aware = _candidate_aware_blend(rows)
    new_matchup_with_depth = (rows["candidate_continuity"].fillna(0.0).to_numpy(float) < 0.5) & (
        rows["pollster_count"].to_numpy(float) >= 4.0
    )
    return np.where(new_matchup_with_depth, candidate_aware, fundamentals)


def _candidate_evidence_ml_blend(
    rows: pd.DataFrame, ridge_margin: np.ndarray, rule_margin: np.ndarray
) -> np.ndarray:
    """Retire ML shrinkage when many pollsters directly test a new matchup.

    Four or fewer pollsters retain the stable 50/50 Ridge/rule blend. For a new
    matchup, the Ridge share then falls linearly to zero at twelve pollsters.
    Incumbent/rematch races keep the 50/50 blend because their prior result is
    directly informative.
    """
    pollster_depth = np.clip((rows["pollster_count"].to_numpy(float) - 4.0) / 8.0, 0.0, 1.0)
    new_matchup = rows["candidate_continuity"].fillna(0.0).to_numpy(float) < 0.5
    ridge_weight = 0.5 * (1.0 - pollster_depth * new_matchup.astype(float))
    return ridge_weight * ridge_margin + (1.0 - ridge_weight) * rule_margin


def _environment_adjusted_blend(rows: pd.DataFrame) -> np.ndarray:
    """Blend local polls with the state's prior result shifted to today's national mood."""
    polling = rows["house_effect_adjusted_margin"].to_numpy(float)
    previous = rows["environment_adjusted_prior"].fillna(rows["previous_margin"])
    previous = previous.fillna(rows["weighted_margin"]).to_numpy(float)
    has_previous = rows["has_previous_margin"].to_numpy(float)
    prior_weight = np.clip(rows["horizon"].to_numpy(float) / 240.0, 0.03, 0.35)
    prior_weight *= has_previous
    return (1.0 - prior_weight) * polling + prior_weight * previous


def _quality_candidate_blend(rows: pd.DataFrame) -> np.ndarray:
    """One fixed challenger: earlier-cycle reliability and bounded poll outliers."""
    quality = rows.copy()
    quality["weighted_margin"] = rows["quality_adjusted_margin"]
    quality["house_effect_adjusted_margin"] = rows["quality_adjusted_margin"]
    return _conditional_candidate_blend(quality)


def make_models() -> dict[str, RegressorMixin]:
    return {
        "ridge": make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=12.0)
        ),
        "hist_gradient_boosting": make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingRegressor(
                learning_rate=0.045,
                max_iter=180,
                max_leaf_nodes=15,
                min_samples_leaf=18,
                l2_regularization=8.0,
                random_state=42,
            ),
        ),
    }


def make_residual_models() -> dict[str, RegressorMixin]:
    """Models that correct systematic polling error instead of replacing polls."""
    return {
        "ridge_residual": make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=24.0)
        ),
        "hist_gradient_boosting_residual": make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingRegressor(
                learning_rate=0.035,
                max_iter=140,
                max_leaf_nodes=9,
                min_samples_leaf=24,
                l2_regularization=12.0,
                random_state=43,
            ),
        ),
    }


def _normal_cdf(value: np.ndarray) -> np.ndarray:
    return np.array([0.5 * (1.0 + math.erf(float(item) / math.sqrt(2.0))) for item in value])


def _uncertainty_table(training: pd.DataFrame) -> dict[tuple[str, int], float]:
    errors = training["actual_margin"] - training["weighted_margin"]
    overall = max(float(np.sqrt(np.mean(np.square(errors)))), 3.0)
    result: dict[tuple[str, int], float] = {}
    for (office, horizon), group in training.assign(error=errors).groupby(["office", "horizon"]):
        group_errors = group["error"].to_numpy(float)
        if len(group_errors) < 12:
            result[(str(office), int(horizon))] = overall
            continue
        median = float(np.median(group_errors))
        mad_sigma = 1.4826 * float(np.median(np.abs(group_errors - median)))
        rmse = float(np.sqrt(np.mean(np.square(group_errors))))
        result[(str(office), int(horizon))] = max(0.55 * mad_sigma + 0.45 * rmse, 2.5)
    result[("__overall__", -1)] = overall
    return result


def _probabilities(
    predicted_margin: np.ndarray, rows: pd.DataFrame, uncertainty: dict[tuple[str, int], float]
) -> np.ndarray:
    overall = uncertainty[("__overall__", -1)]
    sigmas = []
    for row in rows.itertuples():
        exact_key = (str(row.office), int(row.horizon))
        if exact_key in uncertainty:
            sigma = uncertainty[exact_key]
        else:
            candidates = [
                (abs(horizon - int(row.horizon)), value)
                for (office, horizon), value in uncertainty.items()
                if office == str(row.office) and horizon >= 0
            ]
            sigma = min(candidates)[1] if candidates else overall
        # Sparse races deserve visibly wider uncertainty than heavily-polled races.
        sigma *= math.sqrt(max(2.0 / max(float(row.poll_count), 1.0), 1.0))
        sigmas.append(sigma)
    return np.clip(_normal_cdf(predicted_margin / np.asarray(sigmas)), 0.01, 0.99)


def _summarize(group: pd.DataFrame) -> pd.Series:
    actual_winner = group["actual_margin"] > 0
    predicted_winner = group["predicted_margin"] > 0
    outcome = actual_winner.astype(float)
    probability = group["dem_win_probability"].clip(0.001, 0.999)
    return pd.Series(
        {
            "races": len(group),
            "accuracy": float(np.mean(actual_winner == predicted_winner)),
            "mae": float(np.mean(np.abs(group["actual_margin"] - group["predicted_margin"]))),
            "brier": float(np.mean(np.square(probability - outcome))),
            "log_loss": float(
                -np.mean(
                    outcome * np.log(probability) + (1.0 - outcome) * np.log(1.0 - probability)
                )
            ),
            "mean_confidence": float(np.mean(np.maximum(probability, 1.0 - probability))),
        }
    )


def _selection_scores(predictions: pd.DataFrame, target_horizon: int) -> pd.DataFrame:
    """Score candidates on independent races, nearby horizons, and close contests."""
    scored = predictions.copy()
    scored["outcome"] = (scored["actual_margin"] > 0).astype(float)
    scored["brier"] = np.square(scored["dem_win_probability"] - scored["outcome"])
    scored["horizon_weight"] = np.exp(
        -np.abs(scored["horizon"].to_numpy(float) - target_horizon) / 45.0
    )
    max_cycle = int(scored["cycle"].max())
    scored["cycle_weight"] = np.power(0.5, (max_cycle - scored["cycle"].to_numpy(float)) / 8.0)
    # Collapse multiple horizons for a race before scoring. One race with five
    # snapshots must not masquerade as five independent validation examples.
    race_rows: list[dict[str, object]] = []
    for (model, cycle, race_id), group in scored.groupby(["model", "cycle", "race_id"], sort=False):
        horizon_weights = group["horizon_weight"].to_numpy(float)
        race_rows.append(
            {
                "model": str(model),
                "cycle": int(cycle),
                "race_id": str(race_id),
                "brier": float(np.average(group["brier"], weights=horizon_weights)),
                "competitive": bool(group["actual_margin"].abs().min() <= 10.0),
                "weight": float(group["cycle_weight"].iloc[0]),
            }
        )
    races = pd.DataFrame.from_records(race_rows)
    rows: list[dict[str, object]] = []
    for model, group in races.groupby("model", sort=False):
        weights = group["weight"].to_numpy(float)
        brier = group["brier"].to_numpy(float)
        main_score = float(np.average(brier, weights=weights))
        competitive = group[group["competitive"]]
        competitive_score = (
            float(np.average(competitive["brier"], weights=competitive["weight"]))
            if len(competitive) >= 30
            else main_score
        )
        effective_races = float(np.square(weights.sum()) / np.square(weights).sum())
        variance = float(np.average(np.square(brier - main_score), weights=weights))
        rows.append(
            {
                "model": str(model),
                "independent_races": int(len(group)),
                "effective_races": effective_races,
                "target_weighted_brier": main_score,
                "competitive_races": int(len(competitive)),
                "competitive_brier": competitive_score,
                "selection_standard_error": math.sqrt(variance / max(effective_races, 1.0)),
                "selection_score": 0.75 * main_score + 0.25 * competitive_score,
            }
        )
    return pd.DataFrame.from_records(rows).sort_values("selection_score")


def run_walk_forward_backtest(
    snapshots: pd.DataFrame, *, min_training_cycles: int = 3
) -> BacktestResult:
    data = snapshots.dropna(subset=["actual_margin"]).copy()
    cycles = sorted(int(cycle) for cycle in data["cycle"].unique())
    folds: list[pd.DataFrame] = []
    for cycle_index in range(min_training_cycles, len(cycles)):
        test_cycle = cycles[cycle_index]
        training = data[data["cycle"] < test_cycle]
        test = data[data["cycle"] == test_cycle].copy()
        horizon_counts = training.groupby("horizon").size()
        supported_horizons = horizon_counts[horizon_counts >= 30].index
        test = test[test["horizon"].isin(supported_horizons)].copy()
        if len(training) < 100 or test.empty:
            continue
        uncertainty = _uncertainty_table(training)
        model_predictions: dict[str, np.ndarray] = {
            "weighted_poll": test["weighted_margin"].to_numpy(float),
            "house_effect_poll": test["house_effect_adjusted_margin"].to_numpy(float),
            "fundamentals_blend": _fundamentals_blend(test),
            "house_effect_fundamentals_blend": _house_effect_fundamentals_blend(test),
            "adaptive_fundamentals_blend": _adaptive_fundamentals_blend(test),
            "candidate_aware_blend": _candidate_aware_blend(test),
            "conditional_candidate_blend": _conditional_candidate_blend(test),
            "environment_adjusted_blend": _environment_adjusted_blend(test),
            "quality_candidate_blend": _quality_candidate_blend(test),
        }
        fitted = make_models()
        for name, model in fitted.items():
            model.fit(training[MODEL_FEATURES], training["actual_margin"])
            model_predictions[name] = model.predict(test[MODEL_FEATURES])
        residual_target = training["actual_margin"] - training["weighted_margin"]
        residual_models = make_residual_models()
        for name, model in residual_models.items():
            model.fit(training[MODEL_FEATURES], residual_target)
            model_predictions[name] = test["weighted_margin"].to_numpy(float) + model.predict(
                test[MODEL_FEATURES]
            )
        model_predictions["ensemble"] = (
            0.35 * model_predictions["weighted_poll"]
            + 0.40 * model_predictions["ridge"]
            + 0.25 * model_predictions["hist_gradient_boosting"]
        )
        model_predictions["residual_ensemble"] = 0.5 * (
            model_predictions["ridge_residual"]
            + model_predictions["hist_gradient_boosting_residual"]
        )
        # The transparent poll/fundamentals rule and regularized ML make different
        # errors. A fixed symmetric blend is deliberately less tunable than stacking.
        model_predictions["robust_poll_ml_blend"] = 0.5 * (
            model_predictions["ridge"] + model_predictions["conditional_candidate_blend"]
        )
        model_predictions["candidate_evidence_ml_blend"] = _candidate_evidence_ml_blend(
            test,
            model_predictions["ridge"],
            model_predictions["conditional_candidate_blend"],
        )
        for model_name, predicted_margin in model_predictions.items():
            fold = test[
                [
                    "race_id",
                    "cycle",
                    "office",
                    "location",
                    "horizon",
                    "poll_count",
                    "actual_margin",
                ]
            ].copy()
            fold["model"] = model_name
            fold["predicted_margin"] = predicted_margin
            fold["dem_win_probability"] = _probabilities(predicted_margin, test, uncertainty)
            folds.append(fold)
    if not folds:
        raise ValueError("not enough election cycles for walk-forward backtesting")
    predictions = walk_forward_calibrate_predictions(pd.concat(folds, ignore_index=True))
    return summarize_predictions(predictions)


def summarize_predictions(predictions: pd.DataFrame) -> BacktestResult:
    """Reconstruct metrics from verified cached held-out predictions."""
    metrics = predictions.groupby("model", sort=False).apply(_summarize, include_groups=False)
    by_office = predictions.groupby(["model", "office"], sort=False).apply(
        _summarize, include_groups=False
    )
    return BacktestResult(
        predictions=predictions,
        metrics=metrics.reset_index().sort_values("brier"),
        by_office=by_office.reset_index().sort_values(["model", "office"]),
    )


def select_champion(result: BacktestResult, target_horizon: int) -> tuple[str, int, float]:
    """Select the lowest-Brier model at the nearest validated forecast horizon."""
    available = sorted(int(item) for item in result.predictions["horizon"].unique())
    if not available:
        raise ValueError("backtest has no validated horizons")
    nearest = min(available, key=lambda item: abs(item - target_horizon))
    subset = result.predictions[result.predictions["horizon"] == nearest].copy()
    subset["outcome"] = (subset["actual_margin"] > 0).astype(float)
    subset["brier"] = np.square(subset["dem_win_probability"] - subset["outcome"])
    scores = subset.groupby("model")["brier"].mean().sort_values()
    return str(scores.index[0]), nearest, float(scores.iloc[0])


def select_champions_by_office(
    result: BacktestResult,
    target_horizon: int,
    *,
    fallback: str,
    min_races: int = 30,
) -> pd.DataFrame:
    """Select office models using nearby horizons and independent-race safeguards."""
    if result.predictions.empty:
        raise ValueError("backtest has no validated horizons")
    rows: list[dict[str, object]] = []
    for office, office_predictions in result.predictions.groupby("office"):
        available = sorted(int(item) for item in office_predictions["horizon"].unique())
        nearest = min(available, key=lambda item: abs(item - target_horizon))
        subset = office_predictions[office_predictions["horizon"] == nearest].copy()
        subset["outcome"] = (subset["actual_margin"] > 0).astype(float)
        subset["brier"] = np.square(subset["dem_win_probability"] - subset["outcome"])
        office_scores = (
            subset.groupby("model")
            .agg(races=("race_id", "size"), brier=("brier", "mean"))
            .reset_index()
        )
        robust_scores = _selection_scores(office_predictions, target_horizon)
        eligible = robust_scores[robust_scores["independent_races"] >= min_races].sort_values(
            "selection_score"
        )
        if eligible.empty:
            all_horizons = result.by_office[result.by_office["office"] == office].copy()
            # Generic-ballot margin feeds a seats-vote curve, so margin MAE is the
            # relevant selection target here. If the transparent direct estimator is
            # within 0.10 point of the best held-out MAE, take the simpler estimate.
            if office == "generic_ballot" and not all_horizons.empty:
                ranked = all_horizons.sort_values("mae")
                best_mae = float(ranked.iloc[0]["mae"])
                direct = ranked[ranked["model"] == "house_effect_poll"]
                if not direct.empty and float(direct.iloc[0]["mae"]) <= best_mae + 0.10:
                    selected = direct.iloc[0]
                    reason = "all_horizons_margin_parsimony"
                else:
                    selected = ranked.iloc[0]
                    reason = "all_horizons_margin_champion"
            else:
                fallback_rows = office_scores[office_scores["model"] == fallback]
                selected = (
                    fallback_rows.iloc[0]
                    if not fallback_rows.empty
                    else office_scores.sort_values("brier").iloc[0]
                )
                reason = "global_fallback"
        else:
            selected = eligible.iloc[0]
            reason = "robust_target_competitive_champion"
            # Only break a practical tie toward a transparent rule. The narrow
            # tolerance avoids discarding a repeatable ensemble advantage.
            near_best = eligible[
                eligible["selection_score"] <= float(selected["selection_score"]) + 0.00025
            ]
            for transparent in (
                "conditional_candidate_blend",
                "fundamentals_blend",
                "house_effect_fundamentals_blend",
                "environment_adjusted_blend",
            ):
                candidate = near_best[near_best["model"] == transparent]
                if not candidate.empty:
                    selected = candidate.iloc[0]
                    reason = "robust_score_parsimony"
                    break

        selected_model = str(selected["model"])
        nearest_row = office_scores[office_scores["model"] == selected_model]
        robust_row = robust_scores[robust_scores["model"] == selected_model]
        nearest_brier = (
            float(nearest_row.iloc[0]["brier"]) if not nearest_row.empty else float("nan")
        )
        nearest_races = (
            int(nearest_row.iloc[0]["races"])
            if not nearest_row.empty
            else int(robust_row.iloc[0]["independent_races"])
        )
        rows.append(
            {
                "office": str(office),
                "model": selected_model,
                "validated_horizon": nearest,
                "heldout_races": nearest_races,
                "independent_races": int(robust_row.iloc[0]["independent_races"]),
                "brier": nearest_brier,
                "selection_score": float(robust_row.iloc[0]["selection_score"]),
                "selection_reason": reason,
            }
        )
    return pd.DataFrame(rows).sort_values("office").reset_index(drop=True)


def backtest_selection_policy(
    result: BacktestResult,
    target_horizon: int = 60,
    *,
    min_prior_cycles: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate the model-selection rule on cycles it was not allowed to inspect."""
    predictions = result.predictions
    cycles = sorted(int(cycle) for cycle in predictions["cycle"].unique())
    selected_rows: list[pd.DataFrame] = []
    for cycle_index in range(min_prior_cycles, len(cycles)):
        cycle = cycles[cycle_index]
        earlier = predictions[predictions["cycle"] < cycle].copy()
        current = predictions[predictions["cycle"] == cycle].copy()
        if earlier.empty or current.empty:
            continue
        earlier_result = BacktestResult(
            predictions=earlier,
            metrics=(
                earlier.groupby("model", sort=False)
                .apply(_summarize, include_groups=False)
                .reset_index()
            ),
            by_office=(
                earlier.groupby(["model", "office"], sort=False)
                .apply(_summarize, include_groups=False)
                .reset_index()
            ),
        )
        fallback, _, _ = select_champion(earlier_result, target_horizon)
        selections = select_champions_by_office(
            earlier_result,
            target_horizon,
            fallback=fallback,
        )
        for selection in selections.itertuples():
            office_rows = current[
                (current["office"] == selection.office) & (current["model"] == selection.model)
            ]
            if office_rows.empty:
                continue
            available = sorted(int(item) for item in office_rows["horizon"].unique())
            nearest = min(available, key=lambda item: abs(item - target_horizon))
            evaluated = office_rows[office_rows["horizon"] == nearest].copy()
            evaluated["selected_model"] = selection.model
            evaluated["selection_training_cutoff"] = int(earlier["cycle"].max())
            selected_rows.append(evaluated)
    if not selected_rows:
        return pd.DataFrame(), pd.DataFrame()
    detailed = pd.concat(selected_rows, ignore_index=True)
    summary = (
        detailed.groupby("office", sort=True).apply(_summarize, include_groups=False).reset_index()
    )
    overall = _summarize(detailed).to_dict()
    summary = pd.concat(
        [summary, pd.DataFrame([{"office": "__overall__", **overall}])],
        ignore_index=True,
    )
    return detailed, summary


def competitive_backtest_diagnostics(result: BacktestResult) -> pd.DataFrame:
    """Report performance where either outcome or forecast treated a race as close."""
    data = result.predictions.copy()
    actual_close = data["actual_margin"].abs() <= 10.0
    forecast_close = data["dem_win_probability"].between(0.20, 0.80, inclusive="both")
    rows: list[dict[str, object]] = []
    for label, mask in (
        ("actual_margin_within_10", actual_close),
        ("forecast_probability_20_80", forecast_close),
        ("either_close_definition", actual_close | forecast_close),
    ):
        subset = data[mask]
        for model, group in subset.groupby("model", sort=False):
            rows.append({"subset": label, "model": str(model), **_summarize(group).to_dict()})
    return pd.DataFrame.from_records(rows).sort_values(["subset", "brier"])


def backtest_diagnostics(result: BacktestResult) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return horizon scores and reliability bins for probability auditing."""
    by_horizon = (
        result.predictions.groupby(["model", "horizon"], sort=False)
        .apply(_summarize, include_groups=False)
        .reset_index()
        .sort_values(["horizon", "brier"])
    )
    calibration = result.predictions.copy()
    calibration["outcome"] = (calibration["actual_margin"] > 0).astype(float)
    calibration["probability_bin"] = pd.cut(
        calibration["dem_win_probability"],
        bins=np.linspace(0.0, 1.0, 11),
        include_lowest=True,
    )
    calibration = (
        calibration.groupby(["model", "probability_bin"], observed=True)
        .agg(
            races=("race_id", "size"),
            mean_probability=("dem_win_probability", "mean"),
            actual_rate=("outcome", "mean"),
        )
        .reset_index()
    )
    calibration["calibration_gap"] = calibration["mean_probability"] - calibration["actual_rate"]
    calibration["probability_bin"] = calibration["probability_bin"].astype(str)
    return by_horizon, calibration


def fit_and_predict_latest(
    historical_snapshots: pd.DataFrame,
    latest_snapshots: pd.DataFrame,
    *,
    champion: str = "weighted_poll",
    validation_predictions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    training = historical_snapshots.dropna(subset=["actual_margin"]).copy()
    latest = latest_snapshots.copy()
    models = make_models()
    # Historical comparisons fit every challenger; live inference needs only
    # the chosen model and its ML dependencies. Rule-only offices need no fit.
    required_ml = {
        "ensemble": {"ridge", "hist_gradient_boosting"},
        "residual_ensemble": {"ridge_residual", "hist_gradient_boosting_residual"},
        "robust_poll_ml_blend": {"ridge"},
        "candidate_evidence_ml_blend": {"ridge"},
    }.get(champion, {champion})
    predicted: dict[str, np.ndarray] = {
        "weighted_poll": latest["weighted_margin"].to_numpy(float),
        "house_effect_poll": latest["house_effect_adjusted_margin"].to_numpy(float),
        "fundamentals_blend": _fundamentals_blend(latest),
        "house_effect_fundamentals_blend": _house_effect_fundamentals_blend(latest),
        "adaptive_fundamentals_blend": _adaptive_fundamentals_blend(latest),
        "candidate_aware_blend": _candidate_aware_blend(latest),
        "conditional_candidate_blend": _conditional_candidate_blend(latest),
        "environment_adjusted_blend": _environment_adjusted_blend(latest),
        "quality_candidate_blend": _quality_candidate_blend(latest),
    }
    for name, model in models.items():
        if name not in required_ml:
            continue
        model.fit(training[MODEL_FEATURES], training["actual_margin"])
        predicted[name] = model.predict(latest[MODEL_FEATURES])
    residual_target = training["actual_margin"] - training["weighted_margin"]
    for name, model in make_residual_models().items():
        if name not in required_ml:
            continue
        model.fit(training[MODEL_FEATURES], residual_target)
        predicted[name] = latest["weighted_margin"].to_numpy(float) + model.predict(
            latest[MODEL_FEATURES]
        )
    if champion == "ensemble":
        predicted[champion] = (
            0.35 * predicted["weighted_poll"]
            + 0.40 * predicted["ridge"]
            + 0.25 * predicted["hist_gradient_boosting"]
        )
    elif champion == "residual_ensemble":
        predicted[champion] = 0.5 * (
            predicted["ridge_residual"] + predicted["hist_gradient_boosting_residual"]
        )
    elif champion == "robust_poll_ml_blend":
        predicted[champion] = 0.5 * (
            predicted["ridge"] + predicted["conditional_candidate_blend"]
        )
    elif champion == "candidate_evidence_ml_blend":
        predicted[champion] = _candidate_evidence_ml_blend(
            latest, predicted["ridge"], predicted["conditional_candidate_blend"]
        )
    if champion not in predicted:
        raise ValueError(f"unknown champion model: {champion}")
    uncertainty = _uncertainty_table(training)
    output = latest[
        [
            "race_id",
            "cycle",
            "office",
            "location",
            "as_of_date",
            "horizon",
            "dem_candidate",
            "rep_candidate",
            "poll_count",
            "pollster_count",
            "weighted_margin",
            "house_effect_adjusted_margin",
            "mean_pollster_house_effect",
            "quality_adjusted_margin",
            "previous_margin",
            "previous_national_margin",
            "environment_adjusted_prior",
            "candidate_continuity",
        ]
    ].copy()
    output["polling_nowcast_margin"] = latest["house_effect_adjusted_margin"].to_numpy(float)
    raw_polling_probability = _probabilities(
        latest["house_effect_adjusted_margin"].to_numpy(float), latest, uncertainty
    )
    polling_probability, _ = calibrate_latest_probabilities(
        raw_polling_probability,
        latest,
        validation_predictions,
        model="house_effect_poll",
    )
    output["polling_nowcast_dem_win_probability"] = polling_probability
    output["polling_leader"] = np.where(
        output["polling_nowcast_margin"] > 0,
        "D",
        np.where(output["polling_nowcast_margin"] < 0, "R", "TIE"),
    )
    output["predicted_margin"] = predicted[champion]
    raw_probability = _probabilities(predicted[champion], latest, uncertainty)
    calibrated_probability, calibration_fits = calibrate_latest_probabilities(
        raw_probability,
        latest,
        validation_predictions,
        model=champion,
    )
    output["raw_dem_win_probability"] = raw_probability
    output["dem_win_probability"] = calibrated_probability
    output["rep_win_probability"] = 1.0 - output["dem_win_probability"]
    output["probability_calibration_scope"] = [fit.scope for fit in calibration_fits]
    output["calibration_intercept"] = [fit.intercept for fit in calibration_fits]
    output["calibration_slope"] = [fit.slope for fit in calibration_fits]
    output["model"] = champion
    return output.sort_values(["office", "dem_win_probability"], ascending=[True, False])


def build_latest_rule_sensitivity(
    historical_snapshots: pd.DataFrame, latest_snapshots: pd.DataFrame
) -> pd.DataFrame:
    """Expose the full set of transparent rule-model alternatives for each current race."""
    training = historical_snapshots.dropna(subset=["actual_margin"]).copy()
    latest = latest_snapshots.copy()
    uncertainty = _uncertainty_table(training)
    predictions = {
        "weighted_poll": latest["weighted_margin"].to_numpy(float),
        "house_effect_poll": latest["house_effect_adjusted_margin"].to_numpy(float),
        "fundamentals_blend": _fundamentals_blend(latest),
        "house_effect_fundamentals_blend": _house_effect_fundamentals_blend(latest),
        "adaptive_fundamentals_blend": _adaptive_fundamentals_blend(latest),
        "candidate_aware_blend": _candidate_aware_blend(latest),
        "conditional_candidate_blend": _conditional_candidate_blend(latest),
        "environment_adjusted_blend": _environment_adjusted_blend(latest),
    }
    rows: list[pd.DataFrame] = []
    identity = latest[
        [
            "race_id",
            "cycle",
            "office",
            "location",
            "horizon",
            "dem_candidate",
            "rep_candidate",
            "poll_count",
            "pollster_count",
            "candidate_continuity",
        ]
    ]
    for model, margins in predictions.items():
        frame = identity.copy()
        frame["model"] = model
        frame["predicted_margin"] = margins
        frame["dem_win_probability"] = _probabilities(margins, latest, uncertainty)
        rows.append(frame)
    return pd.concat(rows, ignore_index=True).sort_values(["office", "location", "model"])
