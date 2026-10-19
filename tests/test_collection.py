import pytest

from election_forecast.collection import summarize_collection
from election_forecast.lineage import fingerprint


def test_acquisition_freshness_reconciles_counts_and_rejects_future_observations(tmp_path):
    for name in ("polls_latest", "polls_latest_raw_sources"):
        (tmp_path / f"{name}.parquet").write_bytes(b"dataset")
    report = {
        "dataset_sha256": {
            name: fingerprint(tmp_path / f"{name}.parquet")
            for name in ("polls_latest", "polls_latest_raw_sources")
        },
        "checked_at": "2026-10-19T20:00:00+00:00",
        "request_status_counts": {"cache": 1, "failed": 1},
        "requests": [
            {
                "url": "https://example.test/polls",
                "status": "cache",
                "checked_at": "2026-10-19T20:00:00+00:00",
                "observed_at": "2026-10-19T19:00:00+00:00",
            },
            {
                "url": "https://example.test/old-directory",
                "status": "failed",
                "checked_at": "2026-10-19T20:00:00+00:00",
                "http_status": 404,
            },
        ],
        "raw_rows_by_source": {"example": 2},
        "scope": "HTTP acquisition, not authentication",
    }
    summary = summarize_collection(report, tmp_path)
    assert summary["latest_observed_at"] == "2026-10-19T19:00:00+00:00"
    assert summary["request_status_counts"]["cache"] == 1
    assert len(summary["failed_requests"]) == 1
    report["request_status_counts"]["cache"] = 2
    with pytest.raises(ValueError, match="do not reconcile"):
        summarize_collection(report, tmp_path)
    report["request_status_counts"]["cache"] = 1
    report["requests"][0]["observed_at"] = "2026-10-19T21:00:00+00:00"
    with pytest.raises(ValueError, match="future acquisition"):
        summarize_collection(report, tmp_path)
