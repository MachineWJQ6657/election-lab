"""Aggregate early-voting observations; party registration is not vote choice."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO, StringIO

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from ..http_cache import CachedHTTPClient

CIVIC_BASE = "https://civicapi.org/api/v2/early-vote"
NC_COUNTS = (
    "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_11_03/absentee_counts_state_20261103.csv"
)
NC_REFERENCE = "https://www.ncsbe.gov/results-data/absentee-and-provisional-data"
CATEGORIES = ("requested", "returned", "inperson")
FL_STATS = "https://countyfilesvbm-ev.floridados.gov/VoteByMailEarlyVotingReports/PublicStats"


def parse_florida(payload: bytes, *, as_of: date) -> list[dict]:
    text = payload.decode("utf-8-sig")
    plain = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    if "2026 General" not in plain or "11/03/2026" not in plain:
        raise ValueError("Florida report is not the 2026 general election")
    table = pd.read_html(StringIO(text))[0]
    table.columns = [str(column).strip() for column in table.columns]
    parties = {
        "Republican": "Republican",
        "Democrat": "Democratic",
        "Other": "Other",
        "No Party Affiliation": "Unaffiliated",
    }
    modes = {
        "Voted Vote-by-Mail": "returned",
        "Voted Early": "inperson",
        "Vote-by-Mail Provided (Not Yet Returned)": "outstanding",
    }
    rows = []
    for _, row in table.iterrows():
        label = str(row.iloc[0]).strip()
        if label not in modes:
            continue
        snapshot = pd.to_datetime(str(row["Compiled"]).split()[0]).date()
        if snapshot > as_of:
            raise ValueError("Florida report is newer than the forecast")
        counts = {
            party: _count(str(row[column]).replace(",", "")) for column, party in parties.items()
        }
        if sum(counts.values()) != _count(str(row["Total"]).replace(",", "")):
            raise ValueError("Florida party counts do not reconcile to published total")
        for party, count in counts.items():
            rows.append(
                {
                    "state": "FL",
                    "category": modes[label],
                    "party": party,
                    "count": count,
                    "snapshot_date": snapshot.isoformat(),
                    "source": "florida_dos",
                    "source_url": FL_STATS,
                    "source_sha256": hashlib.sha256(payload).hexdigest(),
                    "date_basis": "official compiled date; usually prior-day county activity",
                }
            )
    if len(rows) != 12:
        raise ValueError("Florida statewide categories are incomplete")
    # Issued means outstanding + returned. Outstanding alone is not requests.
    for party in parties.values():
        components = [
            r for r in rows if r["party"] == party and r["category"] in {"outstanding", "returned"}
        ]
        rows.append(
            {**components[0], "category": "requested", "count": sum(r["count"] for r in components)}
        )
    return rows


def _count(value: object) -> int:
    number = float(value)
    if not number.is_integer() or number < 0:
        raise ValueError(f"Invalid ballot count: {value}")
    return int(number)


def reconcile_demographics(
    values: dict, reported_total: object, ballot_total: int
) -> tuple[dict, int]:
    counts = {str(group): _count(count) for group, count in values.items()}
    total = _count(reported_total)
    if sum(counts.values()) != total or total > ballot_total:
        raise ValueError("Demographic counts do not reconcile to observed ballots")
    gap = ballot_total - total
    if gap:
        counts["Not reported / reporting gap"] = counts.get("Not reported / reporting gap", 0) + gap
    return counts, gap


def parse_civic(payload: bytes, *, category: str, as_of: date, url: str) -> list[dict]:
    data = json.loads(payload)
    if data.get("category") != category:
        raise ValueError("Early-vote category does not match requested endpoint")
    snapshot = date.fromisoformat(data["snapshot_date"])
    if snapshot > as_of or snapshot.year != 2026:
        raise ValueError("Early-vote snapshot is future-dated or from another election")
    rows = []
    for state, parties in data["regions"].items():
        if len(state) != 2 or not state.isupper():
            continue
        for party, item in parties.items():
            rows.append(
                {
                    "state": state,
                    "category": category,
                    "party": party,
                    "count": _count(item["votes"]),
                    "snapshot_date": snapshot.isoformat(),
                    "source": "civicapi",
                    "source_url": url,
                    "source_sha256": hashlib.sha256(payload).hexdigest(),
                    "date_basis": "provider_snapshot; underlying county reports can lag",
                }
            )
    return rows


def parse_nc_counts(payload: bytes, *, as_of: date) -> tuple[list[dict], list[dict]]:
    """Sum a disjoint demographic grid once, then derive separate marginal tables."""
    frame = pd.read_csv(BytesIO(payload))
    required = {"abs_request_type", "party_cd", "gender", "race", "ethnicity"}
    if not required.issubset(frame):
        raise ValueError("Unexpected NCSBE aggregate count schema")
    count_columns = [name for name in frame if name not in required]
    if len(count_columns) != 1:
        raise ValueError("NCSBE count column is ambiguous")
    frame["count"] = frame[count_columns[0]].map(_count)
    modes = {
        "CIVILIAN": "returned",
        "MILITARY": "returned",
        "OVERSEAS": "returned",
        "EARLY VOTING": "inperson",
        "ONE-STOP": "inperson",
    }
    unknown = set(frame["abs_request_type"]) - set(modes)
    if unknown:
        raise ValueError(f"Unknown NCSBE ballot modes: {unknown}")
    frame["category"] = frame["abs_request_type"].map(modes)
    metadata = {
        "state": "NC",
        "snapshot_date": as_of.isoformat(),
        "source": "ncsbe",
        "source_url": NC_COUNTS,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "date_basis": "retrieval_date; official daily report, usually prior-day activity",
    }
    parties = {"DEM": "Democratic", "REP": "Republican", "UNA": "Unaffiliated"}
    frame["party"] = frame["party_cd"].map(parties).fillna("Other")
    counts = [
        {**metadata, "category": mode, "party": party, "count": int(count)}
        for (mode, party), count in frame.groupby(["category", "party"])["count"].sum().items()
    ]
    demographics = []
    for dimension in ("gender", "race", "ethnicity"):
        for (mode, label), count in frame.groupby(["category", dimension])["count"].sum().items():
            demographics.append(
                {
                    **metadata,
                    "category": mode,
                    "dimension": dimension,
                    "group": label,
                    "count": int(count),
                }
            )
    return counts, demographics


def election_day(year: int) -> date:
    first = date(year, 11, 1)
    return first + timedelta(days=(0 - first.weekday()) % 7 + 1)


def fetch_early_voting(
    *, as_of: date, refresh: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    client = CachedHTTPClient()
    rows, demographics, issues, history = [], [], [], []

    def fetch_category(category: str) -> tuple[str, bytes]:
        url = f"{CIVIC_BASE}/US/{category}"
        return url, client.get(url, refresh=refresh)

    with ThreadPoolExecutor(max_workers=3) as pool:
        for category, result in zip(CATEGORIES, pool.map(fetch_category, CATEGORIES), strict=True):
            url, payload = result
            rows.extend(parse_civic(payload, category=category, as_of=as_of, url=url))
    frame = pd.DataFrame(rows)
    try:
        payload = client.get(NC_COUNTS, refresh=refresh)
        _, metadata_path = client._paths(NC_COUNTS)
        fetched = date.fromisoformat(json.loads(metadata_path.read_text())["fetched_at"][:10])
        if fetched > as_of:
            raise ValueError("Live NCSBE response cannot be used for a past forecast")
        official, demographics = parse_nc_counts(payload, as_of=fetched)
        nc = pd.DataFrame(official)
        for category in ("returned", "inperson"):
            prior = frame[(frame.state == "NC") & (frame.category == category)]["count"].sum()
            direct = nc[nc.category == category]["count"].sum()
            if abs(int(prior) - int(direct)) > max(100, 0.01 * direct):
                issues.append(
                    {
                        "state": "NC",
                        "check": "provider_official_difference",
                        "category": category,
                        "aggregator": int(prior),
                        "official": int(direct),
                    }
                )
        frame = pd.concat(
            [frame[~((frame.state == "NC") & frame.category.isin(["returned", "inperson"]))], nc],
            ignore_index=True,
        )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        issues.append({"state": "NC", "check": "official_source_unavailable", "detail": str(exc)})

    try:
        official_fl = pd.DataFrame(
            parse_florida(client.get(FL_STATS, refresh=refresh), as_of=as_of)
        )
        for category in ("returned", "inperson"):
            aggregator = frame[(frame.state == "FL") & (frame.category == category)]["count"].sum()
            direct = official_fl[official_fl.category == category]["count"].sum()
            if abs(int(aggregator) - int(direct)) > max(100, 0.01 * direct):
                issues.append(
                    {
                        "state": "FL",
                        "check": "provider_official_difference",
                        "category": category,
                        "aggregator": int(aggregator),
                        "official": int(direct),
                        "resolution": "Use official total; county report times may differ.",
                    }
                )
        frame = pd.concat([frame[frame.state != "FL"], official_fl], ignore_index=True)
    except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
        issues.append({"state": "FL", "check": "official_source_unavailable", "detail": str(exc)})

    # Same days-to-election, never the same calendar date. Historical providers
    # sometimes change what "returned" includes; preserve their label and refuse
    # to infer a mail/in-person split from a historical combined total.
    horizon = (election_day(2026) - as_of).days
    states = sorted(set(frame.state))
    demographic_totals = frame.groupby(["state", "category"])["count"].sum().to_dict()

    def fetch_demographics(state: str) -> tuple[list[dict], list[dict]]:
        if state in {"NC", "FL"}:
            return [], []  # NC official grid is authoritative; FL totals differ from provider.
        output, flags = [], []
        try:
            capabilities = json.loads(
                client.get(f"{CIVIC_BASE}/{state}/capabilities", refresh=refresh)
            )
            for mode in ("returned", "inperson"):
                if not demographic_totals.get((state, mode), 0):
                    continue
                for dimension in ("race", "ethnicity", "gender", "age"):
                    if not capabilities.get("categories", {}).get(mode, {}).get(dimension):
                        continue
                    by = "age_range" if dimension == "age" else dimension
                    url = f"{CIVIC_BASE}/{state}/{mode}/demographics?by={by}"
                    data = json.loads(client.get(url, refresh=refresh))
                    snapshot = date.fromisoformat(data["snapshot_date"])
                    if snapshot > as_of:
                        raise ValueError("Future-dated demographic response")
                    expected = demographic_totals[(state, mode)]
                    try:
                        values, gap = reconcile_demographics(
                            data["values"], data["total"], expected
                        )
                    except ValueError:
                        flags.append(
                            {
                                "state": state,
                                "check": "demographic_total_mismatch",
                                "category": mode,
                                "dimension": dimension,
                                "demographic_total": data["total"],
                                "ballot_total": expected,
                                "resolution": "Exclude mismatched demographic denominator.",
                            }
                        )
                        continue
                    if gap:
                        flags.append(
                            {
                                "state": state,
                                "check": "demographic_partial_coverage",
                                "category": mode,
                                "dimension": dimension,
                                "unreported": gap,
                            }
                        )
                    output.extend(
                        {
                            "state": state,
                            "category": mode,
                            "dimension": dimension,
                            "group": group,
                            "count": count,
                            "source": "civicapi",
                            "source_url": url,
                            "snapshot_date": snapshot.isoformat(),
                        }
                        for group, count in values.items()
                    )
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            flags.append(
                {"state": state, "check": "demographic_source_unavailable", "detail": str(exc)}
            )
        return output, flags

    with ThreadPoolExecutor(max_workers=4) as pool:
        for additional, flags in pool.map(fetch_demographics, states):
            demographics.extend(additional)
            issues.extend(flags)
    jobs = [(year, state) for year in (2020, 2022, 2024) for state in states]

    def fetch_history(job: tuple[int, str]) -> dict:
        year, state = job
        matched = election_day(year) - timedelta(days=horizon)
        url = f"{CIVIC_BASE}/historical/{year}/{state}/returned?date={matched}"
        try:
            data = json.loads(client.get(url, refresh=refresh))
            if data.get("error") or str(data.get("snapshot_date")) != matched.isoformat():
                return {
                    "state": state,
                    "cycle": year,
                    "status": "missing_or_wrong_date",
                    "source_url": url,
                }
            counts = data.get("statewide_total", {})
            if not counts:
                return {
                    "state": state,
                    "cycle": year,
                    "status": "missing_statewide_total",
                    "source_url": url,
                }
            return {
                "state": state,
                "cycle": year,
                "snapshot_date": matched.isoformat(),
                "total": sum(_count(x["votes"]) for x in counts.values()),
                "reported_label": data.get("election_name", ""),
                "democratic": _count(counts["Democratic"]["votes"])
                if "Democratic" in counts
                else None,
                "republican": _count(counts["Republican"]["votes"])
                if "Republican" in counts
                else None,
                "status": "context_only_unverified_mode_comparability",
                "source_url": url,
            }
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            return {
                "state": state,
                "cycle": year,
                "status": "unavailable",
                "detail": str(exc),
                "source_url": url,
            }

    with ThreadPoolExecutor(max_workers=4) as pool:
        history.extend(pool.map(fetch_history, jobs))
    report = {
        "as_of": as_of.isoformat(),
        "election_date": election_day(2026).isoformat(),
        "reporting_states": len(states),
        "rows": len(frame),
        "demographic_states": sorted({row["state"] for row in demographics}),
        "sources": sorted(frame.source.unique()),
        "issues": issues,
        "historical_context": history,
        "model_gate": {
            "accepted": False,
            "probability_weight": 0.0,
            "reason": (
                "No comparable as-published multi-cycle turnout features with validated "
                "incremental forecast gain. Historical 'returned' can include in-person ballots. "
                "Registration and timing cannot identify candidate preference."
            ),
            "required": (
                "Comparable ballot modes, publication timestamps, days-before-election "
                "alignment, and held-out cycle Brier/MAE improvement over polls."
            ),
        },
        "definitions": {
            "requested": (
                "Mail requests or ballots issued, depending on state; never add to ballots cast."
            ),
            "returned": (
                "Reported mail returns; returned does not necessarily mean accepted or counted."
            ),
            "inperson": "Reported in-person early ballots.",
            "party": (
                "Registered affiliation where reported, not candidate votes. "
                "Unspecified is not unaffiliated."
            ),
            "coverage": "Totals cover reporting states and methods only. Missing is not zero.",
        },
        "references": [
            {"name": "civicAPI early vote", "url": "https://civicapi.org/early-vote"},
            {"name": "North Carolina State Board of Elections", "url": NC_REFERENCE},
            {"name": "Florida Division of Elections", "url": FL_STATS},
            {
                "name": "UF Election Lab (independent comparison)",
                "url": "https://election.lab.ufl.edu/early-vote/2026-early-voting/",
            },
        ],
    }
    demographic_columns = [
        "state",
        "category",
        "dimension",
        "group",
        "count",
        "source",
        "source_url",
        "snapshot_date",
        "date_basis",
        "source_sha256",
    ]
    return frame, pd.DataFrame(demographics).reindex(columns=demographic_columns), report
