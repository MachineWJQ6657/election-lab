import json
from datetime import date

import pandas as pd
import pytest

from election_forecast.lineage import fingerprint, verify_forecast_manifest, verify_observed_cutoff


def test_export_rejects_source_refresh_and_partial_output_rewrite(tmp_path):
    artifacts, processed = tmp_path / "artifacts", tmp_path / "processed"
    artifacts.mkdir()
    processed.mkdir()
    poll_file = processed / "polls_latest.parquet"
    forecast_file = artifacts / "latest_forecast.csv"
    poll_file.write_bytes(b"poll snapshot A")
    forecast_file.write_bytes(b"forecast A")
    (artifacts / "forecast_manifest.json").write_text(
        json.dumps(
            {
                "source_sha256": {"polls_latest": fingerprint(poll_file)},
                "output_sha256": {"latest_forecast.csv": fingerprint(forecast_file)},
            }
        )
    )
    verify_forecast_manifest(artifacts, processed)
    poll_file.write_bytes(b"poll snapshot B")
    with pytest.raises(ValueError, match="source snapshot mismatch"):
        verify_forecast_manifest(artifacts, processed)
    poll_file.write_bytes(b"poll snapshot A")
    forecast_file.write_bytes(b"partial forecast B")
    with pytest.raises(ValueError, match="output snapshot mismatch"):
        verify_forecast_manifest(artifacts, processed)


def test_live_tables_cannot_be_backdated_and_use_new_york_day_boundary():
    data = pd.DataFrame({"fetched_at": ["2026-10-20T00:30:00+00:00"]})
    verify_observed_cutoff(data, date(2026, 10, 19), "test")
    with pytest.raises(ValueError, match="after requested as-of"):
        verify_observed_cutoff(data, date(2026, 10, 18), "test")
    with pytest.raises(ValueError, match="archived snapshot"):
        verify_observed_cutoff(
            pd.DataFrame({"end_date": ["2026-10-05"]}), date(2026, 10, 5), "test"
        )
