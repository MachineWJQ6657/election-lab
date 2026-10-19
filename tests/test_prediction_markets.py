from datetime import UTC, datetime

import pandas as pd

from election_forecast.market_calibration import (
    MarketCalibrationConfig,
    _candidate_matches,
    add_chamber_market_context,
    build_market_consensus,
    calibrate_race_probabilities,
)
from election_forecast.sources.prediction_markets import _kalshi_record, _polymarket_record

NOW = datetime(2026, 8, 20, tzinfo=UTC)


def test_market_matching_rejects_same_family_predecessor_but_keeps_name_extensions():
    assert not _candidate_matches("Darline Graham", "Lindsey O. Graham (R)", "R")
    assert _candidate_matches("Darline Graham", "Darline Graham Nordone (R)", "R")
    assert _candidate_matches("Darline Graham", "Graham (R)", "R")
    assert not _candidate_matches("Democratic nominee TBD", "Democratic Party", "D")


def test_polymarket_record_devigs_two_party_prices():
    event = {
        "id": "1",
        "slug": "texas-senate-election-winner",
        "title": "Texas Senate Election Winner",
        "markets": [
            {
                "active": True,
                "closed": False,
                "groupItemTitle": "James Talarico (D)",
                "bestBid": 0.51,
                "bestAsk": 0.52,
                "volumeNum": 400_000,
                "liquidityNum": 50_000,
                "updatedAt": "2026-08-20T00:00:00Z",
            },
            {
                "active": True,
                "closed": False,
                "groupItemTitle": "Ken Paxton (R)",
                "bestBid": 0.49,
                "bestAsk": 0.50,
                "volumeNum": 450_000,
                "liquidityNum": 45_000,
                "updatedAt": "2026-08-20T00:00:00Z",
            },
        ],
    }
    record = _polymarket_record(event, NOW)
    assert record is not None
    assert record["office"] == "senate"
    assert record["location"] == "TX"
    assert abs(float(record["dem_probability"]) - 0.515 / 1.01) < 1e-12
    assert float(record["quality_score"]) > 0.8


def test_kalshi_record_uses_bid_ask_midpoints_and_open_interest():
    payload = {
        "event": {
            "event_ticker": "SENATETX-26",
            "series_ticker": "SENATETX",
            "title": "Texas Senate winner?",
        },
        "markets": [
            {
                "status": "active",
                "ticker": "SENATETX-26-D",
                "title": "Will Democrats win?",
                "yes_sub_title": "James Talarico",
                "yes_bid_dollars": "0.49",
                "yes_ask_dollars": "0.50",
                "volume_fp": "3000000",
                "open_interest_fp": "2000000",
                "updated_time": "2026-08-20T00:00:00Z",
            },
            {
                "status": "active",
                "ticker": "SENATETX-26-R",
                "title": "Will Republicans win?",
                "yes_sub_title": "Ken Paxton",
                "yes_bid_dollars": "0.51",
                "yes_ask_dollars": "0.52",
                "volume_fp": "4000000",
                "open_interest_fp": "2500000",
                "updated_time": "2026-08-20T00:00:00Z",
            },
        ],
    }
    record = _kalshi_record(
        payload,
        office="senate",
        location="TX",
        scope="direct_race",
        fetched_at=NOW,
    )
    assert record is not None
    assert abs(float(record["dem_probability"]) - 0.495 / 1.01) < 1e-12
    assert float(record["liquidity_or_open_interest"]) == 4_500_000


def _signals(scope: str = "direct_race") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": source,
                "office": "senate",
                "location": "TX" if scope == "direct_race" else "US-SENATE",
                "market_scope": scope,
                "dem_probability": probability,
                "quality_score": 0.9,
                "volume": 500_000,
                "liquidity_or_open_interest": 100_000,
                "max_spread": 0.02,
                "market_updated_at": NOW,
                "dem_market_labels": "James Talarico (D)",
                "rep_market_labels": "Ken Paxton (R)",
                "source_url": f"https://example.test/{source}",
            }
            for source, probability in [("polymarket", 0.51), ("kalshi", 0.49)]
        ]
    )


def test_market_calibration_is_bounded_and_preserves_model_probability():
    consensus = build_market_consensus(_signals())
    forecast = pd.DataFrame(
        [
            {
                "race_id": "2026:senate:TX:talarico:paxton",
                "office": "senate",
                "location": "TX",
                "dem_candidate": "James Talarico",
                "rep_candidate": "Ken Paxton",
                "dem_win_probability": 0.37,
                "rep_win_probability": 0.63,
            }
        ]
    )
    calibrated, audit = calibrate_race_probabilities(forecast, consensus)
    row = calibrated.iloc[0]
    assert row["model_only_dem_win_probability"] == 0.37
    assert 0.37 < row["dem_win_probability"] < 0.45
    assert row["market_calibration_weight"] <= 0.30
    assert row["market_probability_shift"] <= 0.08
    assert bool(row["market_candidate_match"])
    assert len(audit) == 1


def test_candidate_mismatch_is_reported_but_not_applied():
    signals = _signals()
    signals.loc[signals["source"] == "polymarket", "dem_market_labels"] = "Democratic Party"
    signals.loc[signals["source"] == "polymarket", "rep_market_labels"] = "Republican Party"
    consensus = build_market_consensus(signals)
    forecast = pd.DataFrame(
        [
            {
                "race_id": "alternate",
                "office": "senate",
                "location": "TX",
                "dem_candidate": "Someone Else",
                "rep_candidate": "Ken Paxton",
                "dem_win_probability": 0.37,
                "rep_win_probability": 0.63,
            }
        ]
    )
    calibrated, _ = calibrate_race_probabilities(forecast, consensus)
    assert calibrated.iloc[0]["dem_win_probability"] == 0.37
    assert not bool(calibrated.iloc[0]["market_candidate_match"])


def test_party_only_market_adjusts_only_central_matchup():
    signals = _signals()
    signals["dem_market_labels"] = "Democratic Party"
    signals["rep_market_labels"] = "Republican Party"
    consensus = build_market_consensus(signals)
    forecast = pd.DataFrame(
        [
            {
                "race_id": race_id,
                "office": "senate",
                "location": "TX",
                "dem_candidate": "James Talarico",
                "rep_candidate": candidate,
                "probability_source": "poll_model",
                "poll_count": poll_count,
                "dem_win_probability": 0.40,
                "rep_win_probability": 0.60,
            }
            for race_id, candidate, poll_count in [
                ("central", "Ken Paxton", 10),
                ("alternative", "Someone Else", 2),
            ]
        ]
    )
    calibrated, audit = calibrate_race_probabilities(forecast, consensus)
    probabilities = calibrated.set_index("race_id")["dem_win_probability"]
    assert probabilities["central"] > 0.40
    assert probabilities["alternative"] == 0.40
    assert audit.set_index("race_id").loc["central", "central_matchup"]
    assert not audit.set_index("race_id").loc["alternative", "central_matchup"]


def test_chamber_market_is_context_not_replacement():
    consensus = build_market_consensus(_signals("chamber_control"))
    control = {
        "senate": {"dem_control_probability": 0.60},
        "house": {"dem_control_probability": 0.70},
    }
    context = add_chamber_market_context(
        control,
        consensus,
        MarketCalibrationConfig(maximum_chamber_probability_shift=0.02),
    )
    assert context["senate"]["dem_control_probability"] == 0.60
    comparison = context["prediction_market_context"]["comparisons"]["senate"]
    assert comparison["bounded_market_context_probability"] < 0.60
    assert comparison["bounded_market_context_probability"] >= 0.58
