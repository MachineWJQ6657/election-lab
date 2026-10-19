"""Official FEC candidate master-file adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pandas as pd

from ..http_cache import CachedHTTPClient

FEC_CANDIDATE_URL = "https://www.fec.gov/files/bulk-downloads/2026/cn26.zip"
FEC_COLUMNS = [
    "candidate_id",
    "candidate_name",
    "party",
    "election_year",
    "candidate_state",
    "office",
    "district",
    "incumbent_challenger",
    "candidate_status",
    "principal_committee_id",
    "address_1",
    "address_2",
    "city",
    "state",
    "zip",
]


def fetch_fec_candidates(
    *, refresh: bool = False, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    """Fetch candidates who filed federal Statements of Candidacy for 2026."""
    client = client or CachedHTTPClient()
    payload = client.get(FEC_CANDIDATE_URL, refresh=refresh, ttl_hours=24)
    with ZipFile(BytesIO(payload)) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".txt"))
        with archive.open(member) as stream:
            frame = pd.read_csv(
                stream,
                sep="|",
                names=FEC_COLUMNS,
                dtype=str,
                encoding="latin-1",
                keep_default_na=False,
            )
    frame = frame[frame["election_year"] == "2026"].copy()
    frame = frame[frame["office"].isin(["H", "S", "P"])].copy()
    office_map = {"H": "house", "S": "senate", "P": "president"}
    frame["office_name"] = frame["office"].map(office_map)
    frame["location"] = frame["candidate_state"]
    house = frame["office"] == "H"
    district = pd.to_numeric(frame["district"], errors="coerce").fillna(0).astype(int)
    frame.loc[house, "location"] = (
        frame.loc[house, "candidate_state"]
        + "-"
        + district.loc[house].map(lambda value: "AL" if value == 0 else f"{value:02d}")
    )
    frame.loc[frame["office"] == "P", "location"] = "US"
    frame["source_url"] = FEC_CANDIDATE_URL
    frame["fetched_at"] = datetime.now(UTC).isoformat()
    return frame.reset_index(drop=True)
