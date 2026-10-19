"""Correlated simulations for 2026 chamber-control and seat-count outcomes."""

from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd


def select_race_matchups(
    forecast: pd.DataFrame, *, strategy: str = "central"
) -> tuple[pd.DataFrame, int]:
    """Choose one matchup per office/location, with nomination-sensitivity options."""
    frame = forecast.copy()
    frame["poll_model_priority"] = (frame["probability_source"] == "poll_model").astype(int)
    frame["candidate_priority"] = (
        ~frame["dem_candidate"].str.contains("TBD", case=False, na=False)
        & ~frame["rep_candidate"].str.contains("TBD", case=False, na=False)
    ).astype(int)
    if strategy == "central":
        frame["confirmed_matchup"] = (
            frame.get("catalog_candidate_match", pd.Series(False, index=frame.index))
            .fillna(False)
            .astype(bool)
        )
        frame["market_matchup"] = (
            frame.get("market_central_matchup", pd.Series(False, index=frame.index))
            .fillna(False)
            .astype(bool)
        )
        frame = frame.sort_values(
            [
                "office",
                "location",
                "confirmed_matchup",
                "market_matchup",
                "poll_model_priority",
                "poll_count",
                "candidate_priority",
            ],
            ascending=[True, True, False, False, False, False, False],
        )
    elif strategy in {"dem_low", "dem_high"}:
        frame = frame.sort_values(
            ["office", "location", "dem_win_probability"],
            ascending=[True, True, strategy == "dem_low"],
        )
    else:
        raise ValueError(f"unknown matchup strategy: {strategy}")
    selected = frame.drop_duplicates(["office", "location"], keep="first").copy()
    return selected, int(len(frame) - len(selected))


def _distribution(values: np.ndarray, office: str) -> pd.DataFrame:
    counts, frequencies = np.unique(values, return_counts=True)
    return pd.DataFrame(
        {
            "office": office,
            "dem_seats": counts.astype(int),
            "simulations": frequencies.astype(int),
            "probability": frequencies / len(values),
        }
    )


def _seat_summary(values: np.ndarray, threshold: int | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "expected_dem_seats": float(np.mean(values)),
        "median_dem_seats": int(np.median(values)),
        "p05_dem_seats": int(np.quantile(values, 0.05)),
        "p95_dem_seats": int(np.quantile(values, 0.95)),
    }
    if threshold is not None:
        result["control_threshold"] = threshold
        result["dem_control_probability"] = float(np.mean(values >= threshold))
        result["rep_control_probability"] = float(np.mean(values < threshold))
    return result


def _simulate_house_seats(
    mean_seats: float, sigma_seats: float, *, simulations: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    draws = np.rint(mean_seats + max(float(sigma_seats), 1.0) * rng.standard_normal(simulations))
    return np.clip(draws, 0, 435).astype(int)


def _simulate_wins(
    selected: pd.DataFrame,
    *,
    simulations: int,
    seed: int,
    national_correlation: float,
    office_correlation: float,
) -> dict[str, np.ndarray]:
    probabilities = selected["dem_win_probability"].astype(float).clip(0.001, 0.999)
    inverse = NormalDist().inv_cdf
    thresholds = np.array([inverse(float(probability)) for probability in probabilities])
    rng = np.random.default_rng(seed)
    national = rng.standard_normal((simulations, 1))
    offices = sorted(selected["office"].unique())
    office_shocks = {office: rng.standard_normal((simulations, 1)) for office in offices}
    idiosyncratic_scale = np.sqrt(1.0 - national_correlation - office_correlation)
    wins: dict[str, np.ndarray] = {}
    for office in offices:
        mask = selected["office"].to_numpy() == office
        latent = (
            thresholds[mask][None, :]
            + np.sqrt(national_correlation) * national
            + np.sqrt(office_correlation) * office_shocks[office]
            + idiosyncratic_scale * rng.standard_normal((simulations, int(mask.sum())))
        )
        wins[office] = (latent > 0).sum(axis=1)
    return wins


def simulate_2026_control(
    forecast: pd.DataFrame,
    catalog: pd.DataFrame,
    *,
    simulations: int = 50_000,
    seed: int = 20260815,
    national_correlation: float = 0.18,
    office_correlation: float = 0.12,
    current_dem_aligned_senate_seats: int = 47,
) -> tuple[dict[str, object], pd.DataFrame]:
    """Preserve race marginals while adding national and office-wide shocks.

    Senate control assumes a Republican vice president, so Democrats need 51
    aligned seats. Independents in the current 47-seat aligned caucus are
    counted with Democrats.
    """
    if national_correlation + office_correlation >= 1.0:
        raise ValueError("correlation components must sum to less than one")
    selected, discarded_matchups = select_race_matchups(forecast)
    selected = selected[selected["office"].isin(["house", "senate", "governor"])].copy()
    independent_sensitivity = None
    unresolved = selected[
        selected.get("unresolved_independent_seat", pd.Series(False, index=selected.index))
        .fillna(False)
        .astype(bool)
        & selected["office"].eq("senate")
    ]
    if not unresolved.empty:
        remaining = selected[~selected.index.isin(unresolved.index)]
        remaining_wins = _simulate_wins(
            remaining,
            simulations=simulations,
            seed=seed,
            national_correlation=national_correlation,
            office_correlation=office_correlation,
        )
        # Current D-aligned seats not up in 2026; do not equate an independent's
        # candidacy or registration with a promised caucus affiliation.
        senate_catalog = catalog[catalog.office.eq("senate")]
        non_up = current_dem_aligned_senate_seats - int(
            senate_catalog.incumbent_party.isin(["D", "I"]).sum()
        )
        lower = non_up + remaining_wins.get("senate", np.zeros(simulations))
        upper = lower + len(unresolved)
        independent_sensitivity = {
            "unresolved_states": sorted(unresolved.location.unique()),
            "dem_control_lower_endpoint": float(np.mean(lower >= 51)),
            "dem_control_upper_endpoint": float(np.mean(upper >= 51)),
            "interpretation": (
                "Stress endpoints: all unresolved seats contribute zero or one D-aligned "
                "seat each. These are neither a confidence interval nor estimates of "
                "independent candidate win/caucus probabilities."
            ),
        }
    wins = _simulate_wins(
        selected,
        simulations=simulations,
        seed=seed,
        national_correlation=national_correlation,
        office_correlation=office_correlation,
    )

    house = wins.get("house", np.zeros(simulations, dtype=int))
    house_rows = selected[selected["office"] == "house"]
    calibrated_house = (
        "house_target_expected_dem_seats" in house_rows
        and house_rows["house_target_expected_dem_seats"].notna().any()
    )
    house_calibration: dict[str, object] | None = None
    if calibrated_house:
        house_mean = float(house_rows["house_target_expected_dem_seats"].dropna().iloc[0])
        house_sigma = float(house_rows["house_seat_sigma"].dropna().iloc[0])
        house = _simulate_house_seats(
            house_mean, house_sigma, simulations=simulations, seed=seed + 101
        )
        house_calibration = {
            "generic_ballot_projection": float(
                house_rows["house_generic_ballot_projection"].dropna().iloc[0]
            ),
            "target_expected_dem_seats": house_mean,
            "seat_sigma": house_sigma,
            "seat_curve_loo_rmse": float(house_rows["house_curve_loo_rmse"].dropna().iloc[0]),
            "rating_prior_z_shift": float(
                house_rows["house_rating_prior_z_shift"].dropna().iloc[0]
            ),
            "interpretation": (
                "House totals use the historical national seats-vote curve because "
                "district polling is sparse; polled districts remain unchanged and "
                "only fallback rating priors are raked to the national expectation."
            ),
        }
    senate_up = wins.get("senate", np.zeros(simulations, dtype=int))
    governor = wins.get("governor", np.zeros(simulations, dtype=int))
    senate_catalog = catalog[catalog["office"] == "senate"]
    up_dem_aligned = int(senate_catalog["incumbent_party"].isin(["D", "I"]).sum())
    non_up_dem_aligned = current_dem_aligned_senate_seats - up_dem_aligned
    senate_total = senate_up + non_up_dem_aligned

    low_selected, _ = select_race_matchups(forecast, strategy="dem_low")
    high_selected, _ = select_race_matchups(forecast, strategy="dem_high")
    low_selected = low_selected[low_selected["office"].isin(["house", "senate", "governor"])].copy()
    high_selected = high_selected[
        high_selected["office"].isin(["house", "senate", "governor"])
    ].copy()
    # Unvalidated rating priors receive an explicit +/-5 point directional stress.
    low_rating = low_selected["probability_source"] == "external_rating_prior"
    high_rating = high_selected["probability_source"] == "external_rating_prior"
    low_selected.loc[low_rating, "dem_win_probability"] = (
        low_selected.loc[low_rating, "dem_win_probability"] - 0.05
    ).clip(0.001, 0.999)
    high_selected.loc[high_rating, "dem_win_probability"] = (
        high_selected.loc[high_rating, "dem_win_probability"] + 0.05
    ).clip(0.001, 0.999)
    low_wins = _simulate_wins(
        low_selected,
        simulations=simulations,
        seed=seed,
        national_correlation=national_correlation,
        office_correlation=office_correlation,
    )
    high_wins = _simulate_wins(
        high_selected,
        simulations=simulations,
        seed=seed,
        national_correlation=national_correlation,
        office_correlation=office_correlation,
    )
    low_house = low_wins.get("house", np.zeros(simulations, dtype=int))
    high_house = high_wins.get("house", np.zeros(simulations, dtype=int))
    if calibrated_house:
        low_house_mean = float(
            low_selected.loc[low_selected["office"] == "house", "dem_win_probability"].sum()
        )
        high_house_mean = float(
            high_selected.loc[high_selected["office"] == "house", "dem_win_probability"].sum()
        )
        low_house = _simulate_house_seats(
            low_house_mean, house_sigma, simulations=simulations, seed=seed + 102
        )
        high_house = _simulate_house_seats(
            high_house_mean, house_sigma, simulations=simulations, seed=seed + 103
        )
    low_senate = low_wins.get("senate", np.zeros(simulations, dtype=int)) + non_up_dem_aligned
    high_senate = high_wins.get("senate", np.zeros(simulations, dtype=int)) + non_up_dem_aligned
    low_governor = low_wins.get("governor", np.zeros(simulations, dtype=int))
    high_governor = high_wins.get("governor", np.zeros(simulations, dtype=int))

    summary: dict[str, object] = {
        "independent_caucus_sensitivity": independent_sensitivity,
        "model_type": (
            "historically calibrated House seats-vote simulation plus correlated "
            "latent-normal Senate/Governor race simulation"
            if calibrated_house
            else "correlated latent-normal simulation over race probabilities"
        ),
        "simulations": simulations,
        "seed": seed,
        "assumptions": {
            "national_correlation": national_correlation,
            "office_correlation": office_correlation,
            "current_dem_aligned_senate_seats": current_dem_aligned_senate_seats,
            "senate_dem_control_threshold": 51,
            "why_not_independent": (
                "National and office shocks let Senate/Governor errors move races "
                "together; House aggregate uncertainty comes from historical "
                "seats-vote and generic-ballot forecast errors."
            ),
        },
        "coverage": {
            "house_races": int((selected["office"] == "house").sum()),
            "senate_races": int((selected["office"] == "senate").sum()),
            "governor_races": int((selected["office"] == "governor").sum()),
            "discarded_alternative_matchups": discarded_matchups,
        },
        "house": _seat_summary(house, 218),
        "senate": {
            **_seat_summary(senate_total, 51),
            "non_up_dem_aligned_seats": non_up_dem_aligned,
            "dem_wins_among_seats_up": float(np.mean(senate_up)),
        },
        "governor_elections": _seat_summary(governor),
        "sensitivity": {
            "method": (
                "Use the least/most Democratic listed matchup in each race and shift every "
                "unvalidated external-rating prior by -/+5 probability points."
            ),
            "house_dem_control_probability_range": [
                float(np.mean(low_house >= 218)),
                float(np.mean(high_house >= 218)),
            ],
            "senate_dem_control_probability_range": [
                float(np.mean(low_senate >= 51)),
                float(np.mean(high_senate >= 51)),
            ],
            "expected_dem_governor_wins_range": [
                float(np.mean(low_governor)),
                float(np.mean(high_governor)),
            ],
            "interpretation": "Stress range, not a statistical confidence interval.",
        },
        "important_limit": (
            "Race-rating fallback probabilities remain provisional. House totals now "
            "receive a national calibration with sparse held-out chamber evidence; individual "
            "unpolled district probabilities are still not direct poll-model outputs."
        ),
    }
    if house_calibration is not None:
        summary["house_national_calibration"] = house_calibration
    distributions = pd.concat(
        [
            _distribution(house, "house"),
            _distribution(senate_total, "senate_total"),
            _distribution(governor, "governor_elections"),
        ],
        ignore_index=True,
    )
    return summary, distributions
