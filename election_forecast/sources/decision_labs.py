"""Decision Labs CC BY 4.0 current-poll adapter."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime

import pandas as pd

from ..http_cache import CachedHTTPClient
from ..schemas import Office, PollRecord, Population

DECISION_LABS_POLLS_URL = "https://decisionlabs.ai/api/export/polls"


def _public_source_url(value: object) -> str:
    """Normalize upstream evidence links and reject pasted local-file paths."""
    text = str(value or "").strip()
    starts = [match.start() for match in re.finditer(r"https?://", text, re.IGNORECASE)]
    return text[starts[-1] :].strip() if starts else DECISION_LABS_POLLS_URL


def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _matches_candidate(candidate_slug: str, candidate_name: str) -> bool:
    expected = _slug(candidate_name)
    if candidate_slug == expected:
        return True
    actual_parts = candidate_slug.split("-")
    expected_parts = expected.split("-")
    return (
        len(actual_parts) >= 2
        and len(expected_parts) >= 2
        and actual_parts[0] == expected_parts[0]
        and actual_parts[-1] == expected_parts[-1]
    )


def _population(value: object) -> Population:
    mapping = {
        "likely_voters": Population.LIKELY_VOTERS,
        "registered_voters": Population.REGISTERED_VOTERS,
        "voters": Population.VOTERS,
        "adults": Population.ADULTS,
    }
    return mapping.get(str(value).lower(), Population.UNKNOWN)


def fetch_decision_labs_polls(
    catalog: pd.DataFrame,
    *,
    election_date: date = date(2026, 11, 3),
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Keep only polls that match both major-party candidates in the current catalog."""
    client = client or CachedHTTPClient()
    payload = client.get(DECISION_LABS_POLLS_URL, refresh=refresh)
    data = json.loads(payload)
    catalog_lookup = {(str(row.office), str(row.location)): row for row in catalog.itertuples()}
    records: list[dict[str, object]] = []
    pattern = re.compile(r"^(?P<state>[a-z]{2})-(?P<office>sen|gov)-2026$")
    office_map = {"sen": Office.SENATE, "gov": Office.GOVERNOR}
    for poll in data.get("polls", []):
        match = pattern.fullmatch(str(poll.get("raceId", "")))
        if not match:
            continue
        office = office_map[match.group("office")]
        location = match.group("state").upper()
        catalog_row = catalog_lookup.get((office.value, location))
        if catalog_row is None:
            continue
        results = poll.get("results", {})
        dem_keys = [key for key in results if _matches_candidate(key, catalog_row.dem_candidate)]
        rep_keys = [key for key in results if _matches_candidate(key, catalog_row.rep_candidate)]
        if len(dem_keys) != 1 or len(rep_keys) != 1:
            continue
        dem_key, rep_key = dem_keys[0], rep_keys[0]
        fingerprint = "|".join(
            [
                str(poll.get("raceId")),
                str(poll.get("date")),
                str(poll.get("pollster")),
                dem_key,
                rep_key,
                str(results[dem_key]),
                str(results[rep_key]),
            ]
        )
        sample_size = poll.get("sampleSize")
        record = PollRecord(
            source="decision_labs",
            source_id=hashlib.sha256(fingerprint.encode()).hexdigest()[:20],
            race_id=(
                f"2026:{office.value}:{location}:{_slug(catalog_row.dem_candidate)}:"
                f"{_slug(catalog_row.rep_candidate)}"
            ),
            cycle=2026,
            office=office,
            location=location,
            pollster=str(poll.get("pollster", "Unknown")),
            end_date=date.fromisoformat(str(poll["date"])),
            election_date=election_date,
            sample_size=int(sample_size) if sample_size else None,
            population=_population(poll.get("population")),
            partisan=None if not poll.get("partisan") else str(poll["partisan"]),
            pollster_grade=None if poll.get("grade") == "unrated" else str(poll.get("grade")),
            dem_candidate=str(catalog_row.dem_candidate),
            rep_candidate=str(catalog_row.rep_candidate),
            dem_pct=float(results[dem_key]),
            rep_pct=float(results[rep_key]),
            source_url=_public_source_url(poll.get("sourceUrl")),
            fetched_at=datetime.now(UTC),
        )
        records.append(record.model_dump(mode="json"))
    return pd.DataFrame.from_records(records)
