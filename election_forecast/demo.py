"""Command-line demo for the statistical forecast."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import ForecastConfig, forecast_states, read_csv, simulate_election

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the toy US presidential forecast")
    parser.add_argument(
        "--fundamentals",
        type=Path,
        default=PROJECT_ROOT / "data" / "demo_fundamentals.csv",
    )
    parser.add_argument("--polls", type=Path, default=PROJECT_ROOT / "data" / "demo_polls.csv")
    parser.add_argument("--simulations", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", type=Path, help="optional JSON output path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = ForecastConfig()
    forecasts = forecast_states(read_csv(args.fundamentals), read_csv(args.polls), config)
    result = simulate_election(forecasts, args.simulations, args.seed, config)

    print("DEMO ONLY - fictional polling scenario, not a real election forecast\n")
    print("State  Prior   Poll  Posterior  D win   EV  Polls")
    print("-----  ------  -----  ---------  ------  --  -----")
    for forecast in sorted(forecasts, key=lambda item: item.state):
        poll = "  n/a" if forecast.poll_mean is None else f"{forecast.poll_mean:+5.1f}"
        probability = result["state_dem_win_probabilities"][forecast.state]
        print(
            f"{forecast.state:5}  {forecast.prior_mean:+6.1f}  {poll}  "
            f"{forecast.posterior_mean:+9.2f}  {probability:6.1%}  "
            f"{forecast.electoral_votes:2d}  {forecast.poll_count:5d}"
        )

    ev = result["dem_electoral_votes"]
    print("\nElectoral College simulation")
    print(f"D win: {result['dem_win_probability']:.1%}")
    print(f"R win: {result['rep_win_probability']:.1%}")
    print(f"269-269 tie: {result['electoral_college_tie_probability']:.1%}")
    print(
        f"D electoral votes: mean {ev['mean']:.1f}, "
        f"median {ev['median']}, 80% interval [{ev['p10']}, {ev['p90']}]"
    )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
