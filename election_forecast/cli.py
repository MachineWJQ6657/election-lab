"""Operational command line interface for data, backtests, and live forecasts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from .audit import run_authenticity_audit
from .backtest import (
    backtest_diagnostics,
    backtest_selection_policy,
    build_latest_rule_sensitivity,
    competitive_backtest_diagnostics,
    fit_and_predict_latest,
    run_walk_forward_backtest,
    select_champion,
    select_champions_by_office,
)
from .contest_scope import annotate_contest_scope
from .coverage import combine_forecast_coverage, summarize_coverage
from .evidence import build_poll_evidence
from .explain import build_forecast_explanations
from .features import build_race_snapshots
from .history import merge_historical_sources
from .house_seats import calibrate_house_forecast
from .lineage import (
    fingerprint,
    source_fingerprints,
    verify_observed_cutoff,
    verify_sources,
    write_forecast_manifest,
)
from .long_range import simulate_2028_scenarios
from .market_calibration import (
    add_chamber_market_context,
    build_market_consensus,
    calibrate_race_probabilities,
)
from .schemas import Office
from .settings import settings
from .simulation import simulate_2026_control
from .sources import (
    fetch_270towin_polls,
    fetch_decision_labs_polls,
    fetch_fec_candidates,
    fetch_fte_full_archive,
    fetch_fte_generic_archive,
    fetch_fte_history,
    fetch_fte_reference_results,
    fetch_hobby_polls,
    fetch_house_national_history,
    fetch_mit_2024_results,
    fetch_polling_source,
    fetch_polling_source_catalog,
    fetch_polling_source_governors,
    fetch_prediction_markets,
    fetch_silver_generic_ballot,
)
from .sources.early_voting import fetch_early_voting
from .sources.merge import merge_current_polls
from .validation_cache import cache_key, cached_validation
from .warehouse import Warehouse

app = typer.Typer(help="US election polling, backtesting, and forecasting pipeline")
data_app = typer.Typer(help="Fetch and inspect polling datasets")
app.add_typer(data_app, name="data")
console = Console()
NON_MODEL_POLL_PATTERN = r"\bstraw(?:\s+poll)?\b"


def _write_quality_report(name: str, frame: pd.DataFrame) -> Path:
    settings.ensure_directories()
    report = {
        "dataset": name,
        "rows": len(frame),
        "races": int(frame["race_id"].nunique()),
        "cycles": sorted(int(item) for item in frame["cycle"].unique()),
        "offices": {str(key): int(value) for key, value in frame.groupby("office").size().items()},
        "locations": int(frame["location"].nunique()),
        "pollsters": int(frame["pollster"].nunique()),
        "earliest_poll": str(pd.to_datetime(frame["end_date"]).min().date()),
        "latest_poll": str(pd.to_datetime(frame["end_date"]).max().date()),
        "missing_sample_size_share": float(frame["sample_size"].isna().mean()),
        "partisan_poll_share": float(frame["partisan"].notna().mean()),
        "sources": {str(key): int(value) for key, value in frame.groupby("source").size().items()},
        "cross_source_corroborated_share": float(
            (
                pd.to_numeric(
                    frame.get("source_count", pd.Series(1, index=frame.index)),
                    errors="coerce",
                )
                > 1
            ).mean()
        ),
    }
    path = settings.artifact_dir / f"{name}_quality.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _write_catalog_report(name: str, frame: pd.DataFrame) -> Path:
    settings.ensure_directories()
    report = {
        "dataset": name,
        "races": len(frame),
        "offices": {str(key): int(value) for key, value in frame.groupby("office").size().items()},
        "ratings": {str(key): int(value) for key, value in frame.groupby("rating").size().items()},
        "missing_dem_candidate_share": float(frame["dem_candidate"].str.endswith("TBD").mean()),
        "missing_rep_candidate_share": float(frame["rep_candidate"].str.endswith("TBD").mean()),
        "fetched_at": str(pd.to_datetime(frame["fetched_at"]).max()),
    }
    path = settings.artifact_dir / f"{name}_quality.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _exclude_non_model_polls(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retain nonrepresentative curiosities in raw data, not in the forecast pool."""
    mask = (
        frame["pollster"]
        .astype(str)
        .str.contains(NON_MODEL_POLL_PATTERN, case=False, regex=True, na=False)
    )
    excluded = frame[mask].copy()
    if not excluded.empty:
        excluded["exclusion_reason"] = "nonrepresentative straw poll"
    return frame[~mask].copy(), excluded


@data_app.command("fetch-history")
def fetch_history(
    refresh: Annotated[bool, typer.Option(help="Ignore cached HTTP snapshot")] = False,
) -> None:
    """Fetch normalized 1998-2022 historical polls with final outcomes."""
    frame = fetch_fte_history(refresh=refresh)
    path = Warehouse().write("polls_history", frame)
    report = _write_quality_report("polls_history", frame)
    console.print(
        f"[green]Historical data ready[/green]: {len(frame):,} polls, "
        f"{frame['race_id'].nunique():,} races -> {path}"
    )
    console.print(f"Quality report -> {report}")


@data_app.command("fetch-reference")
def fetch_reference(
    refresh: Annotated[bool, typer.Option(help="Refresh official/reference files")] = False,
) -> None:
    """Fetch FEC candidates and independently cross-check 2024 outcomes."""
    warehouse = Warehouse()
    reference = fetch_fte_reference_results(refresh=refresh)
    mit = fetch_mit_2024_results(refresh=refresh)
    missing_reference = mit.merge(
        reference[["office", "location"]],
        on=["office", "location"],
        how="left",
        indicator=True,
    )
    missing_reference = missing_reference[missing_reference["_merge"] == "left_only"].drop(
        columns="_merge"
    )
    if not missing_reference.empty:
        missing_reference["dem_candidate"] = "Kamala Harris"
        missing_reference["rep_candidate"] = "Donald Trump"
        reference = pd.concat([reference, missing_reference], ignore_index=True, sort=False)
    fec = fetch_fec_candidates(refresh=refresh)
    house_history = fetch_house_national_history(refresh=refresh)
    reference_path = warehouse.write("reference_results_2024", reference)
    mit_path = warehouse.write("mit_results_2024", mit)
    fec_path = warehouse.write("fec_candidates_2026", fec)
    house_history_path = warehouse.write("house_national_history", house_history)

    comparison = reference.merge(
        mit[["office", "location", "actual_margin"]],
        on=["office", "location"],
        how="inner",
        suffixes=("_fte", "_mit"),
    )
    comparison["absolute_margin_difference"] = (
        comparison["actual_margin_fte"] - comparison["actual_margin_mit"]
    ).abs()
    comparison_path = settings.artifact_dir / "reference_result_comparison.csv"
    comparison.to_csv(comparison_path, index=False)
    console.print(
        f"[green]Reference data ready[/green]: {len(reference):,} 2024 results -> "
        f"{reference_path}; {len(fec):,} FEC filings -> {fec_path}"
    )
    console.print(
        f"MIT cross-check: {len(comparison):,} state races, median absolute difference "
        f"{comparison['absolute_margin_difference'].median():.3f} points -> {comparison_path}"
    )
    console.print(f"MIT normalized results -> {mit_path}")
    console.print(
        f"House national vote/seat history: {len(house_history):,} cycles -> {house_history_path}"
    )


@data_app.command("fetch-latest")
def fetch_latest(
    offices: Annotated[
        list[Office] | None,
        typer.Option("--office", help="Repeat for senate, house, governor, or generic_ballot"),
    ] = None,
    refresh: Annotated[bool, typer.Option(help="Ignore the six-hour cache")] = False,
) -> None:
    """Fetch current 2026 public polling tables."""
    requested = offices or [
        Office.SENATE,
        Office.HOUSE,
        Office.GOVERNOR,
        Office.GENERIC_BALLOT,
    ]
    frames: list[pd.DataFrame] = []
    catalogs: list[pd.DataFrame] = []
    for office in requested:
        if office in (Office.SENATE, Office.HOUSE, Office.GOVERNOR):
            catalogs.append(fetch_polling_source_catalog(office, refresh=refresh))
        if office == Office.GOVERNOR:
            frames.append(fetch_polling_source_governors(refresh=refresh))
        elif office in (Office.SENATE, Office.HOUSE, Office.GENERIC_BALLOT):
            frames.append(fetch_polling_source(office, refresh=refresh))
        else:
            console.print(f"[yellow]Skipping unsupported live office: {office.value}[/yellow]")
    if not frames:
        raise typer.Exit(1)
    catalog = (
        pd.concat(catalogs, ignore_index=True).drop_duplicates(["office", "location"])
        if catalogs
        else pd.DataFrame()
    )
    if any(office in requested for office in (Office.SENATE, Office.GOVERNOR)):
        decision_labs = fetch_decision_labs_polls(catalog, refresh=refresh)
        if not decision_labs.empty:
            frames.append(decision_labs)
        two_seventy = fetch_270towin_polls(
            tuple(office for office in (Office.SENATE, Office.GOVERNOR) if office in requested),
            refresh=refresh,
        )
        if not two_seventy.empty:
            frames.append(two_seventy)
    if Office.GENERIC_BALLOT in requested:
        frames.append(fetch_silver_generic_ballot(refresh=refresh))
    if any(office in requested for office in (Office.SENATE, Office.HOUSE, Office.GOVERNOR)):
        primary = fetch_hobby_polls(refresh=refresh)
        if not primary.empty:
            frames.append(primary[primary["office"].isin([office.value for office in requested])])
    raw_frame = pd.concat(frames, ignore_index=True).drop_duplicates(["source", "source_id"])
    raw_path = Warehouse().write("polls_latest_raw_sources", raw_frame)
    frame, excluded = _exclude_non_model_polls(merge_current_polls(raw_frame))
    excluded_path = settings.artifact_dir / "latest_excluded_polls.csv"
    excluded.to_csv(excluded_path, index=False)
    path = Warehouse().write("polls_latest", frame)
    catalog_path = (
        Warehouse().write("race_catalog_latest", catalog)
        if not catalog.empty
        else "not updated (generic-ballot-only request)"
    )
    report = _write_quality_report("polls_latest", frame)
    catalog_report = (
        _write_catalog_report("race_catalog_latest", catalog) if not catalog.empty else "n/a"
    )
    latest_date = pd.to_datetime(frame["end_date"]).max().date()
    console.print(
        f"[green]Latest data ready[/green]: {len(frame):,} polls, "
        f"{frame['race_id'].nunique():,} matchups, newest {latest_date} -> {path}"
    )
    console.print(
        "Attribution: PollingSource + Decision Labs (CC BY 4.0) + 270toWin + "
        f"Silver Bulletin + UH Hobby primary releases | raw source rows -> {raw_path} "
        f"| excluded -> {excluded_path} "
        f"| quality report -> {report}"
    )
    console.print(
        f"Race catalog: {len(catalog):,} races -> {catalog_path} | report -> {catalog_report}"
    )


@data_app.command("fetch-markets")
def fetch_markets(
    refresh: Annotated[bool, typer.Option(help="Ignore the six-hour cache")] = False,
) -> None:
    """Fetch public Polymarket and Kalshi election probabilities."""
    warehouse = Warehouse()
    if not warehouse.exists("race_catalog_latest"):
        console.print("[red]Missing race_catalog_latest; run elex data fetch-latest[/red]")
        raise typer.Exit(1)
    frame = fetch_prediction_markets(warehouse.read("race_catalog_latest"), refresh=refresh)
    if frame.empty:
        console.print("[red]No qualifying prediction markets were returned[/red]")
        raise typer.Exit(1)
    path = warehouse.write("prediction_markets_latest", frame)
    artifact_path = settings.artifact_dir / "prediction_market_signals.csv"
    frame.to_csv(artifact_path, index=False)
    consensus = build_market_consensus(frame)
    consensus_path = settings.artifact_dir / "prediction_market_consensus.csv"
    consensus.to_csv(consensus_path, index=False)
    console.print(
        f"[green]Prediction markets ready[/green]: {len(frame):,} source-events, "
        f"{len(consensus):,} race/control signals from "
        f"{frame['source'].nunique()} platforms -> {path}"
    )
    console.print(f"Raw signals -> {artifact_path}; de-vigged consensus -> {consensus_path}")


@data_app.command("fetch-early-voting")
def fetch_early_voting_command(
    refresh: Annotated[bool, typer.Option(help="Ignore source cache")] = False,
    as_of: Annotated[str | None, typer.Option(help="Reject observations after YYYY-MM-DD")] = None,
) -> None:
    """Collect aggregate ballots, demographics, and official-source checks."""
    frame, demographics, report = fetch_early_voting(
        as_of=date.fromisoformat(as_of)
        if as_of
        else datetime.now(ZoneInfo("America/New_York")).date(),
        refresh=refresh,
    )
    warehouse = Warehouse()
    warehouse.write("early_voting_latest", frame)
    warehouse.write("early_voting_demographics", demographics)
    report["dataset_sha256"] = {
        name: fingerprint(settings.processed_dir / f"{name}.parquet")
        for name in ("early_voting_latest", "early_voting_demographics")
    }
    report_path = settings.artifact_dir / "early_voting_report.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(report_path)
    frame.to_csv(settings.artifact_dir / "early_voting_latest.csv", index=False)
    console.print(
        f"Early vote: {report['reporting_states']} states, {len(frame)} party/method observations; "
        f"{len(demographics)} aggregate demographic observations; "
        f"{len(report['issues'])} review flags"
    )


@data_app.command("fetch-archive")
def fetch_archive(
    refresh: Annotated[bool, typer.Option(help="Ignore immutable snapshot cache")] = False,
) -> None:
    """Recover full-cycle 2018-2024 polls from immutable Wayback snapshots."""
    warehouse = Warehouse()
    if warehouse.exists("polls_history"):
        outcomes = warehouse.read("polls_history")
    else:
        outcomes = fetch_fte_history()
        warehouse.write("polls_history", outcomes)
    reference = (
        warehouse.read("reference_results_2024")
        if warehouse.exists("reference_results_2024")
        else fetch_fte_reference_results(refresh=refresh)
    )
    if not warehouse.exists("reference_results_2024"):
        warehouse.write("reference_results_2024", reference)
    outcomes = pd.concat([outcomes, reference], ignore_index=True, sort=False)
    frame = fetch_fte_full_archive(outcomes, refresh=refresh)
    national = (
        warehouse.read("house_national_history")
        if warehouse.exists("house_national_history")
        else fetch_house_national_history(refresh=refresh)
    )
    if not warehouse.exists("house_national_history"):
        warehouse.write("house_national_history", national)
    generic = fetch_fte_generic_archive(national, refresh=refresh)
    frame = pd.concat([frame, generic], ignore_index=True, sort=False)
    path = warehouse.write("polls_archive", frame)
    report = _write_quality_report("polls_archive", frame)
    labeled = frame["actual_margin"].notna().mean()
    console.print(
        f"[green]Full-cycle archive ready[/green]: {len(frame):,} polls, "
        f"{frame['race_id'].nunique():,} races, {labeled:.1%} outcome coverage -> {path}"
    )
    console.print(f"Quality report -> {report}")


@data_app.command("status")
def data_status() -> None:
    """Show local dataset coverage and freshness."""
    warehouse = Warehouse()
    table = Table("Dataset", "Rows", "Races", "Offices", "Newest poll")
    for name in ("polls_history", "polls_archive", "polls_latest"):
        if not warehouse.exists(name):
            table.add_row(name, "missing", "-", "-", "-")
            continue
        frame = warehouse.read(name)
        office_counts = frame.groupby("office").size().items()
        counts = ", ".join(f"{key}:{value}" for key, value in office_counts)
        table.add_row(
            name,
            f"{len(frame):,}",
            f"{frame['race_id'].nunique():,}",
            counts,
            str(pd.to_datetime(frame["end_date"]).max().date()),
        )
    console.print(table)
    if warehouse.exists("race_catalog_latest"):
        catalog = warehouse.read("race_catalog_latest")
        console.print(
            f"Current race catalog: {len(catalog):,} races across "
            f"{catalog['office'].nunique()} offices; fetched "
            f"{pd.to_datetime(catalog['fetched_at']).max()}"
        )


@app.command("audit-data")
def audit_data(
    as_of: Annotated[str | None, typer.Option(help="Audit cutoff YYYY-MM-DD")] = None,
) -> None:
    """Verify provenance, hashes, cross-source results, and FEC candidate matches."""
    audit_date = date.fromisoformat(as_of) if as_of else date.today()
    warehouse = Warehouse()
    required = [
        "polls_history",
        "polls_archive",
        "polls_latest",
        "race_catalog_latest",
        "fec_candidates_2026",
        "reference_results_2024",
        "mit_results_2024",
    ]
    missing = [name for name in required if not warehouse.exists(name)]
    if missing:
        console.print(f"[red]Missing audit datasets: {', '.join(missing)}[/red]")
        console.print(
            "Run: elex data fetch-reference; elex data fetch-archive; elex data fetch-latest"
        )
        raise typer.Exit(1)
    reference = warehouse.read("reference_results_2024")
    mit = warehouse.read("mit_results_2024")
    comparison = reference.merge(
        mit[["office", "location", "actual_margin"]],
        on=["office", "location"],
        how="inner",
        suffixes=("_fte", "_mit"),
    )
    comparison["absolute_margin_difference"] = (
        comparison["actual_margin_fte"] - comparison["actual_margin_mit"]
    ).abs()
    report, issues, candidates = run_authenticity_audit(
        history=warehouse.read("polls_history"),
        archive=warehouse.read("polls_archive"),
        latest=warehouse.read("polls_latest"),
        catalog=warehouse.read("race_catalog_latest"),
        fec=warehouse.read("fec_candidates_2026"),
        result_comparison=comparison,
        as_of=audit_date,
    )
    report_path = settings.artifact_dir / "authenticity_report.json"
    issue_path = settings.artifact_dir / "authenticity_issues.csv"
    candidate_path = settings.artifact_dir / "candidate_fec_audit.csv"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    issues.to_csv(issue_path, index=False)
    candidates.to_csv(candidate_path, index=False)
    console.print(
        f"[green]Authenticity audit: {report['verdict']}[/green] | "
        f"issues {report['issue_count']} | report -> {report_path}"
    )
    console.print(
        f"FEC matches {report['fec_candidate_check']['matched']}/"
        f"{report['fec_candidate_check']['checked']} "
        "(unmatched are review flags, not proof of error)"
    )
    console.print(f"Issues -> {issue_path}; candidate audit -> {candidate_path}")


@app.command("backtest")
def backtest_command(
    horizons: Annotated[
        str, typer.Option(help="Comma-separated days before Election Day")
    ] = "7,14,30,60,90",
    min_cycle: Annotated[int, typer.Option(help="Ignore older methodology eras")] = 2008,
) -> None:
    """Run strictly walk-forward multi-office historical validation."""
    warehouse = Warehouse()
    if not warehouse.exists("polls_history"):
        console.print("[yellow]Historical dataset missing; fetching it now.[/yellow]")
        frame = fetch_fte_history()
        warehouse.write("polls_history", frame)
    history = warehouse.read("polls_history")
    history = merge_historical_sources(
        history,
        warehouse.read("polls_archive") if warehouse.exists("polls_archive") else None,
        min_cycle=min_cycle,
    )
    parsed_horizons = tuple(int(item.strip()) for item in horizons.split(",") if item.strip())
    supplemental_outcomes = None
    if warehouse.exists("house_national_history"):
        supplemental_outcomes = warehouse.read("house_national_history")[
            ["cycle", "generic_house_margin"]
        ].rename(columns={"generic_house_margin": "actual_margin"})
        supplemental_outcomes["office"] = Office.GENERIC_BALLOT.value
        supplemental_outcomes["location"] = "US"
    if parsed_horizons == (7, 14, 30, 60, 90) and min_cycle == 2008:
        snapshots, result, _ = cached_validation(history, supplemental_outcomes)
    else:
        snapshots = build_race_snapshots(
            history, parsed_horizons, supplemental_outcomes=supplemental_outcomes
        )
        result = run_walk_forward_backtest(snapshots)
    warehouse.write("historical_snapshots", snapshots)
    settings.ensure_directories()
    result.predictions.to_parquet(
        settings.artifact_dir / "backtest_predictions.parquet", index=False
    )
    result.metrics.to_csv(settings.artifact_dir / "backtest_metrics.csv", index=False)
    result.by_office.to_csv(settings.artifact_dir / "backtest_by_office.csv", index=False)
    by_horizon, calibration = backtest_diagnostics(result)
    by_horizon.to_csv(settings.artifact_dir / "backtest_by_horizon.csv", index=False)
    calibration.to_csv(settings.artifact_dir / "backtest_calibration.csv", index=False)
    competitive = competitive_backtest_diagnostics(result)
    competitive.to_csv(settings.artifact_dir / "backtest_competitive.csv", index=False)
    selection_detail, selection_summary = backtest_selection_policy(result)
    selection_detail.to_parquet(
        settings.artifact_dir / "backtest_selection_predictions.parquet", index=False
    )
    selection_summary.to_csv(settings.artifact_dir / "backtest_selection_summary.csv", index=False)
    horizon_champions = by_horizon.loc[by_horizon.groupby("horizon")["brier"].idxmin()]
    overall_champion = result.metrics.iloc[0]
    model_card = {
        "generated_at": datetime.now(UTC).isoformat(),
        "validation_engine_key": (
            cache_key(history, supplemental_outcomes)
            if parsed_horizons == (7, 14, 30, 60, 90) and min_cycle == 2008
            else None
        ),
        "validation": "strict expanding-window walk-forward by election cycle",
        "training_rule": "each held-out cycle is predicted using earlier cycles only",
        "races": int(snapshots["race_id"].nunique()),
        "cycles": sorted(int(item) for item in snapshots["cycle"].unique()),
        "heldout_prediction_rows": int(len(result.predictions)),
        "independent_heldout_forecasts": int(
            len(result.predictions[["race_id", "cycle", "office", "horizon"]].drop_duplicates())
        ),
        "model_versions_per_forecast": int(result.predictions["model"].nunique()),
        "horizons": sorted(int(item) for item in result.predictions["horizon"].unique()),
        "overall_champion": {
            "model": str(overall_champion["model"]),
            "accuracy": float(overall_champion["accuracy"]),
            "mae": float(overall_champion["mae"]),
            "brier": float(overall_champion["brier"]),
            "log_loss": float(overall_champion["log_loss"]),
        },
        "horizon_champions": horizon_champions.to_dict(orient="records"),
        "nested_model_selection": selection_summary.to_dict(orient="records"),
        "probability_calibration": (
            "A partially pooled logistic calibrator is double-gated by later cycles and "
            "model-level Brier gain; it remains identity when the gain is under 0.001."
        ),
        "important_scope_note": (
            "Metrics apply only to historical poll-model snapshots; external rating priors "
            "used for unpolled current races are not included."
        ),
    }
    (settings.artifact_dir / "model_card.json").write_text(
        json.dumps(model_card, indent=2), encoding="utf-8"
    )

    table = Table("Model", "Races", "Accuracy", "MAE", "Brier", "Log loss")
    for row in result.metrics.itertuples():
        table.add_row(
            row.model,
            f"{int(row.races):,}",
            f"{row.accuracy:.1%}",
            f"{row.mae:.2f}",
            f"{row.brier:.3f}",
            f"{row.log_loss:.3f}",
        )
    console.print(table)
    console.print(
        f"Validated {snapshots['race_id'].nunique():,} races across "
        f"{snapshots['cycle'].nunique()} cycles. Artifacts -> {settings.artifact_dir}"
    )


@app.command("forecast-latest")
def forecast_latest(
    as_of: Annotated[str | None, typer.Option(help="Freeze forecast at YYYY-MM-DD")] = None,
    prediction_markets: Annotated[
        bool,
        typer.Option(
            "--prediction-markets/--no-prediction-markets",
            help="Use bounded real-time Polymarket/Kalshi calibration",
        ),
    ] = True,
    refresh_markets: Annotated[bool, typer.Option(help="Refresh prediction-market cache")] = False,
) -> None:
    """Train on historical cycles and forecast every current polled matchup."""
    try:
        forecast_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError as error:
        raise typer.BadParameter("as-of must use YYYY-MM-DD") from error
    warehouse = Warehouse()
    missing = [
        name
        for name in ("polls_history", "polls_latest", "race_catalog_latest")
        if not warehouse.exists(name)
    ]
    if missing:
        console.print(f"[red]Missing datasets: {', '.join(missing)}[/red]")
        console.print("Run: elex data fetch-history; elex data fetch-latest")
        raise typer.Exit(1)
    history = warehouse.read("polls_history")
    history = merge_historical_sources(
        history,
        warehouse.read("polls_archive") if warehouse.exists("polls_archive") else None,
    )
    input_versions = source_fingerprints()
    latest = warehouse.read("polls_latest")
    if as_of is not None:
        try:
            verify_observed_cutoff(latest, forecast_date, "Live polling table")
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
    latest["election_date"] = pd.to_datetime(latest["election_date"])
    horizon = int((latest["election_date"].min().date() - forecast_date).days)
    if horizon < 0:
        raise typer.BadParameter("as-of date is after Election Day")
    house_history = (
        warehouse.read("house_national_history")
        if warehouse.exists("house_national_history")
        else None
    )
    supplemental_outcomes = None
    if house_history is not None:
        supplemental_outcomes = house_history[["cycle", "generic_house_margin"]].rename(
            columns={"generic_house_margin": "actual_margin"}
        )
        supplemental_outcomes["office"] = Office.GENERIC_BALLOT.value
        supplemental_outcomes["location"] = "US"
    training_snapshots, validation, validation_cached = cached_validation(
        history[history["cycle"] >= 2008], supplemental_outcomes
    )
    console.print(
        "Historical validation: " + ("verified cache hit" if validation_cached else "recomputed")
    )
    current_snapshots = build_race_snapshots(
        pd.concat([history, latest], ignore_index=True),
        (horizon,),
        min_polls=1,
        lookback_days=120,
        target_cycles=(2026,),
        supplemental_outcomes=supplemental_outcomes,
    )
    current_snapshots = current_snapshots[current_snapshots["cycle"] == 2026].copy()
    champion, validated_horizon, champion_brier = select_champion(validation, horizon)
    model_selection = select_champions_by_office(validation, horizon, fallback=champion)
    model_selection = model_selection[
        model_selection["office"].isin(current_snapshots["office"].unique())
    ].reset_index(drop=True)
    rule_sensitivity = build_latest_rule_sensitivity(training_snapshots, current_snapshots)
    selected_models = model_selection[["office", "model"]].rename(
        columns={"model": "selected_model"}
    )
    rule_sensitivity = rule_sensitivity.merge(selected_models, on="office", how="left")
    rule_sensitivity["is_selected_model"] = (
        rule_sensitivity["model"] == rule_sensitivity["selected_model"]
    )
    forecast_frames: list[pd.DataFrame] = []
    for selection in model_selection.itertuples():
        office_snapshots = current_snapshots[current_snapshots["office"] == selection.office]
        if office_snapshots.empty:
            continue
        forecast_frames.append(
            fit_and_predict_latest(
                training_snapshots,
                office_snapshots,
                champion=selection.model,
                validation_predictions=validation.predictions,
            )
        )
    poll_forecast = pd.concat(forecast_frames, ignore_index=True)
    catalogs = warehouse.read("race_catalog_latest")
    if as_of is not None:
        try:
            verify_observed_cutoff(catalogs, forecast_date, "Live race catalog")
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
    forecast = combine_forecast_coverage(
        poll_forecast,
        catalogs,
        as_of_date=forecast_date,
        horizon=horizon,
    )
    house_calibration: dict[str, object] | None = None
    generic_forecast = forecast[forecast["office"] == Office.GENERIC_BALLOT.value]
    if house_history is not None and not generic_forecast.empty:
        generic_row = generic_forecast.sort_values("poll_count", ascending=False).iloc[0]
        generic_metrics = validation.by_office[
            (validation.by_office["office"] == Office.GENERIC_BALLOT.value)
            & (validation.by_office["model"] == generic_row["model"])
        ]
        generic_mae = float(generic_metrics.iloc[0]["mae"]) if not generic_metrics.empty else 3.24
        forecast, house_calibration = calibrate_house_forecast(
            forecast,
            house_history,
            generic_ballot_projection=float(generic_row["predicted_margin"]),
            generic_forecast_mae=generic_mae,
        )
    market_signals = pd.DataFrame()
    market_consensus = pd.DataFrame()
    if prediction_markets and as_of is None:
        try:
            market_signals = fetch_prediction_markets(catalogs, refresh=refresh_markets)
            if not market_signals.empty:
                warehouse.write("prediction_markets_latest", market_signals)
                market_consensus = build_market_consensus(market_signals)
        except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as error:
            if warehouse.exists("prediction_markets_latest"):
                market_signals = warehouse.read("prediction_markets_latest")
                market_consensus = build_market_consensus(market_signals)
                console.print(
                    f"[yellow]Live market refresh failed; using cached snapshot: {error}[/yellow]"
                )
            else:
                console.print(
                    f"[yellow]Prediction markets unavailable; model-only forecast: {error}[/yellow]"
                )
    elif prediction_markets and as_of is not None:
        console.print(
            "[yellow]Frozen as-of forecasts omit live markets to prevent future leakage.[/yellow]"
        )
    forecast, market_calibration = calibrate_race_probabilities(forecast, market_consensus)
    forecast = annotate_contest_scope(
        forecast, catalogs, warehouse.read("polls_latest_raw_sources")
    )
    verify_sources(input_versions)
    coverage = summarize_coverage(forecast)
    csv_path = settings.artifact_dir / "latest_forecast.csv"
    json_path = settings.artifact_dir / "latest_forecast.json"
    coverage_path = settings.artifact_dir / "latest_coverage.csv"
    model_selection_path = settings.artifact_dir / "latest_model_selection.csv"
    rule_sensitivity_path = settings.artifact_dir / "latest_model_sensitivity.csv"
    house_calibration_path = settings.artifact_dir / "house_national_calibration.json"
    market_signal_path = settings.artifact_dir / "prediction_market_signals.csv"
    market_consensus_path = settings.artifact_dir / "prediction_market_consensus.csv"
    market_calibration_path = settings.artifact_dir / "prediction_market_calibration.csv"
    settings.ensure_directories()
    forecast.to_csv(csv_path, index=False)
    json_path.write_text(
        forecast.to_json(orient="records", indent=2, force_ascii=False, date_format="iso"),
        encoding="utf-8",
    )
    coverage.to_csv(coverage_path, index=False)
    model_selection.to_csv(model_selection_path, index=False)
    rule_sensitivity.to_csv(rule_sensitivity_path, index=False)
    market_signals.to_csv(market_signal_path, index=False)
    market_consensus.to_csv(market_consensus_path, index=False)
    market_calibration.to_csv(market_calibration_path, index=False)
    if house_calibration is not None:
        house_calibration_path.write_text(json.dumps(house_calibration, indent=2), encoding="utf-8")
    warehouse.write("latest_forecast", forecast)
    warehouse.write("current_snapshots", current_snapshots)
    generic_path = settings.artifact_dir / "latest_generic_ballot_snapshot.csv"
    current_snapshots[current_snapshots["office"] == Office.GENERIC_BALLOT.value].to_csv(
        generic_path, index=False
    )

    explanations = build_forecast_explanations(forecast, current_snapshots, latest)
    explanation_csv_path = settings.artifact_dir / "latest_explanations.csv"
    explanation_json_path = settings.artifact_dir / "latest_explanations.json"
    explanations.to_csv(explanation_csv_path, index=False)
    explanation_json_path.write_text(
        explanations.to_json(orient="records", indent=2, force_ascii=False), encoding="utf-8"
    )
    evidence = build_poll_evidence(latest, as_of_date=forecast_date)
    evidence_path = settings.artifact_dir / "latest_poll_evidence.csv"
    evidence.to_csv(evidence_path, index=False)

    control, distributions = simulate_2026_control(forecast, catalogs)
    control = add_chamber_market_context(control, market_consensus)
    control_path = settings.artifact_dir / "forecast_2026_control.json"
    distribution_path = settings.artifact_dir / "forecast_2026_seat_distributions.csv"
    control_path.write_text(json.dumps(control, indent=2), encoding="utf-8")
    distributions.to_csv(distribution_path, index=False)

    table = Table("Race", "D", "R", "Polls", "Poll nowcast", "Forecast", "D win")
    competitive = forecast[
        forecast["dem_win_probability"].between(0.20, 0.80, inclusive="both")
    ].copy()
    competitive["distance"] = (competitive["dem_win_probability"] - 0.5).abs()
    for row in competitive.sort_values("distance").head(50).itertuples():
        table.add_row(
            f"{row.office} {row.location}",
            row.dem_candidate,
            row.rep_candidate,
            str(row.poll_count),
            (
                f"{row.polling_nowcast_margin:+.1f}"
                if pd.notna(getattr(row, "polling_nowcast_margin", None))
                else "n/a"
            ),
            f"{row.predicted_margin:+.1f}",
            f"{row.dem_win_probability:.1%}",
        )
    console.print(table)
    coverage_table = Table("Office", "Races", "Poll model", "Rating prior", "Rows")
    for row in coverage.itertuples():
        coverage_table.add_row(
            row.office,
            f"{row.races:,}",
            f"{row.poll_model_races:,}",
            f"{row.rating_prior_races:,}",
            f"{row.matchup_rows:,}",
        )
    console.print(coverage_table)
    write_forecast_manifest(
        as_of=forecast_date.isoformat(),
        sources=input_versions,
        validation_engine_key=cache_key(history[history["cycle"] >= 2008], supplemental_outcomes),
    )
    console.print(f"Forecast frozen at {forecast_date}; CSV -> {csv_path}; JSON -> {json_path}")
    console.print(f"Coverage audit -> {coverage_path}")
    console.print(
        f"Champion at nearest validated horizon ({validated_horizon} days): "
        f"{champion}, Brier {champion_brier:.3f}"
    )
    console.print(f"Office-specific model selection -> {model_selection_path}")
    console.print(f"Rule-model sensitivity -> {rule_sensitivity_path}")
    if house_calibration is not None:
        console.print(f"House national calibration -> {house_calibration_path}")
    console.print(
        f"Explanations -> {explanation_csv_path}; correlated control simulation -> {control_path}"
    )
    console.print(f"Per-poll evidence and weights -> {evidence_path}")
    console.print(f"Generic-ballot feature snapshot -> {generic_path}")
    if not market_consensus.empty:
        calibrated_count = int(forecast["market_calibrated"].sum())
        console.print(
            f"Prediction markets: {len(market_signals):,} source-events, "
            f"{calibrated_count:,} candidate-matched race rows adjusted -> "
            f"{market_calibration_path}"
        )
        console.print(
            f"De-vigged market consensus -> {market_consensus_path}; "
            "model-only probabilities are preserved in the forecast artifact"
        )
    console.print(
        "Source attribution: PollingSource + Decision Labs (CC BY 4.0) + "
        "270toWin + Silver Bulletin; original links and cross-source "
        "corroboration are retained per poll"
    )


@app.command("forecast-2028")
def forecast_2028(
    simulations: Annotated[
        int, typer.Option(help="Monte Carlo draws per popular-vote scenario")
    ] = 60_000,
) -> None:
    """Build candidate-agnostic 2028 Electoral College scenarios."""
    warehouse = Warehouse()
    if not warehouse.exists("reference_results_2024"):
        console.print("[red]Missing reference_results_2024; run elex data fetch-reference[/red]")
        raise typer.Exit(1)
    summary, states, distributions = simulate_2028_scenarios(
        warehouse.read("reference_results_2024"), simulations=simulations
    )
    summary_path = settings.artifact_dir / "forecast_2028_scenarios.json"
    state_path = settings.artifact_dir / "forecast_2028_state_probabilities.csv"
    distribution_path = settings.artifact_dir / "forecast_2028_ev_distributions.csv"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    states.to_csv(state_path, index=False)
    distributions.to_csv(distribution_path, index=False)

    table = Table("Scenario", "D popular win", "D EC win", "Expected D EV", "5%-95% EV")
    for scenario, result in summary["scenarios"].items():
        table.add_row(
            scenario,
            f"{result['dem_popular_vote_win_probability']:.1%}",
            f"{result['dem_electoral_college_win_probability']:.1%}",
            f"{result['expected_dem_electoral_votes']:.0f}",
            f"{result['p05_dem_electoral_votes']}-{result['p95_dem_electoral_votes']}",
        )
    console.print(table)
    console.print(f"Candidate-agnostic scenario model -> {summary_path}")
    console.print("This is conditional on popular-vote scenarios, not a named-candidate forecast.")


if __name__ == "__main__":
    app()
