"""Data authenticity, provenance, and consistency audits."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from .names import candidate_key, candidate_name_match
from .settings import Settings, settings


def _last_name(value: object, *, fec_format: bool = False) -> str:
    text = str(value).lower()
    if fec_format and "," in text:
        text = text.split(",", 1)[0]
    return candidate_key(text)


def _fec_party(value: object) -> str | None:
    party = str(value).upper()
    if party.startswith("DEM") or party == "DFL":
        return "D"
    if party.startswith("REP"):
        return "R"
    return None


def audit_fec_candidates(catalog: pd.DataFrame, fec: pd.DataFrame) -> pd.DataFrame:
    """Check whether named federal candidates have a compatible FEC filing."""
    official = fec.copy()
    official["party_normalized"] = official["party"].map(_fec_party)
    official["last_name"] = official["candidate_name"].map(
        lambda value: _last_name(value, fec_format=True)
    )
    rows: list[dict[str, object]] = []
    for race in catalog[catalog["office"].isin(["house", "senate"])].itertuples():
        for party, column in (("D", "dem_candidate"), ("R", "rep_candidate")):
            candidate = str(getattr(race, column))
            if candidate.endswith("TBD"):
                continue
            last_name = _last_name(candidate)
            surname_matches = official[
                (official["office_name"] == race.office)
                & (official["location"] == race.location)
                & (official["party_normalized"] == party)
                & (official["last_name"] == last_name)
            ]
            strengths = surname_matches["candidate_name"].map(
                lambda value, name=candidate: candidate_name_match(
                    name, value, right_fec_format=True
                )
            )
            matches = surname_matches.loc[
                strengths.isin(
                    ["given_name_compatible", "initial_compatible", "verified_alias_compatible"]
                )
            ]
            rows.append(
                {
                    "office": race.office,
                    "location": race.location,
                    "party": party,
                    "catalog_candidate": candidate,
                    "fec_last_name": last_name,
                    "fec_match": not matches.empty,
                    "fec_candidate_ids": ",".join(matches["candidate_id"].astype(str)),
                    "surname_candidate_ids_for_review": ",".join(
                        surname_matches["candidate_id"].astype(str)
                    ),
                    "name_match_strength": (
                        ",".join(sorted(set(strengths.loc[matches.index])))
                        if not matches.empty
                        else ",".join(sorted(set(strengths))) or "no_compatible_filing"
                    ),
                    "interpretation": (
                        "compatible FEC filing found"
                        if not matches.empty
                        else (
                            "not matched; this is a review flag, not proof the candidate is invalid"
                        )
                    ),
                }
            )
    return pd.DataFrame.from_records(rows)


def audit_cache(project_settings: Settings = settings) -> dict[str, object]:
    metadata_files = list(project_settings.cache_dir.glob("*.json"))
    valid_hashes = 0
    invalid_hashes = 0
    statuses: dict[str, int] = {}
    domains: dict[str, int] = {}
    for path in metadata_files:
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            payload_path = Path(str(path)[: -len(".json")])
            expected = metadata.get("sha256")
            if payload_path.exists() and expected:
                actual = hashlib.sha256(payload_path.read_bytes()).hexdigest()
                if actual == expected:
                    valid_hashes += 1
                else:
                    invalid_hashes += 1
            status = str(metadata.get("status_code", "unknown"))
            statuses[status] = statuses.get(status, 0) + 1
            domain = urlparse(str(metadata.get("url", ""))).netloc
            domains[domain] = domains.get(domain, 0) + 1
        except (OSError, ValueError, TypeError):
            invalid_hashes += 1
    return {
        "metadata_files": len(metadata_files),
        "payload_hashes_verified": valid_hashes,
        "invalid_or_unreadable_entries": invalid_hashes,
        "http_statuses": statuses,
        "domains": domains,
    }


def run_authenticity_audit(
    *,
    history: pd.DataFrame,
    archive: pd.DataFrame,
    latest: pd.DataFrame,
    catalog: pd.DataFrame,
    fec: pd.DataFrame,
    result_comparison: pd.DataFrame,
    as_of: date | None = None,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    """Audit traceability and consistency without claiming unknowable ground truth."""
    as_of = as_of or date.today()
    issues: list[dict[str, object]] = []
    poll_sets = {"history": history, "archive": archive, "latest": latest}
    dataset_summary: dict[str, object] = {}
    for name, frame in poll_sets.items():
        dates = pd.to_datetime(frame["end_date"], errors="coerce")
        elections = pd.to_datetime(frame["election_date"], errors="coerce")
        invalid_pct = (~frame["dem_pct"].between(0, 100)) | (~frame["rep_pct"].between(0, 100))
        after_election = dates > elections
        future = dates.dt.date > as_of if name == "latest" else pd.Series(False, index=frame.index)
        duplicates = frame.duplicated(["source", "source_id"], keep=False)
        valid_url = (
            frame["source_url"]
            .fillna("")
            .map(
                lambda value: (
                    urlparse(str(value)).scheme in {"http", "https"}
                    and bool(urlparse(str(value)).netloc)
                )
            )
        )
        for check, mask, severity in (
            ("invalid_percentage", invalid_pct, "error"),
            ("poll_after_election", after_election, "error"),
            ("future_dated_poll", future, "error"),
            ("duplicate_source_id", duplicates, "warning"),
            ("invalid_or_missing_source_url", ~valid_url, "warning"),
        ):
            if int(mask.sum()):
                issues.append(
                    {
                        "dataset": name,
                        "check": check,
                        "severity": severity,
                        "rows": int(mask.sum()),
                        "detail": "See normalized dataset for affected records",
                    }
                )
        dataset_summary[name] = {
            "rows": len(frame),
            "sources": sorted(str(item) for item in frame["source"].unique()),
            "pollsters": int(frame["pollster"].nunique()),
            "source_url_share": float(frame["source_url"].notna().mean()),
            "valid_http_source_url_share": float(valid_url.mean()),
            "invalid_percentages": int(invalid_pct.sum()),
            "after_election": int(after_election.sum()),
            "future_dated": int(future.sum()),
            "duplicate_source_ids": int(duplicates.sum()),
        }

    candidate_audit = audit_fec_candidates(catalog, fec)
    unmatched = int((~candidate_audit["fec_match"]).sum()) if not candidate_audit.empty else 0
    if unmatched:
        issues.append(
            {
                "dataset": "candidate_catalog",
                "check": "candidate_name_identity_requires_review",
                "severity": "warning",
                "rows": unmatched,
                "detail": "Given names/initials could not establish a compatible filing. "
                "Nicknames, middle names and surname-only records can require adjudication; "
                "this is not proof of invalid candidacy.",
            }
        )
    comparison = result_comparison.copy()
    discrepancies = comparison[comparison["absolute_margin_difference"] > 0.25]
    if len(discrepancies):
        issues.append(
            {
                "dataset": "reference_results_2024",
                "check": "mit_margin_difference_gt_0.25",
                "severity": "warning",
                "rows": len(discrepancies),
                "detail": "Review aggregation modes, special elections, and source revisions",
            }
        )
    latest_domains = (
        latest["source_url"].dropna().map(lambda value: urlparse(str(value)).netloc).value_counts()
    )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "scope_note": (
            "This audit verifies provenance, schema consistency, hashes, cross-source agreement, "
            "and official filing matches. It cannot prove that every published poll "
            "response is true."
        ),
        "datasets": dataset_summary,
        "cache": audit_cache(),
        "latest_source_domains": {str(key): int(value) for key, value in latest_domains.items()},
        "cross_source_corroborated_polls": int((latest.get("source_count", 1) > 1).sum()),
        "fec_candidate_check": {
            "checked": len(candidate_audit),
            "matched": int(candidate_audit["fec_match"].sum()) if len(candidate_audit) else 0,
            "unmatched_review_flags": unmatched,
            "match_strength_counts": {
                str(key): int(value)
                for key, value in candidate_audit.name_match_strength.value_counts().items()
            }
            if len(candidate_audit)
            else {},
            "important_note": "Name-compatible filings are not identity, ballot qualification "
            "or nomination proof. Unresolved nicknames are review flags, not invalid candidates.",
        },
        "mit_result_crosscheck": {
            "races": len(comparison),
            "median_absolute_margin_difference": float(
                comparison["absolute_margin_difference"].median()
            ),
            "max_absolute_margin_difference": float(comparison["absolute_margin_difference"].max()),
            "differences_gt_0_25": len(discrepancies),
        },
        "issue_count": len(issues),
        "verdict": "pass_with_review_flags" if issues or unmatched else "pass",
    }
    return report, pd.DataFrame.from_records(issues), candidate_audit
