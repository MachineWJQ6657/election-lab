"""270toWin public state polling-page adapter."""

from __future__ import annotations

import hashlib
import json
import re
import warnings
from datetime import UTC, date, datetime

import httpx
import pandas as pd
from bs4 import BeautifulSoup, Tag

from ..http_cache import CachedHTTPClient
from ..schemas import Office, PollRecord, Population

MAP_URLS = {
    Office.SENATE: (
        "https://www.270towin.com/partials/maps/custom_map.php?"
        "id=senate-polls-26&show_dc=0&show_evotes=0"
    ),
    Office.GOVERNOR: (
        "https://www.270towin.com/partials/maps/custom_map.php?"
        "id=governor-polls-26&show_dc=0&show_evotes=0"
    ),
}
DEMOCRATIC_COLOR = "#3e5a96"
REPUBLICAN_COLOR = "#c23237"
SAMPLE_RE = re.compile(r"(?P<size>[\d,]+)?\s*(?P<population>LV|RV|V|A)?", re.IGNORECASE)
PERCENT_RE = re.compile(r"-?\d+(?:\.\d+)?")
POLLSTER_MOE_SUFFIX_RE = re.compile(r"\s*(?:±|\+/-)\s*\d+(?:\.\d+)?%?\s*$", re.IGNORECASE)


def _clean_source_url(value: object, page_url: str) -> str:
    """Keep a usable public URL when upstream HTML contains pasted local paths."""
    text = str(value).strip()
    starts = [match.start() for match in re.finditer(r"https?://", text, re.IGNORECASE)]
    if not starts:
        return page_url
    # A few source cells contain the 270toWin URL followed by a pasted topline
    # URL. The last public URL is the intended evidence link.
    return text[starts[-1] :].strip()


def _map_pages(payload: bytes) -> list[tuple[str, str]]:
    """Read state abbreviations and poll-page URLs from the site's public map data."""
    text = payload.decode("utf-8")
    marker = "m.seats = "
    start = text.find(marker)
    if start < 0:
        raise ValueError("270toWin map did not expose m.seats")
    seats, _ = json.JSONDecoder().raw_decode(text[start + len(marker) :])
    pages: set[tuple[str, str]] = set()
    for entries in seats.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("url_link"):
                continue
            state = str(entry.get("state_abbr", "")).upper()
            if re.fullmatch(r"[A-Z]{2}", state):
                pages.add((state, str(entry["url_link"])))
    return sorted(pages)


def _candidate_header(table: Tag, color: str) -> tuple[int, str] | None:
    headers = table.select("thead th.can_name")
    for index, header in enumerate(headers):
        style = str(header.get("style", "")).lower().replace(" ", "")
        if color in style:
            name = header.get_text(" ", strip=True).replace("*", "").strip()
            if name:
                return index, name
    return None


def _sample(value: str) -> tuple[int | None, Population]:
    match = SAMPLE_RE.search(" ".join(value.split()))
    if not match:
        return None, Population.UNKNOWN
    size_text = match.group("size")
    size = int(size_text.replace(",", "")) if size_text else None
    population_text = (match.group("population") or "unknown").lower()
    try:
        population = Population(population_text)
    except ValueError:
        population = Population.UNKNOWN
    return size, population


def _percentage(cell: Tag) -> float | None:
    match = PERCENT_RE.search(cell.get_text(" ", strip=True))
    return float(match.group()) if match else None


def _parse_page(
    payload: bytes,
    *,
    office: Office,
    location: str,
    page_url: str,
    cycle: int,
    election_date: date,
    fetched_at: datetime,
) -> list[dict[str, object]]:
    soup = BeautifulSoup(payload, "lxml")
    general = soup.find(id="GE")
    if not isinstance(general, Tag):
        return []
    records: list[dict[str, object]] = []
    for table in general.find_all("table"):
        if not isinstance(table, Tag):
            continue
        dem_header = _candidate_header(table, DEMOCRATIC_COLOR)
        rep_header = _candidate_header(table, REPUBLICAN_COLOR)
        if dem_header is None or rep_header is None:
            continue
        dem_index, dem_candidate = dem_header
        rep_index, rep_candidate = rep_header
        for poll_row in table.select("tr.poll_row"):
            source_cell = poll_row.select_one("td.poll_src")
            date_cell = poll_row.select_one("td.poll_date")
            sample_cell = poll_row.select_one("td.poll_sample")
            result_cells = poll_row.select("td.poll_data")
            if (
                source_cell is None
                or date_cell is None
                or sample_cell is None
                or max(dem_index, rep_index) >= len(result_cells)
            ):
                continue
            try:
                end_date = pd.to_datetime(date_cell.get_text(" ", strip=True)).date()
            except (TypeError, ValueError):
                continue
            dem_pct = _percentage(result_cells[dem_index])
            rep_pct = _percentage(result_cells[rep_index])
            if dem_pct is None or rep_pct is None:
                continue
            pollster = POLLSTER_MOE_SUFFIX_RE.sub("", source_cell.get_text(" ", strip=True)).strip()
            if not pollster:
                continue
            link = source_cell.find("a", href=True)
            source_url = (
                _clean_source_url(link["href"], page_url) if isinstance(link, Tag) else page_url
            )
            sample_size, population = _sample(sample_cell.get_text(" ", strip=True))
            partisan_match = re.search(r"\(([DR])\)", pollster, re.IGNORECASE)
            partisan = partisan_match.group(1).upper() if partisan_match else None
            fingerprint = "|".join(
                [
                    office.value,
                    location,
                    pollster,
                    end_date.isoformat(),
                    dem_candidate,
                    str(dem_pct),
                    rep_candidate,
                    str(rep_pct),
                ]
            )
            dem_key = re.sub(r"[^a-z]", "", dem_candidate.lower().split()[-1])
            rep_key = re.sub(r"[^a-z]", "", rep_candidate.lower().split()[-1])
            record = PollRecord(
                source="270towin",
                source_id=hashlib.sha256(fingerprint.encode()).hexdigest()[:20],
                race_id=f"{cycle}:{office.value}:{location}:{dem_key}:{rep_key}",
                cycle=cycle,
                office=office,
                location=location,
                pollster=pollster,
                end_date=end_date,
                election_date=election_date,
                sample_size=sample_size,
                population=population,
                methodology="270toWin listed date; direct poll link retained",
                partisan=partisan,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                dem_pct=dem_pct,
                rep_pct=rep_pct,
                source_url=source_url,
                fetched_at=fetched_at,
            )
            records.append(record.model_dump(mode="json"))
    return records


def fetch_270towin_polls(
    offices: tuple[Office, ...] = (Office.SENATE, Office.GOVERNOR),
    *,
    cycle: int = 2026,
    election_date: date = date(2026, 11, 3),
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch major-party general-election matchups from states with public pages."""
    client = client or CachedHTTPClient()
    records: list[dict[str, object]] = []
    fetched_at = datetime.now(UTC)
    for office in offices:
        if office not in MAP_URLS:
            continue
        try:
            discovery = client.get(MAP_URLS[office], refresh=refresh)
        except httpx.HTTPError:
            # Discovery is only a directory of links. Refresh the individual
            # polling pages even when the old map endpoint has disappeared.
            discovery = client.get_cached(MAP_URLS[office])
            warnings.warn(
                f"270toWin {office.value} map unavailable; using verified cached page links; "
                "poll pages are still fetched independently.",
                stacklevel=2,
            )
        pages = _map_pages(discovery)
        for location, page_url in pages:
            try:
                payload = client.get(page_url, refresh=refresh)
            except (httpx.HTTPError, OSError):
                continue
            records.extend(
                _parse_page(
                    payload,
                    office=office,
                    location=location,
                    page_url=page_url,
                    cycle=cycle,
                    election_date=election_date,
                    fetched_at=fetched_at,
                )
            )
    return pd.DataFrame.from_records(records)
