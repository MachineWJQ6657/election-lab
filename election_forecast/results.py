"""Score immutable forecasts against separately sourced, status-aware observations.

No inference from a vote lead, percentage reporting, or a media call to certification.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .names import COMPATIBLE_NAME_MATCHES, candidate_name_match
from .simulation import select_race_matchups


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    party: str = ""
    votes: int | None = Field(default=None, ge=0, strict=True)


class ResultObservation(BaseModel):
    """A single source's assertion, never a winner inferred from partial votes."""

    model_config = ConfigDict(extra="forbid")
    cycle: Literal[2026] = 2026
    election_date: Literal["2026-11-03"] = "2026-11-03"
    stage: Literal["general"] = "general"
    office: Literal["senate", "house", "governor", "generic_ballot"]
    location: str = Field(pattern=r"^(US|[A-Z]{2}(-([0-9]{2}|AL))?)$")
    contest_type: Literal["regular", "special", "national_popular_vote"] = "regular"
    source_id: str
    status: Literal["unresolved", "preliminary", "called", "certified"]
    winner_candidate: str | None = None
    candidates: list[CandidateResult] = Field(default_factory=list)
    vote_basis: Literal["plurality", "first_choice", "final_rcv", "runoff", "national_house"] = (
        "plurality"
    )
    all_candidates_included: bool = False
    source_updated_at: str | None = None
    status_evidence: str = Field(min_length=1)
    certification_url: str | None = None
    certified_at: datetime | None = None

    @model_validator(mode="after")
    def check_status(self) -> ResultObservation:
        if (self.status in {"called", "certified"}) != bool(self.winner_candidate):
            raise ValueError("Only explicit called/certified outcomes have a winner")
        if self.status == "certified":
            if not self.certification_url or self.certified_at is None:
                raise ValueError("Certified outcomes require a certification document and time")
            if self.certified_at.tzinfo is None:
                raise ValueError("Certification timestamp must include a timezone")
        if len({c.name.casefold() for c in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate candidate rows (aggregate fusion-party lines first)")
        if self.office == "house" and "-" not in self.location:
            raise ValueError("House results require an explicit district, including -AL")
        if self.office == "generic_ballot" and (
            self.location != "US" or self.contest_type != "national_popular_vote"
        ):
            raise ValueError("Generic ballot requires a national House popular-vote result")
        return self


def verify_release(directory: Path) -> dict[str, str]:
    """Check sealed files, not today's engine or mutable production tables."""
    release = json.loads((directory / "release.json").read_text("utf-8"))
    if release["release_kind"] != "final_pre_result_forecast" or release["as_of"] != "2026-11-03":
        raise ValueError("Expected the frozen November 3, 2026 pre-result release")
    expected = dict(release["forecast_output_sha256"])
    expected.update(
        {f"{key}.parquet": value for key, value in release["input_table_sha256"].items()}
    )
    for name, digest in expected.items():
        if Path(name).name != name or sha256(directory / name) != digest:
            raise ValueError(f"Frozen release integrity failure: {name}")
    return {p.name: sha256(p) for p in sorted(directory.iterdir()) if p.is_file()}


def validate_sources(sources: list[dict], directory: Path, as_of: datetime) -> dict[str, dict]:
    result = {}
    for source in sources:
        if source["id"] in result:
            raise ValueError(f"Duplicate source ID: {source['id']}")
        retrieved = datetime.fromisoformat(source["retrieved_at"])
        if retrieved.tzinfo is None or retrieved > as_of:
            raise ValueError(f"Invalid/future retrieval timestamp: {source['id']}")
        if source.get("path"):
            path = (directory / source["path"]).resolve()
            if not path.is_relative_to(directory.resolve()) or sha256(path) != source["sha256"]:
                raise ValueError(f"Result source integrity failure: {source['id']}")
        result[source["id"]] = source
    return result


def same_candidate(left: str, right: str) -> bool:
    return candidate_name_match(left, right) in COMPATIBLE_NAME_MATCHES


def candidate_index(name: str, candidates: list[CandidateResult]) -> int | None:
    matches = [i for i, c in enumerate(candidates) if same_candidate(name, c.name)]
    return matches[0] if len(matches) == 1 else None


def contest_type(office: str, location: str) -> str:
    # The archive has one Senate contest per state; these two are unexpired terms.
    if office == "senate" and location in {"FL", "OH"}:
        return "special"
    return "national_popular_vote" if office == "generic_ballot" else "regular"


def score_forecasts(
    forecasts: pd.DataFrame, observations: list[ResultObservation], sources: dict[str, dict]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One central contest row; missing/unresolved results remain in denominators of coverage.

    Each provider's latest observation replaces its older assertion (including retractions).
    Certified outcomes outrank calls; conflicting equal-status winners are never scored.
    Vote totals retain their own source and status, even when attached to a media call.
    """
    selected, _ = select_race_matchups(forecasts)
    selected_ids = set(selected.race_id)
    excluded = forecasts[~forecasts.race_id.isin(selected_ids)].copy()
    grouped: dict[tuple, list[ResultObservation]] = {}
    for obs in observations:
        source = sources[obs.source_id]
        if not source.get("path") or source.get("error"):
            raise ValueError(f"Observation references unavailable source: {obs.source_id}")
        if obs.status == "certified":
            if source["kind"] != "official":
                raise ValueError("Media returns/calls cannot certify a result")
            if obs.certified_at > datetime.fromisoformat(source["retrieved_at"]):
                raise ValueError("Certification postdates source retrieval")
        key = (obs.office, obs.location, obs.contest_type)
        grouped.setdefault(key, []).append(obs)
    output = []
    for f in selected.to_dict("records"):
        p = float(f["dem_win_probability"])
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError(f"Invalid frozen probability: {f['race_id']}")
        key = (f["office"], f["location"], contest_type(f["office"], f["location"]))
        available = sorted(
            grouped.get(key, []),
            key=lambda o: (
                datetime.fromisoformat(sources[o.source_id]["retrieved_at"]),
                o.source_id,
            ),
        )
        # Retractions must replace the same provider's earlier call, not survive it.
        latest = {}
        for obs in available:
            provider = sources[obs.source_id]["provider"]
            previous = latest.get(provider)
            if (
                previous
                and sources[previous.source_id]["retrieved_at"]
                == sources[obs.source_id]["retrieved_at"]
            ):
                if previous.model_dump() != obs.model_dump():
                    raise ValueError(f"Ambiguous equal-time observations: {key}, {provider}")
            latest[provider] = obs
        available = list(latest.values())
        certified = [o for o in available if o.status == "certified"]
        called = [o for o in available if o.status == "called"]
        outcomes = certified or called
        outcome = outcomes[-1] if outcomes else None
        conflict = bool(
            outcome
            and any(
                not same_candidate(o.winner_candidate, outcome.winner_candidate) for o in outcomes
            )
        )
        votes = [
            o for o in available if o.candidates and all(c.votes is not None for c in o.candidates)
        ]
        votes.sort(
            key=lambda o: (
                o.status == "certified",
                sources[o.source_id]["kind"] == "official",
                sources[o.source_id]["retrieved_at"],
            )
        )
        vote = votes[-1] if votes else None
        status = (
            "unresolved"
            if conflict
            else (outcome.status if outcome else ("preliminary" if vote else "unresolved"))
        )
        row = {
            k: f.get(k)
            for k in (
                "race_id",
                "cycle",
                "office",
                "location",
                "dem_candidate",
                "rep_candidate",
                "dem_side_party",
                "probability_event",
                "probability_source",
                "validation_scope",
                "model",
                "predicted_margin",
                "dem_win_probability",
            )
        }
        row.update(
            contest_type=key[2],
            result_status=status,
            winner_candidate=outcome.winner_candidate if outcome and not conflict else None,
            outcome_source_id=outcome.source_id if outcome else None,
            outcome_source_url=sources[outcome.source_id]["url"] if outcome else None,
            outcome_retrieved_at=sources[outcome.source_id]["retrieved_at"] if outcome else None,
            vote_source_id=vote.source_id if vote else None,
            vote_source_url=sources[vote.source_id]["url"] if vote else None,
            vote_retrieved_at=sources[vote.source_id]["retrieved_at"] if vote else None,
            vote_result_status=vote.status if vote else None,
            vote_basis=vote.vote_basis if vote else None,
            probability_scored=False,
            margin_scored=False,
            outcome=None,
            brier=None,
            log_loss=None,
            winner_correct=None,
            actual_margin=None,
            margin_error=None,
            absolute_margin_error=None,
            squared_margin_error=None,
            probability_exclusion="",
            margin_exclusion="",
            identity_scope=None,
        )
        if not outcome or conflict:
            reason = "conflicting_winner_assertions" if conflict else "unresolved_or_no_call"
        elif f.get("probability_event") != "candidate_win":
            reason = "pairwise_probability_not_full_contest_win"
        elif f["office"] == "generic_ballot":
            reason = "generic_ballot_requires_complete_national_house_votes"
        else:
            # Calls can identify the named candidate event without providing vote totals.
            dem_won = same_candidate(f["dem_candidate"], outcome.winner_candidate)
            rep_won = same_candidate(f["rep_candidate"], outcome.winner_candidate)
            reason = "" if dem_won != rep_won else "winner_not_uniquely_in_frozen_matchup"
            if not reason and vote:
                di = candidate_index(f["dem_candidate"], vote.candidates)
                ri = candidate_index(f["rep_candidate"], vote.candidates)
                if di is None or ri is None or di == ri:
                    reason = "frozen_matchup_differs_from_reported_candidates"
            if not reason:
                y = int(dem_won)
                # Finite, explicitly clipped log loss; Brier uses the unmodified probability.
                clipped = min(max(p, 1e-15), 1 - 1e-15)
                row.update(
                    probability_scored=True,
                    outcome=y,
                    brier=(p - y) ** 2,
                    log_loss=-(y * math.log(clipped) + (1 - y) * math.log1p(-clipped)),
                    winner_correct=float((p > 0.5) == bool(y)) if p != 0.5 else 0.5,
                    identity_scope="reported_candidate_list" if vote else "called_winner_only",
                )
        row["probability_exclusion"] = reason
        margin_reason = reason
        if not margin_reason:
            if not vote:
                margin_reason = "no_vote_totals"
            elif vote.vote_basis != "plurality":
                margin_reason = "ranked_choice_or_runoff_margin_not_comparable"
            elif not vote.all_candidates_included:
                margin_reason = "all_candidate_vote_denominator_missing"
            elif f["probability_source"] != "poll_model" or pd.isna(f["predicted_margin"]):
                margin_reason = "rating_prior_has_no_validated_vote_margin"
            else:
                di = candidate_index(f["dem_candidate"], vote.candidates)
                ri = candidate_index(f["rep_candidate"], vote.candidates)
                total = sum(c.votes for c in vote.candidates)
                if total == 0:
                    margin_reason = "zero_total_votes"
                else:
                    actual = 100 * (vote.candidates[di].votes - vote.candidates[ri].votes) / total
                    error = float(f["predicted_margin"]) - actual
                    row.update(
                        margin_scored=True,
                        actual_margin=actual,
                        margin_error=error,
                        absolute_margin_error=abs(error),
                        squared_margin_error=error**2,
                    )
        row["margin_exclusion"] = margin_reason
        output.append(row)
    return pd.DataFrame(output), excluded


def aggregate_scores(races: pd.DataFrame) -> pd.DataFrame:
    """Disjoint called/certified groups, plus explicit provisional and certified-only views."""
    records = []
    for office in ["__overall__", *sorted(races.office.unique())]:
        office_rows = races if office == "__overall__" else races[races.office.eq(office)]
        for source_scope in ["all", "poll_model", "external_rating_prior"]:
            scope = (
                office_rows
                if source_scope == "all"
                else office_rows[office_rows.probability_source.eq(source_scope)]
            )
            for status in ["all_resolved", "called", "certified", "preliminary", "unresolved"]:
                sub = (
                    scope[scope.result_status.isin(["called", "certified"])]
                    if (status == "all_resolved")
                    else scope[scope.result_status.eq(status)]
                )
                probs = sub[sub.probability_scored]
                margins = sub[sub.margin_scored]
                records.append(
                    {
                        "office": office,
                        "forecast_scope": source_scope,
                        "result_status": status,
                        "forecast_contests": len(scope),
                        "status_contests": len(sub),
                        "probability_scored": len(probs),
                        "margin_scored": len(margins),
                        "winner_accuracy": float(probs.winner_correct.mean())
                        if len(probs)
                        else None,
                        "brier": float(probs.brier.mean()) if len(probs) else None,
                        "log_loss": float(probs.log_loss.mean()) if len(probs) else None,
                        "margin_mae": float(margins.absolute_margin_error.mean())
                        if len(margins)
                        else None,
                        "margin_bias": float(margins.margin_error.mean()) if len(margins) else None,
                        "margin_rmse": math.sqrt(float(margins.squared_margin_error.mean()))
                        if len(margins)
                        else None,
                        "preliminary_vote_margins": int(
                            margins.vote_result_status.eq("preliminary").sum()
                        ),
                    }
                )
    return pd.DataFrame(records)
