"""Silver Bulletin public generic-ballot CSV adapter."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from io import BytesIO

import pandas as pd

from ..http_cache import CachedHTTPClient
from ..schemas import Office, PollRecord, Population

SILVER_GENERIC_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRsvXNCZ0ubJr8D_yNcU5q6C0_HBa35K7oDK03KpO7Ca43UwdXaIdvVLWoXEmHHph0EREz5430Hm5yZ/"
    "pub?output=csv"
)


def _population(value: object) -> Population:
    mapping = {
        "LV": Population.LIKELY_VOTERS,
        "RV": Population.REGISTERED_VOTERS,
        "V": Population.VOTERS,
        "A": Population.ADULTS,
    }
    return mapping.get(str(value).upper(), Population.UNKNOWN)


def _partisan(value: object) -> str | None:
    text = str(value).upper()
    if text.startswith("DEM"):
        return "D"
    if text.startswith("REP"):
        return "R"
    return None


def fetch_silver_generic_ballot(
    *,
    cycle: int = 2026,
    election_date: date = date(2026, 11, 3),
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch one preferred all-voter version of each published national poll."""
    client = client or CachedHTTPClient()
    payload = client.get(SILVER_GENERIC_CSV_URL, refresh=refresh)
    frame = pd.read_csv(BytesIO(payload))
    required = {
        "subgroup",
        "pollster",
        "sponsors",
        "enddate",
        "samplesize",
        "population",
        "dem",
        "rep",
        "url",
        "partisan",
        "poll_id",
        "question_id",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Silver generic-ballot CSV missing columns: {sorted(missing)}")

    frame = frame[frame["subgroup"].astype(str).str.casefold() == "all polls"].copy()
    frame["end_date"] = pd.to_datetime(frame["enddate"], errors="coerce")
    frame = frame[
        (frame["end_date"].dt.year == cycle) & frame["dem"].notna() & frame["rep"].notna()
    ].copy()
    # Some pollsters publish adult, registered-voter and likely-voter versions of the
    # same poll. Keep the version closest to the eventual electorate.
    population_priority = {"LV": 0, "RV": 1, "V": 2, "A": 3}
    frame["population_priority"] = (
        frame["population"].astype(str).str.upper().map(population_priority).fillna(4)
    )
    frame = (
        frame.sort_values(
            ["poll_id", "population_priority", "samplesize"],
            ascending=[True, True, False],
        )
        .drop_duplicates("poll_id", keep="first")
        .drop(columns="population_priority")
    )

    fetched_at = datetime.now(UTC)
    records: list[dict[str, object]] = []
    for row in frame.itertuples():
        sponsor = "" if pd.isna(row.sponsors) else str(row.sponsors).strip()
        pollster = str(row.pollster).strip()
        methodology = "Silver Bulletin public polling-average input CSV"
        if sponsor:
            methodology += f"; sponsor={sponsor}"
        fingerprint = f"{row.poll_id}|{row.question_id}|{row.end_date.date().isoformat()}"
        sample_size = None if pd.isna(row.samplesize) else int(row.samplesize)
        source_url = (
            SILVER_GENERIC_CSV_URL if pd.isna(row.url) or not str(row.url).strip() else str(row.url)
        )
        record = PollRecord(
            source="silver_bulletin",
            source_id=hashlib.sha256(fingerprint.encode()).hexdigest()[:20],
            race_id=f"{cycle}:generic_ballot:US:democratic:republican",
            cycle=cycle,
            office=Office.GENERIC_BALLOT,
            location="US",
            pollster=pollster,
            end_date=row.end_date.date(),
            election_date=election_date,
            sample_size=sample_size,
            population=_population(row.population),
            methodology=methodology,
            partisan=_partisan(row.partisan),
            dem_candidate="Democratic",
            rep_candidate="Republican",
            dem_pct=float(row.dem),
            rep_pct=float(row.rep),
            source_url=source_url,
            fetched_at=fetched_at,
        )
        records.append(record.model_dump(mode="json"))
    result = pd.DataFrame.from_records(records)
    if result.empty:
        raise ValueError("Silver generic-ballot source normalized to zero records")
    return result.sort_values("end_date", ascending=False).reset_index(drop=True)
