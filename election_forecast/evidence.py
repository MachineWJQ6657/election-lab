"""Per-poll evidence weights for auditing current race forecasts."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

import numpy as np
import pandas as pd


def build_poll_evidence(
    polls: pd.DataFrame,
    *,
    as_of_date: date,
    lookback_days: int = 120,
    half_life_days: float = 30.0,
) -> pd.DataFrame:
    """Expose every transparent weighting factor used by the current poll average."""
    frame = polls.copy()
    frame["end_date"] = pd.to_datetime(frame["end_date"])
    cutoff = pd.Timestamp(as_of_date)
    frame = frame[
        (frame["end_date"] <= cutoff)
        & (frame["end_date"] >= cutoff - pd.Timedelta(days=lookback_days))
    ].copy()
    if "publication_date" in frame:
        released = pd.to_datetime(frame["publication_date"], errors="coerce")
        frame = frame.loc[released.isna() | released.le(cutoff)].copy()
    frame["days_old"] = (cutoff - frame["end_date"]).dt.days.clip(lower=0)
    frame["recency_weight"] = np.power(0.5, frame["days_old"] / half_life_days)
    samples = pd.to_numeric(frame["sample_size"], errors="coerce").fillna(600).clip(200, 2400)
    frame["sample_weight"] = np.sqrt(samples / 600.0)
    frame["partisan_discount"] = np.where(frame["partisan"].notna(), 0.82, 1.0)
    frame["population_weight"] = (
        frame["population"]
        .astype(str)
        .map({"lv": 1.0, "rv": 0.92, "v": 0.88, "a": 0.78, "unknown": 0.85})
        .fillna(0.85)
    )
    frequency = frame.groupby(["race_id", "pollster"])["pollster"].transform("size")
    frame["organization_cap"] = 1.0 / np.sqrt(frequency)
    frame["raw_weight"] = (
        frame["recency_weight"]
        * frame["sample_weight"]
        * frame["partisan_discount"]
        * frame["population_weight"]
        * frame["organization_cap"]
    )
    totals = frame.groupby("race_id")["raw_weight"].transform("sum")
    frame["normalized_race_weight"] = frame["raw_weight"] / totals
    frame["margin_contribution"] = frame["normalized_race_weight"] * frame["margin"]
    frame["publisher_domain"] = (
        frame["source_url"].fillna("").map(lambda value: urlparse(str(value)).netloc)
    )
    columns = [
        "race_id",
        "office",
        "location",
        "dem_candidate",
        "rep_candidate",
        "pollster",
        "end_date",
        "days_old",
        "sample_size",
        "population",
        "partisan",
        "pollster_grade",
        "dem_pct",
        "rep_pct",
        "margin",
        "recency_weight",
        "sample_weight",
        "partisan_discount",
        "population_weight",
        "organization_cap",
        "normalized_race_weight",
        "margin_contribution",
        "source",
        "publisher_domain",
        "source_url",
    ]
    provenance_columns = [
        "source_count",
        "corroborated_sources",
        "reported_pollster_aliases",
        "reported_end_dates",
        "reported_source_urls",
        "publication_date",
        "primary_source_verified",
        "sample_size_basis",
        "source_content_sha256",
    ]
    columns.extend(column for column in provenance_columns if column in frame.columns)
    return frame[columns].sort_values(
        ["office", "location", "normalized_race_weight"], ascending=[True, True, False]
    )
