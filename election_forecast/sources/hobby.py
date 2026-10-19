"""Strict parsers for identified University of Houston primary polling releases."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from ..http_cache import CachedHTTPClient
from ..schemas import Office, PollRecord, Population

STATEWIDE_URL = "https://www.uh.edu/hobby/texas2026/index.php"
DISTRICT_URL = "https://www.uh.edu/hobby/congress2026/index.php"
LOGGER = logging.getLogger(__name__)


def _match(pattern: str, text: str) -> re.Match:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Hobby release schema changed: {pattern}")
    return match


def parse_hobby_release(payload: bytes, *, url: str, as_of: date) -> pd.DataFrame:
    text = " ".join(BeautifulSoup(payload, "html.parser").get_text(" ", strip=True).split())
    release = _match(r"Media Release (\w+ \d{1,2}, 2026)", text)[1]
    publication = pd.to_datetime(release).date()
    if publication > as_of:
        raise ValueError("Hobby release is not available at the requested date")
    period = _match(
        r"(?:between|fielded between) (Oct(?:ober)?\.?) (\d{1,2}) and "
        r"(?:Oct(?:ober)?\.? )?(\d{1,2}), 2026",
        text,
    )
    start, end = date(2026, 10, int(period[2])), date(2026, 10, int(period[3]))
    if not start <= end <= publication:
        raise ValueError("Hobby fieldwork dates are inconsistent")
    sample = int(_match(r"overall sample population of ([\d,]+)", text)[1].replace(",", ""))
    rows = []
    if url == STATEWIDE_URL:
        _match(r"online statewide survey of likely voters in Texas", text)
        senate = _match(
            r"Democrat James Talarico \(([\d.]+)%\).*?"
            r"Republican challenger Ken Paxton \(([\d.]+)%\)",
            text,
        )
        governor = _match(
            r"Republican incumbent Greg Abbott \(([\d.]+)%\).*?"
            r"Democrat Gina Hinojosa \(([\d.]+)%\)",
            text,
        )
        rows = [
            (
                Office.SENATE,
                "TX",
                "James Talarico",
                "Ken Paxton",
                float(senate[1]),
                float(senate[2]),
            ),
            (
                Office.GOVERNOR,
                "TX",
                "Gina Hinojosa",
                "Greg Abbott",
                float(governor[2]),
                float(governor[1]),
            ),
        ]
    elif url == DISTRICT_URL:
        _match(r"likely voters in TX-9", text)
        house = _match(
            r"Republican Alex Mealer is leading Democratic challenger Leticia Gutierrez.*?"
            r"support from ([\d.]+)% of likely voters, compared with ([\d.]+)% for Gutierrez",
            text,
        )
        rows = [
            (
                Office.HOUSE,
                "TX-09",
                "Leticia Gutierrez",
                "Alex Mealer",
                float(house[2]),
                float(house[1]),
            )
        ]
        # The Senate/Governor cross-tabs here are district-only, NEVER statewide polls.
    else:
        raise ValueError("Unsupported primary release URL")
    records = []
    for office, location, dem, rep, dem_pct, rep_pct in rows:
        if dem_pct + rep_pct > 100.5:
            raise ValueError("Hobby candidate percentages do not reconcile")
        record = PollRecord(
            source="uh_hobby_primary",
            source_id=f"hobby:{office}:{location}:{end}",
            race_id=f"2026:{office}:{location}",
            cycle=2026,
            office=office,
            location=location,
            pollster="University of Houston Hobby School of Public Affairs",
            end_date=end,
            election_date=date(2026, 11, 3),
            sample_size=sample,
            population=Population.LIKELY_VOTERS,
            methodology="SMS invitation to online survey; English and Spanish",
            dem_candidate=dem,
            rep_candidate=rep,
            dem_pct=dem_pct,
            rep_pct=rep_pct,
            source_url=url,
        ).model_dump(mode="json")
        record.update(
            start_date=start.isoformat(),
            publication_date=publication.isoformat(),
            primary_source_verified=True,
            source_content_sha256=hashlib.sha256(payload).hexdigest(),
            sample_size_basis="published likely-voter sample",
            survey_scope="statewide" if location == "TX" else "congressional district",
            district_boundary_changed=location == "TX-09",
        )
        records.append(record)
    return pd.DataFrame(records)


def fetch_hobby_polls(
    *, refresh: bool = False, as_of: date | None = None, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    client = client or CachedHTTPClient()
    as_of = as_of or date.today()
    frames = []
    for url in (STATEWIDE_URL, DISTRICT_URL):
        try:
            frames.append(
                parse_hobby_release(client.get(url, refresh=refresh), url=url, as_of=as_of)
            )
        except (httpx.HTTPError, ValueError, OSError) as exc:
            LOGGER.warning("Primary Hobby release excluded (%s): %s", url, exc)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
