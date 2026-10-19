"""A tiny dependency-free Ridge-regression baseline for state margins."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .metrics import mean_absolute_error

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURES = ("previous_margin", "national_margin", "incumbent_party")


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small linear system using Gaussian elimination with pivoting."""
    size = len(vector)
    augmented = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular design matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(size)]


def fit_ridge(features: list[list[float]], targets: list[float], alpha: float = 8.0) -> list[float]:
    """Fit Ridge with an unpenalized intercept."""
    if not features or len(features) != len(targets):
        raise ValueError("features and targets must have equal non-zero length")
    design = [[1.0, *row] for row in features]
    columns = len(design[0])
    gram = [[0.0] * columns for _ in range(columns)]
    rhs = [0.0] * columns
    for row, target in zip(design, targets, strict=True):
        for i in range(columns):
            rhs[i] += row[i] * target
            for j in range(columns):
                gram[i][j] += row[i] * row[j]
    for index in range(1, columns):
        gram[index][index] += alpha
    return _solve(gram, rhs)


def predict(coefficients: list[float], features: list[float]) -> float:
    return coefficients[0] + sum(
        coefficient * value for coefficient, value in zip(coefficients[1:], features, strict=True)
    )


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a toy Ridge election baseline")
    parser.add_argument(
        "--data", type=Path, default=PROJECT_ROOT / "data" / "historical_training.csv"
    )
    parser.add_argument("--holdout-year", type=int, default=2024)
    parser.add_argument("--alpha", type=float, default=8.0)
    args = parser.parse_args()

    rows = load_rows(args.data)
    training = [row for row in rows if int(row["year"]) < args.holdout_year]
    holdout = [row for row in rows if int(row["year"]) == args.holdout_year]
    if not training or not holdout:
        raise SystemExit("both training rows and holdout rows are required")

    x_train = [[float(row[name]) for name in FEATURES] for row in training]
    y_train = [float(row["outcome_margin"]) for row in training]
    coefficients = fit_ridge(x_train, y_train, args.alpha)

    predictions = [
        predict(coefficients, [float(row[name]) for name in FEATURES]) for row in holdout
    ]
    actual = [float(row["outcome_margin"]) for row in holdout]
    naive = [float(row["previous_margin"]) for row in holdout]

    print("DEMO ONLY - small manually curated subset, not production training data\n")
    print("Feature coefficients")
    print(f"  intercept: {coefficients[0]:+.3f}")
    for name, coefficient in zip(FEATURES, coefficients[1:], strict=True):
        print(f"  {name}: {coefficient:+.3f}")
    print("\nState  Actual  Ridge  Previous-cycle baseline")
    print("-----  ------  -----  -----------------------")
    for row, actual_margin, predicted_margin, naive_margin in zip(
        holdout, actual, predictions, naive, strict=True
    ):
        print(
            f"{row['state']:5}  {actual_margin:+6.2f}  {predicted_margin:+5.2f}  "
            f"{naive_margin:+9.2f}"
        )
    print(f"\nRidge holdout MAE: {mean_absolute_error(actual, predictions):.3f} points")
    print(f"Naive holdout MAE: {mean_absolute_error(actual, naive):.3f} points")
    print(
        "Note: national_margin here is the final national result. In a live forecast, "
        "replace it with an as-of-date national estimate to prevent leakage."
    )


if __name__ == "__main__":
    main()
