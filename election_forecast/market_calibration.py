"""Conservative calibration of model probabilities with prediction markets."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .names import candidate_key


@dataclass(frozen=True)
class MarketCalibrationConfig:
    """Guardrails chosen before looking at any individual race result."""

    max_direct_market_weight: float = 0.30
    max_chamber_market_weight: float = 0.15
    single_source_multiplier: float = 0.75
    minimum_quality: float = 0.35
    minimum_volume: float = 1_000.0
    maximum_spread: float = 0.15
    maximum_direct_probability_shift: float = 0.08
    maximum_chamber_probability_shift: float = 0.05


def _logit(probability: float) -> float:
    value = float(np.clip(probability, 0.01, 0.99))
    return math.log(value / (1.0 - value))


def _expit(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(value)))


def _joined_unique(values: pd.Series) -> str:
    items: set[str] = set()
    for value in values.dropna():
        items.update(item.strip() for item in str(value).split("|") if item.strip())
    return " | ".join(sorted(items))


def build_market_consensus(
    signals: pd.DataFrame,
    config: MarketCalibrationConfig | None = None,
) -> pd.DataFrame:
    """Pool de-vigged prices in log-odds space and retain diagnostics."""
    config = config or MarketCalibrationConfig()
    if signals.empty:
        return pd.DataFrame()
    frame = signals.copy()
    numeric = [
        "dem_probability",
        "quality_score",
        "volume",
        "liquidity_or_open_interest",
        "max_spread",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    eligible = (
        frame["dem_probability"].between(0.01, 0.99, inclusive="both")
        & frame["quality_score"].ge(config.minimum_quality)
        & frame["volume"].ge(config.minimum_volume)
        & (frame["max_spread"].isna() | frame["max_spread"].le(config.maximum_spread))
    )
    frame = frame[eligible].copy()
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    keys = ["market_scope", "office", "location"]
    for key, group in frame.groupby(keys, sort=True):
        weights = group["quality_score"].clip(lower=0.01).to_numpy(float)
        probabilities = group["dem_probability"].to_numpy(float)
        logits = np.array([_logit(value) for value in probabilities])
        consensus = _expit(float(np.average(logits, weights=weights)))
        disagreement = float(np.std(probabilities, ddof=0)) if len(group) > 1 else 0.0
        agreement_score = max(0.0, 1.0 - disagreement / 0.15)
        average_quality = float(np.average(group["quality_score"], weights=weights))
        consensus_quality = average_quality * agreement_score
        rows.append(
            {
                "market_scope": key[0],
                "office": key[1],
                "location": key[2],
                "market_consensus_dem_probability": consensus,
                "market_source_count": int(group["source"].nunique()),
                "market_sources": " | ".join(sorted(group["source"].unique())),
                "market_consensus_quality": consensus_quality,
                "market_source_disagreement_sd": disagreement,
                "market_total_volume": float(group["volume"].sum()),
                "market_total_depth": float(group["liquidity_or_open_interest"].sum()),
                "market_max_spread": float(group["max_spread"].max()),
                "market_updated_at": pd.to_datetime(
                    group["market_updated_at"], utc=True, errors="coerce"
                ).max(),
                "market_dem_labels": _joined_unique(group["dem_market_labels"]),
                "market_rep_labels": _joined_unique(group["rep_market_labels"]),
                "market_source_urls": json.dumps(
                    sorted(set(group["source_url"].dropna().astype(str)))
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _candidate_key(value: object) -> str:
    return candidate_key(value)


def _candidate_matches(candidate: object, labels: object, party: str) -> bool:
    candidate_key = _candidate_key(candidate)
    if not candidate_key or candidate_key == "tbd":
        return False
    label_items = [item.strip().casefold() for item in str(labels).split("|") if item.strip()]
    candidate_labels = [
        item
        for item in label_items
        if not (
            (party == "D" and re.fullmatch(r"(?:the )?democratic party", item))
            or (party == "R" and re.fullmatch(r"(?:the )?republican party", item))
        )
    ]
    if candidate_labels:
        return any(
            re.search(rf"\b{re.escape(candidate_key)}\b", label) for label in candidate_labels
        )
    return any(
        (party == "D" and "democrat" in item) or (party == "R" and "republican" in item)
        for item in label_items
    )


def _bounded_logit_pool(
    model_probability: float,
    market_probability: float,
    weight: float,
    maximum_shift: float,
) -> float:
    pooled = _expit(
        (1.0 - weight) * _logit(model_probability) + weight * _logit(market_probability)
    )
    shift = float(np.clip(pooled - model_probability, -maximum_shift, maximum_shift))
    return float(np.clip(model_probability + shift, 0.01, 0.99))


def calibrate_race_probabilities(
    forecast: pd.DataFrame,
    consensus: pd.DataFrame,
    config: MarketCalibrationConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply a capped log-odds pool to directly matched candidate races."""
    config = config or MarketCalibrationConfig()
    output = forecast.copy()
    output["model_only_dem_win_probability"] = output["dem_win_probability"].astype(float)
    defaults: dict[str, object] = {
        "market_consensus_dem_win_probability": np.nan,
        "market_calibration_weight": 0.0,
        "market_probability_shift": 0.0,
        "market_source_count": 0,
        "market_sources": "",
        "market_consensus_quality": np.nan,
        "market_total_volume": np.nan,
        "market_candidate_match": False,
        "market_central_matchup": False,
        "market_calibrated": False,
        "market_source_urls": "[]",
    }
    for column, value in defaults.items():
        output[column] = value
    if consensus.empty:
        return output, pd.DataFrame()

    direct = consensus[consensus["market_scope"] == "direct_race"].copy()
    if direct.empty:
        return output, pd.DataFrame()
    direct = direct.set_index(["office", "location"])
    ranking = output.copy()
    ranking["_poll_priority"] = (
        (ranking["probability_source"] == "poll_model").astype(int)
        if "probability_source" in ranking
        else 0
    )
    ranking["_candidate_priority"] = (
        ~ranking["dem_candidate"].astype(str).str.contains("TBD", case=False, na=False)
        & ~ranking["rep_candidate"].astype(str).str.contains("TBD", case=False, na=False)
    ).astype(int)
    ranking["_poll_count"] = (
        pd.to_numeric(ranking["poll_count"], errors="coerce").fillna(0)
        if "poll_count" in ranking
        else 0
    )
    central_indices = set(
        ranking.sort_values(
            ["office", "location", "_poll_priority", "_poll_count", "_candidate_priority"],
            ascending=[True, True, False, False, False],
        )
        .drop_duplicates(["office", "location"], keep="first")
        .index
    )
    audit_rows: list[dict[str, object]] = []
    for index, row in output.iterrows():
        key = (str(row["office"]), str(row["location"]))
        if key not in direct.index:
            continue
        market = direct.loc[key]
        if isinstance(market, pd.DataFrame):
            market = market.iloc[0]
        central_matchup = index in central_indices
        candidate_match = (
            central_matchup
            and _candidate_matches(row["dem_candidate"], market["market_dem_labels"], "D")
            and _candidate_matches(row["rep_candidate"], market["market_rep_labels"], "R")
        )
        candidate_match = candidate_match and (
            _candidate_key(row["dem_candidate"]) != _candidate_key(row["rep_candidate"])
        )
        source_count = int(market["market_source_count"])
        source_multiplier = 1.0 if source_count >= 2 else config.single_source_multiplier
        weight = min(
            config.max_direct_market_weight,
            config.max_direct_market_weight
            * float(market["market_consensus_quality"])
            * source_multiplier,
        )
        model_probability = float(row["dem_win_probability"])
        market_probability = float(market["market_consensus_dem_probability"])
        calibrated = model_probability
        if candidate_match and weight > 0:
            calibrated = _bounded_logit_pool(
                model_probability,
                market_probability,
                weight,
                config.maximum_direct_probability_shift,
            )
        output.at[index, "dem_win_probability"] = calibrated
        output.at[index, "rep_win_probability"] = 1.0 - calibrated
        output.at[index, "market_consensus_dem_win_probability"] = market_probability
        output.at[index, "market_calibration_weight"] = weight if candidate_match else 0.0
        output.at[index, "market_probability_shift"] = calibrated - model_probability
        output.at[index, "market_source_count"] = source_count
        output.at[index, "market_sources"] = market["market_sources"]
        output.at[index, "market_consensus_quality"] = market["market_consensus_quality"]
        output.at[index, "market_total_volume"] = market["market_total_volume"]
        output.at[index, "market_candidate_match"] = candidate_match
        output.at[index, "market_central_matchup"] = central_matchup
        output.at[index, "market_calibrated"] = candidate_match and calibrated != model_probability
        output.at[index, "market_source_urls"] = market["market_source_urls"]
        audit_rows.append(
            {
                "race_id": row["race_id"],
                "office": row["office"],
                "location": row["location"],
                "dem_candidate": row["dem_candidate"],
                "rep_candidate": row["rep_candidate"],
                "candidate_match": candidate_match,
                "central_matchup": central_matchup,
                "model_probability": model_probability,
                "market_probability": market_probability,
                "calibration_weight": weight if candidate_match else 0.0,
                "calibrated_probability": calibrated,
                "probability_shift": calibrated - model_probability,
                "sources": market["market_sources"],
                "source_count": source_count,
                "market_quality": market["market_consensus_quality"],
                "market_volume": market["market_total_volume"],
                "source_urls": market["market_source_urls"],
            }
        )
    return output, pd.DataFrame.from_records(audit_rows)


def add_chamber_market_context(
    control: dict[str, Any],
    consensus: pd.DataFrame,
    config: MarketCalibrationConfig | None = None,
) -> dict[str, Any]:
    """Add a bounded external reference without replacing coherent simulations."""
    config = config or MarketCalibrationConfig()
    output = dict(control)
    chamber = consensus[consensus["market_scope"] == "chamber_control"].copy()
    comparisons: dict[str, object] = {}
    for office in ("house", "senate"):
        location = f"US-{office.upper()}"
        market = chamber[(chamber["office"] == office) & (chamber["location"] == location)]
        if market.empty or office not in output:
            continue
        row = market.iloc[0]
        model_probability = float(output[office]["dem_control_probability"])
        market_probability = float(row["market_consensus_dem_probability"])
        source_multiplier = (
            1.0 if int(row["market_source_count"]) >= 2 else config.single_source_multiplier
        )
        weight = min(
            config.max_chamber_market_weight,
            config.max_chamber_market_weight
            * float(row["market_consensus_quality"])
            * source_multiplier,
        )
        bounded_reference = _bounded_logit_pool(
            model_probability,
            market_probability,
            weight,
            config.maximum_chamber_probability_shift,
        )
        comparisons[office] = {
            "simulation_dem_control_probability": model_probability,
            "market_consensus_dem_probability": market_probability,
            "bounded_market_context_probability": bounded_reference,
            "market_context_weight": weight,
            "market_sources": str(row["market_sources"]),
            "market_source_count": int(row["market_source_count"]),
            "market_total_volume": float(row["market_total_volume"]),
            "market_source_urls": json.loads(str(row["market_source_urls"])),
            "interpretation": (
                "External reasonableness reference only; it does not replace the coherent "
                "seat simulation or count as an independently backtested model input."
            ),
        }
    output["prediction_market_context"] = {
        "method": (
            "De-vig each market, pool sources in log-odds space, then cap chamber-level "
            "influence at 15% and any displayed shift at five probability points."
        ),
        "comparisons": comparisons,
    }
    return output
