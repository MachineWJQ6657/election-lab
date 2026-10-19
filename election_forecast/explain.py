"""Human-readable, auditable explanations for current race forecasts."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd


def _source_digest(polls: pd.DataFrame, race_id: str, limit: int = 5) -> str:
    race = polls[polls["race_id"] == race_id].copy()
    if race.empty:
        return "[]"
    race["end_date"] = pd.to_datetime(race["end_date"])
    race = race.sort_values("end_date", ascending=False).drop_duplicates("source_url")
    items = [
        {
            "pollster": str(row.pollster),
            "end_date": row.end_date.date().isoformat(),
            "margin": round(float(row.margin), 2),
            "url": str(row.source_url),
        }
        for row in race.head(limit).itertuples()
    ]
    return json.dumps(items, ensure_ascii=False)


def build_forecast_explanations(
    forecast: pd.DataFrame,
    snapshots: pd.DataFrame,
    latest_polls: pd.DataFrame,
) -> pd.DataFrame:
    """Explain each probability without pretending fallback ratings were backtested.

    Weighted-poll and fundamentals-blend rows receive exact arithmetic
    decompositions. More complex challengers receive a transparent feature
    snapshot rather than a misleading causal attribution.
    """
    snapshot_columns = [
        "race_id",
        "previous_margin",
        "has_previous_margin",
        "candidate_continuity",
        "previous_national_margin",
        "environment_adjusted_prior",
        "has_environment_adjusted_prior",
        "house_effect_adjusted_margin",
        "mean_pollster_house_effect",
        "generic_ballot_margin",
        "has_generic_ballot",
        "trend_per_30d",
        "poll_std",
        "days_since_latest",
    ]
    available = ["race_id"] + [
        column
        for column in snapshot_columns
        if column in snapshots and column != "race_id" and column not in forecast
    ]
    merged = forecast.merge(
        snapshots[available].drop_duplicates("race_id"), on="race_id", how="left"
    )
    rows: list[dict[str, object]] = []
    for row in merged.itertuples():
        model = str(row.model)
        source = str(row.probability_source)
        predicted = float(row.predicted_margin)
        weighted = float(row.weighted_margin) if pd.notna(row.weighted_margin) else math.nan
        previous = (
            float(row.previous_margin)
            if pd.notna(getattr(row, "previous_margin", np.nan))
            else math.nan
        )
        prior_weight = 0.0
        poll_component = math.nan
        prior_component = math.nan
        ml_component = math.nan
        explanation_kind = "assumption_disclosure"

        if source == "external_rating_prior":
            summary = (
                f"No qualifying direct poll snapshot; {row.rating_source} rating "
                f"'{row.rating}' maps to a provisional D win probability of "
                f"{row.dem_win_probability:.1%}. This mapping is not in the poll backtest."
            )
        elif model == "weighted_poll":
            explanation_kind = "exact_rule_decomposition"
            poll_component = weighted
            summary = (
                f"Prediction equals the recency/sample/partisanship-weighted poll margin "
                f"({weighted:+.2f})."
            )
        elif model == "house_effect_poll":
            explanation_kind = "exact_rule_decomposition"
            adjusted = float(row.house_effect_adjusted_margin)
            poll_component = adjusted
            summary = (
                f"Prediction equals the weighted poll margin after subtracting the "
                f"time-safe empirical pollster house effect ({adjusted:+.2f})."
            )
        elif model == "fundamentals_blend":
            explanation_kind = "exact_rule_decomposition"
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            prior_weight *= has_previous
            poll_component = (1.0 - prior_weight) * weighted
            prior_component = prior_weight * (previous if not math.isnan(previous) else weighted)
            summary = (
                f"Exact blend: polls contribute {poll_component:+.2f}; the previous "
                f"same-office result contributes {prior_component:+.2f} at a "
                f"{prior_weight:.1%} prior weight."
            )
        elif model == "house_effect_fundamentals_blend":
            explanation_kind = "exact_rule_decomposition"
            adjusted = float(row.house_effect_adjusted_margin)
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            prior_weight *= has_previous
            poll_component = (1.0 - prior_weight) * adjusted
            prior_component = prior_weight * (previous if not math.isnan(previous) else adjusted)
            summary = (
                f"Exact blend: time-safe house-effect-adjusted polls contribute "
                f"{poll_component:+.2f}; the previous same-seat result contributes "
                f"{prior_component:+.2f} at a {prior_weight:.1%} prior weight."
            )
        elif model == "adaptive_fundamentals_blend":
            explanation_kind = "exact_rule_decomposition"
            adjusted = float(row.house_effect_adjusted_margin)
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            base_prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            evidence_discount = 1.0 / math.sqrt(max(float(row.pollster_count), 1.0))
            prior_weight = base_prior_weight * evidence_discount * has_previous
            poll_component = (1.0 - prior_weight) * adjusted
            prior_component = prior_weight * (previous if not math.isnan(previous) else adjusted)
            summary = (
                f"Exact adaptive blend: house-effect-adjusted polls contribute "
                f"{poll_component:+.2f}; the previous result contributes "
                f"{prior_component:+.2f}. {row.pollster_count} independent pollsters "
                f"reduce the old-result prior to {prior_weight:.1%}."
            )
        elif model in {"robust_poll_ml_blend", "candidate_evidence_ml_blend"}:
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            continuity = float(getattr(row, "candidate_continuity", 0.0) or 0.0)
            base_prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            if continuity < 0.5 and float(row.pollster_count) >= 4.0:
                polling_input = float(row.house_effect_adjusted_margin)
                prior_weight = (
                    base_prior_weight
                    * (1.0 / math.sqrt(max(float(row.pollster_count), 1.0)))
                    * (0.25 + 0.75 * continuity)
                    * has_previous
                )
                selected_rule = "candidate-aware"
            else:
                polling_input = weighted
                prior_weight = base_prior_weight * has_previous
                selected_rule = "standard fundamentals"
            transparent_poll = (1.0 - prior_weight) * polling_input
            transparent_prior = prior_weight * (
                previous if not math.isnan(previous) else polling_input
            )
            transparent_margin = transparent_poll + transparent_prior
            if model == "candidate_evidence_ml_blend" and continuity < 0.5:
                depth = float(np.clip((float(row.pollster_count) - 4.0) / 8.0, 0.0, 1.0))
                ridge_weight = 0.5 * (1.0 - depth)
            else:
                ridge_weight = 0.5
            rule_weight = 1.0 - ridge_weight
            ridge_margin = (
                (predicted - rule_weight * transparent_margin) / ridge_weight
                if ridge_weight > 0.0
                else math.nan
            )
            poll_component = rule_weight * transparent_poll
            prior_component = rule_weight * transparent_prior
            ml_component = ridge_weight * ridge_margin if ridge_weight > 0.0 else 0.0
            explanation_kind = "exact_hybrid_decomposition"
            if model == "candidate_evidence_ml_blend":
                summary = (
                    f"Evidence-adaptive hybrid: the {selected_rule} rule contributes "
                    f"{rule_weight * transparent_margin:+.2f} at {rule_weight:.0%} weight, "
                    f"and regularized Ridge ML contributes {ml_component:+.2f} at "
                    f"{ridge_weight:.0%}. New-matchup evidence from {row.pollster_count} "
                    "pollsters determines the prespecified weight."
                )
            else:
                summary = (
                    f"Fixed 50/50 hybrid: the {selected_rule} polling/fundamentals rule "
                    f"contributes {0.5 * transparent_margin:+.2f}, and regularized Ridge ML "
                    f"contributes {ml_component:+.2f}. The symmetric weight was selected for "
                    "cross-cycle stability, not tuned race by race."
                )
        elif model == "conditional_candidate_blend":
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            continuity = float(getattr(row, "candidate_continuity", 0.0) or 0.0)
            base_prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            if continuity < 0.5 and float(row.pollster_count) >= 4.0:
                adjusted = float(row.house_effect_adjusted_margin)
                evidence_discount = 1.0 / math.sqrt(max(float(row.pollster_count), 1.0))
                continuity_discount = 0.25 + 0.75 * continuity
                prior_weight = (
                    base_prior_weight * evidence_discount * continuity_discount * has_previous
                )
                poll_component = (1.0 - prior_weight) * adjusted
                prior_component = prior_weight * (
                    previous if not math.isnan(previous) else adjusted
                )
                selected_rule = "candidate-aware"
            else:
                prior_weight = base_prior_weight * has_previous
                poll_component = (1.0 - prior_weight) * weighted
                prior_component = prior_weight * (
                    previous if not math.isnan(previous) else weighted
                )
                selected_rule = "standard fundamentals"
            explanation_kind = "exact_rule_decomposition"
            summary = (
                f"Exact conditional blend selected the {selected_rule} rule: polls "
                f"contribute {poll_component:+.2f}; the old result contributes "
                f"{prior_component:+.2f} at a {prior_weight:.1%} prior weight. "
                f"Candidate continuity is {continuity:.0%} with "
                f"{row.pollster_count} pollsters."
            )
        elif model == "candidate_aware_blend":
            explanation_kind = "exact_rule_decomposition"
            adjusted = float(row.house_effect_adjusted_margin)
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            continuity = float(getattr(row, "candidate_continuity", 0.0) or 0.0)
            base_prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            evidence_discount = 1.0 / math.sqrt(max(float(row.pollster_count), 1.0))
            continuity_discount = 0.25 + 0.75 * continuity
            prior_weight = (
                base_prior_weight * evidence_discount * continuity_discount * has_previous
            )
            poll_component = (1.0 - prior_weight) * adjusted
            prior_component = prior_weight * (previous if not math.isnan(previous) else adjusted)
            summary = (
                f"Exact candidate-aware blend: adjusted polls contribute "
                f"{poll_component:+.2f}; the old result contributes {prior_component:+.2f}. "
                f"Candidate continuity is {continuity:.0%}, and {row.pollster_count} "
                f"pollsters reduce the prior to {prior_weight:.1%}."
            )
        elif model == "environment_adjusted_blend":
            explanation_kind = "exact_rule_decomposition"
            adjusted = float(row.house_effect_adjusted_margin)
            environment_prior = float(row.environment_adjusted_prior)
            has_previous = float(getattr(row, "has_previous_margin", 0.0) or 0.0)
            prior_weight = float(np.clip(float(row.horizon) / 240.0, 0.03, 0.35))
            prior_weight *= has_previous
            poll_component = (1.0 - prior_weight) * adjusted
            prior_component = prior_weight * environment_prior
            summary = (
                f"Exact environment-adjusted blend: adjusted local polls contribute "
                f"{poll_component:+.2f}; the previous state result, shifted by the change "
                f"in the national generic ballot, contributes {prior_component:+.2f} at "
                f"a {prior_weight:.1%} weight."
            )
        else:
            explanation_kind = "feature_snapshot_noncausal"
            summary = (
                f"{model} uses the listed polling, trend, prior-result and generic-ballot "
                "features. Values describe inputs, not causal effects."
            )

        market_calibrated = bool(getattr(row, "market_calibrated", False))
        model_only_probability = float(
            getattr(row, "model_only_dem_win_probability", row.dem_win_probability)
        )
        market_probability = getattr(row, "market_consensus_dem_win_probability", np.nan)
        market_weight = float(getattr(row, "market_calibration_weight", 0.0) or 0.0)
        if market_calibrated and pd.notna(market_probability):
            summary += (
                f" A bounded prediction-market calibration moved D win probability "
                f"from {model_only_probability:.1%} to {row.dem_win_probability:.1%}; "
                f"the de-vigged market consensus was {float(market_probability):.1%} "
                f"with {market_weight:.1%} log-odds weight."
            )

        feature_snapshot = {
            "weighted_margin": None if math.isnan(weighted) else round(weighted, 3),
            "house_effect_adjusted_margin": (
                None
                if pd.isna(getattr(row, "house_effect_adjusted_margin", np.nan))
                else round(float(row.house_effect_adjusted_margin), 3)
            ),
            "mean_pollster_house_effect": (
                None
                if pd.isna(getattr(row, "mean_pollster_house_effect", np.nan))
                else round(float(row.mean_pollster_house_effect), 3)
            ),
            "previous_margin": None if math.isnan(previous) else round(previous, 3),
            "candidate_continuity": (
                None
                if pd.isna(getattr(row, "candidate_continuity", np.nan))
                else round(float(row.candidate_continuity), 3)
            ),
            "environment_adjusted_prior": (
                None
                if pd.isna(getattr(row, "environment_adjusted_prior", np.nan))
                else round(float(row.environment_adjusted_prior), 3)
            ),
            "generic_ballot_margin": (
                None
                if pd.isna(getattr(row, "generic_ballot_margin", np.nan))
                else round(float(row.generic_ballot_margin), 3)
            ),
            "trend_per_30d": (
                None
                if pd.isna(getattr(row, "trend_per_30d", np.nan))
                else round(float(row.trend_per_30d), 3)
            ),
            "poll_std": (
                None if pd.isna(getattr(row, "poll_std", np.nan)) else round(float(row.poll_std), 3)
            ),
        }
        rows.append(
            {
                "race_id": row.race_id,
                "office": row.office,
                "location": row.location,
                "dem_candidate": row.dem_candidate,
                "rep_candidate": row.rep_candidate,
                "model": model,
                "probability_source": source,
                "predicted_margin": predicted,
                "dem_win_probability": float(row.dem_win_probability),
                "model_only_dem_win_probability": model_only_probability,
                "market_consensus_dem_win_probability": (
                    float(market_probability) if pd.notna(market_probability) else math.nan
                ),
                "market_calibration_weight": market_weight,
                "market_calibrated": market_calibrated,
                "explanation_kind": explanation_kind,
                "poll_component": poll_component,
                "prior_component": prior_component,
                "ml_component": ml_component,
                "prior_weight": prior_weight,
                "feature_snapshot": json.dumps(feature_snapshot, ensure_ascii=False),
                "recent_source_evidence": _source_digest(latest_polls, str(row.race_id)),
                "summary": summary,
            }
        )
    return pd.DataFrame.from_records(rows)
