"""Export a compact, deterministic website snapshot from forecast artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from election_forecast.backtest import BacktestResult, backtest_selection_policy
from election_forecast.collection import summarize_collection
from election_forecast.lineage import fingerprint, verify_forecast_manifest, verify_table_report
from election_forecast.pollsters import pollster_key
from election_forecast.simulation import select_race_matchups

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
PROCESSED = ROOT / "data" / "processed"
OUTPUT = ROOT / "site" / "lib" / "forecast-data.json"


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    clean = frame.replace({np.nan: None, np.inf: None, -np.inf: None})
    return clean.to_dict(orient="records")


def _load_source_link_audit() -> dict | None:
    path = ARTIFACTS / "source_link_availability_latest.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    verify_table_report(report, PROCESSED, required=("polls_latest",))
    return report


def _final_release_snapshot(forecast: dict) -> dict | None:
    path = ARTIFACTS / "final_release.json"
    if not path.exists():
        return None
    release = json.loads(path.read_text(encoding="utf-8"))
    if (
        release["as_of"] != forecast["as_of"]
        or release["engine_sha256"] != forecast["engine_sha256"]
    ):
        raise ValueError("Final release differs from the forecast; explicitly seal a new release")
    for name, digest in release["input_table_sha256"].items():
        if fingerprint(PROCESSED / f"{name}.parquet") != digest:
            raise ValueError("Final release input changed after sealing")
    for name, digest in release["forecast_output_sha256"].items():
        if fingerprint(ARTIFACTS / name) != digest:
            raise ValueError("Final release prediction changed after sealing")
    return release


def _matching_research(
    directory: str, engine_key: str, *, horizon: int | None = None
) -> dict | None:
    path = ARTIFACTS / directory / "report.json"
    report = json.loads(path.read_text()) if path.exists() else None
    if report and (
        report.get("engine_key") != engine_key
        or (horizon is not None and report.get("target_horizon") != horizon)
    ):
        print(f"Omitting stale research report: {directory}")
        return None
    return report


def _early_vote_snapshot(as_of: str) -> dict | None:
    path = PROCESSED / "early_voting_latest.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    report = json.loads((ARTIFACTS / "early_voting_report.json").read_text())
    hashes = report.get("dataset_sha256", {})
    for name in ("early_voting_latest", "early_voting_demographics"):
        if hashes.get(name) != fingerprint(PROCESSED / f"{name}.parquet"):
            raise ValueError(f"Early-vote component snapshot mismatch: {name}; rerun collection")
    if report["as_of"] > as_of:
        raise ValueError("Early-vote snapshot is newer than the forecast; do not mix as-of dates")
    states = []
    for state, group in frame.groupby("state"):
        totals = group.groupby("category")["count"].sum()
        cast = group[group["category"].isin(["returned", "inperson"])]
        parties = cast.groupby("party")["count"].sum()
        sources = cast if not cast.empty else group
        states.append(
            {
                "state": state,
                "requested": int(totals["requested"]) if "requested" in totals else None,
                "returned": int(totals["returned"]) if "returned" in totals else None,
                "inperson": int(totals["inperson"]) if "inperson" in totals else None,
                "observed_ballots": int(cast["count"].sum()) if not cast.empty else None,
                "democratic": int(parties.get("Democratic", 0)),
                "republican": int(parties.get("Republican", 0)),
                "unspecified": int(parties.get("Unspecified", 0)),
                "other": int(
                    parties.drop(["Democratic", "Republican", "Unspecified"], errors="ignore").sum()
                ),
                "snapshot_date": str(sources["snapshot_date"].max()),
                "mode_snapshot_dates": cast.groupby("category")["snapshot_date"].max().to_dict(),
                "sources": sorted(sources["source"].unique()),
                "source_urls": sorted(sources["source_url"].unique()),
                "review_flags": [
                    issue for issue in report["issues"] if issue.get("state") == state
                ],
                "request_basis": "Ballots issued (returned + outstanding)"
                if state == "FL"
                else "Requests or ballots issued; state definitions vary",
            }
        )
    demographics_path = PROCESSED / "early_voting_demographics.parquet"
    demographics = []
    if demographics_path.exists():
        data = pd.read_parquet(demographics_path)
        # Missing modes remain an explicit unknown bucket, never an inferred race,
        # gender or ethnicity. All shares use the full observed ballot denominator.
        complete = []
        for (state, dimension), group in data.groupby(["state", "dimension"]):
            state_counts = frame[
                frame.state.eq(state) & frame.category.isin(["returned", "inperson"])
            ]
            required_modes = set(state_counts[state_counts["count"].gt(0)].category)
            expected_counts = state_counts.groupby("category")["count"].sum()
            observed_counts = group.groupby("category")["count"].sum()
            available_modes = required_modes & set(group.category)
            reconciles = all(
                observed_counts[mode] == expected_counts[mode] for mode in available_modes
            )
            if required_modes and reconciles:
                missing = [
                    {
                        "state": state,
                        "dimension": dimension,
                        "category": mode,
                        "group": "Not reported / missing voting mode",
                        "count": int(expected_counts[mode]),
                    }
                    for mode in required_modes - available_modes
                ]
                complete.append(pd.concat([group, pd.DataFrame(missing)], ignore_index=True))
        if complete:
            demographics = _records(
                pd.concat(complete)
                .groupby(["state", "dimension", "group"], as_index=False)["count"]
                .sum()
            )
    reference = pd.read_parquet(PROCESSED / "mit_results_2024.parquet")
    reference = reference[
        reference.office.eq("president") & reference.location.isin([s["state"] for s in states])
    ]
    if reference.location.duplicated().any():
        raise ValueError("Ambiguous 2024 turnout reference")
    turnout_reference = {
        row.location: {
            "two_party_votes": int(row.dem_votes + row.rep_votes),
            "source_url": row.source_url,
            "scope": (
                "2024 presidential Democratic + Republican votes; "
                "reference scale only, not a 2026 turnout prediction"
            ),
        }
        for row in reference.itertuples()
    }
    return {
        "as_of": report["as_of"],
        "states": states,
        "demographics": demographics,
        "model_gate": report["model_gate"],
        "references": report["references"],
        "issue_count": len(report["issues"]),
        "reporting_states": report["reporting_states"],
        "turnout_reference_2024": turnout_reference,
        "historical_snapshots_available": sum(
            "total" in row for row in report["historical_context"]
        ),
    }


def main() -> None:
    manifest = verify_forecast_manifest(ARTIFACTS, PROCESSED)
    forecast = pd.read_csv(ARTIFACTS / "latest_forecast.csv")
    if (
        forecast["as_of_date"].nunique() != 1
        or str(forecast["as_of_date"].iloc[0]) != manifest["as_of"]
    ):
        raise ValueError("Forecast manifest and as-of dates differ")
    central, _ = select_race_matchups(forecast)
    central["race_key"] = central["office"].astype(str) + ":" + central["location"].astype(str)
    central["competitiveness"] = (central["dem_win_probability"] - 0.5).abs()
    columns = {
        "race_key": "id",
        "race_id": "source_race_id",
        "office": "office",
        "location": "location",
        "dem_candidate": "dem",
        "rep_candidate": "rep",
        "poll_count": "poll_count",
        "pollster_count": "pollster_count",
        "polling_nowcast_margin": "poll_margin",
        "weighted_margin": "raw_poll_margin",
        "mean_pollster_house_effect": "poll_house_effect",
        "predicted_margin": "model_margin",
        "model_only_dem_win_probability": "model_probability",
        "market_consensus_dem_win_probability": "market_probability",
        "dem_win_probability": "dem_probability",
        "market_calibration_weight": "market_weight",
        "probability_source": "probability_source",
        "validation_scope": "validation_scope",
        "rating": "rating",
        "rating_source": "rating_source",
        "model": "model",
        "competitiveness": "competitiveness",
        "dem_side_party": "dem_side_party",
        "multi_candidate_warning": "multi_candidate_warning",
        "probability_event": "probability_event",
    }
    races = central[list(columns)].rename(columns=columns)
    races["district_boundary_changed"] = central.get(
        "district_boundary_changed", pd.Series(False, index=central.index)
    ).eq(True)
    races = races.sort_values(["office", "competitiveness", "location"])

    evidence = pd.read_csv(ARTIFACTS / "latest_poll_evidence.csv")
    optional_provenance = [
        column
        for column in ("publication_date", "primary_source_verified", "sample_size_basis")
        if column in evidence
    ]
    central_ids = set(central["race_id"].astype(str))
    evidence = evidence[evidence["race_id"].astype(str).isin(central_ids)].copy()
    organization_counts = (
        evidence.assign(organization_key=evidence["pollster"].map(pollster_key))
        .groupby("race_id")["organization_key"]
        .nunique()
    )
    races["normalized_pollster_count"] = races["source_race_id"].map(organization_counts)
    active_poll_count = len(evidence)
    evidence = evidence.sort_values(["race_id", "end_date"], ascending=[True, False])
    evidence = evidence.groupby("race_id", group_keys=False).head(12)
    evidence = evidence[
        [
            "race_id",
            "pollster",
            "end_date",
            "sample_size",
            "population",
            "partisan",
            "dem_pct",
            "rep_pct",
            "margin",
            "normalized_race_weight",
            "source",
            "publisher_domain",
            "source_url",
            "corroborated_sources",
        ]
        + optional_provenance
    ]
    link_audit = _load_source_link_audit()
    link_status = (
        {row["url"]: row["reachable"] for row in link_audit["checks"]} if link_audit else {}
    )
    evidence["source_reachable"] = evidence["source_url"].map(link_status)

    control = json.loads((ARTIFACTS / "forecast_2026_control.json").read_text())
    authenticity = json.loads((ARTIFACTS / "authenticity_report.json").read_text())
    verify_table_report(
        authenticity,
        PROCESSED,
        required=("polls_latest", "race_catalog_latest", "fec_candidates_2026", "mit_results_2024"),
    )
    collection_path = ARTIFACTS / "latest_collection_report.json"
    collection = (
        summarize_collection(json.loads(collection_path.read_text()), PROCESSED)
        if collection_path.exists()
        else None
    )
    model_card = json.loads((ARTIFACTS / "model_card.json").read_text())
    if not model_card.get("validation_engine_key") or model_card[
        "validation_engine_key"
    ] != manifest.get("validation_engine_key"):
        raise ValueError(
            "Validation and forecast engine versions disagree; rerun default backtest and forecast"
        )
    distributions = pd.read_csv(ARTIFACTS / "forecast_2026_seat_distributions.csv")
    distributions = distributions[distributions["probability"] >= 0.0005]
    selection = pd.read_csv(ARTIFACTS / "latest_model_selection.csv")
    predictions = pd.read_parquet(ARTIFACTS / "backtest_predictions.parquet")
    _, nested = backtest_selection_policy(
        BacktestResult(predictions, pd.DataFrame(), pd.DataFrame()),
        target_horizon=int(forecast["horizon"].iloc[0]),
    )
    nested.to_csv(ARTIFACTS / "backtest_selection_current_horizon.csv", index=False)
    market = pd.read_csv(ARTIFACTS / "prediction_market_consensus.csv")
    chamber_market = market[market["market_scope"] == "chamber_control"]

    engine_key = model_card["validation_engine_key"]
    horizon = int(forecast["horizon"].iloc[0])
    decay = _matching_research("decay_experiment_20261019", engine_key)
    lag = _matching_research("publication_lag_experiment_20261019", engine_key)
    house_validation = _matching_research("house_control_backtest_20261019", engine_key)
    research_audit = _matching_research("research_audit_latest", engine_key, horizon=horizon)
    correlation = _matching_research("correlation_experiment_20261019", engine_key)
    identity = _matching_research(
        "pollster_identity_experiment_latest", engine_key, horizon=horizon
    )

    payload = {
        "final_release": _final_release_snapshot(manifest),
        "updated_at": str(forecast["as_of_date"].iloc[0]),
        "days_to_election": int(forecast["horizon"].iloc[0]),
        "heldout_forecasts": model_card["independent_heldout_forecasts"],
        "validation_horizon": int(selection["validated_horizon"].mode().iloc[0]),
        "latest_poll_date": str(pd.to_datetime(evidence["end_date"]).max().date()),
        "active_poll_count": active_poll_count,
        "source_link_check": {
            key: link_audit[key] for key in ("sample_size", "reachable", "generated_at")
        }
        if link_audit
        else None,
        "collection": collection,
        "early_voting": _early_vote_snapshot(manifest["as_of"]),
        "recency_experiment": decay,
        "publication_lag_experiment": lag,
        "house_control_validation": house_validation,
        "research_audit": research_audit,
        "correlation_experiment": correlation,
        "pollster_identity_experiment": identity,
        "snapshot_verified": True,
        "control": control,
        "races": _records(races),
        "evidence": _records(evidence),
        "distributions": _records(distributions),
        "model_selection": _records(selection),
        "nested_backtest": _records(nested),
        "chamber_markets": _records(chamber_market),
        "authenticity": {
            "verdict": authenticity["verdict"],
            "issue_count": authenticity["issue_count"],
            "latest_polls": authenticity["datasets"]["latest"]["rows"],
            "latest_pollsters": authenticity["datasets"]["latest"]["pollsters"],
            "poll_sources": authenticity["datasets"]["latest"]["sources"],
            "hashes_verified": authenticity["cache"]["payload_hashes_verified"],
            "fec_matches": authenticity["fec_candidate_check"]["matched"],
            "fec_checked": authenticity["fec_candidate_check"]["checked"],
            "fec_name_review_flags": authenticity["fec_candidate_check"]["unmatched_review_flags"],
            "fec_match_note": authenticity["fec_candidate_check"]["important_note"],
            "top_source_domains": list(authenticity["latest_source_domains"].items())[:16],
        },
        "model_card": model_card,
    }
    payload["snapshot_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(f"Wrote {OUTPUT} with {len(races)} central races and {len(evidence)} poll records")


if __name__ == "__main__":
    main()
