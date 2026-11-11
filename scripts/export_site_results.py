"""Export the post-election review payload for the website.

Inputs are all tracked in Git, so the export is reproducible from a clean checkout:

* ``site/lib/forecast-data.json`` - the sealed Nov 3 forecast snapshot (chamber distributions);
* ``artifacts/results_2026_20261111_final`` - race-level scoring against called results;
* ``config/results_2026_media_tallies.json`` - manually compiled chamber-level media tallies.

The payload never edits the frozen forecast. Media tallies remain labeled as projections.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FORECAST = ROOT / "site/lib/forecast-data.json"
SCORES = ROOT / "artifacts/results_2026_20261111_final"
TALLIES = ROOT / "config/results_2026_media_tallies.json"
OUTPUT = ROOT / "site/lib/results-data.json"

OFFICE_LABELS = {"senate": "Senate", "house": "House", "governor": "Governor"}


def _round(value: object, digits: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _metric_row(frame: pd.DataFrame, office: str, scope: str) -> dict[str, object]:
    row = frame[
        (frame.office == office)
        & (frame.forecast_scope == scope)
        & (frame.result_status == "called")
    ]
    if row.empty:
        raise ValueError(f"Missing aggregate score row for {office}/{scope}")
    record = row.iloc[0]
    return {
        "races": int(record.probability_scored),
        "winner_accuracy": _round(record.winner_accuracy),
        "brier": _round(record.brier),
    }


def _race_label(race_id: str) -> str:
    parts = race_id.split(":")
    office, location = parts[1], parts[2]
    return f"{location} {OFFICE_LABELS[office]}" if office != "house" else location


def _race_record(row: pd.Series) -> dict[str, object]:
    return {
        "race": _race_label(row.race_id),
        "office": row.office,
        "dem": row.dem_candidate,
        "rep": row.rep_candidate,
        "dem_side_party": row.dem_side_party,
        "forecast_dem_probability": _round(row.dem_win_probability),
        "winner": None if pd.isna(row.winner_candidate) else row.winner_candidate,
        "forecast_source": (
            "Poll model" if row.validation_scope == "walk_forward_poll_model" else "Rating prior"
        ),
    }


def build_payload() -> dict[str, object]:
    forecast = json.loads(FORECAST.read_text(encoding="utf-8"))
    tallies = json.loads(TALLIES.read_text(encoding="utf-8"))
    manifest = json.loads((SCORES / "manifest.json").read_text(encoding="utf-8"))
    aggregates = pd.read_csv(SCORES / "aggregate_scores.csv")
    races = pd.read_csv(SCORES / "race_scores.csv")
    control = forecast["control"]

    senate, house, governors = tallies["senate"], tallies["house"], tallies["governors"]
    if senate["dem_aligned_called"] + senate["rep_called"] + len(senate["uncalled"]) != 100:
        raise ValueError("Senate tally must cover all 100 seats")
    if governors["dem_called"] + governors["rep_called"] + len(governors["uncalled"]) != 36:
        raise ValueError("Governor tally must cover the 36 elections")

    chambers = [
        {
            "office": "House",
            "seats": 435,
            "majority": 218,
            "forecast": {
                "median": control["house"]["median_dem_seats"],
                "mean": _round(control["house"]["expected_dem_seats"], 1),
                "p05": control["house"]["p05_dem_seats"],
                "p95": control["house"]["p95_dem_seats"],
                "dem_control_probability": _round(control["house"]["dem_control_probability"]),
            },
            "result": {
                "control": house["control"],
                # Compare the projected final range: called seats alone already reach p95.
                "dem_low": house["projected_dem_final_range"][0],
                "dem_high": house["projected_dem_final_range"][1],
                "summary": (
                    f"D {house['dem_called_range'][0]}-{house['dem_called_range'][1]} called, "
                    f"{house['uncalled_range'][0]}-{house['uncalled_range'][1]} uncalled; "
                    f"projected ~{house['projected_dem_final_range'][0]}-"
                    f"{house['projected_dem_final_range'][1]}"
                ),
            },
        },
        {
            "office": "Senate",
            "seats": 100,
            "majority": 51,
            "forecast": {
                "median": control["senate"]["median_dem_seats"],
                "mean": _round(control["senate"]["expected_dem_seats"], 1),
                "p05": control["senate"]["p05_dem_seats"],
                "p95": control["senate"]["p95_dem_seats"],
                "dem_control_probability": _round(control["senate"]["dem_control_probability"]),
            },
            "result": {
                "control": senate["control"],
                "dem_low": senate["dem_aligned_called"],
                "dem_high": senate["dem_aligned_called"] + len(senate["uncalled"]),
                "summary": (
                    f"D {senate['dem_aligned_called']} - R {senate['rep_called']}; "
                    + ", ".join(item["state"] for item in senate["uncalled"])
                    + " uncalled (D leading)"
                ),
            },
        },
        {
            "office": "Governors",
            "seats": 36,
            "majority": None,
            "forecast": {
                "median": control["governor_elections"]["median_dem_seats"],
                "mean": _round(control["governor_elections"]["expected_dem_seats"], 1),
                "p05": control["governor_elections"]["p05_dem_seats"],
                "p95": control["governor_elections"]["p95_dem_seats"],
                "dem_control_probability": None,
            },
            "result": {
                "control": None,
                "dem_low": governors["dem_called"],
                "dem_high": governors["dem_called"] + len(governors["uncalled"]),
                "summary": (
                    f"D {governors['dem_called']} - R {governors['rep_called']} of 36; "
                    + ", ".join(item["state"] for item in governors["uncalled"])
                    + " uncalled"
                ),
            },
        },
    ]
    for chamber in chambers:
        low, high = chamber["result"]["dem_low"], chamber["result"]["dem_high"]
        p05, p95 = chamber["forecast"]["p05"], chamber["forecast"]["p95"]
        chamber["result"]["within_90"] = (
            "inside" if low >= p05 and high <= p95 else "above" if low > p95 else "partly_outside"
        )

    scored = races[races.probability_scored.astype(bool)]
    misses = scored[scored.winner_correct == 0].sort_values("brier", ascending=False)
    pending_ids = {("senate", item["state"]) for item in senate["uncalled"]} | {
        ("governor", item["state"]) for item in governors["uncalled"]
    }
    races["state"] = races.race_id.str.split(":").str[2].str[:2]
    keys = pd.Series(list(zip(races.office, races.state, strict=True)), index=races.index)
    pending = races[keys.isin(pending_ids)]
    leaders = {("senate", item["state"]): item for item in senate["uncalled"]} | {
        ("governor", item["state"]): item for item in governors["uncalled"]
    }
    pending_records = []
    for _, row in pending.sort_values(["office", "state"], ascending=[False, True]).iterrows():
        record = _race_record(row)
        record["status"] = leaders[(row.office, row.state)]["status"]
        record["leader"] = leaders[(row.office, row.state)]["leader"]
        pending_records.append(record)

    generic = [race for race in forecast["races"] if race["office"] == "generic_ballot"]
    generic_forecast = control.get("house_national_calibration", {}).get(
        "generic_ballot_projection"
    )
    if generic_forecast is None and generic:
        generic_forecast = generic[0].get("model_margin")

    return {
        "schema_version": 1,
        "compiled_at": tallies["compiled_at"],
        "frozen_release": manifest["frozen_release"],
        "frozen_at": forecast["final_release"]["frozen_at"],
        "scores_as_of": manifest["as_of"],
        "status_counts": manifest["status_counts"],
        "chambers": chambers,
        "national_vote": {
            "forecast_dem_margin": _round(generic_forecast, 1),
            "observed_dem_margin": tallies["national_house_vote"]["dem_margin_pp"],
            "observed_range": tallies["national_house_vote"]["dem_margin_range_pp"],
            "basis": tallies["national_house_vote"]["basis"],
        },
        "flips": {
            "senate_to_dem": senate["flips"]["to_dem"],
            "governor_to_dem": governors["flips"]["to_dem"],
        },
        "race_scores": {
            "overall": _metric_row(aggregates, "__overall__", "all"),
            "poll_model": _metric_row(aggregates, "__overall__", "poll_model"),
            "rating_prior": _metric_row(aggregates, "__overall__", "external_rating_prior"),
            "by_office": {
                office: _metric_row(aggregates, office, "all")
                for office in ("senate", "governor", "house")
            },
        },
        "misses": [_race_record(row) for _, row in misses.iterrows()],
        "pending": pending_records,
        "pending_notes": tallies["pending"],
        "turnout_note": tallies["turnout"]["note"],
        "sources": [
            source
            for section in ("senate", "house", "governors", "national_house_vote", "turnout")
            for source in tallies[section]["sources"]
        ],
        "scope": tallies["scope"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build_payload()
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
