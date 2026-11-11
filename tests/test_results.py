import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from election_forecast.results import (
    ResultObservation,
    aggregate_scores,
    score_forecasts,
    sha256,
    validate_sources,
    verify_release,
)


def forecast(**overrides):
    row = dict(
        race_id="2026:senate:TX:smith:jones",
        cycle=2026,
        office="senate",
        location="TX",
        dem_candidate="Alice Smith",
        rep_candidate="Bob Jones",
        dem_win_probability=0.8,
        predicted_margin=10.0,
        probability_source="poll_model",
        probability_event="candidate_win",
        model="test",
        poll_count=10,
        catalog_candidate_match=True,
    )
    row.update(overrides)
    return pd.DataFrame([row])


def source(provider="State election office", kind="official", **overrides):
    row = dict(
        provider=provider,
        kind=kind,
        path="snapshot.json",
        url="https://example.gov/results",
        retrieved_at="2026-11-11T05:00:00+00:00",
    )
    row.update(overrides)
    return row


def observation(**overrides):
    row = dict(
        office="senate",
        location="TX",
        source_id="votes",
        status="preliminary",
        status_evidence="Unofficial state returns",
        all_candidates_included=True,
        candidates=[
            dict(name="Alice Smith", votes=500, party="D"),
            dict(name="Bob Jones", votes=400, party="R"),
            dict(name="Carol Green", votes=100, party="I"),
        ],
    )
    row.update(overrides)
    return ResultObservation.model_validate(row)


def test_call_uses_separate_preliminary_vote_provenance_and_all_candidate_denominator():
    votes = observation()
    call = observation(
        source_id="call", status="called", winner_candidate="Bob Jones", candidates=[]
    )
    races, _ = score_forecasts(
        forecast(),
        [votes, call],
        {
            "votes": source(),
            "call": source("AP", "media"),
        },
    )
    row = races.iloc[0]
    assert row.result_status == "called" and row.vote_result_status == "preliminary"
    assert row.brier == pytest.approx(0.64)
    assert row.log_loss == pytest.approx(1.6094379124)
    assert row.actual_margin == 10 and row.margin_error == 0
    summary = aggregate_scores(races)
    certified = summary[summary.result_status.eq("certified")]
    assert certified.probability_scored.sum() == 0 and certified.brier.isna().all()


def test_preliminary_leader_and_missing_races_are_unscored():
    for observations in [[], [observation()]]:
        scores, _ = score_forecasts(forecast(), observations, {"votes": source()})
        assert not scores.probability_scored.any() and not scores.margin_scored.any()
        assert scores.brier.isna().all() and scores.actual_margin.isna().all()


def test_certification_requires_document_time_and_official_source():
    with pytest.raises(ValidationError, match="certification document"):
        observation(status="certified", winner_candidate="Alice Smith")
    certified = observation(
        status="certified",
        winner_candidate="Alice Smith",
        certification_url="https://example.gov/canvass",
        certified_at="2026-11-10T12:00:00+00:00",
    )
    with pytest.raises(ValueError, match="cannot certify"):
        score_forecasts(forecast(), [certified], {"votes": source("AP", "media")})
    scores, _ = score_forecasts(forecast(), [certified], {"votes": source()})
    assert scores.iloc[0].result_status == "certified"
    assert scores.iloc[0].brier == pytest.approx(0.04)


def test_conflicting_calls_and_provider_retraction_are_unscored():
    call = observation(source_id="a", status="called", winner_candidate="Alice Smith")
    opposite = observation(source_id="b", status="called", winner_candidate="Bob Jones")
    scores, _ = score_forecasts(
        forecast(),
        [call, opposite],
        {
            "a": source("AP", "media"),
            "b": source("CBS", "media"),
        },
    )
    assert scores.iloc[0].probability_exclusion == "conflicting_winner_assertions"
    retraction = observation(source_id="retracted", status="unresolved", candidates=[])
    scores, _ = score_forecasts(
        forecast(),
        [call, retraction],
        {
            "a": source("AP", "media"),
            "retracted": source("AP", "media", retrieved_at="2026-11-11T06:00:00+00:00"),
        },
    )
    assert not scores.probability_scored.any()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"probability_event": "pairwise_comparison_only"}, "pairwise"),
        ({"rep_candidate": "Other Nominee"}, "matchup_differs"),
    ],
)
def test_candidate_event_must_be_comparable(change, reason):
    call = observation(status="called", winner_candidate="Alice Smith")
    scores, _ = score_forecasts(forecast(**change), [call], {"votes": source()})
    assert reason in scores.iloc[0].probability_exclusion


@pytest.mark.parametrize(
    "basis,prob_source",
    [
        ("final_rcv", "poll_model"),
        ("runoff", "poll_model"),
        ("plurality", "external_rating_prior"),
    ],
)
def test_incomparable_margins_are_excluded(basis, prob_source):
    call = observation(status="called", winner_candidate="Alice Smith", vote_basis=basis)
    scores, _ = score_forecasts(
        forecast(probability_source=prob_source), [call], {"votes": source()}
    )
    assert scores.probability_scored.all() and not scores.margin_scored.any()


def test_alternative_matchups_selected_before_results_and_specials_do_not_cross_join():
    rows = pd.concat(
        [
            forecast(),
            forecast(
                race_id="alternative",
                catalog_candidate_match=False,
                dem_candidate="Other Democrat",
                dem_win_probability=0.1,
            ),
        ]
    )
    call = observation(status="called", winner_candidate="Alice Smith", contest_type="special")
    scores, excluded = score_forecasts(rows, [call], {"votes": source()})
    assert len(scores) == 1 and excluded.race_id.tolist() == ["alternative"]
    assert scores.iloc[0].result_status == "unresolved"


def test_source_and_frozen_archive_integrity(tmp_path):
    raw = tmp_path / "snapshot.json"
    raw.write_bytes(b"retained result")
    record = {"id": "votes", **source(), "sha256": sha256(raw)}
    validate_sources([record], tmp_path, datetime(2026, 11, 12, tzinfo=UTC))
    with pytest.raises(ValueError, match="future"):
        validate_sources([record], tmp_path, datetime(2026, 11, 10, tzinfo=UTC))
    release = dict(
        release_kind="final_pre_result_forecast",
        as_of="2026-11-03",
        forecast_output_sha256={raw.name: sha256(raw)},
        input_table_sha256={},
    )
    (tmp_path / "release.json").write_text(json.dumps(release))
    verify_release(tmp_path)
    raw.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        validate_sources([record], tmp_path, datetime(2026, 11, 12, tzinfo=UTC))
    with pytest.raises(ValueError, match="integrity"):
        verify_release(tmp_path)
