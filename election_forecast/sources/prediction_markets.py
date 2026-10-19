"""Public prediction-market adapters for current U.S. election probabilities.

Market prices are external forecasts, not polls.  This module keeps their
provenance and microstructure diagnostics so downstream code can use them as a
bounded calibration signal without presenting them as ground truth.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd

from ..http_cache import CachedHTTPClient

MarketLeg = tuple[float, str, float, float, float, object]

POLYMARKET_API = "https://gamma-api.polymarket.com"
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

POLYMARKET_TAGS = ("senate-midterms", "governor-midterms", "midterms")
POLYMARKET_CHAMBER_SLUGS = {
    "which-party-will-win-the-house-in-2026": ("house", "US-HOUSE"),
    "which-party-will-win-the-senate-in-2026": ("senate", "US-SENATE"),
}
KALSHI_CHAMBER_EVENTS = {
    "CONTROLH-2026": ("house", "US-HOUSE"),
    "CONTROLS-2026": ("senate", "US-SENATE"),
}

STATE_ABBREVIATIONS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new-hampshire": "NH",
    "new-jersey": "NJ",
    "new-mexico": "NM",
    "new-york": "NY",
    "north-carolina": "NC",
    "north-dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode-island": "RI",
    "south-carolina": "SC",
    "south-dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west-virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _party(*values: object) -> str | None:
    text = " ".join(str(value) for value in values if value is not None).casefold()
    if re.search(r"\(d\)|\bdemocrat(?:ic|s)?\b", text):
        return "D"
    if re.search(r"\(r\)|\brepublican(?:s)?\b", text):
        return "R"
    return None


def _market_midpoint(market: dict[str, Any], *, polymarket: bool) -> tuple[float, float]:
    if polymarket:
        bid = _float(market.get("bestBid"), math.nan)
        ask = _float(market.get("bestAsk"), math.nan)
        if math.isfinite(bid) and math.isfinite(ask) and 0 <= bid <= ask <= 1:
            return (bid + ask) / 2.0, ask - bid
        outcomes = [str(item).casefold() for item in _json_list(market.get("outcomes"))]
        prices = [_float(item, math.nan) for item in _json_list(market.get("outcomePrices"))]
        if "yes" in outcomes and len(prices) == len(outcomes):
            return prices[outcomes.index("yes")], _float(market.get("spread"), math.nan)
    else:
        bid = _float(market.get("yes_bid_dollars"), math.nan)
        ask = _float(market.get("yes_ask_dollars"), math.nan)
        if math.isfinite(bid) and math.isfinite(ask) and 0 <= bid <= ask <= 1:
            return (bid + ask) / 2.0, ask - bid
        last = _float(market.get("last_price_dollars"), math.nan)
        if math.isfinite(last):
            return last, math.nan
    return math.nan, math.nan


def _polymarket_scope(event: dict[str, Any]) -> tuple[str, str, str] | None:
    slug = str(event.get("slug", "")).casefold()
    if slug in POLYMARKET_CHAMBER_SLUGS:
        office, location = POLYMARKET_CHAMBER_SLUGS[slug]
        return office, location, "chamber_control"

    senate = re.fullmatch(r"(.+)-senate-election-winner(?:-\d+)?", slug)
    if senate and senate.group(1) in STATE_ABBREVIATIONS:
        return "senate", STATE_ABBREVIATIONS[senate.group(1)], "direct_race"

    governor_patterns = (
        r"(.+)-governor-election-winner(?:-\d+)?",
        r"(.+)-governor-winner-2026",
        r"(.+)-governor-election-2026",
    )
    for pattern in governor_patterns:
        governor = re.fullmatch(pattern, slug)
        if governor and governor.group(1) in STATE_ABBREVIATIONS:
            return "governor", STATE_ABBREVIATIONS[governor.group(1)], "direct_race"

    house = re.fullmatch(r"([a-z]{2})-(\d{1,2})-house-election-winner(?:-\d+)?", slug)
    if house:
        return "house", f"{house.group(1).upper()}-{int(house.group(2)):02d}", "direct_race"
    return None


def _quality_score(
    *,
    volume: float,
    depth: float,
    spread: float,
    updated_at: object,
    fetched_at: datetime,
) -> float:
    volume_score = min(math.log10(1.0 + max(volume, 0.0)) / 6.0, 1.0)
    depth_score = min(math.log10(1.0 + max(depth, 0.0)) / 5.0, 1.0)
    spread_score = 0.5 if not math.isfinite(spread) else max(0.0, 1.0 - spread / 0.12)
    updated = pd.to_datetime(updated_at, utc=True, errors="coerce")
    if pd.isna(updated):
        freshness_score = 0.5
    else:
        age_days = max((pd.Timestamp(fetched_at) - updated).total_seconds() / 86400.0, 0.0)
        freshness_score = 0.5 ** (age_days / 14.0)
    return float(
        0.35 * volume_score + 0.25 * depth_score + 0.25 * spread_score + 0.15 * freshness_score
    )


def _normalized_record(
    *,
    source: str,
    office: str,
    location: str,
    scope: str,
    event_id: str,
    event_title: str,
    dem: list[MarketLeg],
    rep: list[MarketLeg],
    source_url: str,
    fetched_at: datetime,
) -> dict[str, object] | None:
    dem_raw = sum(item[0] for item in dem if math.isfinite(item[0]))
    rep_raw = sum(item[0] for item in rep if math.isfinite(item[0]))
    total = dem_raw + rep_raw
    if total <= 0 or not dem or not rep:
        return None
    volume = sum(item[2] for item in dem + rep)
    depth = sum(item[3] for item in dem + rep)
    market_spreads = [item[4] for item in dem + rep if math.isfinite(item[4])]
    spread = max(market_spreads) if market_spreads else math.nan
    updated_values = [pd.to_datetime(item[5], utc=True, errors="coerce") for item in dem + rep]
    updated_values = [item for item in updated_values if not pd.isna(item)]
    updated_at = max(updated_values) if updated_values else pd.NaT
    quality = _quality_score(
        volume=volume,
        depth=depth,
        spread=spread,
        updated_at=updated_at,
        fetched_at=fetched_at,
    )
    return {
        "source": source,
        "office": office,
        "location": location,
        "market_scope": scope,
        "event_id": event_id,
        "event_title": event_title,
        "dem_probability_raw": dem_raw,
        "rep_probability_raw": rep_raw,
        "dem_probability": dem_raw / total,
        "rep_probability": rep_raw / total,
        "two_party_price_sum": total,
        "overround": total - 1.0,
        "dem_market_labels": " | ".join(sorted({item[1] for item in dem})),
        "rep_market_labels": " | ".join(sorted({item[1] for item in rep})),
        "volume": volume,
        "liquidity_or_open_interest": depth,
        "max_spread": spread,
        "quality_score": quality,
        "market_updated_at": updated_at,
        "fetched_at": fetched_at,
        "source_url": source_url,
    }


def _polymarket_record(event: dict[str, Any], fetched_at: datetime) -> dict[str, object] | None:
    scope = _polymarket_scope(event)
    if scope is None:
        return None
    office, location, market_scope = scope
    parties: dict[str, list[MarketLeg]] = {"D": [], "R": []}
    for market in event.get("markets", []):
        if not isinstance(market, dict) or not market.get("active") or market.get("closed"):
            continue
        party = _party(
            market.get("groupItemTitle"),
            market.get("question"),
            market.get("slug"),
        )
        if party is None:
            continue
        price, spread = _market_midpoint(market, polymarket=True)
        if not math.isfinite(price) or not 0 < price < 1:
            continue
        label = str(market.get("groupItemTitle") or market.get("question") or party)
        parties[party].append(
            (
                price,
                label,
                _float(market.get("volumeNum", market.get("volume"))),
                _float(market.get("liquidityNum", market.get("liquidity"))),
                spread,
                market.get("updatedAt"),
            )
        )
    return _normalized_record(
        source="polymarket",
        office=office,
        location=location,
        scope=market_scope,
        event_id=str(event.get("id") or event.get("slug")),
        event_title=str(event.get("title", "")),
        dem=parties["D"],
        rep=parties["R"],
        source_url=f"https://polymarket.com/event/{event.get('slug')}",
        fetched_at=fetched_at,
    )


def fetch_polymarket_markets(
    *,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Discover liquid 2026 election-winner events through public event tags."""
    client = client or CachedHTTPClient()
    fetched_at = datetime.now(UTC)
    events: dict[str, dict[str, Any]] = {}
    for tag in POLYMARKET_TAGS:
        url = (
            f"{POLYMARKET_API}/events?tag_slug={tag}&active=true&closed=false"
            "&limit=500&order=volume&ascending=false"
        )
        payload = json.loads(client.get(url, refresh=refresh))
        if not isinstance(payload, list):
            continue
        for event in payload:
            if isinstance(event, dict) and event.get("slug"):
                events[str(event["slug"])] = event
    rows = [
        record
        for event in events.values()
        if (record := _polymarket_record(event, fetched_at)) is not None
    ]
    return pd.DataFrame.from_records(rows)


def _kalshi_record(
    payload: dict[str, Any],
    *,
    office: str,
    location: str,
    scope: str,
    fetched_at: datetime,
) -> dict[str, object] | None:
    event = payload.get("event", {})
    markets = payload.get("markets") or event.get("markets") or []
    parties: dict[str, list[MarketLeg]] = {"D": [], "R": []}
    for market in markets:
        if not isinstance(market, dict) or market.get("status") != "active":
            continue
        party = _party(
            market.get("subtitle"),
            market.get("title"),
            market.get("rules_primary"),
            market.get("ticker"),
        )
        if party is None:
            continue
        price, spread = _market_midpoint(market, polymarket=False)
        if not math.isfinite(price) or not 0 < price < 1:
            continue
        label = str(market.get("yes_sub_title") or market.get("subtitle") or party)
        parties[party].append(
            (
                price,
                label,
                _float(market.get("volume_fp")),
                _float(market.get("liquidity_dollars")) or _float(market.get("open_interest_fp")),
                spread,
                market.get("updated_time"),
            )
        )
    event_id = str(event.get("event_ticker", ""))
    series = str(event.get("series_ticker", "")).casefold()
    return _normalized_record(
        source="kalshi",
        office=office,
        location=location,
        scope=scope,
        event_id=event_id,
        event_title=str(event.get("title", "")),
        dem=parties["D"],
        rep=parties["R"],
        source_url=f"https://kalshi.com/markets/{series}/{event_id.casefold()}",
        fetched_at=fetched_at,
    )


def fetch_kalshi_markets(
    catalog: pd.DataFrame,
    *,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch chamber and state Senate winner events from Kalshi's public API."""
    client = client or CachedHTTPClient()
    fetched_at = datetime.now(UTC)
    event_specs = [
        (event, office, location, "chamber_control")
        for event, (office, location) in KALSHI_CHAMBER_EVENTS.items()
    ]
    senate_locations = sorted(
        {
            str(location).upper()
            for location in catalog.loc[catalog["office"] == "senate", "location"]
            if re.fullmatch(r"[A-Z]{2}", str(location).upper())
        }
    )
    event_specs.extend(
        (f"SENATE{location}-26", "senate", location, "direct_race") for location in senate_locations
    )
    rows: list[dict[str, object]] = []
    for event_id, office, location, scope in event_specs:
        url = f"{KALSHI_API}/events/{event_id}"
        try:
            payload = json.loads(client.get(url, refresh=refresh))
        except (httpx.HTTPError, OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        record = _kalshi_record(
            payload,
            office=office,
            location=location,
            scope=scope,
            fetched_at=fetched_at,
        )
        if record is not None:
            rows.append(record)
    return pd.DataFrame.from_records(rows)


def fetch_prediction_markets(
    catalog: pd.DataFrame,
    *,
    refresh: bool = False,
    client: CachedHTTPClient | None = None,
) -> pd.DataFrame:
    """Fetch and concatenate supported public election prediction markets."""
    client = client or CachedHTTPClient()
    frames = [
        fetch_polymarket_markets(refresh=refresh, client=client),
        fetch_kalshi_markets(catalog, refresh=refresh, client=client),
    ]
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return pd.DataFrame()
    return (
        pd.concat(populated, ignore_index=True)
        .sort_values(["market_scope", "office", "location", "source"])
        .reset_index(drop=True)
    )
