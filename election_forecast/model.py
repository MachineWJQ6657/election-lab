"""Core statistical model and correlated election simulation."""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ForecastConfig:
    poll_half_life_days: float = 21.0
    base_poll_margin_se: float = 4.0
    poll_systematic_floor: float = 1.6
    national_error_sigma: float = 1.15
    regional_error_sigma: float = 0.70
    safe_dem_electoral_votes: int = 226
    safe_rep_electoral_votes: int = 219


@dataclass(frozen=True)
class StateForecast:
    state: str
    region: str
    electoral_votes: int
    prior_mean: float
    prior_sigma: float
    poll_mean: float | None
    poll_sigma: float | None
    posterior_mean: float
    posterior_sigma: float
    poll_count: int


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _positive_float(row: dict[str, str], key: str) -> float:
    value = float(row[key])
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def aggregate_polls(
    polls: list[dict[str, str]], config: ForecastConfig
) -> tuple[float, float, int] | None:
    """Return weighted margin, its uncertainty, and poll count."""
    if not polls:
        return None

    weighted_margins: list[tuple[float, float, float]] = []
    for poll in polls:
        days_old = max(float(poll["days_old"]), 0.0)
        sample_size = _positive_float(poll, "sample_size")
        rating = _positive_float(poll, "pollster_rating")
        margin = float(poll["dem_share"]) - float(poll["rep_share"])
        recency_weight = 0.5 ** (days_old / config.poll_half_life_days)
        size_weight = math.sqrt(sample_size / 600.0)
        weight = recency_weight * size_weight * rating
        sampling_se = config.base_poll_margin_se / size_weight
        weighted_margins.append((margin, weight, sampling_se))

    weight_sum = sum(weight for _, weight, _ in weighted_margins)
    if weight_sum <= 0:
        raise ValueError("poll weights must sum to a positive number")
    normalized = [weight / weight_sum for _, weight, _ in weighted_margins]
    mean = sum(
        margin * normalized_weight
        for (margin, _, _), normalized_weight in zip(weighted_margins, normalized, strict=True)
    )
    sampling_variance = sum(
        (normalized_weight * sampling_se) ** 2
        for (_, _, sampling_se), normalized_weight in zip(weighted_margins, normalized, strict=True)
    )
    sigma = math.sqrt(sampling_variance + config.poll_systematic_floor**2)
    return mean, sigma, len(polls)


def combine_normal_estimates(
    prior_mean: float,
    prior_sigma: float,
    observation_mean: float | None,
    observation_sigma: float | None,
) -> tuple[float, float]:
    if prior_sigma <= 0:
        raise ValueError("prior_sigma must be positive")
    if observation_mean is None or observation_sigma is None:
        return prior_mean, prior_sigma
    if observation_sigma <= 0:
        raise ValueError("observation_sigma must be positive")
    prior_precision = 1.0 / prior_sigma**2
    observation_precision = 1.0 / observation_sigma**2
    posterior_variance = 1.0 / (prior_precision + observation_precision)
    posterior_mean = posterior_variance * (
        prior_mean * prior_precision + observation_mean * observation_precision
    )
    return posterior_mean, math.sqrt(posterior_variance)


def forecast_states(
    fundamentals: list[dict[str, str]],
    polls: list[dict[str, str]],
    config: ForecastConfig | None = None,
) -> list[StateForecast]:
    config = config or ForecastConfig()
    polls_by_state: dict[str, list[dict[str, str]]] = defaultdict(list)
    for poll in polls:
        polls_by_state[poll["state"]].append(poll)

    forecasts: list[StateForecast] = []
    for row in fundamentals:
        state = row["state"]
        prior_mean = (
            float(row["previous_margin"])
            + float(row["national_environment"])
            + float(row["incumbency_adjustment"])
        )
        prior_sigma = _positive_float(row, "prior_sigma")
        aggregate = aggregate_polls(polls_by_state[state], config)
        if aggregate is None:
            poll_mean, poll_sigma, poll_count = None, None, 0
        else:
            poll_mean, poll_sigma, poll_count = aggregate
        posterior_mean, posterior_sigma = combine_normal_estimates(
            prior_mean, prior_sigma, poll_mean, poll_sigma
        )
        forecasts.append(
            StateForecast(
                state=state,
                region=row["region"],
                electoral_votes=int(row["electoral_votes"]),
                prior_mean=prior_mean,
                prior_sigma=prior_sigma,
                poll_mean=poll_mean,
                poll_sigma=poll_sigma,
                posterior_mean=posterior_mean,
                posterior_sigma=posterior_sigma,
                poll_count=poll_count,
            )
        )
    return forecasts


def _quantile(sorted_values: list[int], probability: float) -> int:
    if not sorted_values:
        raise ValueError("values cannot be empty")
    index = round((len(sorted_values) - 1) * probability)
    return sorted_values[index]


def simulate_election(
    forecasts: list[StateForecast],
    simulations: int = 20_000,
    seed: int = 42,
    config: ForecastConfig | None = None,
) -> dict[str, Any]:
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    config = config or ForecastConfig()
    total_ev = (
        config.safe_dem_electoral_votes
        + config.safe_rep_electoral_votes
        + sum(f.electoral_votes for f in forecasts)
    )
    if total_ev != 538:
        raise ValueError(f"electoral votes must total 538, got {total_ev}")

    rng = random.Random(seed)
    dem_wins = 0
    ties = 0
    state_wins = {forecast.state: 0 for forecast in forecasts}
    dem_ev_samples: list[int] = []

    for _ in range(simulations):
        national_error = rng.gauss(0.0, config.national_error_sigma)
        regional_errors = {
            region: rng.gauss(0.0, config.regional_error_sigma)
            for region in {forecast.region for forecast in forecasts}
        }
        dem_ev = config.safe_dem_electoral_votes
        for forecast in forecasts:
            shared_variance = config.national_error_sigma**2 + config.regional_error_sigma**2
            # Preserve the posterior total variance while imposing correlation.
            state_sigma = math.sqrt(max(forecast.posterior_sigma**2 - shared_variance, 0.25))
            margin = (
                forecast.posterior_mean
                + national_error
                + regional_errors[forecast.region]
                + rng.gauss(0.0, state_sigma)
            )
            if margin > 0:
                dem_ev += forecast.electoral_votes
                state_wins[forecast.state] += 1
        dem_ev_samples.append(dem_ev)
        if dem_ev >= 270:
            dem_wins += 1
        elif dem_ev == 269:
            ties += 1

    dem_ev_samples.sort()
    state_probabilities = {state: wins / simulations for state, wins in sorted(state_wins.items())}
    return {
        "simulations": simulations,
        "seed": seed,
        "dem_win_probability": dem_wins / simulations,
        "electoral_college_tie_probability": ties / simulations,
        "rep_win_probability": (simulations - dem_wins - ties) / simulations,
        "dem_electoral_votes": {
            "mean": sum(dem_ev_samples) / simulations,
            "p10": _quantile(dem_ev_samples, 0.10),
            "median": _quantile(dem_ev_samples, 0.50),
            "p90": _quantile(dem_ev_samples, 0.90),
        },
        "state_dem_win_probabilities": state_probabilities,
        "state_forecasts": [asdict(forecast) for forecast in forecasts],
    }
