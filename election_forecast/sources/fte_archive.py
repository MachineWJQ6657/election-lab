"""Full-cycle 2018-2024 polling snapshots recovered from Internet Archive."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO

import pandas as pd

from ..http_cache import CachedHTTPClient
from ..names import candidate_key

ARCHIVE_PREFIX = (
    "https://web.archive.org/web/20241106000000id_/"
    "https://projects.fivethirtyeight.com/polls-page/data"
)

ARCHIVE_FILES = {
    "president": f"{ARCHIVE_PREFIX}/president_polls_historical.csv",
    "senate": f"{ARCHIVE_PREFIX}/senate_polls_historical.csv",
    "house": f"{ARCHIVE_PREFIX}/house_polls_historical.csv",
    "governor": f"{ARCHIVE_PREFIX}/governor_polls_historical.csv",
}

CURRENT_2024_FILES = {
    "president": f"{ARCHIVE_PREFIX}/president_polls.csv",
    "senate": f"{ARCHIVE_PREFIX}/senate_polls.csv",
    "house": f"{ARCHIVE_PREFIX}/house_polls.csv",
    "governor": f"{ARCHIVE_PREFIX}/governor_polls.csv",
}

GENERIC_FILES = (
    f"{ARCHIVE_PREFIX}/generic_ballot_polls_historical.csv",
    f"{ARCHIVE_PREFIX}/generic_ballot_polls.csv",
)

OFFICE_MAP = {
    "U.S. President": "president",
    "U.S. Senate": "senate",
    "U.S. House": "house",
    "Governor": "governor",
}

STATE_ABBREVIATIONS = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


def _location(state: object, office: str, seat_number: object) -> str | None:
    if pd.isna(state) or not str(state).strip():
        return "US" if office == "president" else None
    state_text = str(state).strip()
    if state_text in STATE_ABBREVIATIONS:
        abbreviation = STATE_ABBREVIATIONS[state_text]
    elif re.fullmatch(r"[A-Z]{2}", state_text):
        abbreviation = state_text
    else:
        district_match = re.search(r"([A-Za-z ]+)\s+(?:CD|District)[ -]?(\d+)", state_text)
        if not district_match:
            return None
        abbreviation = STATE_ABBREVIATIONS.get(district_match.group(1).strip())
        if not abbreviation:
            return None
        return f"{abbreviation}-{int(district_match.group(2)):02d}"
    if office == "house" and not pd.isna(seat_number):
        return f"{abbreviation}-{int(float(seat_number)):02d}"
    return abbreviation


def _population(value: object) -> str:
    normalized = str(value).lower().strip()
    return normalized if normalized in {"lv", "rv", "v", "a"} else "unknown"


def _outcome_lookup(outcomes: pd.DataFrame) -> pd.DataFrame:
    frame = outcomes.copy()
    frame["election_date"] = pd.to_datetime(frame["election_date"]).dt.date.astype(str)
    frame = frame.dropna(subset=["actual_margin"]).copy()
    frame["outcome_dem_candidate"] = frame.get("dem_candidate")
    frame["outcome_rep_candidate"] = frame.get("rep_candidate")
    return frame.groupby(["cycle", "office", "location", "election_date"], as_index=False).agg(
        actual_margin=("actual_margin", "median"),
        outcome_dem_candidate=("outcome_dem_candidate", "first"),
        outcome_rep_candidate=("outcome_rep_candidate", "first"),
    )


def _surname(value: object) -> str:
    return candidate_key(value)


def normalize_generic_archive(raw: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Normalize national wide-format questions, choosing one population per wave.

    created_at is retained as archive metadata, NOT assumed to be the original
    release time: that field also contains retrospective backfills.
    """
    frame = raw.copy()
    national = frame["state"].fillna("").astype(str).str.strip().isin(["", "US", "National"])
    frame = frame.loc[national & frame["stage"].astype(str).str.lower().eq("general")].copy()
    for column in ("dem", "rep", "sample_size", "cycle", "question_id", "poll_id"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("end_date", "election_date"):
        frame[column] = pd.to_datetime(frame[column], format="mixed", errors="coerce")
    frame = frame.dropna(
        subset=["dem", "rep", "cycle", "question_id", "poll_id", "end_date", "election_date"]
    )
    frame = frame.loc[
        frame["dem"].between(0, 100)
        & frame["rep"].between(0, 100)
        & (frame["dem"] + frame["rep"]).between(1, 100.5)
        & frame["end_date"].le(frame["election_date"])
    ].copy()
    frame["population"] = frame["population"].map(_population)
    frame["population_rank"] = frame["population"].map(
        {"lv": 0, "rv": 1, "v": 2, "a": 3, "unknown": 4}
    )
    frame = frame.sort_values(
        ["population_rank", "sample_size", "question_id"], ascending=[True, False, False]
    ).drop_duplicates(["cycle", "poll_id", "end_date"])
    frame["cycle"] = frame["cycle"].astype(int)
    lookup = outcomes[["cycle", "generic_house_margin"]].dropna().drop_duplicates("cycle")
    frame = frame.merge(lookup, on="cycle", how="inner", validate="many_to_one")
    frame["office"], frame["location"] = "generic_ballot", "US"
    frame["source"] = "fivethirtyeight_wayback_generic"
    frame["source_id"] = "generic:" + frame["question_id"].astype(int).astype(str)
    frame["race_id"] = frame["cycle"].astype(str) + ":generic_ballot:US"
    frame["dem_candidate"], frame["rep_candidate"] = "Democratic", "Republican"
    frame["dem_pct"], frame["rep_pct"] = frame["dem"], frame["rep"]
    frame["margin"] = frame["dem"] - frame["rep"]
    frame["actual_margin"] = frame["generic_house_margin"]
    frame["days_to_election"] = (frame["election_date"] - frame["end_date"]).dt.days
    for column in ("end_date", "election_date"):
        frame[column] = frame[column].dt.date.astype(str)
    frame.loc[frame["sample_size"].lt(1), "sample_size"] = float("nan")
    frame["source_url"] = frame["url"].where(
        frame["url"].fillna("").str.startswith("https://"), frame["archive_url"]
    )
    frame["source_created_at"] = frame.get("created_at")
    frame["fetched_at"] = datetime.now(UTC).isoformat()
    columns = [
        "source",
        "source_id",
        "race_id",
        "cycle",
        "office",
        "location",
        "pollster",
        "end_date",
        "election_date",
        "sample_size",
        "population",
        "methodology",
        "partisan",
        "dem_candidate",
        "rep_candidate",
        "dem_pct",
        "rep_pct",
        "actual_margin",
        "source_url",
        "archive_url",
        "source_created_at",
        "fetched_at",
        "margin",
        "days_to_election",
    ]
    return frame[columns].sort_values(["cycle", "end_date", "source_id"]).reset_index(drop=True)


def fetch_fte_generic_archive(
    outcomes: pd.DataFrame,
    *,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    client = client or CachedHTTPClient()
    frames = []
    for url in GENERIC_FILES:
        frame = pd.read_csv(
            BytesIO(client.get(url, refresh=refresh, ttl_hours=24 * 365)), low_memory=False
        )
        frame["archive_url"] = url
        frames.append(frame)
    result = normalize_generic_archive(pd.concat(frames, ignore_index=True), outcomes)
    if result.empty:
        raise ValueError("Generic-ballot archive normalized to zero records")
    return result


def fetch_fte_full_archive(
    outcomes: pd.DataFrame,
    *,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch full-cycle polls and attach outcomes from the ratings history.

    The Internet Archive is used because the original 538 endpoints began
    redirecting after the publication closed. Snapshot URLs are immutable.
    """
    client = client or CachedHTTPClient()
    raw_frames = []
    all_files = list(ARCHIVE_FILES.values()) + list(CURRENT_2024_FILES.values())
    for url in all_files:
        payload = client.get(url, refresh=refresh, ttl_hours=24 * 365)
        raw_frames.append(pd.read_csv(BytesIO(payload), low_memory=False))
    raw = pd.concat(raw_frames, ignore_index=True)
    raw = raw[raw["office_type"].isin(OFFICE_MAP)].copy()
    raw = raw[raw["party"].isin(["DEM", "REP"])].copy()
    raw = raw[raw["stage"].astype(str).str.lower().isin(["general", "runoff"])].copy()
    raw["pct"] = pd.to_numeric(raw["pct"], errors="coerce")
    raw = raw.dropna(subset=["question_id", "pct", "end_date", "election_date"])

    # Keep the leading candidate of each major party for multi-candidate polls.
    raw = raw.sort_values("pct").drop_duplicates(["question_id", "party"], keep="last")
    dem = raw[raw["party"] == "DEM"].copy()
    rep = raw[raw["party"] == "REP"][["question_id", "candidate_name", "answer", "pct"]].copy()
    rep = rep.rename(
        columns={
            "candidate_name": "rep_candidate",
            "answer": "rep_answer",
            "pct": "rep_pct",
        }
    )
    pairs = dem.merge(rep, on="question_id", how="inner")
    pairs["office"] = pairs["office_type"].map(OFFICE_MAP)
    pairs["location"] = pairs.apply(
        lambda row: _location(row["state"], row["office"], row["seat_number"]), axis=1
    )
    pairs = pairs.dropna(subset=["location"])
    pairs["end_date"] = pd.to_datetime(pairs["end_date"], format="mixed").dt.date.astype(str)
    pairs["election_date"] = pd.to_datetime(pairs["election_date"], format="mixed").dt.date.astype(
        str
    )
    pairs["dem_candidate"] = pairs["candidate_name"].fillna(pairs["answer"])
    pairs["rep_candidate"] = pairs["rep_candidate"].fillna(pairs["rep_answer"])
    pairs["sample_size"] = pd.to_numeric(pairs["sample_size"], errors="coerce")
    pairs.loc[pairs["sample_size"] < 1, "sample_size"] = pd.NA
    pairs["transparency_score"] = pd.to_numeric(pairs["transparency_score"], errors="coerce")
    pairs["cycle"] = pairs["cycle"].astype(int)

    outcome_lookup = _outcome_lookup(outcomes)
    pairs = pairs[pairs["cycle"].isin(outcome_lookup["cycle"].unique())].copy()
    pairs = pairs.merge(
        outcome_lookup,
        on=["cycle", "office", "location", "election_date"],
        how="left",
    )
    final_candidate = (
        (pairs["cycle"] != 2024)
        | pairs["outcome_dem_candidate"].isna()
        | (
            (pairs["dem_candidate"].map(_surname) == pairs["outcome_dem_candidate"].map(_surname))
            & (pairs["rep_candidate"].map(_surname) == pairs["outcome_rep_candidate"].map(_surname))
        )
    )
    pairs = pairs[final_candidate].copy()
    fetched_at = datetime.now(UTC).isoformat()
    pairs["source"] = "fivethirtyeight_wayback_full_cycle"
    pairs["source_id"] = "archive:" + pairs["question_id"].astype(int).astype(str)
    pairs["race_id"] = (
        pairs["cycle"].astype(str) + ":archive:" + pairs["race_id"].astype(int).astype(str)
    )
    pairs["population"] = pairs["population"].map(_population)
    pairs["dem_pct"] = pairs["pct"].astype(float)
    pairs["margin"] = pairs["dem_pct"] - pairs["rep_pct"].astype(float)
    pairs["days_to_election"] = (
        pd.to_datetime(pairs["election_date"]) - pd.to_datetime(pairs["end_date"])
    ).dt.days
    pairs["source_url"] = pairs.apply(
        lambda row: (
            CURRENT_2024_FILES[str(row["office"])]
            if int(row["cycle"]) == 2024
            else ARCHIVE_FILES[str(row["office"])]
        ),
        axis=1,
    )
    pairs["fetched_at"] = fetched_at

    columns = [
        "source",
        "source_id",
        "race_id",
        "cycle",
        "office",
        "location",
        "pollster",
        "end_date",
        "election_date",
        "sample_size",
        "population",
        "methodology",
        "partisan",
        "transparency_score",
        "dem_candidate",
        "rep_candidate",
        "dem_pct",
        "rep_pct",
        "actual_margin",
        "source_url",
        "fetched_at",
        "margin",
        "days_to_election",
    ]
    result = pairs[columns].drop_duplicates(["source", "source_id"], keep="last")
    if result.empty:
        raise ValueError("full-cycle archive normalized to zero records")
    return result.sort_values(["cycle", "office", "race_id", "end_date"]).reset_index(drop=True)
