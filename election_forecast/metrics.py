"""Evaluation metrics for probabilistic election forecasts."""

from __future__ import annotations

from collections.abc import Iterable


def mean_absolute_error(actual: Iterable[float], predicted: Iterable[float]) -> float:
    pairs = list(zip(actual, predicted, strict=True))
    if not pairs:
        raise ValueError("at least one observation is required")
    return sum(abs(a - p) for a, p in pairs) / len(pairs)


def brier_score(outcomes: Iterable[int], probabilities: Iterable[float]) -> float:
    pairs = list(zip(outcomes, probabilities, strict=True))
    if not pairs:
        raise ValueError("at least one observation is required")
    for outcome, probability in pairs:
        if outcome not in (0, 1):
            raise ValueError("outcomes must be 0 or 1")
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probabilities must be between 0 and 1")
    return sum((probability - outcome) ** 2 for outcome, probability in pairs) / len(pairs)


def calibration_bins(
    outcomes: Iterable[int], probabilities: Iterable[float], bins: int = 10
) -> list[dict[str, float | int]]:
    if bins <= 0:
        raise ValueError("bins must be positive")
    grouped: list[list[tuple[int, float]]] = [[] for _ in range(bins)]
    for outcome, probability in zip(outcomes, probabilities, strict=True):
        if outcome not in (0, 1) or not 0.0 <= probability <= 1.0:
            raise ValueError("invalid outcome or probability")
        index = min(int(probability * bins), bins - 1)
        grouped[index].append((outcome, probability))

    result: list[dict[str, float | int]] = []
    for index, observations in enumerate(grouped):
        if not observations:
            continue
        result.append(
            {
                "bin_start": index / bins,
                "bin_end": (index + 1) / bins,
                "count": len(observations),
                "mean_probability": sum(p for _, p in observations) / len(observations),
                "observed_rate": sum(y for y, _ in observations) / len(observations),
            }
        )
    return result
