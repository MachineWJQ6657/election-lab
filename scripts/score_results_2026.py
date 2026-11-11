"""Reproduce 2026 scoring offline from retained public-source snapshots."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from election_forecast.results import (
    aggregate_scores,
    score_forecasts,
    sha256,
    validate_sources,
    verify_release,
)
from election_forecast.sources.results_2026 import parse_source, parse_state_directory

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/results/2026_20261111"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release", type=Path, default=ROOT / "artifacts/final_2026_20261103T064943Z"
    )
    parser.add_argument("--source-manifest", type=Path, action="append")
    parser.add_argument(
        "--reviews", type=Path, default=ROOT / "config/results_2026_reviewed_calls.json"
    )
    parser.add_argument("--as-of", default="2026-11-11T23:59:59+00:00")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/results_2026_replay")
    args = parser.parse_args()
    frozen_before = verify_release(args.release)
    if args.output.resolve().is_relative_to(args.release.resolve()):
        raise ValueError("Results output must be outside the frozen release")
    if args.output.exists():
        raise ValueError("Output exists; select a new directory to preserve previous scores")
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        raise ValueError("--as-of must include a timezone")
    manifests = args.source_manifest or [
        SNAPSHOT / "sources.json",
        SNAPSHOT / "web_sources.json",
        SNAPSHOT / "supplement/sources.json",
        SNAPSHOT / "news/sources.json",
    ]
    sources, directories = {}, {}
    input_hashes = {}
    for manifest in manifests:
        records = json.loads(manifest.read_text("utf-8"))["sources"]
        validated = validate_sources(records, manifest.parent, as_of)
        if set(sources).intersection(validated):
            raise ValueError("Duplicate source IDs across manifests")
        sources.update(validated)
        directories.update({key: manifest.parent for key in validated})
        input_hashes[str(manifest.resolve())] = sha256(manifest)
    reviews = json.loads(args.reviews.read_text("utf-8"))
    observations, failures, authorities = [], [], []
    for source_id, source in sources.items():
        if source.get("error"):
            failures.append({"source_id": source_id, "error": source["error"]})
            continue
        payload = (directories[source_id] / source["path"]).read_bytes()
        try:
            parsed = parse_source(payload, source, reviews)
            observations.extend(parsed)
            if source["adapter"] == "state_directory":
                authorities.extend(parse_state_directory(payload, source))
        except (ValueError, KeyError) as exc:
            failures.append({"source_id": source_id, "error": str(exc)})
    if not observations or len(authorities) != 50:
        raise ValueError("Need result observations and an authoritative 50-state source directory")
    forecasts = pd.read_csv(args.release / "latest_forecast.csv")
    races, excluded = score_forecasts(forecasts, observations, sources)
    summary = aggregate_scores(races)
    authority_map = {a["state"]: a for a in authorities}
    races["authoritative_result_source"] = races.location.map(
        lambda location: (
            authority_map[location[:2]]["authority_url"]
            if location != "US"
            else "https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/"
        )
    )
    if verify_release(args.release) != frozen_before:
        raise ValueError("Frozen archive changed during scoring")
    args.output.mkdir(parents=True, exist_ok=False)
    races.to_csv(args.output / "race_scores.csv", index=False, lineterminator="\n")
    summary.to_csv(args.output / "aggregate_scores.csv", index=False, lineterminator="\n")
    excluded.to_csv(
        args.output / "excluded_alternative_matchups.csv", index=False, lineterminator="\n"
    )
    (args.output / "observations.json").write_text(
        json.dumps(
            [o.model_dump(mode="json") for o in observations],
            indent=2,
            allow_nan=False,
        )
        + "\n",
        "utf-8",
    )
    (args.output / "authoritative_sources.json").write_text(
        json.dumps(authorities, indent=2) + "\n",
        "utf-8",
    )
    overall = summary[
        (summary.office == "__overall__")
        & (summary.forecast_scope == "all")
        & (summary.result_status == "all_resolved")
    ].iloc[0]
    counts = races.result_status.value_counts().to_dict()
    report = [
        "# 2026 general-election results scoring",
        "",
        f"Results retrieved through {max(s['retrieved_at'] for s in sources.values())}.",
        f"Frozen baseline: `{args.release.name}`; all {len(frozen_before)} file hashes unchanged.",
        "",
        "## Coverage and interpretation",
        "",
        f"{len(forecasts)} frozen rows → {len(races)} central contest/aggregate rows; "
        f"{len(excluded)} alternative matchups excluded before looking at outcomes.",
        f"Status counts: {json.dumps(counts, sort_keys=True)}.",
        "This is a partial public-source snapshot, not a complete national election score. "
        "Missing or uncalled contests and preliminary leaders are unscored.",
        "Called results are media projections. A call does not certify the attached vote totals. "
        "Certified-only metrics are empty until certification evidence is imported.",
        "",
        "## Provisional comparisons",
        "",
        f"Probability scores: {int(overall.probability_scored)} comparable resolved forecasts; "
        f"winner accuracy {overall.winner_accuracy:.2%}, Brier {overall.brier:.6f}, "
        f"log loss {overall.log_loss:.6f}.",
        f"Vote margins: {int(overall.margin_scored)} comparable resolved poll-model forecasts; "
        f"MAE {overall.margin_mae:.4f} percentage points. "
        "The vote_result_status column identifies preliminary versus certified totals.",
        "",
        "| Office | Probability N | Accuracy | Brier | Margin N | Margin MAE (pp) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary[
        (summary.office != "__overall__")
        & (summary.forecast_scope == "all")
        & (summary.result_status == "all_resolved")
    ].itertuples():

        def fmt(x):
            return "—" if pd.isna(x) else f"{x:.4f}"

        report.append(
            f"| {row.office} | {row.probability_scored} | {fmt(row.winner_accuracy)} | "
            f"{fmt(row.brier)} | {row.margin_scored} | {fmt(row.margin_mae)} |"
        )
    report.extend(
        [
            "",
            "## Definitions",
            "",
            "Brier = (p − y)² for the frozen named Democratic-side candidate event; "
            "independents retain candidate identity and are not silently treated as Democrats. "
            "Log loss clips p to [1e-15, 1−1e-15]. A 0.5 forecast receives half-credit.",
            "Margin = 100 × (Democratic-side candidate votes − Republican-side candidate votes) / "
            "all candidate votes. Error = forecast − observed; positive bias is toward the D side. "
            "Third-party/write-in votes stay in the denominator. House rating priors have no "
            "validated margin and are excluded from margin error.",
            "Probability scores exclude pairwise-only forecasts and unmatched winners. "
            "When a vote list is available both frozen candidates must match uniquely. Winner-only "
            "calls are labeled called_winner_only; they do not verify the full ballot matchup. "
            "RCV/runoff margins, unresolved races, alternative matchups and incomplete national "
            "generic-ballot totals are excluded. "
            "Partial coverage cannot establish chamber control.",
            "Aggregates separate status, offices, and poll-model/rating-prior forecasts. "
            "The all_resolved view is provisional and includes certified outcomes if present.",
            "",
            "## Authoritative sources",
            "",
            "For Senate, House and governor, use the relevant state election authority and its "
            "contest-specific canvass/certification document. authoritative_sources.json includes "
            "all 50 FEC-listed authorities; race_scores.csv links each forecast to its authority. "
            "The FEC compiles certified federal results; states publish governor results. National "
            "House popular-vote comparison requires complete compatible district returns including "
            "unopposed contests. AP/CBS/WRAL provide calls, not certification.",
            "",
            "## Retrieval / parsing gaps",
            "",
        ]
    )
    report.extend(f"- {f['source_id']}: {f['error'].splitlines()[0]}" for f in failures)
    (args.output / "report.md").write_text("\n".join(report) + "\n", "utf-8")
    manifest = {
        "schema_version": 1,
        "as_of": args.as_of,
        "frozen_release": args.release.name,
        "frozen_file_sha256": frozen_before,
        "input_manifest_sha256": input_hashes,
        "reviewed_calls_sha256": sha256(args.reviews),
        "scoring_code_sha256": {
            str(p.relative_to(ROOT)): sha256(p)
            for p in [
                Path(__file__),
                ROOT / "election_forecast/results.py",
                ROOT / "election_forecast/sources/results_2026.py",
                ROOT / "election_forecast/names.py",
                ROOT / "election_forecast/simulation.py",
            ]
        },
        "sources": list(sources.values()),
        "failures": failures,
        "forecast_rows": len(forecasts),
        "central_rows": len(races),
        "status_counts": counts,
        "observation_rows": len(observations),
        "output_sha256": {p.name: sha256(p) for p in sorted(args.output.iterdir())},
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        "utf-8",
    )
    print("\n".join(report[:16]))
    print(f"Artifact: {args.output}")


if __name__ == "__main__":
    main()
