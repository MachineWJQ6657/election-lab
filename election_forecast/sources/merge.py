"""Cross-source current-poll deduplication with corroboration metadata."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from ..names import candidate_key

AGGREGATOR_DOMAINS = {
    "pollingsource.com",
    "www.pollingsource.com",
    "270towin.com",
    "www.270towin.com",
    "docs.google.com",
}
POLLSTER_MOE_SUFFIX_RE = re.compile(r"\s*(?:±|\+/-)\s*\d+(?:\.\d+)?%?\s*$", re.IGNORECASE)
POLLSTER_PARTISAN_TAG_RE = re.compile(r"\s+partisan\s*[·:|/-]?\s*[DR]\s*$", re.IGNORECASE)


def _last_name(value: object) -> str:
    return candidate_key(value) or "unknown"


def _clean_pollster(value: object) -> str:
    text = " ".join(str(value).split())
    text = re.sub(r"\s+20\d{2}\s+err\b.*$", "", text, flags=re.IGNORECASE)
    text = POLLSTER_MOE_SUFFIX_RE.sub("", text)
    text = POLLSTER_PARTISAN_TAG_RE.sub("", text)
    return text.strip()


def _sample_compatible(left: object, right: object) -> bool:
    if pd.isna(left) or pd.isna(right):
        return True
    left_value = float(left)
    right_value = float(right)
    tolerance = max(10.0, 0.02 * max(left_value, right_value))
    return abs(left_value - right_value) <= tolerance


def _same_pollster(left: object, right: object) -> bool:
    """Require a shared distinctive organization name, not matching vote shares."""

    def tokens(value: object) -> set[str]:
        text = re.sub(r"\([DR]\)", "", _clean_pollster(value), flags=re.IGNORECASE)
        words = set(re.findall(r"[a-z0-9]+", text.casefold()))
        return words - {
            "poll",
            "polls",
            "polling",
            "research",
            "public",
            "opinion",
            "the",
            "university",
            "univ",
            "college",
            "of",
            "and",
            "group",
            "insights",
            "news",
            "survey",
            "project",
            "state",
            "co",
            "inc",
        }

    first, second = tokens(left), tokens(right)
    # Fox publishes surveys conducted jointly by Beacon and Shaw. Aggregators
    # may credit either the publisher or that specific two-firm partnership.
    if (first == {"fox"} and {"beacon", "shaw"}.issubset(second)) or (
        second == {"fox"} and {"beacon", "shaw"}.issubset(first)
    ):
        return True
    return bool(first & second) and (first.issubset(second) or second.issubset(first))


def _same_survey_identity(left: pd.Series, right: pd.Series) -> bool:
    left_url, right_url = str(left.get("source_url", "")), str(right.get("source_url", ""))
    parsed = urlparse(left_url)
    shared_document = (
        left_url == right_url
        and parsed.scheme in {"http", "https"}
        and parsed.netloc.casefold() not in AGGREGATOR_DOMAINS
        and parsed.path not in {"", "/"}
    )
    return shared_document or _same_pollster(left["pollster"], right["pollster"])


def _survey_clusters(data: pd.DataFrame) -> pd.Series:
    """Cluster cross-source duplicates despite publication/end-date conventions."""
    base_columns = [
        "office",
        "location",
        "dem_key",
        "rep_key",
        "dem_value_key",
        "rep_value_key",
    ]
    assignments = pd.Series(index=data.index, dtype="object")
    for base_key, group in data.groupby(base_columns, sort=False, dropna=False):
        clusters: list[list[object]] = []
        for index in group.sort_values("parsed_end_date").index:
            row = data.loc[index]
            assigned = None
            for cluster_number, members in enumerate(clusters):
                # Never bridge distinct waves from one source through a third row.
                if any(
                    str(data.loc[item, "source"]) == str(row["source"])
                    and data.loc[item, "parsed_end_date"] != row["parsed_end_date"]
                    for item in members
                ):
                    continue
                for member_index in members:
                    member = data.loc[member_index]
                    day_difference = abs((row["parsed_end_date"] - member["parsed_end_date"]).days)
                    same_day = day_difference == 0
                    different_source = str(row["source"]) != str(member["source"])
                    both_samples_known = pd.notna(row["sample_size"]) and pd.notna(
                        member["sample_size"]
                    )
                    # Allow release-date differences only with survey identity.
                    date_tolerance = 21 if both_samples_known else 4
                    if (
                        day_difference <= date_tolerance
                        and (same_day or different_source)
                        and _same_survey_identity(row, member)
                        and (
                            row["population"] == member["population"]
                            or "unknown" in {str(row["population"]), str(member["population"])}
                        )
                        and _sample_compatible(row["sample_size"], member["sample_size"])
                    ):
                        assigned = cluster_number
                        break
                if assigned is not None:
                    break
            if assigned is None:
                assigned = len(clusters)
                clusters.append([])
            clusters[assigned].append(index)
            assignments.loc[index] = "|".join(map(str, base_key)) + f"|{assigned}"
    return assignments


def merge_current_polls(frame: pd.DataFrame) -> pd.DataFrame:
    """Do not count one underlying survey twice when aggregators overlap."""
    data = frame.copy()
    if "sample_size" not in data:
        data["sample_size"] = np.nan
    if "population" not in data:
        data["population"] = "unknown"
    if "partisan" not in data:
        data["partisan"] = None
    data["parsed_end_date"] = pd.to_datetime(data["end_date"])
    data["dem_key"] = data["dem_candidate"].map(_last_name)
    data["rep_key"] = data["rep_candidate"].map(_last_name)
    # Some sources preserve tenths while others publish the identical survey rounded
    # to whole percentages. Sample compatibility below prevents broad over-merging.
    data["dem_value_key"] = pd.to_numeric(data["dem_pct"]).round(0)
    data["rep_value_key"] = pd.to_numeric(data["rep_pct"]).round(0)
    data["cross_source_key"] = _survey_clusters(data)
    corroboration = data.groupby("cross_source_key")["source"].agg(
        lambda values: ",".join(sorted(set(values)))
    )
    data["corroborated_sources"] = data["cross_source_key"].map(corroboration)
    data["source_count"] = data["corroborated_sources"].str.count(",") + 1
    aliases = data.groupby("cross_source_key")["pollster"].agg(
        lambda values: " | ".join(sorted(set(str(value) for value in values)))
    )
    data["reported_pollster_aliases"] = data["cross_source_key"].map(aliases)
    data["clean_pollster"] = data["pollster"].map(_clean_pollster)
    canonical_pollsters = data.groupby("cross_source_key")["clean_pollster"].agg(
        lambda values: max(
            {str(value).strip() for value in values if str(value).strip()},
            key=len,
        )
    )
    data["canonical_pollster"] = data["cross_source_key"].map(canonical_pollsters)
    partisan_labels = data.groupby("cross_source_key")["partisan"].agg(
        lambda values: next(
            (str(value) for value in values if pd.notna(value) and str(value).strip()),
            None,
        )
    )
    data["merged_partisan"] = data["cross_source_key"].map(partisan_labels)
    date_variants = data.groupby("cross_source_key")["parsed_end_date"].agg(
        lambda values: " | ".join(sorted({value.date().isoformat() for value in values}))
    )
    data["reported_end_dates"] = data["cross_source_key"].map(date_variants)
    source_urls = data.groupby("cross_source_key")["source_url"].agg(
        lambda values: " | ".join(sorted({str(value) for value in values if pd.notna(value)}))
    )
    data["reported_source_urls"] = data["cross_source_key"].map(source_urls)
    data["direct_source"] = (
        data["source_url"]
        .fillna("")
        .map(lambda value: int(urlparse(str(value)).netloc.casefold() not in AGGREGATOR_DOMAINS))
    )
    population_detail = data["population"].fillna("unknown").astype(str).ne("unknown").astype(int)
    data["detail_score"] = (
        1000
        * data.get("primary_source_verified", pd.Series(False, index=data.index))
        .fillna(False)
        .astype(int)
        + 100 * data["direct_source"]
        + 10 * data["sample_size"].notna().astype(int)
        + 5 * population_detail
        + data["pollster"].fillna("").astype(str).str.len() / 100.0
    )
    result = (
        data.sort_values(["source_count", "detail_score"], ascending=False)
        .drop_duplicates("cross_source_key", keep="first")
        .drop(
            columns=[
                "cross_source_key",
                "direct_source",
                "detail_score",
                "parsed_end_date",
                "dem_key",
                "rep_key",
                "dem_value_key",
                "rep_value_key",
                "clean_pollster",
            ]
        )
    )
    result["pollster"] = result.pop("canonical_pollster")
    result["partisan"] = result.pop("merged_partisan")
    # Adapters use different candidate slug conventions (full name versus surname).
    # Canonicalize after provenance-aware deduplication so one matchup becomes one pool.
    cycles = (
        result["cycle"].astype(str) if "cycle" in result else pd.Series("2026", index=result.index)
    )
    result["race_id"] = (
        cycles
        + ":"
        + result["office"].astype(str)
        + ":"
        + result["location"].astype(str)
        + ":"
        + result["dem_candidate"].map(_last_name)
        + ":"
        + result["rep_candidate"].map(_last_name)
    )
    # Keep a numeric source count even when a single source name contains punctuation.
    result["source_count"] = pd.to_numeric(result["source_count"], errors="coerce").fillna(1)
    result["source_count"] = np.maximum(result["source_count"].astype(int), 1)
    return result.sort_values(["office", "location", "end_date"]).reset_index(drop=True)
