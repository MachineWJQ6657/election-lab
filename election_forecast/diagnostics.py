"""Descriptive forecast diagnostics with election-cycle, not row, resampling."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import calibration_bins


def integer_distribution_score(samples: np.ndarray, actual: int, maximum: int) -> float:
    """Ranked probability loss on a bounded integer count (lower is better).

    Summed squared CDF errors over unit-spaced thresholds are the discrete
    analogue of CRPS. A deterministic forecast reduces to absolute error.
    """
    values = np.asarray(samples)
    if (
        values.ndim != 1
        or not len(values)
        or not np.isfinite(values).all()
        or (values < 0).any()
        or (values > maximum).any()
        or not np.equal(values, np.rint(values)).all()
        or not 0 <= actual <= maximum
        or int(actual) != actual
    ):
        raise ValueError("Samples and outcome must be valid integer counts")
    cdf = np.cumsum(np.bincount(values.astype(int), minlength=maximum + 1)) / len(values)
    actual_cdf = (np.arange(maximum + 1) >= actual).astype(float)
    return float(np.square(cdf - actual_cdf).sum())


def probability_diagnostics(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"races": 0}
    actual = frame.actual_margin.gt(0).astype(float)
    probability = frame.dem_win_probability.astype(float)
    bins = calibration_bins(actual.astype(int), probability)
    return {
        "races": len(frame),
        "cycles": int(frame.cycle.nunique()),
        "winner_accuracy": float(np.mean(frame.predicted_margin.gt(0) == actual.astype(bool))),
        "probability_accuracy": float(np.mean(probability.ge(0.5) == actual.astype(bool))),
        "brier": float(np.mean(np.square(probability - actual))),
        "margin_mae": float(np.mean(np.abs(frame.predicted_margin - frame.actual_margin))),
        "mean_confidence": float(np.mean(np.maximum(probability, 1 - probability))),
        "ece_10_bins": float(
            sum(row["count"] * abs(row["mean_probability"] - row["observed_rate"]) for row in bins)
            / len(frame)
        ),
        "calibration_bins": bins,
        "margin_probability_direction_disagreements": int(
            np.sum(frame.predicted_margin.gt(0) != probability.ge(0.5))
        ),
    }


def paired_cycle_bootstrap(
    selected: pd.DataFrame, baseline: pd.DataFrame, *, draws: int = 10000, seed: int = 20261019
) -> dict:
    """Compare Brier on identical races, preserving shared within-cycle errors.

    This is an exploratory cluster interval, not evidence from new elections or
    an assumption that districts in an election cycle are independent.
    """
    keys = ["cycle", "office", "race_id", "horizon"]
    if selected.duplicated(keys).any() or baseline.duplicated(keys).any():
        raise ValueError("Each model must have one prediction per race/horizon")
    paired = selected[keys + ["actual_margin", "dem_win_probability"]].merge(
        baseline[keys + ["dem_win_probability"]],
        on=keys,
        suffixes=("", "_baseline"),
        validate="one_to_one",
    )
    if paired.empty:
        raise ValueError("No common held-out races for comparison")
    y = paired.actual_margin.gt(0).astype(float)
    paired["delta"] = np.square(paired.dem_win_probability - y) - np.square(
        paired.dem_win_probability_baseline - y
    )
    grouped = paired.groupby("cycle").delta.agg(["sum", "count"])
    if len(grouped) < 2:
        raise ValueError("At least two election cycles are required")
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(grouped), size=(draws, len(grouped)))
    deltas = grouped["sum"].to_numpy()[samples].sum(axis=1)
    deltas /= grouped["count"].to_numpy()[samples].sum(axis=1)
    return {
        "common_races": len(paired),
        "independent_cycle_clusters": len(grouped),
        "draws": draws,
        "seed": seed,
        "selected_minus_baseline_brier": float(paired.delta.mean()),
        "exploratory_95pct_cycle_interval": np.quantile(deltas, [0.025, 0.975]).tolist(),
        "resampling_unit": "entire election cycle; race-weighted paired Brier difference",
        "scope": "Few heterogeneous election cycles; exploratory uncertainty, "
        "not proof of superiority.",
    }


def research_complexity_guard(
    selected: pd.DataFrame, baseline: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict]]:
    """Research only: require earlier-cycle evidence before using a complex policy."""
    keys = ["race_id", "cycle", "office", "horizon"]
    joined = selected.merge(
        baseline[keys + ["dem_win_probability", "predicted_margin"]],
        on=keys,
        suffixes=("", "_baseline"),
        validate="one_to_one",
    )
    output, decisions = [], []
    for cycle in sorted(joined.cycle.unique()):
        for office in sorted(joined.office.unique()):
            past = joined[joined.cycle.lt(cycle) & joined.office.eq(office)]
            current = joined[joined.cycle.eq(cycle) & joined.office.eq(office)].copy()
            if current.empty:
                continue
            y = past.actual_margin.gt(0).astype(float)
            gain = (
                float(
                    (
                        np.square(past.dem_win_probability_baseline - y)
                        - np.square(past.dem_win_probability - y)
                    ).mean()
                )
                if len(past)
                else 0.0
            )
            use_selected = len(past) >= 80 and past.cycle.nunique() >= 3 and gain >= 0.002
            if not use_selected:
                current["dem_win_probability"] = current.dem_win_probability_baseline
                current["predicted_margin"] = current.predicted_margin_baseline
            output.append(current)
            decisions.append(
                {
                    "cycle": int(cycle),
                    "office": office,
                    "earlier_races": len(past),
                    "earlier_cycles": int(past.cycle.nunique()),
                    "earlier_brier_gain": gain,
                    "used_selected_policy": bool(use_selected),
                }
            )
    return pd.concat(output, ignore_index=True), decisions
