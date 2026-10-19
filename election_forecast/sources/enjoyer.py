"""Identified Michigan publisher release; never import state-House generic polls."""

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

RELEASE_URL = "https://enjoyer.com/michigan-poll-fall-2026/"
LOGGER = logging.getLogger(__name__)


def parse_enjoyer_release(payload: bytes, *, as_of: date) -> pd.DataFrame:
    soup = BeautifulSoup(payload, "html.parser")
    published = soup.find("meta", property="article:published_time")
    if published is None or not published.get("content"):
        raise ValueError("Michigan release lacks an identifiable publication date")
    publication = pd.to_datetime(str(published["content"]), utc=True).date()
    if publication > as_of:
        raise ValueError("Michigan release is not available at the requested date")
    text = " ".join(soup.get_text(" ", strip=True).split())
    fieldwork = re.search(r"from Sept\. (\d{1,2})[–—-](\d{1,2}), 2026", text)
    sample = re.search(r"among ([\d,]+) likely 2026 general election voters in Michigan", text)
    if fieldwork is None or sample is None:
        raise ValueError("Michigan release fieldwork/sample schema changed")
    if "conducted by Cygnal in conjunction with Beacon Research" not in text:
        raise ValueError("Michigan release fieldwork organizations changed")
    start = date(2026, 9, int(fieldwork[1]))
    end = date(2026, 9, int(fieldwork[2]))
    if not start <= end <= publication:
        raise ValueError("Michigan release fieldwork dates are inconsistent")
    records = []
    for office, heading_text, caption, dem, rep in (
        (Office.GOVERNOR, "Governor", "Governor", "Jocelyn Benson", "John James"),
        (Office.SENATE, r"U\.S\. Senate", "U.S. Senate", "Abdul El-Sayed", "Mike Rogers"),
    ):
        heading = next(
            (
                item
                for item in soup.find_all("h3")
                if re.fullmatch(rf"\s*\d\s*\.\s*{heading_text}\s*", item.get_text(" ", strip=True))
            ),
            None,
        )
        table = heading.find_next("table") if heading else None
        table_caption = table.find("caption") if table else None
        if table is None or table_caption is None or table_caption.get_text(strip=True) != caption:
            raise ValueError(f"Michigan release lacks a scoped {caption} table")
        answers = {}
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) in (2, 3):
                # The responsive page inserts a presentation-only bar column.
                answers[cells[0].get_text(" ", strip=True)] = cells[-1].get_text(strip=True)
        values = []
        for name, party in ((dem, "Democratic"), (rep, "Republican")):
            raw = answers.get(f"{name} ({party})", "")
            if not re.fullmatch(r"\d+(?:\.\d+)?%", raw):
                raise ValueError(f"Michigan release lacks an unambiguous topline for {name}")
            values.append(float(raw[:-1]))
        if sum(values) > 100.5:
            raise ValueError("Michigan candidate percentages do not reconcile")
        record = PollRecord(
            source="enjoyer_primary",
            source_id=f"enjoyer:MI:{office}:{end}",
            race_id=f"2026:{office}:MI",
            cycle=2026,
            office=office,
            location="MI",
            pollster="Cygnal/Beacon Research",
            end_date=end,
            election_date=date(2026, 11, 3),
            sample_size=int(sample[1].replace(",", "")),
            population=Population.LIKELY_VOTERS,
            methodology="Registered-voter sample; live phone and text; likely-voter weighting",
            dem_candidate=dem,
            rep_candidate=rep,
            dem_pct=values[0],
            rep_pct=values[1],
            source_url=RELEASE_URL,
        ).model_dump(mode="json")
        record.update(
            start_date=start.isoformat(),
            publication_date=publication.isoformat(),
            primary_source_verified=True,
            source_content_sha256=hashlib.sha256(payload).hexdigest(),
            sample_size_basis="published Michigan likely-voter sample",
            survey_scope="statewide",
            publisher="Michigan Enjoyer",
            sponsor_disclosure="No party sponsor identified in published methodology; "
            "absence of disclosure does not establish nonpartisanship",
        )
        records.append(record)
    return pd.DataFrame(records)


def fetch_enjoyer_polls(
    *, refresh: bool = False, as_of: date | None = None, client: CachedHTTPClient | None = None
) -> pd.DataFrame:
    client = client or CachedHTTPClient()
    try:
        return parse_enjoyer_release(
            client.get(RELEASE_URL, refresh=refresh), as_of=as_of or date.today()
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        LOGGER.warning("Primary Michigan release excluded: %s", exc)
        return pd.DataFrame()
