"""Adapter for FiveThirtyEight's public pollster-rating history."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pandas as pd

from ..http_cache import CachedHTTPClient
from ..schemas import Office, PollRecord, Population

FTE_HISTORY_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/data/master/pollster-ratings/raw_polls.csv"
)

OFFICE_MAP = {
    "Pres-G": Office.PRESIDENT,
    "Sen-G": Office.SENATE,
    "House-G": Office.HOUSE,
    "Gov-G": Office.GOVERNOR,
    "House-G-US": Office.GENERIC_BALLOT,
}


def _population_from_row(_: pd.Series) -> Population:
    # This ratings export does not retain the population field consistently.
    return Population.UNKNOWN


def fetch_fte_history(
    *, refresh: bool = False, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    client = client or CachedHTTPClient()
    payload = client.get(FTE_HISTORY_URL, refresh=refresh, ttl_hours=24 * 30)
    raw = pd.read_csv(BytesIO(payload), low_memory=False)
    raw = raw[raw["type_simple"].isin(OFFICE_MAP)].copy()
    raw = raw[(raw["cand1_party"] == "DEM") & (raw["cand2_party"] == "REP")].copy()
    required = [
        "poll_id",
        "question_id",
        "race_id",
        "cycle",
        "location",
        "pollster",
        "polldate",
        "electiondate",
        "cand1_pct",
        "cand2_pct",
        "margin_actual",
    ]
    raw = raw.dropna(subset=required)
    fetched_at = datetime.now(UTC)

    records: list[dict[str, object]] = []
    for _, row in raw.iterrows():
        sample_size = None if pd.isna(row.get("samplesize")) else max(int(row["samplesize"]), 1)
        transparency = (
            None if pd.isna(row.get("transparency_score")) else float(row["transparency_score"])
        )
        record = PollRecord(
            source="fivethirtyeight_pollster_ratings",
            source_id=f"{int(row['poll_id'])}:{int(row['question_id'])}",
            race_id=f"{int(row['cycle'])}:{row['type_simple']}:{int(row['race_id'])}",
            cycle=int(row["cycle"]),
            office=OFFICE_MAP[str(row["type_simple"])],
            location=str(row["location"]),
            pollster=str(row["pollster"]),
            end_date=pd.to_datetime(row["polldate"]).date(),
            election_date=pd.to_datetime(row["electiondate"]).date(),
            sample_size=sample_size,
            population=_population_from_row(row),
            methodology=None if pd.isna(row.get("methodology")) else str(row["methodology"]),
            partisan=None if pd.isna(row.get("partisan")) else str(row["partisan"]),
            transparency_score=transparency,
            dem_candidate=str(row["cand1_name"]),
            rep_candidate=str(row["cand2_name"]),
            dem_pct=float(row["cand1_pct"]),
            rep_pct=float(row["cand2_pct"]),
            actual_margin=float(row["margin_actual"]),
            source_url=FTE_HISTORY_URL,
            fetched_at=fetched_at,
        )
        records.append(record.model_dump(mode="json"))

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError("FiveThirtyEight history normalized to zero records")
    frame = frame.drop_duplicates(subset=["source", "source_id"], keep="last")
    return frame.sort_values(["cycle", "office", "race_id", "end_date"]).reset_index(drop=True)
