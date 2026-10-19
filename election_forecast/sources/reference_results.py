"""Reference election results from public FiveThirtyEight and MIT repositories."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO, StringIO

import pandas as pd

from ..http_cache import CachedHTTPClient

FTE_RESULTS_BASE = "https://raw.githubusercontent.com/fivethirtyeight/election-results/main"
FTE_RESULT_FILES = {
    "president": f"{FTE_RESULTS_BASE}/election_results_presidential.csv",
    "senate": f"{FTE_RESULTS_BASE}/election_results_senate.csv",
    "house": f"{FTE_RESULTS_BASE}/election_results_house.csv",
    "governor": f"{FTE_RESULTS_BASE}/election_results_gubernatorial.csv",
}
FTE_GENERIC_HOUSE_URL = f"{FTE_RESULTS_BASE}/election_results_generichouse.csv"
HOUSE_PARTY_DIVISIONS_URL = "https://history.house.gov/Institution/Party-Divisions/Party-Divisions/"

MIT_2024_FILES = {
    "president": (
        "https://raw.githubusercontent.com/MEDSL/2024-elections-official/"
        "main/2024-president-state.csv"
    ),
    "senate": (
        "https://raw.githubusercontent.com/MEDSL/2024-elections-official/main/2024-senate-state.csv"
    ),
}


def _result_location(row: pd.Series, office: str) -> str | None:
    state = "US" if pd.isna(row.get("state_abbrev")) else str(row["state_abbrev"])
    presidential_districts = {
        "M1": "ME-01",
        "M2": "ME-02",
        "N1": "NE-01",
        "N2": "NE-02",
        "N3": "NE-03",
    }
    if office == "president" and state in presidential_districts:
        return presidential_districts[state]
    seat = str(row.get("office_seat_name", ""))
    if office == "president" and state in {"ME", "NE"}:
        match = re.search(r"(\d+)", seat)
        if match:
            return f"{state}-{int(match.group(1)):02d}"
    if office != "house":
        return state
    match = re.search(r"(\d+)", seat)
    if match:
        return f"{state}-{int(match.group(1)):02d}"
    return f"{state}-AL" if state not in {"US", "NAN"} else None


def fetch_fte_reference_results(
    *, cycle: int = 2024, refresh: bool = False, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    """Normalize major-party general-election results for outcome attachment."""
    client = client or CachedHTTPClient()
    rows: list[pd.DataFrame] = []
    for office, url in FTE_RESULT_FILES.items():
        raw = pd.read_csv(BytesIO(client.get(url, refresh=refresh)), low_memory=False)
        raw = raw[
            (raw["cycle"] == cycle)
            & (raw["stage"].astype(str).str.lower() == "general")
            & raw["ballot_party"].isin(["DEM", "REP"])
        ].copy()
        # A same-state special and regular Senate race needs a richer key than our current
        # state-only poll schema. Keep the regular contest and report this limitation.
        if office == "senate":
            raw = raw[~raw["special"].fillna(False).astype(bool)].copy()
        selected: list[pd.DataFrame] = []
        for _, race in raw.groupby("race_id"):
            rounds = pd.to_numeric(race["ranked_choice_round"], errors="coerce")
            if rounds.notna().any():
                race = race[rounds == rounds.max()].copy()
            selected.append(
                race.sort_values("percent").drop_duplicates("ballot_party", keep="last")
            )
        if not selected:
            continue
        paired = pd.concat(selected, ignore_index=True)
        dem = paired[paired["ballot_party"] == "DEM"].copy()
        rep = paired[paired["ballot_party"] == "REP"][
            ["race_id", "candidate_name", "percent", "votes"]
        ].rename(
            columns={
                "candidate_name": "rep_candidate",
                "percent": "rep_pct",
                "votes": "rep_votes",
            }
        )
        paired = dem.merge(rep, on="race_id", how="inner")
        paired["office"] = office
        paired["location"] = paired.apply(
            lambda row, current_office=office: _result_location(row, current_office), axis=1
        )
        paired = paired.dropna(subset=["location", "percent", "rep_pct"])
        paired["actual_margin"] = paired["percent"].astype(float) - paired["rep_pct"].astype(float)
        paired["dem_candidate"] = paired["candidate_name"]
        paired["dem_votes"] = pd.to_numeric(paired["votes"], errors="coerce")
        paired["rep_votes"] = pd.to_numeric(paired["rep_votes"], errors="coerce")
        paired["cycle"] = cycle
        paired["election_date"] = "2024-11-05"
        paired["reference_source"] = "fivethirtyeight_election_results"
        paired["source_url"] = url
        rows.append(paired)
    result = pd.concat(rows, ignore_index=True)
    result["fetched_at"] = datetime.now(UTC).isoformat()
    columns = [
        "cycle",
        "office",
        "location",
        "election_date",
        "actual_margin",
        "dem_candidate",
        "rep_candidate",
        "dem_votes",
        "rep_votes",
        "reference_source",
        "source_url",
        "fetched_at",
    ]
    return result[columns].drop_duplicates(["cycle", "office", "location"])


def fetch_mit_2024_results(
    *, refresh: bool = False, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    """Normalize 2024 MEDSL state results for independent outcome cross-checks."""
    client = client or CachedHTTPClient()
    rows: list[dict[str, object]] = []
    for office, url in MIT_2024_FILES.items():
        raw = pd.read_csv(BytesIO(client.get(url, refresh=refresh)), low_memory=False)
        raw = raw[
            (raw["mode"] == "TOTAL")
            & (raw["stage"] == "GEN")
            & raw["party_simplified"].isin(["DEMOCRAT", "REPUBLICAN"])
        ].copy()
        if office == "senate":
            raw = raw[~raw["special"].fillna(False).astype(bool)].copy()
        national_dem = 0.0
        national_rep = 0.0
        national_total = 0.0
        for location, race in raw.groupby("state_po"):
            party = race.groupby("party_simplified", as_index=False)["votes"].sum()
            if set(party["party_simplified"]) != {"DEMOCRAT", "REPUBLICAN"}:
                continue
            dem_votes = float(party.loc[party["party_simplified"] == "DEMOCRAT", "votes"].iloc[0])
            rep_votes = float(party.loc[party["party_simplified"] == "REPUBLICAN", "votes"].iloc[0])
            total_votes = float(race["totalvotes"].max())
            national_dem += dem_votes
            national_rep += rep_votes
            national_total += total_votes
            rows.append(
                {
                    "cycle": 2024,
                    "office": office,
                    "location": str(location),
                    "election_date": "2024-11-05",
                    "actual_margin": 100.0 * (dem_votes - rep_votes) / total_votes,
                    "dem_votes": dem_votes,
                    "rep_votes": rep_votes,
                    "reference_source": "mit_medsl_2024",
                    "source_url": url,
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
            )
        if office == "president" and national_total > 0:
            rows.append(
                {
                    "cycle": 2024,
                    "office": office,
                    "location": "US",
                    "election_date": "2024-11-05",
                    "actual_margin": 100.0 * (national_dem - national_rep) / national_total,
                    "dem_votes": national_dem,
                    "rep_votes": national_rep,
                    "reference_source": "mit_medsl_2024_aggregated",
                    "source_url": url,
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
            )
    return pd.DataFrame.from_records(rows)


def _leading_integer(value: object) -> int | None:
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group()) if match else None


def _house_2024_major_party_margin(raw: pd.DataFrame) -> float:
    """Aggregate fusion ballot lines once per candidate before taking the vote margin."""
    frame = raw[
        (raw["cycle"] == 2024)
        & (raw["stage"].astype(str).str.lower() == "general")
        & ~raw["special"].fillna(False).astype(bool)
        & raw["state_abbrev"].ne("PR")
    ].copy()
    frame["is_dem"] = frame["ballot_party"].eq("DEM")
    frame["is_rep"] = frame["ballot_party"].eq("REP")
    candidates = (
        frame.groupby(["race_id", "candidate_id"], dropna=False)
        .agg(
            votes=("votes", "sum"),
            is_dem=("is_dem", "max"),
            is_rep=("is_rep", "max"),
        )
        .reset_index()
    )
    dem_votes = float(candidates.loc[candidates["is_dem"], "votes"].sum())
    rep_votes = float(candidates.loc[candidates["is_rep"], "votes"].sum())
    if dem_votes <= 0 or rep_votes <= 0:
        raise ValueError("could not aggregate 2024 major-party House votes")
    return 100.0 * (dem_votes - rep_votes) / (dem_votes + rep_votes)


def _normalize_house_party_divisions(table: pd.DataFrame) -> pd.DataFrame:
    """Normalize the official House historian table for the modern two-party era."""
    if len(table.columns) < 4:
        raise ValueError("House party-division table has fewer than four columns")
    congress_col, seats_col, dem_col, rep_col = table.columns[:4]
    output = pd.DataFrame(
        {
            "congress": table[congress_col].map(_leading_integer),
            "house_seats": table[seats_col].map(_leading_integer),
            "dem_seats": table[dem_col].map(_leading_integer),
            "rep_seats": table[rep_col].map(_leading_integer),
        }
    ).dropna()
    output = output.astype(int)
    output["cycle"] = 1788 + 2 * (output["congress"] - 1)
    return output[output["cycle"] >= 2000].copy()


def fetch_house_national_history(
    *, refresh: bool = False, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    """Fetch auditable national House vote margins and official party seat totals."""
    client = client or CachedHTTPClient()
    generic = pd.read_csv(
        BytesIO(client.get(FTE_GENERIC_HOUSE_URL, refresh=refresh)), low_memory=False
    )
    major = generic[generic["ballot_party"].isin(["DEM", "REP"])].copy()
    vote = major.pivot_table(index="cycle", columns="ballot_party", values="percent", aggfunc="sum")
    vote["generic_house_margin"] = vote["DEM"] - vote["REP"]

    house_results = pd.read_csv(
        BytesIO(client.get(FTE_RESULT_FILES["house"], refresh=refresh)), low_memory=False
    )
    vote.loc[2024, "generic_house_margin"] = _house_2024_major_party_margin(house_results)

    historian_html = client.get(HOUSE_PARTY_DIVISIONS_URL, refresh=refresh).decode(
        "utf-8", errors="replace"
    )
    tables = pd.read_html(StringIO(historian_html))
    if not tables:
        raise ValueError("House historian page contained no tables")
    seats = _normalize_house_party_divisions(tables[0])
    result = seats.merge(
        vote[["generic_house_margin"]], left_on="cycle", right_index=True, how="inner"
    )
    result["vote_source_url"] = FTE_GENERIC_HOUSE_URL
    result.loc[result["cycle"] == 2024, "vote_source_url"] = FTE_RESULT_FILES["house"]
    result["seat_source_url"] = HOUSE_PARTY_DIVISIONS_URL
    result["fetched_at"] = datetime.now(UTC).isoformat()
    return (
        result[
            [
                "cycle",
                "congress",
                "house_seats",
                "dem_seats",
                "rep_seats",
                "generic_house_margin",
                "vote_source_url",
                "seat_source_url",
                "fetched_at",
            ]
        ]
        .sort_values("cycle")
        .reset_index(drop=True)
    )
