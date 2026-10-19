"""Time-safe race snapshot construction."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from .names import COMPATIBLE_NAME_MATCHES, candidate_key, candidate_name_match
from .pollsters import pollster_key

OFFICES = ("president", "senate", "house", "governor", "generic_ballot")
SENATE_SPECIAL_PRIOR_CYCLES = {(2026, "FL"): 2022, (2026, "OH"): 2022}


def _candidate_key(value: object) -> str:
    return candidate_key(value)


def _mode_text(values: pd.Series) -> str:
    modes = values.dropna().astype(str).mode()
    return str(modes.iloc[0]) if not modes.empty else ""


def _weighted_slope(days_old: np.ndarray, margins: np.ndarray, weights: np.ndarray) -> float:
    if len(margins) < 3 or np.ptp(days_old) < 1:
        return 0.0
    x = -days_old / 30.0
    x_mean = np.average(x, weights=weights)
    y_mean = np.average(margins, weights=weights)
    denominator = np.sum(weights * (x - x_mean) ** 2)
    if denominator <= 1e-9:
        return 0.0
    return float(np.sum(weights * (x - x_mean) * (margins - y_mean)) / denominator)


def build_race_snapshots(
    polls: pd.DataFrame,
    horizons: Iterable[int] = (7, 14, 30, 60, 90),
    *,
    lookback_days: int = 120,
    half_life_days: float = 30.0,
    min_polls: int = 2,
    publication_lag_days: int = 0,
    target_cycles: Iterable[int] | None = None,
    supplemental_outcomes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Create one feature row per race and forecast horizon.

    A poll is eligible only if its end date is on or before the simulated as-of
    date. The target is copied only after features are complete.
    """
    if publication_lag_days < 0:
        raise ValueError("Publication lag cannot be negative")
    frame = polls.copy()
    requested_cycles = None if target_cycles is None else {int(cycle) for cycle in target_cycles}
    target_cycle_values = sorted(
        int(cycle)
        for cycle in frame["cycle"].unique()
        if requested_cycles is None or int(cycle) in requested_cycles
    )
    for column in ("end_date", "election_date"):
        frame[column] = pd.to_datetime(frame[column])
    if "margin" not in frame:
        frame["margin"] = frame["dem_pct"].astype(float) - frame["rep_pct"].astype(float)
    frame = frame.drop_duplicates(["source", "source_id"]).copy()
    outcome_history = (
        frame.dropna(subset=["actual_margin"])
        .groupby(["cycle", "office", "location"], as_index=False)
        .agg(
            actual_margin=("actual_margin", "median"),
            dem_candidate=("dem_candidate", _mode_text),
            rep_candidate=("rep_candidate", _mode_text),
        )
        .sort_values(["office", "location", "cycle"])
    )
    if supplemental_outcomes is not None and not supplemental_outcomes.empty:
        supplemental = supplemental_outcomes[
            ["cycle", "office", "location", "actual_margin"]
        ].copy()
        supplemental["dem_candidate"] = supplemental_outcomes.get("dem_candidate", "Democratic")
        supplemental["rep_candidate"] = supplemental_outcomes.get("rep_candidate", "Republican")
        outcome_history = (
            pd.concat([outcome_history, supplemental], ignore_index=True)
            .groupby(["cycle", "office", "location"], as_index=False)
            .agg(
                actual_margin=("actual_margin", "median"),
                dem_candidate=("dem_candidate", _mode_text),
                rep_candidate=("rep_candidate", _mode_text),
            )
            .sort_values(["office", "location", "cycle"])
        )
    prior_lookup: dict[tuple[int, str, str], float] = {}
    prior_cycle_lookup: dict[tuple[int, str, str], int] = {}
    prior_candidate_lookup: dict[tuple[int, str, str], tuple[str, str]] = {}
    for (office, location), outcomes in outcome_history.groupby(["office", "location"]):
        ordered = outcomes.sort_values("cycle")
        for target_cycle in target_cycle_values:
            earlier = ordered[ordered["cycle"] < target_cycle]
            if str(office) == "senate":
                same_seat_cycle = SENATE_SPECIAL_PRIOR_CYCLES.get(
                    (target_cycle, str(location)), target_cycle - 6
                )
                earlier = earlier[earlier["cycle"] == same_seat_cycle]
            if not earlier.empty:
                prior_row = earlier.iloc[-1]
                key = (target_cycle, str(office), str(location))
                prior_lookup[key] = float(prior_row["actual_margin"])
                prior_cycle_lookup[key] = int(prior_row["cycle"])
                prior_candidate_lookup[key] = (
                    str(prior_row["dem_candidate"]),
                    str(prior_row["rep_candidate"]),
                )
    generic_outcomes = outcome_history[
        (outcome_history["office"] == "generic_ballot") & (outcome_history["location"] == "US")
    ].set_index("cycle")["actual_margin"]
    # Estimate pollster house effects strictly from earlier completed cycles. First
    # collapse repeated releases within a race so prolific pollsters do not dominate.
    completed = frame.dropna(subset=["actual_margin"]).copy()
    completed["poll_error"] = completed["margin"] - completed["actual_margin"]
    pollster_races = completed.groupby(["cycle", "pollster", "race_id"], as_index=False)[
        "poll_error"
    ].median()
    pollster_bias_lookup: dict[tuple[int, str], float] = {}
    reliability_lookup: dict[tuple[int, str], float] = {}
    quality_history = completed.copy()
    quality_history["quality_pollster"] = quality_history["pollster"].map(pollster_key)
    quality_history = quality_history.groupby(
        ["cycle", "office", "race_id", "quality_pollster"], as_index=False
    )["poll_error"].median()
    quality_history["relative_error"] = quality_history["poll_error"] - quality_history.groupby(
        ["cycle", "office"]
    )["poll_error"].transform("median")
    for target_cycle in target_cycle_values:
        earlier = pollster_races[pollster_races["cycle"] < target_cycle]
        if earlier.empty:
            continue
        stats = earlier.groupby("pollster")["poll_error"].agg(["median", "count"])
        shrinkage = stats["count"] / (stats["count"] + 8.0)
        shrunk = (stats["median"] * shrinkage).clip(-5.0, 5.0)
        pollster_bias_lookup.update(
            {(target_cycle, str(pollster)): float(bias) for pollster, bias in shrunk.items()}
        )
        quality = quality_history[quality_history["cycle"] < target_cycle].copy()
        quality["abs_error"] = quality["relative_error"].abs()
        typical_error = max(float(quality["abs_error"].median()), 1.5)
        stats = quality.groupby("quality_pollster")["abs_error"].agg(["median", "count"])
        shrinkage = stats["count"] / (stats["count"] + 12.0)
        shrunk_error = stats["median"] * shrinkage + typical_error * (1.0 - shrinkage)
        reliability = (typical_error / shrunk_error.clip(lower=1.0)).clip(0.6, 1.25)
        reliability_lookup.update(
            {(target_cycle, str(name)): float(weight) for name, weight in reliability.items()}
        )
    output: list[dict[str, object]] = []

    for race_id, race in frame.groupby("race_id", sort=False):
        if requested_cycles is not None and int(race["cycle"].iloc[0]) not in requested_cycles:
            continue
        election_date = race["election_date"].iloc[0]
        actual_values = race["actual_margin"].dropna() if "actual_margin" in race else pd.Series()
        actual_margin = float(actual_values.iloc[0]) if not actual_values.empty else math.nan
        for horizon in sorted(set(int(item) for item in horizons)):
            as_of = election_date - pd.Timedelta(days=horizon)
            eligible = race[
                (race["end_date"] <= as_of)
                & (race["end_date"] + pd.Timedelta(days=publication_lag_days) <= as_of)
                & (race["end_date"] >= as_of - pd.Timedelta(days=lookback_days))
            ].copy()
            if "publication_date" in eligible:
                released = pd.to_datetime(eligible["publication_date"], errors="coerce")
                eligible = eligible.loc[released.isna() | released.le(as_of)].copy()
            if len(eligible) < min_polls:
                continue
            eligible["age"] = (as_of - eligible["end_date"]).dt.days.clip(lower=0)
            samples = (
                pd.to_numeric(eligible["sample_size"], errors="coerce").fillna(600).clip(200, 2400)
            )
            recency = np.power(0.5, eligible["age"].to_numpy(float) / half_life_days)
            size = np.sqrt(samples.to_numpy(float) / 600.0)
            partisan = eligible["partisan"].notna().to_numpy()
            partisan_discount = np.where(partisan, 0.82, 1.0)
            population_weight = (
                eligible.get("population", pd.Series("unknown", index=eligible.index))
                .astype(str)
                .map({"lv": 1.0, "rv": 0.92, "v": 0.88, "a": 0.78, "unknown": 0.85})
                .fillna(0.85)
                .to_numpy(float)
            )
            pollster_frequency = (
                eligible.groupby("pollster")["pollster"].transform("size").to_numpy(float)
            )
            organization_cap = 1.0 / np.sqrt(pollster_frequency)
            weights = recency * size * partisan_discount * population_weight * organization_cap
            margins = eligible["margin"].to_numpy(float)
            pollster_biases = np.array(
                [
                    pollster_bias_lookup.get((int(race["cycle"].iloc[0]), str(pollster)), 0.0)
                    for pollster in eligible["pollster"]
                ]
            )
            adjusted_margins = margins - pollster_biases
            reliability = np.array(
                [
                    reliability_lookup.get((int(race["cycle"].iloc[0]), pollster_key(name)), 1.0)
                    for name in eligible["pollster"]
                ]
            )
            quality_weights = weights * reliability
            adjusted_median = float(np.median(adjusted_margins))
            quality_margin = float(
                np.average(
                    np.clip(adjusted_margins, adjusted_median - 12.0, adjusted_median + 12.0),
                    weights=quality_weights,
                )
            )
            median = float(np.median(margins))
            robust_margins = np.clip(margins, median - 12.0, median + 12.0)
            latest_date = eligible["end_date"].max()
            latest = eligible[eligible["end_date"] == latest_date]
            office = str(race["office"].iloc[0])
            location = str(race["location"].iloc[0])
            cycle = int(race["cycle"].iloc[0])
            previous_margin = prior_lookup.get((cycle, office, location), math.nan)
            previous_cycle = prior_cycle_lookup.get((cycle, office, location))
            boundary_changed = bool(
                office == "house"
                and "district_boundary_changed" in eligible
                and eligible["district_boundary_changed"].eq(True).any()
            )
            if boundary_changed:
                # Same district number does not imply the same electorate after
                # redistricting. No reconstructed prior is available yet.
                previous_margin, previous_cycle = math.nan, None
            previous_national_margin = (
                float(generic_outcomes.get(previous_cycle, math.nan))
                if previous_cycle is not None
                else math.nan
            )
            dem_candidate = _mode_text(eligible["dem_candidate"])
            rep_candidate = _mode_text(eligible["rep_candidate"])
            previous_candidates = prior_candidate_lookup.get((cycle, office, location))
            if boundary_changed:
                previous_candidates = None
            candidate_continuity = (
                0.5
                * (
                    int(
                        candidate_name_match(dem_candidate, previous_candidates[0])
                        in COMPATIBLE_NAME_MATCHES
                    )
                    + int(
                        candidate_name_match(rep_candidate, previous_candidates[1])
                        in COMPATIBLE_NAME_MATCHES
                    )
                )
                if previous_candidates
                else 0.0
            )
            row: dict[str, object] = {
                "race_id": race_id,
                "cycle": cycle,
                "office": office,
                "location": location,
                "election_date": election_date.date().isoformat(),
                "as_of_date": as_of.date().isoformat(),
                "horizon": horizon,
                "weighted_margin": float(np.average(margins, weights=weights)),
                "house_effect_adjusted_margin": float(
                    np.average(adjusted_margins, weights=weights)
                ),
                "mean_pollster_house_effect": float(np.average(pollster_biases, weights=weights)),
                "quality_adjusted_margin": quality_margin,
                "robust_margin": float(np.average(robust_margins, weights=weights)),
                "simple_margin": float(np.mean(margins)),
                "latest_margin": float(latest["margin"].mean()),
                "poll_std": float(np.std(margins, ddof=1)) if len(margins) > 1 else 0.0,
                "log_poll_count": math.log1p(len(eligible)),
                "log_pollster_count": math.log1p(eligible["pollster"].nunique()),
                "log_sample_size": math.log1p(float(samples.mean())),
                "partisan_share": float(np.mean(partisan)),
                "days_since_latest": int((as_of - latest_date).days),
                "trend_per_30d": _weighted_slope(eligible["age"].to_numpy(float), margins, weights),
                "previous_margin": previous_margin,
                "previous_national_margin": previous_national_margin,
                "has_previous_margin": int(not math.isnan(previous_margin)),
                "candidate_continuity": candidate_continuity,
                "polling_swing": (
                    float(np.average(margins, weights=weights)) - previous_margin
                    if not math.isnan(previous_margin)
                    else 0.0
                ),
                "is_redistricting_cycle": int(
                    office == "house" and (cycle % 10 == 2 or boundary_changed)
                ),
                "district_boundary_changed": boundary_changed,
                "actual_margin": actual_margin,
                "dem_candidate": dem_candidate,
                "rep_candidate": rep_candidate,
                "poll_count": len(eligible),
                "pollster_count": int(eligible["pollster"].nunique()),
            }
            for known_office in OFFICES:
                row[f"is_{known_office}"] = int(office == known_office)
            output.append(row)
    result = pd.DataFrame.from_records(output)
    if result.empty:
        return result
    generic = (
        result[result["office"] == "generic_ballot"]
        .groupby(["cycle", "horizon"], as_index=False)["weighted_margin"]
        .median()
        .rename(columns={"weighted_margin": "generic_ballot_margin"})
    )
    result = result.merge(generic, on=["cycle", "horizon"], how="left")
    result["has_generic_ballot"] = result["generic_ballot_margin"].notna().astype(int)
    can_adjust_prior = (
        result["previous_margin"].notna()
        & result["previous_national_margin"].notna()
        & result["generic_ballot_margin"].notna()
    )
    result["environment_adjusted_prior"] = result["previous_margin"]
    result.loc[can_adjust_prior, "environment_adjusted_prior"] = (
        result.loc[can_adjust_prior, "previous_margin"]
        - result.loc[can_adjust_prior, "previous_national_margin"]
        + result.loc[can_adjust_prior, "generic_ballot_margin"]
    )
    result["has_environment_adjusted_prior"] = can_adjust_prior.astype(int)
    return result


MODEL_FEATURES = [
    "weighted_margin",
    "house_effect_adjusted_margin",
    "mean_pollster_house_effect",
    "robust_margin",
    "simple_margin",
    "latest_margin",
    "poll_std",
    "log_poll_count",
    "log_pollster_count",
    "log_sample_size",
    "partisan_share",
    "days_since_latest",
    "trend_per_30d",
    "previous_margin",
    "previous_national_margin",
    "environment_adjusted_prior",
    "has_environment_adjusted_prior",
    "has_previous_margin",
    "candidate_continuity",
    "polling_swing",
    "is_redistricting_cycle",
    "horizon",
    "is_president",
    "is_senate",
    "is_house",
    "is_governor",
    "is_generic_ballot",
    "generic_ballot_margin",
    "has_generic_ballot",
]
