"""Adapter for recent public general-election tables on PollingSource."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from io import BytesIO

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from ..http_cache import CachedHTTPClient
from ..schemas import Office, PollRecord, Population

LATEST_URLS = {
    Office.SENATE: "https://pollingsource.com/senate/polls",
    Office.HOUSE: "https://pollingsource.com/house/",
    Office.GENERIC_BALLOT: "https://pollingsource.com/polls/generic-ballot",
}

CATALOG_URLS = {
    Office.SENATE: "https://pollingsource.com/senate/",
    Office.HOUSE: "https://pollingsource.com/house/",
    Office.GOVERNOR: "https://pollingsource.com/governors/",
}

CATALOG_VARIABLES = {
    Office.SENATE: "senateStateData",
    Office.HOUSE: "districtInfo",
    Office.GOVERNOR: "govStateData",
}

GOVERNOR_STATES_2026 = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IA",
    "KS",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "NE",
    "NV",
    "NH",
    "NM",
    "NY",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "VT",
    "WI",
    "WY",
)

PERCENT_RE = re.compile(r"(?P<name>.*?)\s+(?P<pct>\d+(?:\.\d+)?)%\s*$")
SAMPLE_RE = re.compile(r"(?P<size>[\d,]+)?\s*(?P<population>LV|RV|V|A)?", re.IGNORECASE)


def _source_url(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value
    return fallback


def _pollster_label(value: object) -> str:
    return re.sub(r"\s+20\d{2}\s+err\b.*$", "", str(value), flags=re.IGNORECASE).strip()


def _extract_javascript_json(payload: bytes, variable: str) -> dict[str, dict[str, object]]:
    """Extract a JSON object assigned to a known JavaScript constant.

    PollingSource renders its race maps from server-produced JSON. Parsing that object is
    less brittle than scraping hundreds of tooltip elements, while the explicit variable
    allowlist prevents this helper from becoming a general JavaScript evaluator.
    """
    text = payload.decode("utf-8")
    pattern = re.compile(rf"const\s+{re.escape(variable)}\s*=\s*(\{{.*?\}});", re.DOTALL)
    match = pattern.search(text)
    if not match:
        raise ValueError(f"could not find JavaScript catalog variable {variable}")
    result = json.loads(match.group(1))
    if not isinstance(result, dict):
        raise ValueError(f"catalog variable {variable} was not an object")
    return result


def _party_candidate(info: dict[str, object], party: str) -> str:
    nominees = info.get("nominees", info.get("nom", []))
    opposing_names: set[str] = set()
    if isinstance(nominees, list):
        opposing_names = {
            str(item.get("n", "")).strip().casefold()
            for item in nominees
            if isinstance(item, dict)
            and str(item.get("p", "")).upper() not in {"", party}
            and str(item.get("n", "")).strip()
        }
        eligible = [
            item
            for item in nominees
            if isinstance(item, dict)
            and str(item.get("p", "")).upper() == party
            and not item.get("w", False)
        ]
        if eligible:
            nominee = next((item for item in eligible if item.get("i", False)), eligible[0])
            name = str(nominee.get("n", "")).strip()
            if name:
                return name
    incumbent_party = str(info.get("incumbent_party", info.get("party", ""))).upper()
    incumbent_name = str(info.get("incumbent", info.get("name", ""))).strip()
    # Live map records can temporarily put a declared challenger in the
    # ``incumbent`` field while retaining the old incumbent's party. Never copy a
    # name across parties when the nominees array identifies it with the other party.
    if (
        incumbent_party == party
        and incumbent_name
        and not incumbent_name.startswith("OPEN")
        and incumbent_name.casefold() not in opposing_names
    ):
        return incumbent_name
    label = "Democratic" if party == "D" else "Republican"
    return f"{label} nominee TBD"


def fetch_polling_source_catalog(
    office: Office,
    *,
    cycle: int = 2026,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch a complete current race catalog, including races without polls."""
    if office not in CATALOG_URLS:
        raise ValueError(f"PollingSource catalog does not support {office.value}")
    client = client or CachedHTTPClient()
    url = CATALOG_URLS[office]
    fetched_at = datetime.now(UTC)
    data = _extract_javascript_json(client.get(url, refresh=refresh), CATALOG_VARIABLES[office])
    rows: list[dict[str, object]] = []
    for location, raw_info in data.items():
        if not isinstance(raw_info, dict):
            continue
        rating = str(raw_info.get("rating", "")).strip()
        if not rating:
            continue
        rows.append(
            {
                "race_id": f"{cycle}:{office.value}:{str(location).upper()}",
                "cycle": cycle,
                "office": office.value,
                "location": str(location).upper(),
                "rating": rating,
                "rating_source": str(raw_info.get("src", "expert/poll consensus")),
                "incumbent": str(raw_info.get("incumbent", raw_info.get("name", ""))),
                "incumbent_party": str(
                    raw_info.get("incumbent_party", raw_info.get("party", ""))
                ).upper(),
                "dem_candidate": _party_candidate(raw_info, "D"),
                "rep_candidate": _party_candidate(raw_info, "R"),
                "nominees_json": json.dumps(raw_info.get("nominees", raw_info.get("nom", []))),
                "source_poll_average": raw_info.get("margin", raw_info.get("avg")),
                "source_poll_count": int(raw_info.get("poll_count", 0) or 0),
                "source_url": url,
                "fetched_at": fetched_at,
            }
        )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        raise ValueError(f"{office.value} catalog normalized to zero races")
    return frame.sort_values("location").reset_index(drop=True)


def _candidate_cell(value: object) -> tuple[str, float] | None:
    text = " ".join(str(value).split())
    match = PERCENT_RE.search(text)
    if not match:
        return None
    name = match.group("name").strip()
    if name.lower() in {"dem", "rep", "nan", ""}:
        return None
    return name, float(match.group("pct"))


def _sample_cell(value: object) -> tuple[int | None, Population]:
    text = " ".join(str(value).split())
    match = SAMPLE_RE.match(text)
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


def _find_poll_table(payload: bytes, default_location: str | None = None) -> pd.DataFrame:
    # pandas.read_html is more resilient to small markup changes than fixed CSS selectors.
    tables = pd.read_html(BytesIO(payload), flavor="lxml")
    soup = BeautifulSoup(payload, "lxml")
    for table in tables:
        normalized_columns = {str(column).strip().lower(): column for column in table.columns}
        if {"pollster", "date", "sample", "dem", "rep"}.issubset(normalized_columns):
            location_name = "state" if "state" in normalized_columns else "district"
            renamed = table.rename(
                columns={
                    normalized_columns["pollster"]: "pollster",
                    normalized_columns["date"]: "end_date",
                    normalized_columns["sample"]: "sample",
                    normalized_columns["dem"]: "dem",
                    normalized_columns["rep"]: "rep",
                }
            )
            if "ind" in normalized_columns:
                renamed = renamed.rename(columns={normalized_columns["ind"]: "ind"})
            # read_html discards hyperlinks. Keep the date-cell link to the
            # original release instead of pointing every survey at this index.
            for html_table in soup.find_all("table"):
                headers = [
                    cell.get_text(" ", strip=True).lower() for cell in html_table.select("thead th")
                ]
                if not headers:
                    first = html_table.find("tr")
                    headers = (
                        [cell.get_text(" ", strip=True).lower() for cell in first.find_all("th")]
                        if first
                        else []
                    )
                if not {"pollster", "date", "sample", "dem", "rep"}.issubset(headers):
                    continue
                urls = []
                for html_row in html_table.find_all("tr"):
                    cells = html_row.find_all("td", recursive=False)
                    if len(cells) <= headers.index("date"):
                        continue
                    anchor = cells[headers.index("date")].find("a", href=True)
                    href = str(anchor.get("href", "")) if anchor else ""
                    urls.append(href if href.startswith(("https://", "http://")) else None)
                if len(urls) == len(renamed):
                    renamed["source_url"] = urls
                    break
            if location_name in normalized_columns:
                return renamed.rename(columns={normalized_columns[location_name]: "location"})
            if default_location:
                renamed["location"] = default_location
                return renamed
    # Include a useful page title when the provider changes its table structure.
    title = BeautifulSoup(payload, "lxml").title
    page_title = title.string if title else "untitled page"
    raise ValueError(f"no compatible polling table found ({page_title})")


def fetch_polling_source(
    office: Office,
    *,
    cycle: int = 2026,
    election_date: date = date(2026, 11, 3),
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    if office not in LATEST_URLS:
        raise ValueError(f"PollingSource adapter does not support {office.value}")
    client = client or CachedHTTPClient()
    url = LATEST_URLS[office]
    payload = client.get(url, refresh=refresh)
    table = _find_poll_table(
        payload, default_location="US" if office == Office.GENERIC_BALLOT else None
    )
    fetched_at = datetime.now(UTC)
    records: list[dict[str, object]] = []

    for _, row in table.iterrows():
        dem = _candidate_cell(row["dem"])
        rep = _candidate_cell(row["rep"])
        if dem is None or rep is None:
            continue
        if office == Office.GENERIC_BALLOT:
            # Aggregator pages occasionally leak a state-race row into the generic table.
            # Require party labels and normalize their spelling into one national series.
            if not dem[0].lower().startswith("democrat") or not rep[0].lower().startswith(
                "republican"
            ):
                continue
            dem = ("Democratic", dem[1])
            rep = ("Republican", rep[1])
        try:
            end_date = pd.to_datetime(row["end_date"]).date()
        except (TypeError, ValueError):
            continue
        location = str(row["location"]).strip().upper().replace(" SPECIAL", "")
        pollster = _pollster_label(" ".join(str(row["pollster"]).split()))
        sample_size, population = _sample_cell(row["sample"])
        partisan_match = re.search(r"partisan[·\s]*([DR])", pollster, re.IGNORECASE)
        partisan = partisan_match.group(1).upper() if partisan_match else None
        candidate_key = lambda name: re.sub(r"[^a-z]", "", name.lower().split()[-1])  # noqa: E731
        dem_key = candidate_key(dem[0])
        rep_key = candidate_key(rep[0])
        fingerprint = "|".join(
            [location, pollster, end_date.isoformat(), dem[0], str(dem[1]), rep[0], str(rep[1])]
        )
        source_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
        record = PollRecord(
            source="pollingsource",
            source_id=source_id,
            race_id=f"{cycle}:{office.value}:{location}:{dem_key}:{rep_key}",
            cycle=cycle,
            office=office,
            location=location,
            pollster=pollster,
            end_date=end_date,
            election_date=election_date,
            sample_size=sample_size,
            population=population,
            partisan=partisan,
            dem_candidate=dem[0],
            rep_candidate=rep[0],
            dem_pct=dem[1],
            rep_pct=rep[1],
            source_url=_source_url(row.get("source_url"), url),
            fetched_at=fetched_at,
        )
        normalized = record.model_dump(mode="json")
        independent = _candidate_cell(row.get("ind", ""))
        if independent is not None:
            normalized["ind_candidate"] = independent[0]
            normalized["ind_pct"] = independent[1]
        records.append(normalized)

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError(f"{office.value} latest source normalized to zero records")

    # Survey identity is resolved centrally. Equal scores on the same day do
    # not establish that two institutes surveyed the same people.
    frame = frame.drop_duplicates(["source", "source_id"])
    return frame.sort_values(["office", "location", "end_date"], ascending=[True, True, False])


def fetch_polling_source_governors(
    *,
    cycle: int = 2026,
    election_date: date = date(2026, 11, 3),
    states: tuple[str, ...] = GOVERNOR_STATES_2026,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch visible recent general-election polls from 2026 governor race pages."""
    client = client or CachedHTTPClient()
    frames: list[pd.DataFrame] = []
    for state in states:
        url = f"https://pollingsource.com/governors/{state}"
        try:
            payload = client.get(url, refresh=refresh)
            table = _find_poll_table(payload, default_location=state)
        except (httpx.HTTPError, ValueError, OSError):
            continue
        fetched_at = datetime.now(UTC)
        records: list[dict[str, object]] = []
        for _, row in table.iterrows():
            dem = _candidate_cell(row["dem"])
            rep = _candidate_cell(row["rep"])
            if dem is None or rep is None:
                continue
            try:
                end_date = pd.to_datetime(row["end_date"]).date()
            except (TypeError, ValueError):
                continue
            pollster = " ".join(str(row["pollster"]).split())
            sample_size, population = _sample_cell(row["sample"])
            partisan_match = re.search(r"partisan[·\s]*([DR])", pollster, re.IGNORECASE)
            partisan = partisan_match.group(1).upper() if partisan_match else None
            dem_key = re.sub(r"[^a-z]", "", dem[0].lower().split()[-1])
            rep_key = re.sub(r"[^a-z]", "", rep[0].lower().split()[-1])
            fingerprint = "|".join(
                [state, pollster, end_date.isoformat(), dem_key, str(dem[1]), rep_key, str(rep[1])]
            )
            record = PollRecord(
                source="pollingsource",
                source_id=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20],
                race_id=f"{cycle}:governor:{state}:{dem_key}:{rep_key}",
                cycle=cycle,
                office=Office.GOVERNOR,
                location=state,
                pollster=pollster,
                end_date=end_date,
                election_date=election_date,
                sample_size=sample_size,
                population=population,
                partisan=partisan,
                dem_candidate=dem[0],
                rep_candidate=rep[0],
                dem_pct=dem[1],
                rep_pct=rep[1],
                source_url=_source_url(row.get("source_url"), url),
                fetched_at=fetched_at,
            )
            normalized = record.model_dump(mode="json")
            independent = _candidate_cell(row.get("ind", ""))
            if independent is not None:
                normalized["ind_candidate"] = independent[0]
                normalized["ind_pct"] = independent[1]
            records.append(normalized)
        if records:
            frames.append(pd.DataFrame.from_records(records))
    if not frames:
        raise ValueError("governor latest sources normalized to zero records")
    frame = pd.concat(frames, ignore_index=True)
    return (
        frame.drop_duplicates(["source", "source_id"])
        .sort_values(["location", "end_date"], ascending=[True, False])
        .reset_index(drop=True)
    )
