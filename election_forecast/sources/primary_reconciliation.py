"""Fail-closed, document-verified corrections to conflicting aggregator transcriptions."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from ..http_cache import CachedHTTPClient


def canonical_release_url(value: object) -> str:
    parsed = urlsplit(str(value))
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def reconcile_primary_releases(
    frame: pd.DataFrame, *, client: CachedHTTPClient, rules_path: Path
) -> tuple[pd.DataFrame, list[dict]]:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    result = frame.copy()
    audit = []
    for rule in rules["releases"]:
        mask = (
            result.source_url.map(canonical_release_url).eq(canonical_release_url(rule["url"]))
            & result.location.eq(rule["location"])
            & result.office.isin(rule["offices"])
        )
        if not mask.any():
            continue
        verification_origin = "current_response"
        try:
            payload = client.get(rule["url"])
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {403, 404}:
                raise
            # This older survey is still usable as archived evidence. Do not
            # bypass access restrictions or call its prior fact check live.
            payload = client.get_cached(rule["url"])
            verification_origin = "archived_review_source_unavailable"
        digest = hashlib.sha256(payload).hexdigest()
        if "sha256" in rule and digest != rule["sha256"]:
            raise ValueError(f"Reviewed primary document changed: {rule['url']}")
        if rule.get("required_patterns"):
            text = " ".join(BeautifulSoup(payload, "html.parser").get_text(" ", strip=True).split())
            if any(not re.search(pattern, text) for pattern in rule["required_patterns"]):
                raise ValueError(f"Reviewed primary release facts changed: {rule['url']}")
        before = result.loc[
            mask, ["source", "office", "end_date", "sample_size", "dem_pct", "rep_pct"]
        ]
        # Accommodate non-integer percentages and dates in previously sparse columns.
        for field in ("dem_pct", "rep_pct", "sample_size"):
            result[field] = pd.to_numeric(result[field], errors="coerce").astype(float)
        for key in (
            "pollster",
            "source_url",
            "start_date",
            "end_date",
            "population",
            "publication_date",
            "sample_size_basis",
            "source_content_sha256",
        ):
            if key not in result:
                result[key] = pd.Series(None, index=result.index, dtype="object")
            else:
                result[key] = result[key].astype("object")
        for key in (
            "start_date",
            "end_date",
            "sample_size",
            "population",
            "pollster",
            "sample_size_basis",
        ):
            result.loc[mask, key] = rule[key]
        if "publication_date" in rule:
            result.loc[mask, "publication_date"] = rule["publication_date"]
        result.loc[mask, "source_url"] = rule["url"]
        result.loc[mask, "source_content_sha256"] = digest
        result.loc[mask, "primary_source_verified"] = True
        result.loc[mask, "primary_review_date"] = rules["reviewed_as_of"]
        for office, values in rule["offices"].items():
            selected = mask & result.office.eq(office)
            for key, value in values.items():
                result.loc[selected, key] = value
        audit.append(
            {
                "verification_origin": verification_origin,
                "url": rule["url"],
                "sha256": digest,
                "upstream_rows": before.to_dict("records"),
                "rule": rule,
            }
        )
    # The raw table still records one row per upstream source. Normal deduplication
    # then collapses versions of the verified survey without multiplying its weight.
    result["margin"] = result.dem_pct - result.rep_pct
    return result, audit
